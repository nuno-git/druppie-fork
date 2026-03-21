"""Benchmark run database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class BenchmarkRun(Base):
    """A benchmark run that groups evaluation results."""

    __tablename__ = "benchmark_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    run_type = Column(String(50), nullable=False)  # batch, live, manual
    git_commit = Column(String(40))
    git_branch = Column(String(255))
    judge_model = Column(String(100))
    config_summary = Column(Text)  # Plain text summary of run configuration
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    results = relationship(
        "EvaluationResult",
        back_populates="benchmark_run",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "run_type": self.run_type,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "judge_model": self.judge_model,
            "config_summary": self.config_summary,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
