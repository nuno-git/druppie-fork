"""SQLAlchemy database models for Druppie platform.

Models match druppie/db/schema.sql with normalized tables.
LLM calls include JSON columns for full request/response debugging.
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
    JSON,
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

    steps = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.step_index",
    )

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
#
# DESIGN DECISION: Using JSONB for tool arguments instead of a separate table.
#
# We considered two approaches:
#
# 1. NORMALIZED (separate tool_call_arguments table):
#    - Pros: Can query by argument value, SQL constraints
#    - Cons: Multiple inserts, JOINs for every display, more complex
#
# 2. JSONB COLUMN (arguments stored as JSON in tool_calls):
#    - Pros: Single insert, faster reads, simpler schema
#    - Cons: Can't efficiently query by argument value
#
# We chose JSONB because:
# - We NEVER query tool calls by argument values (e.g., "find calls where path=/etc")
# - We ALWAYS fetch all arguments together for display
# - The `approvals` table already uses JSONB for the same data (consistency)
# - Matches how the domain layer represents it (dict[str, Any])
#
# =============================================================================


class ToolCall(Base):
    """A tool call made by an agent.

    Tool calls represent MCP tool invocations (e.g., coding:write_file) or
    built-in tools (e.g., execute_agent, done).

    The `arguments` column stores tool parameters as JSONB. This is consistent
    with how `approvals.arguments` stores the same data. We use JSONB because:
    1. Arguments are only used for display, never queried individually
    2. Simpler schema (no separate table, no JOINs)
    3. Single atomic insert when creating a tool call
    """

    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))

    mcp_server = Column(String(100), nullable=False)
    tool_name = Column(String(200), nullable=False)

    # Tool arguments as JSONB - e.g., {"path": "/app/main.py", "content": "..."}
    # Previously this was a separate `tool_call_arguments` table, but that added
    # complexity without benefit since we never query by argument values.
    arguments = Column(JSON)

    status = Column(String(20), default="pending")  # pending, executing, completed, failed
    result = Column(Text)
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    executed_at = Column(DateTime(timezone=True))

    agent_run = relationship("AgentRun", back_populates="tool_calls")

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
            "arguments": self.arguments or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


# NOTE: ToolCallArgument table has been REMOVED.
# Tool arguments are now stored as JSONB in tool_calls.arguments.
# See the design decision comment above for rationale.


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

    @property
    def required_roles(self) -> list[str]:
        """Get required roles as a list (for API compatibility)."""
        if not self.required_role:
            return []
        return [r.strip() for r in self.required_role.split(",") if r.strip()]

    @property
    def approvals_received(self) -> list[str]:
        """Get list of approvals received (for multi-approval API compatibility)."""
        if self.status == "approved" and self.resolved_by:
            return [str(self.resolved_by)]
        return []

    @property
    def approved_by(self) -> str | None:
        """Get the user who approved (for API compatibility)."""
        if self.status == "approved" and self.resolved_by:
            return str(self.resolved_by)
        return None

    @property
    def approved_at(self):
        """Get approval timestamp (for API compatibility)."""
        if self.status == "approved":
            return self.resolved_at
        return None

    @property
    def rejected_by(self) -> str | None:
        """Get the user who rejected (for API compatibility)."""
        if self.status == "rejected" and self.resolved_by:
            return str(self.resolved_by)
        return None

    # Danger level for MCP tools
    danger_level = Column(String(20))  # low, medium, high

    status = Column(String(20), default="pending")  # pending, approved, rejected

    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    # Tool arguments for execution after approval
    arguments = Column(JSON)

    # Agent state for resumption after approval
    agent_state = Column(JSON)

    # Agent ID that requested the approval
    agent_id = Column(String(100))

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
            "required_roles": self.required_roles,  # List version for API
            "danger_level": self.danger_level,
            "status": self.status,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "rejection_reason": self.rejection_reason,
            "arguments": self.arguments,
            "agent_state": self.agent_state,
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# HITL (Human-in-the-Loop) QUESTIONS
# =============================================================================
#
# DESIGN DECISION: Using JSONB for question choices instead of a separate table.
#
# Same reasoning as tool_calls.arguments:
# - We ALWAYS fetch all choices together for display
# - We NEVER query questions by choice text
# - When user answers, we store the answer text and optionally selected indices
#
# The `choices` JSONB column stores an array of choice objects:
#   [{"text": "Option A"}, {"text": "Option B"}, {"text": "Option C"}]
#
# The `selected_indices` column stores which choices were selected (for multiple choice):
#   [0, 2] means first and third options were selected
#
# This is simpler than a separate table and matches how the domain layer works.
#
# =============================================================================


class HitlQuestion(Base):
    """A question from an agent to the user (human-in-the-loop).

    HITL questions allow agents to ask for user input during execution.
    There are three question types:
    - text: Free-form text answer (choices is NULL)
    - single_choice: One option must be selected
    - multiple_choice: Multiple options can be selected

    For choice questions, the `choices` column stores the available options as
    JSONB array: [{"text": "Option A"}, {"text": "Option B"}]

    When answered, `selected_indices` stores which choices were picked: [0, 2]
    The `answer` field contains the text of the answer (for text questions) or
    the selected choice texts joined (for display).
    """

    __tablename__ = "hitl_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    agent_id = Column(String(50))  # Direct reference to agent name (router, architect, etc.)

    question = Column(Text, nullable=False)
    question_type = Column(String(20), default="text")  # text, single_choice, multiple_choice

    # Choices for single_choice/multiple_choice questions as JSONB array.
    # Format: [{"text": "Option A"}, {"text": "Option B"}]
    # NULL for text questions.
    # Previously this was a separate `hitl_question_choices` table, but that added
    # complexity without benefit since we never query by choice text.
    choices = Column(JSON)

    # Which choices were selected (indices into the choices array).
    # Format: [0, 2] means first and third options selected.
    # NULL for text questions or unanswered questions.
    selected_indices = Column(JSON)

    status = Column(String(20), default="pending")  # pending, answered
    answer = Column(Text)  # Text answer or display string of selected choices
    answered_at = Column(DateTime(timezone=True))

    # Agent state for resumption (messages, iteration, context, workflow info)
    agent_state = Column(JSON)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    agent_run = relationship("AgentRun", foreign_keys=[agent_run_id])

    def to_dict(self) -> dict[str, Any]:
        # Build choices list with selection state for API compatibility
        choices_with_selection = []
        if self.choices:
            selected = self.selected_indices or []
            for idx, choice in enumerate(self.choices):
                choices_with_selection.append({
                    "choice_index": idx,
                    "choice_text": choice.get("text", ""),
                    "is_selected": idx in selected,
                })

        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "agent_id": self.agent_id,
            "question": self.question,
            "question_type": self.question_type,
            "choices": choices_with_selection,
            "status": self.status,
            "answer": self.answer,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "agent_state": self.agent_state,  # For resumption
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# NOTE: HitlQuestionChoice table has been REMOVED.
# Question choices are now stored as JSONB in hitl_questions.choices.
# Selected choices are tracked in hitl_questions.selected_indices.
# See the design decision comment above for rationale.


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
    status = Column(String(20), default="pending")  # pending, building, built, running, stopped, failed
    is_preview = Column(Boolean, default=False)  # True for preview builds, False for main
    port = Column(Integer)  # Host port allocated for this build
    container_name = Column(String(255))  # Docker container name
    app_url = Column(String(512))  # URL to access the running app
    build_logs = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id) if self.project_id else None,
            "session_id": str(self.session_id) if self.session_id else None,
            "branch": self.branch,
            "status": self.status,
            "is_preview": self.is_preview,
            "port": self.port,
            "container_name": self.container_name,
            "app_url": self.app_url,
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
    """Tracks LLM API calls for cost transparency and debugging."""

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
    # Full request/response data for debugging
    request_messages = Column(JSON)  # Array of messages sent to LLM
    response_content = Column(Text)  # LLM response text
    response_tool_calls = Column(JSON)  # Tool calls returned by LLM
    tools_provided = Column(JSON)  # Tools available to the LLM
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
            "request_messages": self.request_messages,
            "response_content": self.response_content,
            "response_tool_calls": self.response_tool_calls,
            "tools_provided": self.tools_provided,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# SESSION EVENTS (unified event log for timeline display)
# =============================================================================


class SessionEvent(Base):
    """Unified event log for session timeline display.

    This provides a single source of truth for session history,
    instead of reconstructing events from multiple tables.
    """

    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))

    # Event classification
    event_type = Column(String(50), nullable=False)
    # Types: agent_started, agent_completed, tool_call, tool_result,
    #        approval_pending, approval_granted, approval_rejected,
    #        hitl_question, hitl_answered, deployment_started,
    #        deployment_complete, error

    # Actor identification
    agent_id = Column(String(100))  # Which agent triggered this event

    # Event details (denormalized for easy display)
    title = Column(String(500))  # Human-readable event title
    tool_name = Column(String(200))  # For tool events: coding:write_file

    # References to detailed records (optional, for drill-down)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id"))
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approvals.id"))
    hitl_question_id = Column(UUID(as_uuid=True), ForeignKey("hitl_questions.id"))

    # Event-specific data (minimal, for display only)
    event_data = Column(JSON)

    timestamp = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "title": self.title,
            "tool_name": self.tool_name,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "approval_id": str(self.approval_id) if self.approval_id else None,
            "hitl_question_id": str(self.hitl_question_id) if self.hitl_question_id else None,
            "event_data": self.event_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
