"""Analytics repository for test run aggregation queries."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func

from ..db.models import TestRun
from ..db.models.test_assertion_result import TestAssertionResult
from .base import BaseRepository


class AnalyticsRepository(BaseRepository):
    """SQL-aggregated analytics queries for test runs and assertions."""

    def get_summary(self, days: int = 30) -> dict:
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

    def get_trends(self, days: int = 30) -> list[dict]:
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

    def get_by_agent(self, batch_id: str | None = None) -> list[dict]:
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

    def get_by_eval(self, batch_id: str | None = None) -> list[dict]:
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

    def get_by_tool(self, batch_id: str | None = None) -> list[dict]:
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

    def get_by_test(self, batch_id: str | None = None) -> list[dict]:
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

    def get_batch_detail(self, batch_id: str) -> dict:
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
        by_agent = self.get_by_agent(batch_id)

        # Eval breakdown via SQL
        by_eval = self.get_by_eval(batch_id)

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
