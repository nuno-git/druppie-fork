"""Test run database model for testing framework."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class TestRun(Base):
    """A single test execution within a benchmark run."""

    __tablename__ = "test_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    benchmark_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("benchmark_runs.id", ondelete="CASCADE"),
    )
    test_name = Column(String(255), nullable=False)
    test_description = Column(Text, nullable=True)
    test_user = Column(String(255), nullable=True)
    hitl_profile = Column(String(100), nullable=True)
    judge_profile = Column(String(100), nullable=True)
    sessions_seeded = Column(Integer, nullable=True)
    assertions_total = Column(Integer, nullable=True)
    assertions_passed = Column(Integer, nullable=True)
    judge_checks_total = Column(Integer, nullable=True)
    judge_checks_passed = Column(Integer, nullable=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(50), nullable=True)  # passed, failed, error
    duration_ms = Column(Integer, nullable=True)
    batch_id = Column(String(36), nullable=True, index=True)  # Groups tests from same Run click
    created_at = Column(DateTime(timezone=True), default=utcnow)

    agent_id = Column(String(100), nullable=True)  # Primary agent tested
    mode = Column(String(20), nullable=True)  # tool, agent

    # Relationships
    benchmark_run = relationship("BenchmarkRun", back_populates="test_runs")
    tags = relationship(
        "TestRunTag",
        back_populates="test_run",
        cascade="all, delete-orphan",
    )
    assertion_results = relationship(
        "TestAssertionResult",
        back_populates="test_run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_test_runs_created_at", "created_at"),
        Index("idx_test_runs_agent_id", "agent_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "benchmark_run_id": str(self.benchmark_run_id) if self.benchmark_run_id else None,
            "batch_id": self.batch_id,
            "test_name": self.test_name,
            "test_description": self.test_description,
            "test_user": self.test_user,
            "hitl_profile": self.hitl_profile,
            "judge_profile": self.judge_profile,
            "session_id": str(self.session_id) if self.session_id else None,
            "sessions_seeded": self.sessions_seeded,
            "assertions_total": self.assertions_total,
            "assertions_passed": self.assertions_passed,
            "judge_checks_total": self.judge_checks_total,
            "judge_checks_passed": self.judge_checks_passed,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "agent_id": self.agent_id,
            "mode": self.mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "assertion_results": [r.to_dict() for r in self.assertion_results] if self.assertion_results else [],
        }
