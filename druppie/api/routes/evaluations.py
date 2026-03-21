"""Evaluations API routes.

Admin-only endpoints for viewing benchmark runs, evaluation results,
and triggering new benchmark scenarios.

Architecture:
    Route (this file)
      |
      +---> EvaluationService ---> EvaluationRepository ---> Database
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import structlog

from druppie.api.deps import (
    get_evaluation_service,
    require_admin,
)
from druppie.domain.evaluation import (
    BenchmarkRunDetail,
    BenchmarkRunSummary,
    EvaluationResultDetail,
    EvaluationResultSummary,
)
from druppie.services import EvaluationService

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class PaginatedBenchmarkRuns(BaseModel):
    """Paginated list of benchmark runs."""

    items: list[BenchmarkRunSummary]
    total: int
    page: int
    limit: int


class PaginatedEvaluationResults(BaseModel):
    """Paginated list of evaluation results."""

    items: list[EvaluationResultSummary]
    total: int
    page: int
    limit: int


class TriggerBenchmarkRequest(BaseModel):
    """Request body for triggering a benchmark run."""

    scenario_name: str
    judge_model: str | None = None


class TriggerBenchmarkResponse(BaseModel):
    """Response for a triggered benchmark run."""

    success: bool
    benchmark_run_id: str
    message: str


class AgentSummaryResponse(BaseModel):
    """Aggregated evaluation summary for an agent."""

    agent_id: str
    total: int
    binary_pass_rate: float | None = None
    graded_avg: float | None = None


# =============================================================================
# ROUTES
# =============================================================================


@router.get(
    "/evaluations/benchmark-runs",
    response_model=PaginatedBenchmarkRuns,
)
async def list_benchmark_runs(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    run_type: str | None = Query(None, description="Filter by run type (batch, live, manual)"),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> PaginatedBenchmarkRuns:
    """List benchmark runs with pagination.

    Admin only. Optionally filter by run_type.

    Query Parameters:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        run_type: Optional filter (batch, live, manual)

    Returns:
        Paginated list of BenchmarkRunSummary objects
    """
    runs, total = service.list_benchmark_runs(
        page=page,
        limit=limit,
        run_type=run_type,
    )

    return PaginatedBenchmarkRuns(
        items=runs,
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/evaluations/benchmark-runs/{run_id}",
    response_model=BenchmarkRunDetail,
)
async def get_benchmark_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> BenchmarkRunDetail:
    """Get benchmark run detail with results.

    Admin only.

    Args:
        run_id: Benchmark run UUID

    Returns:
        Full benchmark run detail with evaluation results

    Raises:
        NotFoundError: Benchmark run not found
    """
    return service.get_benchmark_run_detail(run_id)


@router.delete("/evaluations/benchmark-runs/{run_id}")
async def delete_benchmark_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Delete a benchmark run and its results.

    Admin only.

    Args:
        run_id: Benchmark run UUID

    Returns:
        Success confirmation

    Raises:
        NotFoundError: Benchmark run not found
    """
    service.delete_benchmark_run(run_id)

    logger.info("benchmark_run_deleted_via_api", run_id=str(run_id), user_id=user.get("sub"))
    return {"success": True, "message": "Benchmark run deleted"}


@router.get(
    "/evaluations/results",
    response_model=PaginatedEvaluationResults,
)
async def list_results(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    benchmark_run_id: UUID | None = Query(None, description="Filter by benchmark run"),
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    evaluation_name: str | None = Query(None, description="Filter by evaluation name"),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> PaginatedEvaluationResults:
    """List evaluation results with optional filters.

    Admin only. Filter by benchmark_run_id, agent_id, and/or evaluation_name.

    Query Parameters:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        benchmark_run_id: Optional filter by benchmark run UUID
        agent_id: Optional filter by agent ID
        evaluation_name: Optional filter by evaluation name

    Returns:
        Paginated list of EvaluationResultSummary objects
    """
    results, total = service.list_results(
        benchmark_run_id=benchmark_run_id,
        agent_id=agent_id,
        evaluation_name=evaluation_name,
        page=page,
        limit=limit,
    )

    return PaginatedEvaluationResults(
        items=results,
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/evaluations/results/{result_id}",
    response_model=EvaluationResultDetail,
)
async def get_result(
    result_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> EvaluationResultDetail:
    """Get a single evaluation result with full details.

    Admin only.

    Args:
        result_id: Evaluation result UUID

    Returns:
        Full evaluation result detail including judge prompt/response

    Raises:
        NotFoundError: Evaluation result not found
    """
    return service.get_result_detail(result_id)


@router.get(
    "/evaluations/agent-summary/{agent_id}",
    response_model=AgentSummaryResponse,
)
async def get_agent_summary(
    agent_id: str,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> AgentSummaryResponse:
    """Get aggregated evaluation summary for an agent.

    Admin only. Returns pass rate and graded average scores.

    Args:
        agent_id: Agent identifier

    Returns:
        Summary with total count, binary pass rate, and graded average
    """
    summary = service.get_agent_summary(agent_id)
    return AgentSummaryResponse(
        agent_id=agent_id,
        **summary,
    )


@router.post(
    "/evaluations/trigger-benchmark",
    response_model=TriggerBenchmarkResponse,
)
async def trigger_benchmark(
    body: TriggerBenchmarkRequest,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
) -> TriggerBenchmarkResponse:
    """Trigger a benchmark scenario run.

    Admin only. Loads a scenario YAML and runs all evaluations.

    Args:
        body: Scenario name and optional judge model override

    Returns:
        Created benchmark run ID

    Raises:
        HTTPException 404: Scenario YAML not found
    """
    try:
        benchmark_run_id = service.trigger_benchmark(
            scenario_name=body.scenario_name,
            judge_model=body.judge_model,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(
        "benchmark_triggered_via_api",
        scenario=body.scenario_name,
        benchmark_run_id=str(benchmark_run_id),
        user_id=user.get("sub"),
    )

    return TriggerBenchmarkResponse(
        success=True,
        benchmark_run_id=str(benchmark_run_id),
        message=f"Benchmark '{body.scenario_name}' started",
    )


@router.get("/evaluations/config")
async def get_evaluation_config(
    user: dict = Depends(require_admin),
):
    """Get the live evaluation configuration.

    Admin only. Returns the current evaluation config from YAML.

    Returns:
        Current live evaluation config (enabled, sample_rate, agent_evaluations, etc.)
    """
    from druppie.testing.eval_config import get_evaluation_config as _get_config

    config = _get_config()
    return {
        "enabled": config.enabled,
        "sample_rate": config.sample_rate,
        "judge_model": config.judge_model,
        "agent_evaluations": config.agent_evaluations,
    }
