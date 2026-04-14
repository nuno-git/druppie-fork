"""Evaluation repository for benchmark runs and evaluation results."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload

from ..db.models import BenchmarkRun, EvaluationResult, TestBatchRun, TestRun, TestRunTag
from ..db.models.test_assertion_result import TestAssertionResult
from .base import BaseRepository


class EvaluationRepository(BaseRepository):
    """Database access for benchmark runs and evaluation results."""

    # =========================================================================
    # BENCHMARK RUN METHODS
    # =========================================================================

    def list_benchmark_runs(
        self,
        limit: int = 20,
        offset: int = 0,
        run_type: str | None = None,
    ) -> tuple[list[BenchmarkRun], int]:
        """List benchmark runs with pagination.

        Args:
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            run_type: Optional filter by run type (batch, live, manual).

        Returns:
            Tuple of (benchmark_runs, total_count).
        """
        query = self.db.query(BenchmarkRun)

        if run_type is not None:
            query = query.filter(BenchmarkRun.run_type == run_type)

        total = query.count()
        runs = (
            query.order_by(BenchmarkRun.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return runs, total

    def get_benchmark_run(self, run_id: UUID) -> BenchmarkRun | None:
        """Get a benchmark run by ID.

        Args:
            run_id: Benchmark run UUID.

        Returns:
            BenchmarkRun or None if not found.
        """
        return self.db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()

    def get_benchmark_run_with_results(self, run_id: UUID) -> BenchmarkRun | None:
        """Get a benchmark run by ID with eagerly loaded results.

        Args:
            run_id: Benchmark run UUID.

        Returns:
            BenchmarkRun with results loaded, or None if not found.
        """
        return (
            self.db.query(BenchmarkRun)
            .options(joinedload(BenchmarkRun.results))
            .filter(BenchmarkRun.id == run_id)
            .first()
        )

    def delete_benchmark_run(self, run_id: UUID) -> bool:
        """Delete a benchmark run and its results (via cascade).

        Args:
            run_id: Benchmark run UUID.

        Returns:
            True if the run was found and deleted, False otherwise.
        """
        run = self.db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if not run:
            return False
        self.db.delete(run)
        self.db.flush()
        return True

    # =========================================================================
    # EVALUATION RESULT METHODS
    # =========================================================================

    def list_results(
        self,
        benchmark_run_id: UUID | None = None,
        agent_id: str | None = None,
        evaluation_name: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EvaluationResult], int]:
        """List evaluation results with optional filters and pagination.

        Args:
            benchmark_run_id: Optional filter by benchmark run.
            agent_id: Optional filter by agent ID.
            evaluation_name: Optional filter by evaluation name.
            limit: Maximum number of results to return.
            offset: Number of results to skip.

        Returns:
            Tuple of (results, total_count).
        """
        query = self.db.query(EvaluationResult)

        if benchmark_run_id is not None:
            query = query.filter(EvaluationResult.benchmark_run_id == benchmark_run_id)
        if agent_id is not None:
            query = query.filter(EvaluationResult.agent_id == agent_id)
        if evaluation_name is not None:
            query = query.filter(EvaluationResult.evaluation_name == evaluation_name)

        total = query.count()
        results = (
            query.order_by(EvaluationResult.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return results, total

    def get_result(self, result_id: UUID) -> EvaluationResult | None:
        """Get an evaluation result by ID.

        Args:
            result_id: Evaluation result UUID.

        Returns:
            EvaluationResult or None if not found.
        """
        return (
            self.db.query(EvaluationResult)
            .filter(EvaluationResult.id == result_id)
            .first()
        )

    # =========================================================================
    # AGGREGATION METHODS
    # =========================================================================

    # =========================================================================
    # TEST RUN METHODS (testing framework)
    # =========================================================================

    def list_test_runs(
        self,
        limit: int = 20,
        offset: int = 0,
        tag: str | None = None,
    ) -> tuple[list[TestRun], int]:
        """List test runs with pagination, optionally filtered by tag.

        Args:
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            tag: Optional tag filter.

        Returns:
            Tuple of (test_runs, total_count).
        """
        query = self.db.query(TestRun)

        if tag:
            query = query.join(TestRunTag).filter(TestRunTag.tag == tag)

        total = query.count()
        items = (
            query.options(subqueryload(TestRun.tags))
            .order_by(TestRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return items, total

    def get_test_run(self, test_run_id: UUID) -> TestRun | None:
        """Get a single test run by ID with tags attached.

        Args:
            test_run_id: Test run UUID.

        Returns:
            TestRun or None if not found.
        """
        run = (
            self.db.query(TestRun)
            .options(joinedload(TestRun.tags))
            .filter(TestRun.id == test_run_id)
            .first()
        )
        return run

    def list_test_batches(
        self,
        page: int = 1,
        limit: int = 10,
        tag: str | None = None,
    ) -> tuple[list[dict], int]:
        """List test runs grouped by batch_id.

        Returns:
            Tuple of (batches, total_batch_count). Each batch contains
            summary stats and individual test run dicts.
        """
        # Get distinct batch_ids ordered by most recent created_at
        batch_query = (
            self.db.query(
                TestRun.batch_id,
                func.min(TestRun.created_at).label("started_at"),
                func.count(TestRun.id).label("test_count"),
                func.sum(TestRun.duration_ms).label("total_duration_ms"),
            )
            .filter(TestRun.batch_id.isnot(None))
        )

        if tag:
            batch_query = batch_query.join(TestRunTag).filter(TestRunTag.tag == tag)

        batch_query = batch_query.group_by(TestRun.batch_id)

        total = batch_query.count()
        offset = (page - 1) * limit

        batch_rows = (
            batch_query
            .order_by(func.min(TestRun.created_at).desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Batch-fetch all runs for the returned batches in one query
        batch_ids = [row.batch_id for row in batch_rows]
        all_runs = (
            self.db.query(TestRun)
            .options(joinedload(TestRun.tags))
            .filter(TestRun.batch_id.in_(batch_ids))
            .order_by(TestRun.created_at.asc())
            .all()
        )
        runs_by_batch: dict[str, list[TestRun]] = {}
        for run in all_runs:
            runs_by_batch.setdefault(run.batch_id, []).append(run)

        batches = []
        for row in batch_rows:
            batch_id = row.batch_id
            runs = runs_by_batch.get(batch_id, [])

            run_dicts = [
                run.to_domain(include_assertions=False).model_dump(mode="json")
                for run in runs
            ]

            passed = sum(1 for r in runs if r.status == "passed")
            total_tests = len(runs)

            batches.append({
                "batch_id": batch_id,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "test_count": total_tests,
                "passed": passed,
                "failed": total_tests - passed,
                "total_duration_ms": row.total_duration_ms,
                "runs": run_dicts,
            })

        # Count unbatched runs separately for consistent pagination total
        if not tag:
            unbatched_count = (
                self.db.query(func.count(TestRun.id))
                .filter(TestRun.batch_id.is_(None))
                .scalar()
            ) or 0
            total += unbatched_count

        # Include unbatched runs (batch_id is NULL) as individual batches on page 1
        # Limit to remaining capacity so page 1 doesn't exceed `limit`
        if page == 1 and not tag:
            remaining = max(0, limit - len(batches))
            if remaining > 0:
                unbatched = (
                    self.db.query(TestRun)
                    .options(subqueryload(TestRun.tags))
                    .filter(TestRun.batch_id.is_(None))
                    .order_by(TestRun.created_at.desc())
                    .limit(remaining)
                    .all()
                )
                for run in unbatched:
                    d = run.to_domain(include_assertions=False).model_dump(mode="json")
                    batches.append({
                        "batch_id": str(run.id),
                        "started_at": run.created_at.isoformat() if run.created_at else None,
                        "test_count": 1,
                        "passed": 1 if run.status == "passed" else 0,
                        "failed": 0 if run.status == "passed" else 1,
                        "total_duration_ms": run.duration_ms,
                        "runs": [d],
                    })

        return batches, total

    def list_tags(self) -> list[dict]:
        """Get all unique tags with test run counts.

        Returns:
            List of dicts with 'tag' and 'count' keys.
        """
        results = (
            self.db.query(TestRunTag.tag, func.count(TestRunTag.id))
            .group_by(TestRunTag.tag)
            .order_by(TestRunTag.tag)
            .all()
        )
        return [{"tag": tag, "count": count} for tag, count in results]

    def delete_test_users(self) -> int:
        """Delete all test users (matching test-* pattern) and cascade their data.

        Uses ORM-level delete (db.delete) instead of bulk Query.delete() to ensure
        ORM cascade relationships are properly triggered for child records.

        Returns:
            Number of test users deleted.
        """
        from ..db.models import User, Session as SessionModel, Project

        test_users = (
            self.db.query(User)
            .filter(User.username.like("test-%") | User.username.like("t-%"))
            .all()
        )
        count = len(test_users)
        for user in test_users:
            # Delete sessions via ORM to trigger cascade to agent_runs, tool_calls, etc.
            sessions = (
                self.db.query(SessionModel)
                .filter(SessionModel.user_id == user.id)
                .all()
            )
            for session in sessions:
                self.db.delete(session)

            # Delete projects via ORM to trigger cascade
            projects = (
                self.db.query(Project)
                .filter(Project.owner_id == user.id)
                .all()
            )
            for project in projects:
                self.db.delete(project)

            self.db.delete(user)

        return count

    # =========================================================================
    # AGGREGATION METHODS
    # =========================================================================

    def get_agent_summary(self, agent_id: str) -> dict:
        """Get aggregated evaluation summary for an agent.

        Computes:
        - total: Total number of evaluation results.
        - binary_pass_rate: Percentage of binary evaluations that passed (0.0-1.0).
        - graded_avg: Average graded score (normalized to max_score).

        Args:
            agent_id: Agent identifier.

        Returns:
            Dict with keys: total, binary_pass_rate, graded_avg.
        """
        base_query = self.db.query(EvaluationResult).filter(
            EvaluationResult.agent_id == agent_id
        )

        total = base_query.count()

        # Binary pass rate
        binary_total = base_query.filter(
            EvaluationResult.score_type == "binary"
        ).count()
        binary_passed = base_query.filter(
            EvaluationResult.score_type == "binary",
            EvaluationResult.score_binary.is_(True),
        ).count()
        binary_pass_rate = (
            binary_passed / binary_total if binary_total > 0 else None
        )

        # Graded average (normalized: score_graded / max_score)
        graded_result = (
            self.db.query(
                func.avg(
                    EvaluationResult.score_graded / EvaluationResult.max_score
                )
            )
            .filter(
                EvaluationResult.agent_id == agent_id,
                EvaluationResult.score_type == "graded",
                EvaluationResult.max_score > 0,
            )
            .scalar()
        )
        graded_avg = float(graded_result) if graded_result is not None else None

        return {
            "total": total,
            "binary_pass_rate": binary_pass_rate,
            "graded_avg": graded_avg,
        }

    def get_test_run_assertions(self, test_run_id: UUID) -> list[dict]:
        """Get assertion results for a test run."""
        results = (
            self.db.query(TestAssertionResult)
            .filter(TestAssertionResult.test_run_id == test_run_id)
            .order_by(TestAssertionResult.created_at)
            .all()
        )
        return [r.to_dict() for r in results]

    def get_batch_assertions(
        self, batch_id: str,
        assertion_type: str | None = None,
        agent_id: str | None = None,
        check_text: str | None = None,
    ) -> dict:
        """Get all assertion results for a batch, optionally filtered."""
        runs = (
            self.db.query(TestRun)
            .filter(TestRun.batch_id == batch_id)
            .order_by(TestRun.created_at)
            .all()
        )

        run_ids = [r.id for r in runs]

        result = {
            "batch_id": batch_id,
            "summary": {"assertions": 0, "assertions_passed": 0,
                         "judge": 0, "judge_passed": 0,
                         "judge_eval": 0, "judge_eval_passed": 0},
            "runs": [],
        }

        if not run_ids:
            return result

        # Single batch query for all assertions instead of per-run N+1
        query = self.db.query(TestAssertionResult).filter(
            TestAssertionResult.test_run_id.in_(run_ids)
        )
        if assertion_type:
            if assertion_type == "assertions":
                query = query.filter(TestAssertionResult.assertion_type.in_(["completed", "tool"]))
            else:
                query = query.filter(TestAssertionResult.assertion_type == assertion_type)
        if agent_id:
            query = query.filter(TestAssertionResult.agent_id == agent_id)
        if check_text:
            query = query.filter(TestAssertionResult.message == check_text)
        all_assertions = query.order_by(TestAssertionResult.created_at).all()

        # Group by test_run_id
        assertions_by_run: dict = {}
        for ar in all_assertions:
            assertions_by_run.setdefault(ar.test_run_id, []).append(ar)

        for run in runs:
            run_assertions = []
            for ar in assertions_by_run.get(run.id, []):
                d = ar.to_dict()
                if ar.assertion_type in ("completed", "tool"):
                    result["summary"]["assertions"] += 1
                    if ar.passed:
                        result["summary"]["assertions_passed"] += 1
                elif ar.assertion_type == "judge_check":
                    result["summary"]["judge"] += 1
                    if ar.passed:
                        result["summary"]["judge_passed"] += 1
                elif ar.assertion_type == "judge_eval":
                    result["summary"]["judge_eval"] += 1
                    if ar.passed:
                        result["summary"]["judge_eval_passed"] += 1
                run_assertions.append(d)

            result["runs"].append({
                "test_run_id": str(run.id),
                "test_name": run.test_name,
                "test_description": run.test_description,
                "status": run.status,
                "mode": run.mode,
                "duration_ms": run.duration_ms,
                "session_id": str(run.session_id) if run.session_id else None,
                "assertions": run_assertions,
            })

        return result

    def get_batch_filters(self, batch_id: str) -> dict:
        """Get all unique filterable values for a batch."""
        run_ids = [
            r.id for r in self.db.query(TestRun.id)
            .filter(TestRun.batch_id == batch_id).all()
        ]
        if not run_ids:
            return {"checks": [], "agents": [], "tools": [], "types": []}

        all_assertions = (
            self.db.query(TestAssertionResult)
            .filter(TestAssertionResult.test_run_id.in_(run_ids))
            .all()
        )

        checks: dict = {}
        agents: set = set()
        types: set = set()

        for ar in all_assertions:
            if ar.agent_id:
                agents.add(ar.agent_id)
            types.add(ar.assertion_type)

            msg = ar.message or ""
            if msg not in checks:
                checks[msg] = {
                    "text": msg,
                    "type": ar.assertion_type,
                    "passed": 0,
                    "failed": 0,
                    "agents": set(),
                    "test_runs": set(),
                }
            if ar.passed:
                checks[msg]["passed"] += 1
            else:
                checks[msg]["failed"] += 1
            if ar.agent_id:
                checks[msg]["agents"].add(ar.agent_id)
            checks[msg]["test_runs"].add(str(ar.test_run_id))

        check_list = []
        for c in checks.values():
            c["agents"] = sorted(c["agents"])
            c["test_runs"] = sorted(c["test_runs"])
            c["total"] = c["passed"] + c["failed"]
            check_list.append(c)

        type_order = {"judge_check": 0, "judge_eval": 1, "completed": 2, "tool": 3}
        check_list.sort(key=lambda c: (type_order.get(c["type"], 9), c["text"]))

        tools = {ar.tool_name for ar in all_assertions if ar.tool_name}

        return {
            "checks": check_list,
            "agents": sorted(agents),
            "tools": sorted(tools),
            "types": sorted(types),
        }

    # =========================================================================
    # BATCH RUN STATUS (replaces in-memory _test_run_status dict)
    # =========================================================================

    def create_batch_run(self, batch_id: str, total_tests: int = 0) -> TestBatchRun:
        batch = TestBatchRun(
            id=batch_id, status="running",
            message="Loading tests...", total_tests=total_tests,
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    def update_batch_run(self, batch_id: str, **kwargs) -> None:
        batch = self.db.query(TestBatchRun).filter(TestBatchRun.id == batch_id).first()
        if batch:
            for key, val in kwargs.items():
                setattr(batch, key, val)
            self.db.flush()

    def get_batch_run(self, batch_id: str) -> TestBatchRun | None:
        return self.db.query(TestBatchRun).filter(TestBatchRun.id == batch_id).first()

    def get_active_batch_run(self) -> TestBatchRun | None:
        return (
            self.db.query(TestBatchRun)
            .filter(TestBatchRun.status == "running")
            .order_by(TestBatchRun.started_at.desc())
            .first()
        )

    def get_completed_test_runs(self, batch_id: str) -> list[dict]:
        runs = (
            self.db.query(TestRun)
            .filter(TestRun.batch_id == batch_id)
            .order_by(TestRun.created_at.asc())
            .all()
        )
        return [
            {"test_name": r.test_name, "status": r.status, "duration_ms": r.duration_ms}
            for r in runs
        ]
