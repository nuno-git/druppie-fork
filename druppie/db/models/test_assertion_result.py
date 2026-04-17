"""Per-assertion result storage for testing framework analytics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class TestAssertionResult(Base):
    """Individual assertion/judge/verify result within a test run.

    Assertion types:
    - completed: agent completed check
    - tool_called: tool was called check
    - judge_check: LLM judge check
    - result_valid: Layer 1 result validator
    - verify: Layer 2 side-effect verifier
    - status_check: Layer 3 tool call status assertion
    """

    __tablename__ = "test_assertion_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    test_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    assertion_type = Column(String(50), nullable=False)
    agent_id = Column(String(100), nullable=True)
    tool_name = Column(String(200), nullable=True)
    eval_name = Column(String(200), nullable=True)
    passed = Column(Boolean, nullable=False)
    message = Column(Text, nullable=True)
    judge_reasoning = Column(Text, nullable=True)
    judge_raw_input = Column(Text, nullable=True)
    judge_raw_output = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    test_run = relationship("TestRun", back_populates="assertion_results")

    __table_args__ = (
        Index("idx_tar_test_run_id", "test_run_id"),
        Index("idx_tar_agent_id", "agent_id"),
        Index("idx_tar_eval_name", "eval_name"),
        Index("idx_tar_tool_name", "tool_name"),
        Index("idx_tar_assertion_type", "assertion_type"),
    )

    def to_domain(self) -> "TestAssertionResultSummary":
        from druppie.domain.evaluation import TestAssertionResultSummary
        return TestAssertionResultSummary.model_validate(self, from_attributes=True)

    def to_dict(self) -> dict[str, Any]:
        return self.to_domain().model_dump(mode="json")
