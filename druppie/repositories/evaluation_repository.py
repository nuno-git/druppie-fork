"""Evaluation repository for benchmark runs and evaluation results."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..db.models import BenchmarkRun, EvaluationResult, TestRun, TestRunTag
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
            query.order_by(TestRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Attach tags to each test run
        for item in items:
            item._tags = [
                t.tag
                for t in self.db.query(TestRunTag)
                .filter(TestRunTag.test_run_id == item.id)
                .all()
            ]

        return items, total

    def get_test_run(self, test_run_id: UUID) -> TestRun | None:
        """Get a single test run by ID with tags attached.

        Args:
            test_run_id: Test run UUID.

        Returns:
            TestRun with _tags attribute, or None if not found.
        """
        run = self.db.query(TestRun).filter(TestRun.id == test_run_id).first()
        if run:
            run._tags = [
                t.tag
                for t in self.db.query(TestRunTag)
                .filter(TestRunTag.test_run_id == run.id)
                .all()
            ]
        return run

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
        from ..db.models import User, Session as SessionModel

        test_users = (
            self.db.query(User).filter(User.username.like("test-%")).all()
        )
        count = len(test_users)
        for user in test_users:
            # Delete sessions (cascades to agent_runs, tool_calls, etc.)
            self.db.query(SessionModel).filter(
                SessionModel.user_id == user.id
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
