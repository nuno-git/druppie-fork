"""Session database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class Session(Base):
    """A conversation session."""

    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    title = Column(String(500))
    status = Column(String(20), default="active")  # active, paused, paused_approval, paused_hitl, paused_crashed, completed, failed
    error_message = Column(Text)  # Error details when status is 'failed'
    intent = Column(String(50))  # create_project, update_project, update_core, general_chat
    branch_name = Column(String(255), nullable=True)  # Feature branch for update_project

    # Repo context for update_core (GitHub) — not linked to a project record
    repo_url = Column(String(500), nullable=True)  # e.g. https://github.com/nuno-git/druppie-fork.git
    repo_owner = Column(String(255), nullable=True)  # e.g. nuno-git
    repo_name = Column(String(255), nullable=True)  # e.g. druppie-fork
    base_branch = Column(String(255), nullable=True)  # e.g. colab-dev

    language = Column(String(10), nullable=True)  # Detected conversational language (e.g., "nl", "en")

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
            "error_message": self.error_message,
            "intent": self.intent,
            "branch_name": self.branch_name,
            "repo_url": self.repo_url,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "base_branch": self.base_branch,
            "language": self.language,
            "prompt_tokens": self.prompt_tokens or 0,
            "completion_tokens": self.completion_tokens or 0,
            "total_tokens": self.total_tokens or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
