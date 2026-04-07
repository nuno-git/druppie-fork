"""Project dependency database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class ProjectDependency(Base):
    """A package dependency used by a project, discovered from sandbox cache."""

    __tablename__ = "project_dependencies"
    __table_args__ = (
        UniqueConstraint("project_id", "manager", "name", "version", name="uq_project_dep"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manager = Column(String(20), nullable=False)  # npm, pip, uv, bun, pnpm
    name = Column(String(255), nullable=False)
    version = Column(String(100), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), default=utcnow)
    last_seen_at = Column(DateTime(timezone=True), default=utcnow)
