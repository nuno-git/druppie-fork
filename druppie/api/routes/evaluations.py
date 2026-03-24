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
    test_names: list[str] | None = None  # Run multiple tests by name
    tag: str | None = None  # Run tests matching a tag
    run_all: bool = False  # Run all tests
    # Phase toggles (seed always runs; only execute and judge are toggleable)
    execute: bool = True  # Phase 2: Run agents with real LLMs + HITL
    judge: bool = True  # Phase 3: Run LLM judge checks


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

    Admin only. Scans the testing/tests directory for YAML test definitions
    and returns their metadata without running anything.

    Returns:
        List of test definition summaries (name, description, sessions, agents, message)
    """
    from pathlib import Path

    import yaml as _yaml

    from druppie.testing.v2_schema import TestFile

    # parents[3] goes from druppie/api/routes/ up to project root (/app/)
    tests_dir = Path(__file__).resolve().parents[3] / "testing" / "tests"
    tests = []
    if tests_dir.exists():
        for path in sorted(tests_dir.glob("*.yaml")):
            data = _yaml.safe_load(path.read_text())
            test_def = TestFile(**data).test
            tests.append({
                "name": test_def.name,
                "description": test_def.description,
                "mode": test_def.mode,
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
                "evals": [
                    {
                        "name": e.eval,
                        "expected": e.expected,
                    }
                    for e in test_def.evals
                ],
            })
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
    # Prevent concurrent runs
    from fastapi.responses import JSONResponse
    for existing in _test_run_status.values():
        if existing.get("status") == "running":
            return JSONResponse(
                status_code=409,
                content={"error": "A test run is already in progress", "status": "busy"},
            )

    run_id = str(uuid_mod.uuid4())
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
    user_id = user.get("sub")

    def _run():
        from druppie.db.database import SessionLocal
        from druppie.repositories.evaluation_repository import EvaluationRepository
        from druppie.testing.v2_runner import TestRunner

        db = SessionLocal()
        try:
            runner = TestRunner(db=db)
            phase_flags = dict(execute=execute, judge=judge, batch_id=run_id)

            # Resolve which tests to run
            tests_to_run = []
            if test_name:
                test_path = runner._testing_dir / "tests" / f"{test_name}.yaml"
                if test_path.exists():
                    tests_to_run.append((test_name, runner.load_test(test_path)))
            elif test_names:
                for name in test_names:
                    test_path = runner._testing_dir / "tests" / f"{name}.yaml"
                    if test_path.exists():
                        tests_to_run.append((name, runner.load_test(test_path)))
            elif tag:
                all_tests = runner.load_all_tests()
                for _path, test_def in all_tests:
                    for eval_ref in test_def.evals:
                        eval_def = runner._evals.get(eval_ref.eval)
                        if eval_def and tag in eval_def.tags:
                            tests_to_run.append((test_def.name, test_def))
                            break
            elif run_all:
                all_tests = runner.load_all_tests()
                tests_to_run = [(td.name, td) for _p, td in all_tests]

            total = len(tests_to_run)
            _test_run_status[run_id]["total_tests"] = total
            _test_run_status[run_id]["message"] = f"Running 0/{total} tests..."

            all_results = []
            for idx, (name, test_def) in enumerate(tests_to_run):
                # Update status: which test is running now
                _test_run_status[run_id]["current_test"] = name
                _test_run_status[run_id]["message"] = f"Running {idx + 1}/{total}: {name}"

                try:
                    test_results = runner.run_test(test_def, **phase_flags)
                    all_results.extend(test_results)

                    # Update completed list
                    for r in test_results:
                        _test_run_status[run_id]["completed_tests"].append({
                            "test_name": r.test_name,
                            "status": r.status,
                            "duration_ms": r.duration_ms,
                        })
                except Exception as test_err:
                    logger.error("test_failed", test=name, error=str(test_err), exc_info=True)
                    _test_run_status[run_id]["completed_tests"].append({
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

            _test_run_status[run_id] = {
                "status": "completed",
                "message": f"{passed}/{result['total']} passed",
                "results": result,
                "current_test": None,
                "completed_tests": _test_run_status[run_id]["completed_tests"],
                "total_tests": total,
            }
        except Exception as e:
            logger.error("tests_run_error", run_id=run_id, error=str(e), exc_info=True)
            _test_run_status[run_id] = {
                "status": "error",
                "message": str(e),
                "results": None,
                "current_test": None,
                "completed_tests": _test_run_status[run_id].get("completed_tests", []),
                "total_tests": _test_run_status[run_id].get("total_tests", 0),
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
    import re
    import subprocess

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "druppie/tests/", "-v", "--tb=short", "-rs"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )

        # Parse verbose pytest output.
        # Lines look like:
        #   druppie/tests/test_seed_ids.py::test_func PASSED
        #   druppie/tests/test_eval_judge.py::TestClass::test_method SKIPPED (reason)
        #   druppie/tests/test_foo.py::test_bar FAILED
        lines = result.stdout.strip().split("\n")
        tests = []
        test_line_re = re.compile(
            r"^([\w/\\.]+\.py)"  # file path
            r"::"
            r"([\w:]+)"  # class::method or just method
            r"\s+"
            r"(PASSED|FAILED|SKIPPED|ERROR)"  # status
            r"(.*)?$"  # optional tail (skip reason, etc.)
        )

        for line in lines:
            m = test_line_re.search(line.strip())
            if not m:
                continue
            file_path = m.group(1)
            name_part = m.group(2)
            status = m.group(3).lower()
            tail = (m.group(4) or "").strip()

            # Split class::method if present
            if "::" in name_part:
                cls_name, method_name = name_part.split("::", 1)
            else:
                cls_name = None
                method_name = name_part

            # Extract file basename
            file_name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

            # Extract reason from tail (e.g. "(reason text here)")
            reason = None
            if tail:
                reason_match = re.search(r"\((.+)\)", tail)
                if reason_match:
                    reason = reason_match.group(1)

            tests.append({
                "file": file_name,
                "class": cls_name,
                "name": method_name,
                "status": status,
                "reason": reason,
            })

        # Parse summary line for duration.
        # Example: "= 85 passed, 12 skipped, 6 warnings in 1.11s ="
        summary = ""
        duration_seconds = None
        for line in reversed(lines):
            if "passed" in line or "failed" in line:
                summary = line.strip().strip("=").strip()
                dur_match = re.search(r"in\s+([\d.]+)s", line)
                if dur_match:
                    duration_seconds = float(dur_match.group(1))
                break

        # Also capture FAILED test details from --tb=short output
        failure_details: dict[str, str] = {}
        in_failure = False
        current_test_key = None
        failure_lines: list[str] = []
        for line in lines:
            if line.startswith("FAILED "):
                # e.g. "FAILED druppie/tests/test_foo.py::test_bar - AssertionError: ..."
                parts = line.split(" - ", 1)
                key = parts[0].replace("FAILED ", "").strip()
                msg = parts[1].strip() if len(parts) > 1 else ""
                failure_details[key] = msg

        # Enrich tests with failure messages
        for t in tests:
            if t["status"] == "failed":
                # Build lookup key: file::class::method or file::method
                if t["class"]:
                    key = f"druppie/tests/{t['file']}::{t['class']}::{t['name']}"
                else:
                    key = f"druppie/tests/{t['file']}::{t['name']}"
                if key in failure_details:
                    t["reason"] = failure_details[key]

        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "summary": summary,
            "total": len(tests),
            "passed": sum(1 for t in tests if t["status"] == "passed"),
            "failed": sum(1 for t in tests if t["status"] == "failed"),
            "skipped": sum(1 for t in tests if t["status"] == "skipped"),
            "tests": tests,
            "output": result.stdout,
            "errors": result.stderr if result.returncode != 0 else "",
            "duration_seconds": duration_seconds,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "summary": "Timeout after 120 seconds",
            "total": 0, "passed": 0, "failed": 0, "skipped": 0,
            "tests": [], "output": "", "errors": "Timeout",
            "duration_seconds": None,
        }
    except Exception as e:
        return {
            "status": "error",
            "summary": str(e),
            "total": 0, "passed": 0, "failed": 0, "skipped": 0,
            "tests": [], "output": "", "errors": str(e),
            "duration_seconds": None,
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


# =============================================================================
# ANALYTICS ENDPOINTS (v3)
# =============================================================================


@router.get("/evaluations/analytics/summary")
async def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Global analytics summary: totals, pass rate, avg duration."""
    from datetime import timedelta

    from druppie.db.models import TestRun as TestRunModel

    db = service.eval_repo.db
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    runs = (
        db.query(TestRunModel)
        .filter(TestRunModel.created_at >= cutoff)
        .all()
    )
    total = len(runs)
    passed = sum(1 for r in runs if r.status == "passed")
    failed = total - passed
    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    return {
        "total_runs": total,
        "total_passed": passed,
        "total_failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "avg_duration_ms": avg_duration,
    }


@router.get("/evaluations/analytics/trends")
async def get_analytics_trends(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Pass rate trends over time, grouped by day."""
    from collections import defaultdict
    from datetime import timedelta

    from druppie.db.models import TestRun as TestRunModel

    db = service.eval_repo.db
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    runs = (
        db.query(TestRunModel)
        .filter(TestRunModel.created_at >= cutoff)
        .order_by(TestRunModel.created_at)
        .all()
    )

    by_day: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for r in runs:
        day = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        by_day[day]["total"] += 1
        if r.status == "passed":
            by_day[day]["passed"] += 1
        else:
            by_day[day]["failed"] += 1

    return [
        {
            "date": day,
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
            "pass_rate": round(data["passed"] / data["total"] * 100, 1) if data["total"] else 0,
        }
        for day, data in sorted(by_day.items())
    ]


@router.get("/evaluations/analytics/by-agent")
async def get_analytics_by_agent(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by agent."""
    from collections import defaultdict

    from druppie.db.models import TestAssertionResult, TestRun as TestRunModel

    db = service.eval_repo.db
    query = db.query(TestAssertionResult)
    if batch_id:
        query = query.join(TestRunModel).filter(TestRunModel.batch_id == batch_id)

    results = query.filter(TestAssertionResult.agent_id.isnot(None)).all()

    by_agent: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for r in results:
        agent = r.agent_id or "unknown"
        by_agent[agent]["total"] += 1
        if r.passed:
            by_agent[agent]["passed"] += 1
        else:
            by_agent[agent]["failed"] += 1

    return [
        {
            "agent": agent,
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
            "pass_rate": round(data["passed"] / data["total"] * 100, 1) if data["total"] else 0,
        }
        for agent, data in sorted(by_agent.items())
    ]


@router.get("/evaluations/analytics/by-eval")
async def get_analytics_by_eval(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by eval name."""
    from collections import defaultdict

    from druppie.db.models import TestAssertionResult, TestRun as TestRunModel

    db = service.eval_repo.db
    query = db.query(TestAssertionResult)
    if batch_id:
        query = query.join(TestRunModel).filter(TestRunModel.batch_id == batch_id)

    results = query.filter(TestAssertionResult.eval_name.isnot(None)).all()

    by_eval: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for r in results:
        name = r.eval_name or "unknown"
        by_eval[name]["total"] += 1
        if r.passed:
            by_eval[name]["passed"] += 1
        else:
            by_eval[name]["failed"] += 1

    return [
        {
            "eval_name": name,
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
            "pass_rate": round(data["passed"] / data["total"] * 100, 1) if data["total"] else 0,
        }
        for name, data in sorted(by_eval.items())
    ]


@router.get("/evaluations/analytics/by-tool")
async def get_analytics_by_tool(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by tool name."""
    from collections import defaultdict

    from druppie.db.models import TestAssertionResult, TestRun as TestRunModel

    db = service.eval_repo.db
    query = db.query(TestAssertionResult)
    if batch_id:
        query = query.join(TestRunModel).filter(TestRunModel.batch_id == batch_id)

    results = query.filter(TestAssertionResult.tool_name.isnot(None)).all()

    by_tool: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for r in results:
        tool = r.tool_name or "unknown"
        by_tool[tool]["total"] += 1
        if r.passed:
            by_tool[tool]["passed"] += 1
        else:
            by_tool[tool]["failed"] += 1

    return [
        {
            "tool": tool,
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
            "pass_rate": round(data["passed"] / data["total"] * 100, 1) if data["total"] else 0,
        }
        for tool, data in sorted(by_tool.items())
    ]


@router.get("/evaluations/analytics/by-test")
async def get_analytics_by_test(
    batch_id: str | None = Query(default=None),
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Results grouped by test name."""
    from collections import defaultdict

    from druppie.db.models import TestRun as TestRunModel

    db = service.eval_repo.db
    query = db.query(TestRunModel)
    if batch_id:
        query = query.filter(TestRunModel.batch_id == batch_id)

    runs = query.all()

    by_test: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0, "durations": []}
    )
    for r in runs:
        name = r.test_name
        by_test[name]["total"] += 1
        if r.status == "passed":
            by_test[name]["passed"] += 1
        else:
            by_test[name]["failed"] += 1
        if r.duration_ms is not None:
            by_test[name]["durations"].append(r.duration_ms)

    return [
        {
            "test_name": name,
            "total": data["total"],
            "passed": data["passed"],
            "failed": data["failed"],
            "pass_rate": round(data["passed"] / data["total"] * 100, 1) if data["total"] else 0,
            "avg_duration_ms": int(sum(data["durations"]) / len(data["durations"])) if data["durations"] else 0,
        }
        for name, data in sorted(by_test.items())
    ]


@router.get("/evaluations/analytics/batch/{batch_id}")
async def get_analytics_batch_detail(
    batch_id: str,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Detailed analytics for a single batch."""
    from collections import defaultdict

    from druppie.db.models import TestAssertionResult, TestRun as TestRunModel

    db = service.eval_repo.db
    runs = (
        db.query(TestRunModel)
        .filter(TestRunModel.batch_id == batch_id)
        .all()
    )
    if not runs:
        return {"batch_id": batch_id, "total": 0, "passed": 0, "failed": 0}

    total = len(runs)
    passed = sum(1 for r in runs if r.status == "passed")
    failed = total - passed
    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    total_duration = sum(durations) if durations else 0
    created_at = min(r.created_at for r in runs if r.created_at) if runs else None

    # Per-agent breakdown from assertion results
    run_ids = [r.id for r in runs]
    assertion_results = (
        db.query(TestAssertionResult)
        .filter(TestAssertionResult.test_run_id.in_(run_ids))
        .all()
    )

    by_agent: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    by_eval: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    for ar in assertion_results:
        if ar.agent_id:
            by_agent[ar.agent_id]["total"] += 1
            if ar.passed:
                by_agent[ar.agent_id]["passed"] += 1
            else:
                by_agent[ar.agent_id]["failed"] += 1
        if ar.eval_name:
            by_eval[ar.eval_name]["total"] += 1
            if ar.passed:
                by_eval[ar.eval_name]["passed"] += 1
            else:
                by_eval[ar.eval_name]["failed"] += 1

    return {
        "batch_id": batch_id,
        "created_at": created_at.isoformat() if created_at else None,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "duration_ms": total_duration,
        "by_agent": [
            {"agent": a, **d, "pass_rate": round(d["passed"] / d["total"] * 100, 1) if d["total"] else 0}
            for a, d in sorted(by_agent.items())
        ],
        "by_eval": [
            {"eval_name": e, **d, "pass_rate": round(d["passed"] / d["total"] * 100, 1) if d["total"] else 0}
            for e, d in sorted(by_eval.items())
        ],
        "by_test": [
            {
                "test_name": r.test_name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "hitl_profile": r.hitl_profile,
                "judge_profile": r.judge_profile,
                "assertions_total": r.assertions_total,
                "assertions_passed": r.assertions_passed,
                "judge_checks_total": r.judge_checks_total,
                "judge_checks_passed": r.judge_checks_passed,
                "assertion_results": [ar.to_dict() for ar in assertion_results if ar.test_run_id == r.id],
            }
            for r in runs
        ],
    }


@router.get("/evaluations/test-runs/{test_run_id}/assertions")
async def get_test_run_assertions(
    test_run_id: UUID,
    user: dict = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Get detailed assertion results for a test run."""
    from druppie.db.models import TestAssertionResult

    db = service.eval_repo.db
    results = (
        db.query(TestAssertionResult)
        .filter(TestAssertionResult.test_run_id == test_run_id)
        .order_by(TestAssertionResult.created_at)
        .all()
    )
    return [r.to_dict() for r in results]
