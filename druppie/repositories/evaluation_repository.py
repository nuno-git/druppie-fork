"""Evaluation repository for benchmark runs and evaluation results."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from ..db.models import BenchmarkRun, EvaluationResult, TestRun, TestRunTag
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
    # TEST RUN METHODS (v2 testing framework)
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
            Tuple of (test_runs, total_count). Each test run has a _tags attribute.
        """
        query = self.db.query(TestRun)

        if tag:
            query = query.join(TestRunTag).filter(TestRunTag.tag == tag)

        total = query.count()
        items = (
            query.options(joinedload(TestRun.tags))
            .order_by(TestRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Attach tags from eagerly-loaded relationship
        for item in items:
            item._tags = [t.tag for t in item.tags]

        return items, total

    def get_test_run(self, test_run_id: UUID) -> TestRun | None:
        """Get a single test run by ID with tags attached.

        Args:
            test_run_id: Test run UUID.

        Returns:
            TestRun with _tags attribute, or None if not found.
        """
        run = (
            self.db.query(TestRun)
            .options(joinedload(TestRun.tags))
            .filter(TestRun.id == test_run_id)
            .first()
        )
        if run:
            run._tags = [t.tag for t in run.tags]
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

            run_dicts = []
            for run in runs:
                run._tags = [t.tag for t in run.tags]
                d = run.to_dict()
                d["tags"] = run._tags
                run_dicts.append(d)

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

        # Also include unbatched runs (batch_id is NULL) as individual batches
        if page == 1 and not tag:
            unbatched = (
                self.db.query(TestRun)
                .options(joinedload(TestRun.tags))
                .filter(TestRun.batch_id.is_(None))
                .order_by(TestRun.created_at.desc())
                .limit(limit)
                .all()
            )
            for run in unbatched:
                run._tags = [t.tag for t in run.tags]
                d = run.to_dict()
                d["tags"] = run._tags
                batches.append({
                    "batch_id": str(run.id),
                    "started_at": run.created_at.isoformat() if run.created_at else None,
                    "test_count": 1,
                    "passed": 1 if run.status == "passed" else 0,
                    "failed": 0 if run.status == "passed" else 1,
                    "total_duration_ms": run.duration_ms,
                    "runs": [d],
                })
            total += len(unbatched)

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
            # Delete sessions (cascades to agent_runs, tool_calls, etc.)
            self.db.query(SessionModel).filter(
                SessionModel.user_id == user.id
            ).delete()
            # Delete projects owned by test user
            self.db.query(Project).filter(
                Project.owner_id == user.id
            ).delete()
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

    # =========================================================================
    # ANALYTICS METHODS
    # =========================================================================

    def get_analytics_summary(self, days: int = 30) -> dict:
        """Global analytics summary using SQL aggregation."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        row = (
            self.db.query(
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
                func.avg(TestRun.duration_ms).label("avg_duration"),
            )
            .filter(TestRun.created_at >= cutoff)
            .first()
        )
        total = row.total or 0
        passed = row.passed or 0
        return {
            "total_runs": total,
            "total_passed": passed,
            "total_failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total else 0,
            "avg_duration_ms": int(row.avg_duration or 0),
        }

    def get_analytics_trends(self, days: int = 30) -> list[dict]:
        """Pass rate trends grouped by day using SQL aggregation."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            self.db.query(
                func.date(TestRun.created_at).label("day"),
                func.count(TestRun.id).label("total"),
                func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
            )
            .filter(TestRun.created_at >= cutoff)
            .group_by(func.date(TestRun.created_at))
            .order_by(func.date(TestRun.created_at))
            .all()
        )
        return [
            {
                "date": str(r.day),
                "total": r.total,
                "passed": r.passed,
                "failed": r.total - r.passed,
                "pass_rate": round(r.passed / r.total * 100, 1) if r.total else 0,
            }
            for r in rows
        ]

    def get_analytics_by_agent(self, batch_id: str | None = None) -> list[dict]:
        """Assertion results grouped by agent using SQL aggregation."""
        query = self.db.query(
            TestAssertionResult.agent_id,
            func.count(TestAssertionResult.id).label("total"),
            func.sum(case((TestAssertionResult.passed == True, 1), else_=0)).label("passed"),  # noqa: E712
        ).filter(TestAssertionResult.agent_id.isnot(None))
        if batch_id:
            query = query.join(TestRun).filter(TestRun.batch_id == batch_id)
        rows = query.group_by(TestAssertionResult.agent_id).order_by(TestAssertionResult.agent_id).all()
        return [
            {
                "agent": r.agent_id,
                "total": r.total,
                "passed": r.passed,
                "failed": r.total - r.passed,
                "pass_rate": round(r.passed / r.total * 100, 1) if r.total else 0,
            }
            for r in rows
        ]

    def get_analytics_by_eval(self, batch_id: str | None = None) -> list[dict]:
        """Assertion results grouped by eval name using SQL aggregation."""
        query = self.db.query(
            TestAssertionResult.eval_name,
            func.count(TestAssertionResult.id).label("total"),
            func.sum(case((TestAssertionResult.passed == True, 1), else_=0)).label("passed"),  # noqa: E712
        ).filter(TestAssertionResult.eval_name.isnot(None))
        if batch_id:
            query = query.join(TestRun).filter(TestRun.batch_id == batch_id)
        rows = query.group_by(TestAssertionResult.eval_name).order_by(TestAssertionResult.eval_name).all()
        return [
            {
                "eval_name": r.eval_name,
                "total": r.total,
                "passed": r.passed,
                "failed": r.total - r.passed,
                "pass_rate": round(r.passed / r.total * 100, 1) if r.total else 0,
            }
            for r in rows
        ]

    def get_analytics_by_tool(self, batch_id: str | None = None) -> list[dict]:
        """Assertion results grouped by tool name using SQL aggregation."""
        query = self.db.query(
            TestAssertionResult.tool_name,
            func.count(TestAssertionResult.id).label("total"),
            func.sum(case((TestAssertionResult.passed == True, 1), else_=0)).label("passed"),  # noqa: E712
        ).filter(TestAssertionResult.tool_name.isnot(None))
        if batch_id:
            query = query.join(TestRun).filter(TestRun.batch_id == batch_id)
        rows = query.group_by(TestAssertionResult.tool_name).order_by(TestAssertionResult.tool_name).all()
        return [
            {
                "tool": r.tool_name,
                "total": r.total,
                "passed": r.passed,
                "failed": r.total - r.passed,
                "pass_rate": round(r.passed / r.total * 100, 1) if r.total else 0,
            }
            for r in rows
        ]

    def get_analytics_by_test(self, batch_id: str | None = None) -> list[dict]:
        """Test runs grouped by test name using SQL aggregation."""
        query = self.db.query(
            TestRun.test_name,
            func.count(TestRun.id).label("total"),
            func.sum(case((TestRun.status == "passed", 1), else_=0)).label("passed"),
            func.avg(TestRun.duration_ms).label("avg_duration"),
        )
        if batch_id:
            query = query.filter(TestRun.batch_id == batch_id)
        rows = query.group_by(TestRun.test_name).order_by(TestRun.test_name).all()
        return [
            {
                "test_name": r.test_name,
                "total": r.total,
                "passed": r.passed,
                "failed": r.total - r.passed,
                "pass_rate": round(r.passed / r.total * 100, 1) if r.total else 0,
                "avg_duration_ms": int(r.avg_duration or 0),
            }
            for r in rows
        ]

    def get_analytics_batch_detail(self, batch_id: str) -> dict:
        """Detailed analytics for a single batch."""
        runs = (
            self.db.query(TestRun)
            .filter(TestRun.batch_id == batch_id)
            .all()
        )
        if not runs:
            return {"batch_id": batch_id, "total": 0, "passed": 0, "failed": 0}

        total = len(runs)
        passed = sum(1 for r in runs if r.status == "passed")
        durations = [r.duration_ms for r in runs if r.duration_ms is not None]
        total_duration = sum(durations) if durations else 0
        created_at = min(r.created_at for r in runs if r.created_at) if runs else None

        run_ids = [r.id for r in runs]

        # Agent breakdown via SQL
        by_agent = self.get_analytics_by_agent(batch_id)

        # Eval breakdown via SQL
        by_eval = self.get_analytics_by_eval(batch_id)

        # Per-test details (need assertion results per run)
        assertion_results = (
            self.db.query(TestAssertionResult)
            .filter(TestAssertionResult.test_run_id.in_(run_ids))
            .all()
        )
        ar_by_run: dict = {}
        for ar in assertion_results:
            ar_by_run.setdefault(ar.test_run_id, []).append(ar)

        return {
            "batch_id": batch_id,
            "created_at": created_at.isoformat() if created_at else None,
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total else 0,
            "duration_ms": total_duration,
            "by_agent": by_agent,
            "by_eval": [{"eval_name": e.pop("eval_name"), **e} for e in by_eval],
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
                    "assertion_results": [ar.to_dict() for ar in ar_by_run.get(r.id, [])],
                }
                for r in runs
            ],
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
        from ..db.models import ToolCall, AgentRun

        runs = (
            self.db.query(TestRun)
            .filter(TestRun.batch_id == batch_id)
            .order_by(TestRun.created_at)
            .all()
        )

        result = {
            "batch_id": batch_id,
            "summary": {"assertions": 0, "assertions_passed": 0,
                         "judge": 0, "judge_passed": 0,
                         "judge_eval": 0, "judge_eval_passed": 0},
            "runs": [],
        }

        for run in runs:
            query = self.db.query(TestAssertionResult).filter(
                TestAssertionResult.test_run_id == run.id
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
            assertions = query.order_by(TestAssertionResult.created_at).all()

            run_assertions = []
            for ar in assertions:
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

        return {
            "checks": check_list,
            "agents": sorted(agents),
            "types": sorted(types),
        }
