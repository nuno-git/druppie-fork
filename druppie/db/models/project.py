"""Project database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class Project(Base):
    """A project with a Gitea repository."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    repo_name = Column(String(255), nullable=True)  # org/repo - set when deployed to Gitea
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
