"""Test execution, polling, and test run management routes.

Background test runs are tracked via TestBatchRun in the database,
not in-memory dicts. This means status survives process restarts
and there's no lock/eviction complexity.
"""

import threading
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_evaluation_service, require_admin
from druppie.services import EvaluationService

logger = structlog.get_logger()
router = APIRouter()


class RunTestsRequest(BaseModel):
    """Request body for running tests."""
    test_name: str | None = None
    test_names: list[str] | None = None
    tag: str | None = None
    run_all: bool = False
    execute: bool = True
    judge: bool = True
    input_values: dict[str, str] | None = None


@router.get("/evaluations/available-tests")
async def list_available_tests(user: dict = Depends(require_admin)):
    """List all test YAML definitions."""
    from pathlib import Path
    import yaml as _yaml
    from druppie.testing.schema import AgentTestFile, ToolTestFile

    base_dir = Path(__file__).resolve().parents[3] / "testing"
    tests = []

    tools_dir = base_dir / "tools"
    if tools_dir.exists():
        for path in sorted(tools_dir.glob("*.yaml")):
            try:
                data = _yaml.safe_load(path.read_text())
                test_def = ToolTestFile(**data).tool_test
                tests.append({
                    "name": test_def.name, "description": test_def.description,
                    "type": "tool", "manual_input": False, "inputs": [],
                    "setup": test_def.setup, "agents": [], "message": "",
                    "hitl": "none", "judge": "none",
                    "num_sessions": len(test_def.setup),
                    "tags": test_def.tags, "extends": test_def.extends, "checks": [],
                })
            except Exception as e:
                logger.warning("Failed to load tool test %s: %s", path, e)

    for subdir in ["agents", "agents/manual"]:
        agents_dir = base_dir / subdir
        if not agents_dir.exists():
            continue
        for path in sorted(agents_dir.glob("*.yaml")):
            try:
                data = _yaml.safe_load(path.read_text())
                test_def = AgentTestFile(**data).agent_test
                tests.append({
                    "name": test_def.name, "description": test_def.description,
                    "type": "agent" if not test_def.is_manual else "manual",
                    "manual_input": test_def.is_manual,
                    "inputs": [
                        {"name": inp.name, "label": inp.label or inp.name,
                         "type": inp.type, "required": inp.required,
                         "default": inp.default, "options": inp.options}
                        for inp in test_def.inputs
                    ] if test_def.inputs else [],
                    "setup": test_def.setup, "agents": test_def.agents,
                    "message": test_def.message,
                    "hitl": (test_def.hitl if isinstance(test_def.hitl, str)
                             else "inline" if test_def.hitl else "default"),
                    "judge": test_def.judge_profile or "default",
                    "num_sessions": len(test_def.setup),
                    "tags": test_def.tags, "extends": test_def.extends,
                    "checks": [{"name": c.check, "expected": c.expected}
                               for c in test_def.assert_],
                })
            except Exception as e:
                logger.warning("Failed to load agent test %s: %s", path, e)

    return tests


@router.post("/evaluations/run-tests")
async def run_tests(
    body: RunTestsRequest,
    user: dict = Depends(require_admin),
):
    """Start test execution in the background.

    Returns a run_id to poll status via /run-status/{run_id}.
    Returns 409 if a test run is already in progress.
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories.evaluation_repository import EvaluationRepository

    # Check for active run in DB
    db_check = SessionLocal()
    try:
        repo = EvaluationRepository(db_check)
        active = repo.get_active_batch_run()
        if active:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "A test run is already in progress",
                    "status": "busy",
                    "run_id": active.id,
                },
            )
        run_id = str(uuid_mod.uuid4())
        repo.create_batch_run(run_id)
        db_check.commit()
    finally:
        db_check.close()

    test_name = body.test_name
    test_names = body.test_names
    tag = body.tag
    run_all = body.run_all
    execute = body.execute
    judge = body.judge
    input_values = body.input_values or {}

    def _update_batch(status=None, current_test=None, message=None,
                      total_tests=None, completed_at=None):
        """Update batch run status with a short-lived DB session."""
        _db = SessionLocal()
        try:
            _repo = EvaluationRepository(_db)
            _repo.update_batch_run(
                run_id, status=status, current_test=current_test,
                message=message, total_tests=total_tests,
                completed_at=completed_at,
            )
            _db.commit()
        finally:
            _db.close()

    def _run():
        import os
        from druppie.testing.runner import TestRunner

        # Use a short-lived session just for loading test definitions.
        # Each individual test gets its own session via runner.with_db().
        setup_db = SessionLocal()
        try:
            gitea_url = os.getenv("GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000"))
            runner = TestRunner(db=setup_db, gitea_url=gitea_url)
            phase_flags = dict(execute=execute, judge=judge, batch_id=run_id)

            def _find_test(name):
                if "/" in name or "\\" in name or ".." in name:
                    logger.warning("Rejected test name with path characters: %s", name)
                    return None
                for subdir in ["tools", "agents", "agents/manual"]:
                    p = runner._testing_dir / subdir / f"{name}.yaml"
                    if p.exists():
                        resolved = p.resolve()
                        if not str(resolved).startswith(str(runner._testing_dir.resolve())):
                            logger.warning("Rejected test outside testing dir: %s -> %s", name, resolved)
                            return None
                        return p
                return None

            def _load_and_resolve(name):
                path = _find_test(name)
                if not path:
                    return None
                test_def = runner.load_test(path)
                if hasattr(test_def, "is_manual") and test_def.is_manual and input_values:
                    test_inputs = {}
                    prefix = f"{name}:"
                    for key, val in input_values.items():
                        if key.startswith(prefix):
                            test_inputs[key[len(prefix):]] = val
                        elif ":" not in key:
                            test_inputs[key] = val
                    test_def = test_def.resolve_inputs(test_inputs)
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
                    test_tags = getattr(test_def, "tags", [])
                    if tag in test_tags:
                        tests_to_run.append((test_def.name, test_def))
                        continue
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
        finally:
            setup_db.close()

        total = len(tests_to_run)
        _update_batch(total_tests=total, message=f"Running 0/{total} tests...")

        all_results = []
        test_timeout = int(os.getenv("TEST_TIMEOUT_SECONDS", "600"))  # 10 min default

        try:
            for idx, (name, test_def) in enumerate(tests_to_run):
                _update_batch(current_test=name,
                              message=f"Running {idx + 1}/{total}: {name}")

                try:
                    # Each test gets its own DB session — created and closed
                    # within the worker thread so no cross-thread sharing.
                    def _run_single_test():
                        test_db = SessionLocal()
                        try:
                            test_runner = runner.with_db(test_db)
                            return test_runner.run_test(test_def, **phase_flags)
                        finally:
                            test_db.close()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(_run_single_test)
                        test_results = future.result(timeout=test_timeout)
                    all_results.extend(test_results)
                except FuturesTimeoutError:
                    logger.error("test_timed_out", test=name, timeout=test_timeout)
                    from druppie.testing.runner import TestRunResult
                    all_results.append(TestRunResult(
                        test_name=name, test_user="timeout", test_type="tool",
                        assertion_results=[], status="error",
                        duration_ms=test_timeout * 1000,
                    ))
                except Exception as test_err:
                    logger.error("test_failed", test=name, error=str(test_err), exc_info=True)

            passed = sum(1 for r in all_results if r.status == "passed")
            _update_batch(
                status="completed", current_test=None,
                message=f"{passed}/{len(all_results)} passed",
                completed_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error("tests_run_error", run_id=run_id, error=str(e), exc_info=True)
            try:
                _update_batch(
                    status="error", current_test=None,
                    message=str(e), completed_at=datetime.now(timezone.utc),
                )
            except Exception:
                pass

    thread = threading.Thread(target=_run, daemon=True, name=f"test-run-{run_id}")
    thread.start()

    return {"run_id": run_id, "status": "running"}


@router.get("/evaluations/run-status/{run_id}")
async def get_run_status(
    run_id: str,
    user: dict = Depends(require_admin),
):
    """Poll for test run status from DB."""
    from druppie.db.database import SessionLocal
    from druppie.repositories.evaluation_repository import EvaluationRepository

    db = SessionLocal()
    try:
        repo = EvaluationRepository(db)
        batch = repo.get_batch_run(run_id)
        if not batch:
            return JSONResponse(status_code=404, content={"status": "not_found"})

        completed_tests = repo.get_completed_test_runs(run_id)

        return {
            "status": batch.status,
            "message": batch.message,
            "current_test": batch.current_test,
            "total_tests": batch.total_tests,
            "completed_tests": completed_tests,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "results": {
                "total": len(completed_tests),
                "passed": sum(1 for t in completed_tests if t["status"] == "passed"),
                "failed": sum(1 for t in completed_tests if t["status"] != "passed"),
                "results": completed_tests,
            },
        }
    finally:
        db.close()


@router.get("/evaluations/active-run")
async def get_active_run(user: dict = Depends(require_admin)):
    """Check if a test run is currently active."""
    from druppie.db.database import SessionLocal
    from druppie.repositories.evaluation_repository import EvaluationRepository

    db = SessionLocal()
    try:
        repo = EvaluationRepository(db)
        active = repo.get_active_batch_run()
        if not active:
            return {"active": False}

        completed_tests = repo.get_completed_test_runs(active.id)
        return {
            "active": True,
            "run_id": active.id,
            "status": active.status,
            "message": active.message,
            "current_test": active.current_test,
            "total_tests": active.total_tests,
            "completed_tests": completed_tests,
        }
    finally:
        db.close()


@router.get("/evaluations/test-runs")
async def list_test_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List test runs, optionally filtered by tag."""
    items, total = service.list_test_runs(page=page, limit=limit, tag=tag)
    total_pages = max(1, (total + limit - 1) // limit)
    return {"items": items, "total": total, "page": page, "limit": limit, "total_pages": total_pages}


@router.get("/evaluations/test-runs/{test_run_id}")
async def get_test_run(
    test_run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Get a single test run with details."""
    return service.get_test_run_detail(test_run_id)


@router.get("/evaluations/test-batches")
async def list_test_batches(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    tag: str | None = Query(None),
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List test runs grouped by batch."""
    batches, total = service.list_test_batches(page=page, limit=limit, tag=tag)
    total_pages = max(1, (total + limit - 1) // limit)
    return {"items": batches, "total": total, "page": page, "limit": limit, "total_pages": total_pages}


@router.get("/evaluations/tags")
async def list_tags(
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """List all unique tags with test run counts."""
    return service.list_tags()


@router.delete("/evaluations/test-users")
async def delete_test_users(
    service: EvaluationService = Depends(get_evaluation_service),
    user: dict = Depends(require_admin),
):
    """Delete all test users and their data."""
    count = service.delete_test_users()
    logger.info("test_users_deleted_via_api", count=count, user_id=user.get("sub"))
    return {"success": True, "deleted_count": count, "message": f"Deleted {count} test user(s) and their data"}


@router.post("/evaluations/run-unit-tests")
async def run_unit_tests(user: dict = Depends(require_admin)):
    """Run pytest unit tests and return results."""
    return EvaluationService.run_unit_tests()
