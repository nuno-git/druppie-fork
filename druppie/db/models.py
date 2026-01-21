"""SQLAlchemy database models for Druppie platform.

Simplified schema for sessions, approvals, projects, builds, and workspaces.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Session(Base):
    """Session model for tracking execution state."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(255), nullable=True, index=True)
    status = Column(
        String(20),
        default="active",
        index=True,
    )  # active, paused, completed, failed
    state = Column(JSON, nullable=True)  # ExecutionState as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "state": self.state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Approval(Base):
    """Approval model for tracking approval requests."""

    __tablename__ = "approvals"

    id = Column(String(36), primary_key=True)  # UUID
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False)
    arguments = Column(JSON, nullable=True)
    status = Column(
        String(20),
        default="pending",
        index=True,
    )  # pending, approved, rejected
    required_roles = Column(JSON, nullable=True)  # List of roles that can approve
    approvals_received = Column(JSON, nullable=True)  # List of {user_id, role, timestamp}
    danger_level = Column(String(20), default="low")  # low, medium, high, critical
    description = Column(Text, nullable=True)
    agent_state = Column(JSON, nullable=True)  # Full LangGraph state for resume
    approved_by = Column(String(255), nullable=True)  # User ID who approved
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(255), nullable=True)  # User ID who rejected
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status,
            "required_roles": self.required_roles,
            "approvals_received": self.approvals_received,
            "danger_level": self.danger_level,
            "description": self.description,
            "agent_state": self.agent_state,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": self.rejected_by,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Project(Base):
    """A project with a Gitea repository."""

    __tablename__ = "projects"

    id = Column(String(36), primary_key=True)  # UUID
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    repo_name = Column(String(255), nullable=False)  # Gitea repo name
    repo_url = Column(String(512), nullable=True)  # Full Gitea URL
    clone_url = Column(String(512), nullable=True)  # Git clone URL
    owner_id = Column(String(255), nullable=True, index=True)  # Keycloak user ID
    status = Column(String(20), default="active", index=True)  # active, archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "clone_url": self.clone_url,
            "owner_id": self.owner_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Build(Base):
    """A Docker build for a project branch."""

    __tablename__ = "builds"

    id = Column(String(36), primary_key=True)  # UUID
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    branch = Column(String(255), default="main")
    status = Column(
        String(20),
        default="pending",
        index=True,
    )  # pending, building, running, stopped, failed
    container_name = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True)
    app_url = Column(String(512), nullable=True)
    is_preview = Column(Boolean, default=False)
    build_logs = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "branch": self.branch,
            "status": self.status,
            "container_name": self.container_name,
            "port": self.port,
            "app_url": self.app_url,
            "is_preview": self.is_preview,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Workspace(Base):
    """A workspace for a session/conversation."""

    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True)  # UUID
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    branch = Column(String(255), default="main")
    local_path = Column(String(512), nullable=True)  # /app/workspace/{session_id}
    is_new_project = Column(Boolean, default=False)  # True if this conversation created the project
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "branch": self.branch,
            "local_path": self.local_path,
            "is_new_project": self.is_new_project,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HitlQuestion(Base):
    """HITL question from an agent to the user."""

    __tablename__ = "hitl_questions"

    id = Column(String(36), primary_key=True)  # UUID
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False)
    question = Column(Text, nullable=False)
    question_type = Column(String(20), default="text")  # text, choice
    choices = Column(JSON, nullable=True)  # For choice questions
    answer = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending", index=True)  # pending, answered, expired
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "question": self.question,
            "question_type": self.question_type,
            "choices": self.choices,
            "answer": self.answer,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
