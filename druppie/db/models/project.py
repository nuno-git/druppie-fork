"""Project database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID

from druppie.domain.document_formatter import DEFAULT_HOUSE_STYLE, DocumentHouseStyle

from .base import Base, utcnow


class Project(Base):
    """A project with a Gitea repository."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    repo_name = Column(String(255), nullable=True)  # repo name only (e.g., "todo-app-abc12345")
    repo_owner = Column(String(255), nullable=True)  # Gitea username who owns the repo
    repo_url = Column(String(512))  # Full public URL (e.g., "http://gitea:3000/username/repo") - kept for backward compat
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    status = Column(String(20), default="active")  # active, archived
    # Corporate identity used when the documenter renders this project's PDFs.
    # Constrained column (not free text, not JSON) so the set of valid styles
    # is enforced by the database.
    house_style = Column(
        SQLEnum(
            DocumentHouseStyle,
            name="document_house_style",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=DEFAULT_HOUSE_STYLE,
        server_default=DEFAULT_HOUSE_STYLE.value,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "repo_name": self.repo_name,
            "repo_owner": self.repo_owner,
            "repo_url": self.repo_url,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "status": self.status,
            "house_style": self.house_style.value if self.house_style else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
