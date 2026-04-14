"""Evaluations API routes.

Admin-only endpoints for viewing benchmark runs, evaluation results,
and running v2 tests.

Architecture:
    Route (this file)
      |
      +---> EvaluationService ---> EvaluationRepository ---> Database
"""

import threading
import uuid as uuid_mod
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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

# In-memory store for background test run status.
# Persisted to DB via batch_id — the in-memory dict is for live progress updates.
# On restart, active-run endpoint checks DB for incomplete batches.
# _run_lock protects ALL reads and writes to _test_run_status and _active_run_id.
_run_lock = threading.Lock()
_test_run_status: dict[str, dict] = {}
_active_run_id: str | None = None  # currently running batch_id


def _update_run_status(run_id: str, **updates: object) -> None:
    """Thread-safe update of run status fields."""
    with _run_lock:
        if run_id in _test_run_status:
            _test_run_status[run_id].update(updates)


def _set_run_status(run_id: str, status: dict) -> None:
    """Thread-safe full replacement of run status."""
    with _run_lock:
        _test_run_status[run_id] = status


def _get_run_status_snapshot(run_id: str) -> dict | None:
    """Thread-safe read of run status."""
    with _run_lock:
        status = _test_run_status.get(run_id)
        return dict(status) if status else None


def _append_completed_test(run_id: str, test_info: dict) -> None:
    """Thread-safe append to completed_tests list."""
    with _run_lock:
        if run_id in _test_run_status:
            _test_run_status[run_id]["completed_tests"].append(test_info)


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
    test_names: list[str] | None = None  # Run multiple tests by name
    tag: str | None = None  # Run tests matching a tag
    run_all: bool = False  # Run all tests
    # Phase toggles (seed always runs; only execute and judge are toggleable)
    execute: bool = True  # Phase 2: Run agents with real LLMs + HITL
    judge: bool = True  # Phase 3: Run LLM judge checks
    # Manual input values: {input_name: value} for manual tests
    input_values: dict[str, str] | None = None



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


# =============================================================================
# V2 TEST RUN ENDPOINTS
# =============================================================================


@router.get("/evaluations/available-tests")
async def list_available_tests(
    user: dict = Depends(require_admin),
):
    """List all test YAML definitions (not results).

    Admin only. Scans testing/tools/, testing/agents/, and testing/agents/manual/
    for YAML test definitions and returns their metadata.
    """
    from pathlib import Path

    import yaml as _yaml

    from druppie.testing.schema import AgentTestFile, ToolTestFile

    base_dir = Path(__file__).resolve().parents[3] / "testing"
    tests = []

    # Scan tool tests
    tools_dir = base_dir / "tools"
    if tools_dir.exists():
        for path in sorted(tools_dir.glob("*.yaml")):
            try:
                data = _yaml.safe_load(path.read_text())
                test_def = ToolTestFile(**data).tool_test
                tests.append({
                    "name": test_def.name,
                    "description": test_def.description,
                    "type": "tool",
                    "manual_input": False,
                    "inputs": [],
                    "setup": test_def.setup,
                    "agents": [],
                    "message": "",
                    "hitl": "none",
                    "judge": "none",
                    "num_sessions": len(test_def.setup),
                    "tags": test_def.tags,
                    "extends": test_def.extends,
                    "checks": [],
                })
            except Exception as e:
                logger.warning("Failed to load tool test %s: %s", path, e)

    # Scan agent tests (including manual/)
    for subdir in ["agents", "agents/manual"]:
        agents_dir = base_dir / subdir
        if not agents_dir.exists():
            continue
        for path in sorted(agents_dir.glob("*.yaml")):
            try:
                data = _yaml.safe_load(path.read_text())
                test_def = AgentTestFile(**data).agent_test
                tests.append({
                    "name": test_def.name,
                    "description": test_def.description,
                    "type": "agent" if not test_def.is_manual else "manual",
                    "manual_input": test_def.is_manual,
                    "inputs": [
                        {
                            "name": inp.name,
                            "label": inp.label or inp.name,
                            "type": inp.type,
                            "required": inp.required,
                            "default": inp.default,
                            "options": inp.options,
                        }
                        for inp in test_def.inputs
                    ] if test_def.inputs else [],
                    "setup": test_def.setup,
                    "agents": test_def.agents,
                    "message": test_def.message,
                    "hitl": (
                        test_def.hitl
                        if isinstance(test_def.hitl, str)
                        else "inline" if test_def.hitl else "default"
                    ),
                    "judge": test_def.judge_profile or "default",
                    "num_sessions": len(test_def.setup),
                    "tags": test_def.tags,
                    "extends": test_def.extends,
                    "checks": [
                        {"name": c.check, "expected": c.expected}
                        for c in test_def.assert_
                    ],
                })
            except Exception as e:
                logger.warning("Failed to load agent test %s: %s", path, e)

    return tests




@router.post("/evaluations/run-tests")
async def run_tests(
    body: RunTestsRequest,
    user: dict = Depends(require_admin),
):
    """Start test execution in the background. Returns a run_id to poll status.

    Admin only. Returns immediately with a run_id. Poll /run-status/{run_id}
    for progress and results. Tests run one-by-one with per-test status updates.

    Returns 409 if a test run is already in progress.
    """
    # Prevent concurrent runs (lock protects check-then-set)
    global _active_run_id
    from fastapi.responses import JSONResponse
    with _run_lock:
        if _active_run_id and _active_run_id in _test_run_status:
            if _test_run_status[_active_run_id].get("status") == "running":
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "A test run is already in progress",
                        "status": "busy",
                        "run_id": _active_run_id,
                    },
                )

        run_id = str(uuid_mod.uuid4())
        _active_run_id = run_id
        _test_run_status[run_id] = {
            "status": "running",
            "message": "Loading tests...",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "results": None,
            "current_test": None,
            "completed_tests": [],
            "total_tests": 0,
        }

    test_name = body.test_name
    test_names = body.test_names
    tag = body.tag
    run_all = body.run_all
    execute = body.execute
    judge = body.judge
    input_values = body.input_values or {}
    user_id = user.get("sub")

    def _run():
        from druppie.db.database import SessionLocal
        from druppie.repositories.evaluation_repository import EvaluationRepository
        from druppie.testing.runner import TestRunner

        import os
        db = SessionLocal()
        try:
            gitea_url = os.getenv("GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000"))
            runner = TestRunner(db=db, gitea_url=gitea_url)
            phase_flags = dict(execute=execute, judge=judge, batch_id=run_id)

            def _find_test(name):
                """Find test YAML in tools/, agents/, or agents/manual/."""
                # Reject path traversal attempts
                if "/" in name or "\\" in name or ".." in name:
                    logger.warning("Rejected test name with path characters: %s", name)
                    return None
                for subdir in ["tools", "agents", "agents/manual"]:
                    p = runner._testing_dir / subdir / f"{name}.yaml"
                    if p.exists():
                        return p
                return None

            def _load_and_resolve(name):
                """Load test and resolve manual inputs."""
                path = _find_test(name)
                if not path:
                    return None
                test_def = runner.load_test(path)
                if hasattr(test_def, "is_manual") and test_def.is_manual and input_values:
                    test_def = test_def.resolve_inputs(input_values)
                elif hasattr(test_def, "manual_input") and test_def.manual_input and input_values:
                    test_def = test_def.resolve_inputs(input_values)
                return test_def

            # Resolve which tests to run
            tests_to_run = []
            if test_name:
                td = _load_and_resolve(test_name)
                if td:
                    tests_to_run.append((test_name, td))
            elif test_names:
                for name in test_names:
                    td = _load_and_resolve(name)
                    if td:
                        tests_to_run.append((name, td))
            elif tag:
                all_tests = runner.load_all_tests()
                for _path, test_def in all_tests:
                    # Check tags on the test itself
                    test_tags = getattr(test_def, "tags", [])
                    if tag in test_tags:
                        tests_to_run.append((test_def.name, test_def))
                        continue
                    # Check tags on referenced checks
                    check_refs = getattr(test_def, "assert_", [])
                    for check_ref in check_refs:
                        if hasattr(check_ref, "check"):
                            try:
                                check_def = runner._checks.get(check_ref.check)
                                if check_def and tag in check_def.tags:
                                    tests_to_run.append((test_def.name, test_def))
                                    break
                            except KeyError:
                                pass
            elif run_all:
                all_tests = runner.load_all_tests()
                tests_to_run = [(td.name, td) for _p, td in all_tests]

            total = len(tests_to_run)
            _update_run_status(run_id, total_tests=total, message=f"Running 0/{total} tests...")

            all_results = []
            for idx, (name, test_def) in enumerate(tests_to_run):
                # Update status: which test is running now
                _update_run_status(run_id, current_test=name, message=f"Running {idx + 1}/{total}: {name}")

                try:
                    test_results = runner.run_test(test_def, **phase_flags)
                    all_results.extend(test_results)

                    # Update completed list
                    for r in test_results:
                        _append_completed_test(run_id, {
                            "test_name": r.test_name,
                            "status": r.status,
                            "duration_ms": r.duration_ms,
                        })
                except Exception as test_err:
                    logger.error("test_failed", test=name, error=str(test_err), exc_info=True)
                    _append_completed_test(run_id, {
                        "test_name": name,
                        "status": "error",
                        "duration_ms": 0,
                        "error": str(test_err),
                    })

            db.commit()

            passed = sum(1 for r in all_results if r.status == "passed")
            failed = len(all_results) - passed
            result = {
                "total": len(all_results),
                "passed": passed,
                "failed": failed,
                "results": [
                    {
                        "test_name": r.test_name,
                        "status": r.status,
                        "duration_ms": r.duration_ms,
                    }
                    for r in all_results
                ],
            }

            with _run_lock:
                completed = _test_run_status[run_id]["completed_tests"]
            _set_run_status(run_id, {
                "status": "completed",
                "message": f"{passed}/{result['total']} passed",
                "results": result,
                "current_test": None,
                "completed_tests": completed,
                "total_tests": total,
            })
        except Exception as e:
            logger.error("tests_run_error", run_id=run_id, error=str(e), exc_info=True)
            with _run_lock:
                prev = _test_run_status.get(run_id, {})
                completed = prev.get("completed_tests", [])
                total_tests = prev.get("total_tests", 0)
            _set_run_status(run_id, {
                "status": "error",
                "message": str(e),
                "results": None,
                "current_test": None,
                "completed_tests": completed,
                "total_tests": total_tests,
            })
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            global _active_run_id
            with _run_lock:
                _active_run_id = None
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
    status = _get_run_status_snapshot(run_id)
    if not status:
        return {"status": "not_found"}
    return status


@router.get("/evaluations/active-run")
async def get_active_run(
    user: dict = Depends(require_admin),
):
    """Check if a test run is currently active.

    Returns the active run status (from memory) or indicates no run is active.
    The frontend should call this on page load to restore the running state.
    """
    with _run_lock:
        active_id = _active_run_id
        status = dict(_test_run_status[active_id]) if active_id and active_id in _test_run_status else None
    if status and status.get("status") == "running":
        return {"active": True, "run_id": active_id, **status}
    return {"active": False}


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


@router.get("/evaluations/test-batches")
async def list_test_batches(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    tag: str | None = Query(None, description="Filter by tag"),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List test runs grouped by batch (each Run click = one batch).

    Admin only. Returns batches with summary stats and individual test runs.

    Query Parameters:
        page: Page number (default 1)
        limit: Batches per page (default 10, max 50)
        tag: Optional tag filter

    Returns:
        Paginated list of batch objects, each containing its test runs
    """
    batches, total = service.list_test_batches(page=page, limit=limit, tag=tag)
    total_pages = max(1, (total + limit - 1) // limit)
    return {
        "items": batches,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


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


@router.post("/evaluations/run-unit-tests")
async def run_unit_tests(
    user: dict = Depends(require_admin),
):
    """Run pytest unit tests and return results."""
    return EvaluationService.run_unit_tests()


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


# =============================================================================
# ANALYTICS ENDPOINTS
# =============================================================================


@router.get("/evaluations/analytics/summary")
async def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Global analytics summary: totals, pass rate, avg duration."""
    return service.get_analytics_summary(days)


@router.get("/evaluations/analytics/trends")
async def get_analytics_trends(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Pass rate trends over time, grouped by day."""
    return service.get_analytics_trends(days)


@router.get("/evaluations/analytics/by-agent")
async def get_analytics_by_agent(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by agent."""
    return service.get_analytics_by_agent(batch_id)


@router.get("/evaluations/analytics/by-eval")
async def get_analytics_by_eval(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by eval name."""
    return service.get_analytics_by_eval(batch_id)


@router.get("/evaluations/analytics/by-tool")
async def get_analytics_by_tool(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by tool name."""
    return service.get_analytics_by_tool(batch_id)


@router.get("/evaluations/analytics/by-test")
async def get_analytics_by_test(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by test name."""
    return service.get_analytics_by_test(batch_id)


@router.get("/evaluations/analytics/batch/{batch_id}")
async def get_analytics_batch_detail(
    batch_id: str,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Detailed analytics for a single batch."""
    return service.get_analytics_batch_detail(batch_id)


@router.get("/evaluations/test-runs/{test_run_id}/assertions")
async def get_test_run_assertions(
    test_run_id: UUID,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get detailed assertion results for a test run."""
    return service.get_test_run_assertions(test_run_id)


@router.get("/evaluations/batch/{batch_id}/assertions")
async def get_batch_assertions(
    batch_id: str,
    assertion_type: str | None = Query(None, description="Filter: assertions, judge_check, judge_eval"),
    agent_id: str | None = Query(None, description="Filter by agent"),
    check_text: str | None = Query(None, description="Filter by exact check message text"),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get all assertion results for a batch, optionally filtered."""
    return service.get_batch_assertions(batch_id, assertion_type, agent_id, check_text)


@router.get("/evaluations/batch/{batch_id}/filters")
async def get_batch_filters(
    batch_id: str,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get all unique filterable values for a batch."""
    return service.get_batch_filters(batch_id)
