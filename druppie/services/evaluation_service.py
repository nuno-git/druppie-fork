"""Evaluation service for benchmark runs, evaluation results, and tests."""

from uuid import UUID

import structlog

from ..api.errors import NotFoundError
from ..db.models import BenchmarkRun, EvaluationResult, TestRun
from ..domain.evaluation import (
    BenchmarkRunDetail,
    BenchmarkRunSummary,
    EvaluationResultDetail,
    EvaluationResultSummary,
    TestAssertionResultSummary,
    TestRunDetail,
    TestRunSummary,
)
from ..repositories import EvaluationRepository

logger = structlog.get_logger()


class EvaluationService:
    """Business logic for benchmark runs and evaluation results."""

    def __init__(self, eval_repo: EvaluationRepository, analytics_repo=None):
        self.eval_repo = eval_repo
        self._analytics_repo = analytics_repo

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
    # TEST RUNS (testing framework)
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
        return [self._test_run_to_summary(r).model_dump(mode="json") for r in runs], total

    def get_test_run_detail(self, test_run_id: UUID) -> dict:
        """Get a single test run with details.

        Raises:
            NotFoundError: If the test run does not exist.
        """
        run = self.eval_repo.get_test_run(test_run_id)
        if not run:
            raise NotFoundError("test_run", str(test_run_id))
        return self._test_run_to_detail(run).model_dump(mode="json")

    def list_test_batches(
        self,
        page: int = 1,
        limit: int = 10,
        tag: str | None = None,
    ) -> tuple[list[dict], int]:
        """List test runs grouped by batch_id.

        Returns:
            Tuple of (batches, total_batch_count). Each batch is a dict
            with summary stats and a list of individual test runs.
        """
        return self.eval_repo.list_test_batches(page=page, limit=limit, tag=tag)

    def list_tags(self) -> list[dict]:
        """Get all unique tags with test run counts."""
        return self.eval_repo.list_tags()

    @staticmethod
    def run_unit_tests() -> dict:
        """Run pytest unit tests and return parsed results."""
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

            lines = result.stdout.strip().split("\n")
            tests = []
            test_line_re = re.compile(
                r"^([\w/\\.]+\.py)"
                r"::"
                r"([\w:]+)"
                r"\s+"
                r"(PASSED|FAILED|SKIPPED|ERROR)"
                r"(.*)?$"
            )

            for line in lines:
                m = test_line_re.search(line.strip())
                if not m:
                    continue
                file_path = m.group(1)
                name_part = m.group(2)
                status = m.group(3).lower()
                tail = (m.group(4) or "").strip()

                if "::" in name_part:
                    cls_name, method_name = name_part.split("::", 1)
                else:
                    cls_name = None
                    method_name = name_part

                file_name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

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

            summary = ""
            duration_seconds = None
            for line in reversed(lines):
                if "passed" in line or "failed" in line:
                    summary = line.strip().strip("=").strip()
                    dur_match = re.search(r"in\s+([\d.]+)s", line)
                    if dur_match:
                        duration_seconds = float(dur_match.group(1))
                    break

            failure_details: dict[str, str] = {}
            for line in lines:
                if line.startswith("FAILED "):
                    parts = line.split(" - ", 1)
                    key = parts[0].replace("FAILED ", "").strip()
                    msg = parts[1].strip() if len(parts) > 1 else ""
                    failure_details[key] = msg

            for t in tests:
                if t["status"] == "failed":
                    if t["class"]:
                        key = f"druppie/tests/{t['file']}::{t['class']}::{t['name']}"
                    else:
                        key = f"druppie/tests/{t['file']}::{t['name']}"
                    if key in failure_details:
                        t["reason"] = failure_details[key]

            # Truncate raw output to avoid leaking sensitive paths/env vars
            max_output = 10_000
            safe_output = result.stdout[:max_output] if result.stdout else ""
            safe_errors = result.stderr[:max_output] if result.returncode != 0 and result.stderr else ""

            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "summary": summary,
                "total": len(tests),
                "passed": sum(1 for t in tests if t["status"] == "passed"),
                "failed": sum(1 for t in tests if t["status"] == "failed"),
                "skipped": sum(1 for t in tests if t["status"] == "skipped"),
                "tests": tests,
                "output": safe_output,
                "errors": safe_errors,
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

    # =========================================================================
    # ANALYTICS
    # =========================================================================

    def get_analytics_summary(self, days: int = 30) -> dict:
        return self._analytics_repo.get_summary(days)

    def get_analytics_trends(self, days: int = 30) -> list[dict]:
        return self._analytics_repo.get_trends(days)

    def get_analytics_by_agent(self, batch_id: str | None = None) -> list[dict]:
        return self._analytics_repo.get_by_agent(batch_id)

    def get_analytics_by_eval(self, batch_id: str | None = None) -> list[dict]:
        return self._analytics_repo.get_by_eval(batch_id)

    def get_analytics_by_tool(self, batch_id: str | None = None) -> list[dict]:
        return self._analytics_repo.get_by_tool(batch_id)

    def get_analytics_by_test(self, batch_id: str | None = None) -> list[dict]:
        return self._analytics_repo.get_by_test(batch_id)

    def get_analytics_batch_detail(self, batch_id: str) -> dict:
        return self._analytics_repo.get_batch_detail(batch_id)

    def get_test_run_assertions(self, test_run_id) -> list[dict]:
        return self.eval_repo.get_test_run_assertions(test_run_id)

    def get_batch_assertions(
        self, batch_id: str,
        assertion_type: str | None = None,
        agent_id: str | None = None,
        check_text: str | None = None,
    ) -> dict:
        return self.eval_repo.get_batch_assertions(
            batch_id, assertion_type, agent_id, check_text,
        )

    def get_batch_filters(self, batch_id: str) -> dict:
        return self.eval_repo.get_batch_filters(batch_id)

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
    def _test_run_to_summary(run: TestRun) -> TestRunSummary:
        """Convert a TestRun DB model to a TestRunSummary domain model."""
        return TestRunSummary(
            id=run.id,
            benchmark_run_id=run.benchmark_run_id,
            batch_id=run.batch_id,
            test_name=run.test_name,
            test_description=run.test_description,
            test_user=run.test_user,
            hitl_profile=run.hitl_profile,
            judge_profile=run.judge_profile,
            session_id=run.session_id,
            sessions_seeded=run.sessions_seeded,
            assertions_total=run.assertions_total,
            assertions_passed=run.assertions_passed,
            judge_checks_total=run.judge_checks_total,
            judge_checks_passed=run.judge_checks_passed,
            status=run.status,
            duration_ms=run.duration_ms,
            agent_id=run.agent_id,
            mode=run.mode,
            created_at=run.created_at,
            tags=getattr(run, "_tags", []),
        )

    @classmethod
    def _test_run_to_detail(cls, run: TestRun) -> TestRunDetail:
        """Convert a TestRun DB model to a TestRunDetail domain model."""
        summary = cls._test_run_to_summary(run)
        assertion_results = [
            TestAssertionResultSummary(
                id=ar.id,
                test_run_id=ar.test_run_id,
                assertion_type=ar.assertion_type,
                agent_id=ar.agent_id,
                tool_name=ar.tool_name,
                eval_name=ar.eval_name,
                passed=ar.passed,
                message=ar.message,
                judge_reasoning=ar.judge_reasoning,
                judge_raw_input=ar.judge_raw_input,
                judge_raw_output=ar.judge_raw_output,
                created_at=ar.created_at,
            )
            for ar in (run.assertion_results or [])
        ]
        return TestRunDetail(
            **summary.model_dump(),
            assertion_results=assertion_results,
        )

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
