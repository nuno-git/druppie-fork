"""Evaluation result database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class EvaluationResult(Base):
    """An individual evaluation result from a judge model."""

    __tablename__ = "evaluation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    benchmark_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("benchmark_runs.id", ondelete="CASCADE"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
    )
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
    )
    agent_id = Column(String(100))
    evaluation_name = Column(String(255))
    rubric_name = Column(String(255))
    score_type = Column(String(20))  # binary, graded
    score_binary = Column(Boolean)
    score_graded = Column(Float)
    max_score = Column(Float)
    judge_model = Column(String(100))
    judge_prompt = Column(Text)
    judge_response = Column(Text)
    judge_reasoning = Column(Text)
    llm_model = Column(String(100))
    llm_provider = Column(String(100))
    judge_duration_ms = Column(Integer)
    judge_tokens_used = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Indexes
    __table_args__ = (
        Index("ix_evaluation_results_agent_id", "agent_id"),
        Index("ix_evaluation_results_rubric_name", "rubric_name"),
        Index("ix_evaluation_results_benchmark_run_id", "benchmark_run_id"),
        Index("ix_evaluation_results_created_at", "created_at"),
    )

    # Relationships
    benchmark_run = relationship("BenchmarkRun", back_populates="results")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "benchmark_run_id": str(self.benchmark_run_id) if self.benchmark_run_id else None,
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "agent_id": self.agent_id,
            "evaluation_name": self.evaluation_name,
            "rubric_name": self.rubric_name,
            "score_type": self.score_type,
            "score_binary": self.score_binary,
            "score_graded": self.score_graded,
            "max_score": self.max_score,
            "judge_model": self.judge_model,
            "judge_prompt": self.judge_prompt,
            "judge_response": self.judge_response,
            "judge_reasoning": self.judge_reasoning,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "judge_duration_ms": self.judge_duration_ms,
            "judge_tokens_used": self.judge_tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
