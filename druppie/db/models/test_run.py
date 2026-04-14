"""Test run database model for testing framework."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
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

    def to_domain(self, include_assertions: bool = True) -> "TestRunDetail | TestRunSummary":
        from druppie.domain.evaluation import TestRunDetail, TestRunSummary
        tags = [t.tag for t in self.tags] if self.tags else []
        if include_assertions:
            assertion_results = [
                ar.to_domain() for ar in self.assertion_results
            ] if self.assertion_results else []
            return TestRunDetail(
                **{k: getattr(self, k) for k in TestRunSummary.model_fields if k != "tags"},
                tags=tags,
                assertion_results=assertion_results,
            )
        return TestRunSummary(
            **{k: getattr(self, k) for k in TestRunSummary.model_fields if k != "tags"},
            tags=tags,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_domain().model_dump(mode="json")
