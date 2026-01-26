"""SQLAlchemy database models for Druppie platform.

Models match druppie/db/schema.sql exactly.
NO JSON/JSONB columns - everything is normalized into proper tables.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid4())


# =============================================================================
# USERS & ROLES (synced from Keycloak)
# =============================================================================


class User(Base):
    """User synced from Keycloak."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255))
    display_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    tokens = relationship("UserToken", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "roles": [r.role for r in self.roles] if self.roles else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserRole(Base):
    """User role mapping."""

    __tablename__ = "user_roles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(50), primary_key=True)

    user = relationship("User", back_populates="roles")


class UserToken(Base):
    """OBO tokens for external services."""

    __tablename__ = "user_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    service = Column(String(100), nullable=False)  # gitea, sharepoint
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="tokens")


# =============================================================================
# PROJECTS (Gitea repositories)
# =============================================================================


class Project(Base):
    """A project with a Gitea repository."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    repo_name = Column(String(255), nullable=False)  # org/repo
    repo_url = Column(String(512))
    clone_url = Column(String(512))
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    status = Column(String(20), default="active")  # active, archived
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "clone_url": self.clone_url,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# SESSIONS
# =============================================================================


class Session(Base):
    """A conversation session."""

    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"))
    title = Column(String(500))
    status = Column(String(20), default="active")  # active, paused_approval, paused_hitl, completed, failed

    # Token usage (aggregated)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "title": self.title,
            "status": self.status,
            "prompt_tokens": self.prompt_tokens or 0,
            "completion_tokens": self.completion_tokens or 0,
            "total_tokens": self.total_tokens or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# WORKFLOWS (execution plans from planner)
# =============================================================================


class Workflow(Base):
    """An execution plan created by the planner."""

    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    name = Column(String(255))
    status = Column(String(20), default="pending")  # pending, running, paused, completed, failed
    current_step = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    steps = relationship("WorkflowStep", back_populates="workflow", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "name": self.name,
            "status": self.status,
            "current_step": self.current_step,
            "steps": [s.to_dict() for s in self.steps] if self.steps else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WorkflowStep(Base):
    """A step in a workflow."""

    __tablename__ = "workflow_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"))
    step_index = Column(Integer, nullable=False)
    agent_id = Column(String(100), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="pending")  # pending, running, waiting_approval, completed, failed, skipped
    result_summary = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    workflow = relationship("Workflow", back_populates="steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "step_index": self.step_index,
            "agent_id": self.agent_id,
            "description": self.description,
            "status": self.status,
            "result_summary": self.result_summary,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# =============================================================================
# AGENT RUNS (each time an agent is invoked)
# =============================================================================


class AgentRun(Base):
    """Tracks each agent execution for message isolation."""

    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    workflow_step_id = Column(UUID(as_uuid=True), ForeignKey("workflow_steps.id"))
    agent_id = Column(String(100), nullable=False)
    parent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    status = Column(String(20), default="running")  # running, paused_tool, paused_hitl, completed, failed
    iteration_count = Column(Integer, default=0)

    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))

    # Relationships
    messages = relationship("Message", back_populates="agent_run")
    tool_calls = relationship("ToolCall", back_populates="agent_run")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "workflow_step_id": str(self.workflow_step_id) if self.workflow_step_id else None,
            "agent_id": self.agent_id,
            "parent_run_id": str(self.parent_run_id) if self.parent_run_id else None,
            "status": self.status,
            "iteration_count": self.iteration_count,
            "prompt_tokens": self.prompt_tokens or 0,
            "completion_tokens": self.completion_tokens or 0,
            "total_tokens": self.total_tokens or 0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# =============================================================================
# MESSAGES (conversation history, linked to agent_run for isolation)
# =============================================================================


class Message(Base):
    """A message in the conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)

    agent_id = Column(String(100))  # For assistant messages
    tool_name = Column(String(200))  # For tool messages
    tool_call_id = Column(String(100))  # For tool messages

    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    agent_run = relationship("AgentRun", back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "role": self.role,
            "content": self.content,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# TOOL CALLS
# =============================================================================


class ToolCall(Base):
    """A tool call made by an agent."""

    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    mcp_server = Column(String(100), nullable=False)
    tool_name = Column(String(200), nullable=False)

    status = Column(String(20), default="pending")  # pending, executing, completed, failed
    result = Column(Text)
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    executed_at = Column(DateTime(timezone=True))

    agent_run = relationship("AgentRun", back_populates="tool_calls")
    arguments = relationship("ToolCallArgument", back_populates="tool_call", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "mcp_server": self.mcp_server,
            "tool_name": self.tool_name,
            "status": self.status,
            "result": self.result,
            "error_message": self.error_message,
            "arguments": {a.arg_name: a.arg_value for a in self.arguments} if self.arguments else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class ToolCallArgument(Base):
    """Arguments for a tool call (normalized, no JSON)."""

    __tablename__ = "tool_call_arguments"

    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="CASCADE"), primary_key=True)
    arg_name = Column(String(100), primary_key=True)
    arg_value = Column(Text)

    tool_call = relationship("ToolCall", back_populates="arguments")


# =============================================================================
# APPROVALS
# =============================================================================


class Approval(Base):
    """An approval request for a tool call or workflow step."""

    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id"))
    workflow_step_id = Column(UUID(as_uuid=True), ForeignKey("workflow_steps.id"))

    approval_type = Column(String(20), nullable=False)  # tool_call, workflow_step

    mcp_server = Column(String(100))
    tool_name = Column(String(200))

    title = Column(String(500))
    description = Column(Text)

    required_role = Column(String(50))  # architect, developer, infra_engineer, admin

    status = Column(String(20), default="pending")  # pending, approved, rejected

    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "workflow_step_id": str(self.workflow_step_id) if self.workflow_step_id else None,
            "approval_type": self.approval_type,
            "mcp_server": self.mcp_server,
            "tool_name": self.tool_name,
            "title": self.title,
            "description": self.description,
            "required_role": self.required_role,
            "status": self.status,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# HITL (Human-in-the-Loop) QUESTIONS
# =============================================================================


class HitlQuestion(Base):
    """A question from an agent to the user."""

    __tablename__ = "hitl_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    question = Column(Text, nullable=False)
    question_type = Column(String(20), default="text")  # text, single_choice, multiple_choice

    status = Column(String(20), default="pending")  # pending, answered
    answer = Column(Text)
    answered_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=utcnow)

    choices = relationship("HitlQuestionChoice", back_populates="question", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "question": self.question,
            "question_type": self.question_type,
            "choices": [c.to_dict() for c in self.choices] if self.choices else [],
            "status": self.status,
            "answer": self.answer,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HitlQuestionChoice(Base):
    """A choice for a HITL question (normalized, no JSON)."""

    __tablename__ = "hitl_question_choices"

    question_id = Column(UUID(as_uuid=True), ForeignKey("hitl_questions.id", ondelete="CASCADE"), primary_key=True)
    choice_index = Column(Integer, primary_key=True)
    choice_text = Column(String(500), nullable=False)
    is_selected = Column(Boolean, default=False)

    question = relationship("HitlQuestion", back_populates="choices")

    def to_dict(self) -> dict[str, Any]:
        return {
            "choice_index": self.choice_index,
            "choice_text": self.choice_text,
            "is_selected": self.is_selected,
        }


# =============================================================================
# WORKSPACES
# =============================================================================


class Workspace(Base):
    """A workspace for a session."""

    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"))
    branch = Column(String(255), default="main")
    local_path = Column(String(512))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "branch": self.branch,
            "local_path": self.local_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# BUILDS & DEPLOYMENTS
# =============================================================================


class Build(Base):
    """A Docker build for a project."""

    __tablename__ = "builds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"))
    branch = Column(String(255), default="main")
    status = Column(String(20), default="pending")  # pending, building, success, failed
    build_logs = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id) if self.project_id else None,
            "session_id": str(self.session_id) if self.session_id else None,
            "branch": self.branch,
            "status": self.status,
            "build_logs": self.build_logs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Deployment(Base):
    """A running deployment of a build."""

    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey("builds.id"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    container_name = Column(String(255))
    container_id = Column(String(100))
    host_port = Column(Integer)
    app_url = Column(String(512))
    status = Column(String(20), default="starting")  # starting, running, stopped, failed
    is_preview = Column(Boolean, default=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    stopped_at = Column(DateTime(timezone=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "build_id": str(self.build_id) if self.build_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "host_port": self.host_port,
            "app_url": self.app_url,
            "status": self.status,
            "is_preview": self.is_preview,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
        }


# =============================================================================
# LLM USAGE TRACKING
# =============================================================================


class LlmCall(Base):
    """Tracks LLM API calls for cost transparency."""

    __tablename__ = "llm_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    provider = Column(String(50), nullable=False)  # deepinfra, zai, openai
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
