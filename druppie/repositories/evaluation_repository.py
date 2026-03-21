"""Evaluation repository for benchmark runs and evaluation results."""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..db.models import BenchmarkRun, EvaluationResult
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
