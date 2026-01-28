"""Build and deployment database models."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


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
