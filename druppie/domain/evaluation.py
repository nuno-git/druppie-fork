"""Domain models for evaluation results."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EvaluationResultSummary(BaseModel):
    """Lightweight evaluation result for lists."""

    id: UUID
    agent_id: str
    evaluation_name: str
    rubric_name: str
    score_type: str
    score_binary: bool | None = None
    score_graded: float | None = None
    max_score: float | None = None
    created_at: datetime


class EvaluationResultDetail(EvaluationResultSummary):
    """Full evaluation result with judge details."""

    benchmark_run_id: UUID
    session_id: UUID
    agent_run_id: UUID
    judge_model: str
    judge_prompt: str
    judge_response: str | None = None
    judge_reasoning: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    judge_duration_ms: int | None = None
    judge_tokens_used: int | None = None


class BenchmarkRunSummary(BaseModel):
    """Lightweight benchmark run for lists."""

    id: UUID
    name: str
    run_type: str
    git_commit: str | None = None
    git_branch: str | None = None
    judge_model: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class BenchmarkRunDetail(BenchmarkRunSummary):
    """Full benchmark run with results."""

    config_summary: str | None = None
    results: list[EvaluationResultSummary] = []
