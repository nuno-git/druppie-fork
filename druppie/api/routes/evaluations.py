"""Evaluations API routes.

Admin-only endpoints for viewing benchmark runs, evaluation results,
and triggering new benchmark scenarios.

Architecture:
    Route (this file)
      |
      +---> EvaluationService ---> EvaluationRepository ---> Database
"""

import threading
import uuid as uuid_mod
from datetime import datetime, timezone
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

# In-memory store for background test run status (no DB needed for this)
_test_run_status: dict[str, dict] = {}


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


class RunTestsRequest(BaseModel):
    """Request body for running v2 tests."""

    test_name: str | None = None  # Run a specific test by name
    tag: str | None = None  # Run tests matching a tag
    run_all: bool = False  # Run all tests
    # Phase toggles (seed always runs; only execute and judge are toggleable)
    execute: bool = True  # Phase 2: Run agents with real LLMs + HITL
    judge: bool = True  # Phase 3: Run LLM judge checks


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


# =============================================================================
# V2 TEST RUN ENDPOINTS
# =============================================================================


@router.get("/evaluations/available-tests")
async def list_available_tests(
    user: dict = Depends(require_admin),
):
    """List all test YAML definitions (not results).

    Admin only. Scans the testing/tests directory for YAML test definitions
    and returns their metadata without running anything.

    Returns:
        List of test definition summaries (name, description, sessions, agents, message)
    """
    from pathlib import Path

    import yaml as _yaml

    from druppie.testing.v2_schema import TestFile

    tests_dir = Path(__file__).resolve().parents[2] / "testing" / "tests"
    tests = []
    if tests_dir.exists():
        for path in sorted(tests_dir.glob("*.yaml")):
            data = _yaml.safe_load(path.read_text())
            test_def = TestFile(**data).test
            tests.append({
                "name": test_def.name,
                "description": test_def.description,
                "sessions": test_def.sessions,
                "real_agents": test_def.run.real_agents,
                "message": test_def.run.message,
                "hitl": (
                    test_def.hitl
                    if isinstance(test_def.hitl, str)
                    else "inline" if test_def.hitl else "default"
                ),
                "judge": test_def.judge or "default",
                "num_sessions": len(test_def.sessions),
            })
    return tests


@router.post("/evaluations/run-tests")
async def run_tests(
    body: RunTestsRequest,
    user: dict = Depends(require_admin),
):
    """Start test execution in the background. Returns a run_id to poll status.

    Admin only. Returns immediately with a run_id. Poll /run-status/{run_id}
    for progress and results.

    Args:
        body: Specifies which tests to run (test_name, tag, or run_all)

    Returns:
        run_id and initial status
    """
    run_id = str(uuid_mod.uuid4())
    _test_run_status[run_id] = {
        "status": "running",
        "message": "Starting tests...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "results": None,
    }

    # Capture request params for the background thread
    test_name = body.test_name
    tag = body.tag
    run_all = body.run_all
    execute = body.execute
    judge = body.judge
    user_id = user.get("sub")

    def _run():
        from druppie.db.database import SessionLocal
        from druppie.repositories.evaluation_repository import EvaluationRepository

        db = SessionLocal()
        try:
            repo = EvaluationRepository(db)
            svc = EvaluationService(repo)

            result = svc.run_tests(
                test_name=test_name,
                tag=tag,
                run_all=run_all,
                execute=execute,
                judge=judge,
            )
            db.commit()

            logger.info(
                "tests_run_via_api",
                run_id=run_id,
                total=result["total"],
                passed=result["passed"],
                failed=result["failed"],
                user_id=user_id,
            )

            _test_run_status[run_id] = {
                "status": "completed",
                "message": f"{result['passed']}/{result['total']} passed",
                "results": result,
            }
        except Exception as e:
            logger.error(
                "tests_run_error",
                run_id=run_id,
                error=str(e),
                exc_info=True,
            )
            _test_run_status[run_id] = {
                "status": "error",
                "message": str(e),
                "results": None,
            }
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    thread = threading.Thread(target=_run, daemon=True, name=f"test-run-{run_id}")
    thread.start()

    return {"run_id": run_id, "status": "running"}


@router.get("/evaluations/run-status/{run_id}")
async def get_run_status(
    run_id: str,
    user: dict = Depends(require_admin),
):
    """Poll for test run status.

    Admin only. Returns the current status and results (when completed)
    for a background test run.

    Args:
        run_id: The run_id returned by POST /evaluations/run-tests

    Returns:
        Status object with status, message, and results (when completed)
    """
    status = _test_run_status.get(run_id)
    if not status:
        return {"status": "not_found"}
    return status


@router.get("/evaluations/test-runs")
async def list_test_runs(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    tag: str | None = Query(None, description="Filter by tag"),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List v2 test runs, optionally filtered by tag.

    Admin only. Returns paginated list of test runs with tags, assertions,
    HITL/judge profile info.

    Query Parameters:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        tag: Optional tag filter

    Returns:
        Paginated list of test run dicts
    """
    items, total = service.list_test_runs(page=page, limit=limit, tag=tag)
    total_pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


@router.get("/evaluations/test-runs/{test_run_id}")
async def get_test_run(
    test_run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Get a single test run with details.

    Admin only.

    Args:
        test_run_id: Test run UUID

    Returns:
        Full test run dict with tags and assertion details

    Raises:
        NotFoundError: Test run not found
    """
    return service.get_test_run_detail(test_run_id)


@router.get("/evaluations/tags")
async def list_tags(
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List all unique tags with test run counts.

    Admin only.

    Returns:
        List of {tag, count} objects
    """
    return service.list_tags()


@router.delete("/evaluations/test-users")
async def delete_test_users(
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Delete all test users (test-*) and their data.

    Admin only. Removes all users whose username matches the test-* pattern,
    along with their sessions, agent runs, tool calls, etc.

    Returns:
        Success confirmation with count of deleted users
    """
    count = service.delete_test_users()
    logger.info(
        "test_users_deleted_via_api",
        count=count,
        user_id=user.get("sub"),
    )
    return {
        "success": True,
        "deleted_count": count,
        "message": f"Deleted {count} test user(s) and their data",
    }


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
