"""Evaluation service for benchmark runs and results."""

from pathlib import Path
from uuid import UUID

import structlog

from ..api.errors import NotFoundError
from ..db.models import BenchmarkRun, EvaluationResult, TestRun
from ..domain.evaluation import (
    BenchmarkRunDetail,
    BenchmarkRunSummary,
    EvaluationResultDetail,
    EvaluationResultSummary,
)
from ..repositories import EvaluationRepository

logger = structlog.get_logger()


class EvaluationService:
    """Business logic for benchmark runs and evaluation results."""

    def __init__(self, eval_repo: EvaluationRepository):
        self.eval_repo = eval_repo

    # =========================================================================
    # BENCHMARK RUNS
    # =========================================================================

    def list_benchmark_runs(
        self,
        page: int = 1,
        limit: int = 20,
        run_type: str | None = None,
    ) -> tuple[list[BenchmarkRunSummary], int]:
        """List benchmark runs with pagination."""
        offset = (page - 1) * limit
        runs, total = self.eval_repo.list_benchmark_runs(
            limit=limit, offset=offset, run_type=run_type
        )
        return [self._run_to_summary(r) for r in runs], total

    def get_benchmark_run_detail(self, run_id: UUID) -> BenchmarkRunDetail:
        """Get benchmark run with results.

        Raises:
            NotFoundError: If the benchmark run does not exist.
        """
        run = self.eval_repo.get_benchmark_run_with_results(run_id)
        if not run:
            raise NotFoundError("benchmark_run", str(run_id))
        return self._run_to_detail(run)

    def delete_benchmark_run(self, run_id: UUID) -> None:
        """Delete a benchmark run and its results.

        Raises:
            NotFoundError: If the benchmark run does not exist.
        """
        deleted = self.eval_repo.delete_benchmark_run(run_id)
        if not deleted:
            raise NotFoundError("benchmark_run", str(run_id))
        self.eval_repo.commit()
        logger.info("benchmark_run_deleted", run_id=str(run_id))

    # =========================================================================
    # EVALUATION RESULTS
    # =========================================================================

    def list_results(
        self,
        benchmark_run_id: UUID | None = None,
        agent_id: str | None = None,
        evaluation_name: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[EvaluationResultSummary], int]:
        """List evaluation results with optional filters and pagination."""
        offset = (page - 1) * limit
        results, total = self.eval_repo.list_results(
            benchmark_run_id=benchmark_run_id,
            agent_id=agent_id,
            evaluation_name=evaluation_name,
            limit=limit,
            offset=offset,
        )
        return [self._result_to_summary(r) for r in results], total

    def get_result_detail(self, result_id: UUID) -> EvaluationResultDetail:
        """Get a single evaluation result with full details.

        Raises:
            NotFoundError: If the evaluation result does not exist.
        """
        result = self.eval_repo.get_result(result_id)
        if not result:
            raise NotFoundError("evaluation_result", str(result_id))
        return self._result_to_detail(result)

    # =========================================================================
    # AGGREGATION
    # =========================================================================

    def get_agent_summary(self, agent_id: str) -> dict:
        """Get aggregated evaluation summary for an agent.

        Returns:
            Dict with keys: total, binary_pass_rate, graded_avg.
        """
        return self.eval_repo.get_agent_summary(agent_id)

    # =========================================================================
    # TEST RUNS (v2 testing framework)
    # =========================================================================

    def list_test_runs(
        self,
        page: int = 1,
        limit: int = 20,
        tag: str | None = None,
    ) -> tuple[list[dict], int]:
        """List test runs with pagination, optionally filtered by tag."""
        offset = (page - 1) * limit
        runs, total = self.eval_repo.list_test_runs(
            limit=limit, offset=offset, tag=tag
        )
        return [self._test_run_to_dict(r) for r in runs], total

    def get_test_run_detail(self, test_run_id: UUID) -> dict:
        """Get a single test run with details.

        Raises:
            NotFoundError: If the test run does not exist.
        """
        run = self.eval_repo.get_test_run(test_run_id)
        if not run:
            raise NotFoundError("test_run", str(test_run_id))
        return self._test_run_to_dict(run)

    def list_tags(self) -> list[dict]:
        """Get all unique tags with test run counts."""
        return self.eval_repo.list_tags()

    def run_tests(
        self,
        test_name: str | None = None,
        test_names: list[str] | None = None,
        tag: str | None = None,
        run_all: bool = False,
        execute: bool = True,
        judge: bool = True,
    ) -> dict:
        """Run tests and return results.

        Args:
            test_name: Run a specific test by name.
            test_names: Run multiple tests by name.
            tag: Run tests matching a tag.
            run_all: Run all tests.
            execute: Phase 2 -- run real agents with LLMs + HITL.
            judge: Phase 3 -- run LLM judge checks.

        Returns:
            Dict with total/passed/failed counts and per-test result details.
        """
        from ..testing.v2_runner import TestRunner

        runner = TestRunner(db=self.eval_repo.db)
        results = []
        phase_flags = dict(execute=execute, judge=judge)

        if test_name:
            tests_dir = runner._testing_dir / "tests"
            test_path = tests_dir / f"{test_name}.yaml"
            if not test_path.exists():
                raise FileNotFoundError(f"Test not found: {test_path}")
            test_def = runner.load_test(test_path)
            results = runner.run_test(test_def, **phase_flags)
        elif test_names:
            tests_dir = runner._testing_dir / "tests"
            for name in test_names:
                test_path = tests_dir / f"{name}.yaml"
                if not test_path.exists():
                    raise FileNotFoundError(f"Test not found: {test_path}")
                test_def = runner.load_test(test_path)
                results.extend(runner.run_test(test_def, **phase_flags))
        elif tag:
            all_tests = runner.load_all_tests()
            for _path, test_def in all_tests:
                # Check if any eval references an eval with this tag
                for eval_ref in test_def.evals:
                    eval_def = runner._evals.get(eval_ref.eval)
                    if eval_def and tag in eval_def.tags:
                        results.extend(runner.run_test(test_def, **phase_flags))
                        break
        elif run_all:
            all_tests = runner.load_all_tests()
            for _path, test_def in all_tests:
                results.extend(runner.run_test(test_def, **phase_flags))

        self.eval_repo.db.commit()

        return {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [
                {
                    "test_name": r.test_name,
                    "status": r.status,
                    "assertions": (
                        f"{sum(1 for a in r.assertion_results if a.passed)}"
                        f"/{len(r.assertion_results)}"
                    ),
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ],
        }

    def delete_test_users(self) -> int:
        """Delete all test users and their data.

        Returns:
            Number of test users deleted.
        """
        count = self.eval_repo.delete_test_users()
        self.eval_repo.commit()
        logger.info("test_users_deleted", count=count)
        return count

    @staticmethod
    def _test_run_to_dict(run: TestRun) -> dict:
        """Convert a TestRun DB model to a dict for API response."""
        d = run.to_dict()
        d["tags"] = getattr(run, "_tags", [])
        return d

    # =========================================================================
    # BENCHMARK TRIGGER
    # =========================================================================

    def trigger_benchmark(
        self,
        scenario_name: str,
        judge_model: str | None = None,
    ) -> UUID:
        """Load and run a benchmark scenario, returning the benchmark_run_id.

        Args:
            scenario_name: Name of the scenario YAML file (without extension).
            judge_model: Optional judge model override.

        Returns:
            The UUID of the created benchmark run.

        Raises:
            FileNotFoundError: If the scenario YAML does not exist.
        """
        from ..testing.bench_runner import ScenarioRunner, load_scenario

        scenarios_dir = Path(__file__).resolve().parent.parent.parent / "testing" / "scenarios"
        scenario_path = scenarios_dir / f"{scenario_name}.yaml"

        if not scenario_path.exists():
            raise FileNotFoundError(f"Scenario not found: {scenario_path}")

        scenario = load_scenario(scenario_path)
        runner = ScenarioRunner(
            db=self.eval_repo.db,
            judge_model=judge_model,
        )
        result = runner.run(scenario)

        logger.info(
            "benchmark_triggered",
            scenario=scenario_name,
            benchmark_run_id=str(result.benchmark_run_id),
            passed=result.passed,
        )

        return result.benchmark_run_id

    # =========================================================================
    # CONVERSION HELPERS
    # =========================================================================

    @staticmethod
    def _run_to_summary(run: BenchmarkRun) -> BenchmarkRunSummary:
        """Convert BenchmarkRun DB model to BenchmarkRunSummary domain model."""
        return BenchmarkRunSummary(
            id=run.id,
            name=run.name,
            run_type=run.run_type,
            git_commit=run.git_commit,
            git_branch=run.git_branch,
            judge_model=run.judge_model,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )

    @staticmethod
    def _result_to_summary(result: EvaluationResult) -> EvaluationResultSummary:
        """Convert EvaluationResult DB model to EvaluationResultSummary domain model."""
        return EvaluationResultSummary(
            id=result.id,
            agent_id=result.agent_id,
            evaluation_name=result.evaluation_name,
            rubric_name=result.rubric_name,
            score_type=result.score_type,
            score_binary=result.score_binary,
            score_graded=result.score_graded,
            max_score=result.max_score,
            created_at=result.created_at,
        )

    @staticmethod
    def _result_to_detail(result: EvaluationResult) -> EvaluationResultDetail:
        """Convert EvaluationResult DB model to EvaluationResultDetail domain model."""
        return EvaluationResultDetail(
            id=result.id,
            agent_id=result.agent_id,
            evaluation_name=result.evaluation_name,
            rubric_name=result.rubric_name,
            score_type=result.score_type,
            score_binary=result.score_binary,
            score_graded=result.score_graded,
            max_score=result.max_score,
            created_at=result.created_at,
            benchmark_run_id=result.benchmark_run_id,
            session_id=result.session_id,
            agent_run_id=result.agent_run_id,
            judge_model=result.judge_model,
            judge_prompt=result.judge_prompt,
            judge_response=result.judge_response,
            judge_reasoning=result.judge_reasoning,
            llm_model=result.llm_model,
            llm_provider=result.llm_provider,
            judge_duration_ms=result.judge_duration_ms,
            judge_tokens_used=result.judge_tokens_used,
        )

    @classmethod
    def _run_to_detail(cls, run: BenchmarkRun) -> BenchmarkRunDetail:
        """Convert BenchmarkRun DB model to BenchmarkRunDetail domain model."""
        return BenchmarkRunDetail(
            id=run.id,
            name=run.name,
            run_type=run.run_type,
            git_commit=run.git_commit,
            git_branch=run.git_branch,
            judge_model=run.judge_model,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            config_summary=run.config_summary,
            results=[cls._result_to_summary(r) for r in run.results],
        )
