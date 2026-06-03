"""Job database models for scheduled cron jobs."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class JobDefinition(Base):
    """A scheduled job definition loaded from YAML configuration."""

    __tablename__ = "job_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    schedule = Column(String(100), nullable=False)
    agent_id = Column(String(100), nullable=False)
    prompt = Column(Text, nullable=False)
    approval_required = Column(Boolean, default=False)
    required_role = Column(String(50))

    enabled = Column(Boolean, default=True)
    yaml_path = Column(String(500))

    last_triggered_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    configs = relationship(
        "JobDefinitionConfig",
        back_populates="job_definition",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def to_dict(self) -> dict[str, Any]:
        config_items = {
            cfg.config_key: cfg.config_value
            for cfg in (self.configs or [])
        }
        return {
            "id": str(self.id),
            "job_id": self.job_id,
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "agent_id": self.agent_id,
            "prompt": self.prompt,
            "approval_required": self.approval_required,
            "required_role": self.required_role,
            "config": config_items if config_items else None,
            "enabled": self.enabled,
            "yaml_path": self.yaml_path,
            "last_triggered_at": self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class JobDefinitionConfig(Base):
    """Normalized configuration key-value pairs for a job definition."""

    __tablename__ = "job_definition_configs"
    __table_args__ = (
        Index("idx_job_definition_configs_job_definition_id", "job_definition_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_definition_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    config_key = Column(String(255), nullable=False)
    config_value = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job_definition = relationship("JobDefinition", back_populates="configs")


class JobRun(Base):
    """A single execution instance of a scheduled job."""

    __tablename__ = "job_runs"
    __table_args__ = (
        Index("idx_job_runs_job_definition_id", "job_definition_id"),
        Index("idx_job_runs_agent_run_id", "agent_run_id"),
        Index("idx_job_runs_status", "status"),
        Index("idx_job_runs_created_at", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_definition_id = Column(UUID(as_uuid=True), ForeignKey("job_definitions.id", ondelete="CASCADE"))
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"))

    trigger_type = Column(String(20), default="scheduled")
    status = Column(String(20), default="pending")  # pending, running, waiting_approval, completed, failed, cancelled, rejected
    error_message = Column(Text)
    logs = Column(Text)

    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "job_definition_id": str(self.job_definition_id) if self.job_definition_id else None,
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "error_message": self.error_message,
            "logs": self.logs,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
