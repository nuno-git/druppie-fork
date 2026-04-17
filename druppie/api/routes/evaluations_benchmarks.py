"""Benchmark runs and evaluation results routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_evaluation_service, require_admin
from druppie.domain.evaluation import (
    BenchmarkRunDetail,
    BenchmarkRunSummary,
    EvaluationResultDetail,
    EvaluationResultSummary,
)
from druppie.services import EvaluationService

logger = structlog.get_logger()
router = APIRouter()


class PaginatedBenchmarkRuns(BaseModel):
    items: list[BenchmarkRunSummary]
    total: int
    page: int
    limit: int


class PaginatedEvaluationResults(BaseModel):
    items: list[EvaluationResultSummary]
    total: int
    page: int
    limit: int


class AgentSummaryResponse(BaseModel):
    agent_id: str
    total: int
    binary_pass_rate: float | None = None
    graded_avg: float | None = None


@router.get("/evaluations/benchmark-runs", response_model=PaginatedBenchmarkRuns)
async def list_benchmark_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    run_type: str | None = Query(None),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> PaginatedBenchmarkRuns:
    """List benchmark runs with pagination."""
    runs, total = service.list_benchmark_runs(page=page, limit=limit, run_type=run_type)
    return PaginatedBenchmarkRuns(items=runs, total=total, page=page, limit=limit)


@router.get("/evaluations/benchmark-runs/{run_id}", response_model=BenchmarkRunDetail)
async def get_benchmark_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> BenchmarkRunDetail:
    """Get benchmark run detail with results."""
    return service.get_benchmark_run_detail(run_id)


@router.delete("/evaluations/benchmark-runs/{run_id}")
async def delete_benchmark_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Delete a benchmark run and its results."""
    service.delete_benchmark_run(run_id)
    logger.info("benchmark_run_deleted_via_api", run_id=str(run_id), user_id=user.get("sub"))
    return {"success": True, "message": "Benchmark run deleted"}


@router.get("/evaluations/results", response_model=PaginatedEvaluationResults)
async def list_results(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    benchmark_run_id: UUID | None = Query(None),
    agent_id: str | None = Query(None),
    evaluation_name: str | None = Query(None),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> PaginatedEvaluationResults:
    """List evaluation results with optional filters."""
    results, total = service.list_results(
        benchmark_run_id=benchmark_run_id, agent_id=agent_id,
        evaluation_name=evaluation_name, page=page, limit=limit,
    )
    return PaginatedEvaluationResults(items=results, total=total, page=page, limit=limit)


@router.get("/evaluations/results/{result_id}", response_model=EvaluationResultDetail)
async def get_result(
    result_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> EvaluationResultDetail:
    """Get a single evaluation result with full details."""
    return service.get_result_detail(result_id)


@router.get("/evaluations/agent-summary/{agent_id}", response_model=AgentSummaryResponse)
async def get_agent_summary(
    agent_id: str,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> AgentSummaryResponse:
    """Get aggregated evaluation summary for an agent."""
    summary = service.get_agent_summary(agent_id)
    return AgentSummaryResponse(agent_id=agent_id, **summary)


@router.get("/evaluations/config")
async def get_evaluation_config(user: dict = Depends(require_admin)):
    """Get the live evaluation configuration."""
    from druppie.testing.eval_config import get_evaluation_config as _get_config

    config = _get_config()
    return {
        "enabled": config.enabled,
        "sample_rate": config.sample_rate,
        "judge_model": config.judge_model,
        "agent_evaluations": config.agent_evaluations,
    }
