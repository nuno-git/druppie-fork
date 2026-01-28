"""Workspace database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


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
