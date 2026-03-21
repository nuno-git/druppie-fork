"""Benchmark scenario runner."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.benchmarks.assertions import AssertionResult, check_assertions
from druppie.benchmarks.schema import ScenarioDefinition, ScenarioFile
from druppie.benchmarks.user_simulator import UserSimulator
from druppie.db.models import BenchmarkRun, EvaluationResult
from druppie.evaluation.judge import JudgeEngine
from druppie.fixtures.ids import fixture_uuid
from druppie.fixtures.loader import seed_fixture
from druppie.fixtures.schema import (
    AgentRunFixture,
    MessageFixture,
    SessionFixture,
    SessionMetadata,
    ToolCallFixture,
)

logger = logging.getLogger(__name__)


class ScenarioResult:
    def __init__(self, scenario_name: str, session_id: UUID, benchmark_run_id: UUID):
        self.scenario_name = scenario_name
        self.session_id = session_id
        self.benchmark_run_id = benchmark_run_id
        self.assertion_results: list[AssertionResult] = []
        self.evaluation_results: list[EvaluationResult] = []
        self.errors: list[str] = []

    @property
    def assertions_passed(self) -> bool:
        return all(r.passed for r in self.assertion_results)

    @property
    def passed(self) -> bool:
        return self.assertions_passed and not self.errors


def load_scenario(path: Path) -> ScenarioDefinition:
    data = yaml.safe_load(path.read_text())
    return ScenarioFile(**data).scenario


def load_all_scenarios(scenarios_dir: Path) -> list[tuple[Path, ScenarioDefinition]]:
    return [(p, load_scenario(p)) for p in sorted(scenarios_dir.glob("*.yaml"))]


class ScenarioRunner:
    def __init__(
        self,
        db: DbSession,
        evaluations_dir: Path | None = None,
        judge_model: str | None = None,
        call_judge_fn=None,
    ):
        self._db = db
        self._judge_engine = JudgeEngine(evaluations_dir=evaluations_dir)
        self._judge_model = judge_model
        self._call_judge_fn = call_judge_fn

    def run(self, scenario: ScenarioDefinition) -> ScenarioResult:
        scenario_id = f"benchmark-{scenario.name}"
        session_id = fixture_uuid(scenario_id)

        git_commit, git_branch = _git_info()
        benchmark_run = BenchmarkRun(
            name=f"benchmark-{scenario.name}",
            run_type="batch",
            git_commit=git_commit,
            git_branch=git_branch,
            judge_model=self._judge_model,
            config_summary=f"scenario={scenario.name}",
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(benchmark_run)
        self._db.flush()

        result = ScenarioResult(scenario.name, session_id, benchmark_run.id)

        try:
            # Step 1: Convert scenario to fixture and seed DB
            fixture = self._scenario_to_fixture(scenario, scenario_id)
            seed_fixture(self._db, fixture)
            self._db.flush()

            # Step 2: Run assertions
            if scenario.assertions:
                result.assertion_results = check_assertions(
                    self._db, session_id, scenario.assertions
                )

            # Step 3: Run evaluations
            for eval_name in scenario.evaluations:
                try:
                    eval_results = self._judge_engine.evaluate(
                        db=self._db,
                        session_id=session_id,
                        evaluation_name=eval_name,
                        benchmark_run_id=benchmark_run.id,
                        judge_model_override=self._judge_model,
                        call_judge_fn=self._call_judge_fn,
                    )
                    result.evaluation_results.extend(eval_results)
                except (KeyError, ValueError) as e:
                    result.errors.append(f"Evaluation '{eval_name}': {e}")

            benchmark_run.completed_at = datetime.now(timezone.utc)
            self._db.flush()
        except Exception as e:
            result.errors.append(f"Scenario execution failed: {e}")
            logger.exception("Scenario %s failed", scenario.name)

        return result

    def _scenario_to_fixture(
        self, scenario: ScenarioDefinition, scenario_id: str
    ) -> SessionFixture:
        agents: list[AgentRunFixture] = []

        # Mocked agents: pre-defined tool calls
        for mocked in scenario.mocked_agents:
            agents.append(
                AgentRunFixture(
                    id=mocked.agent_id,
                    status=mocked.status,
                    tool_calls=list(mocked.tool_calls),
                    planned_prompt=mocked.planned_prompt,
                    error_message=mocked.error_message,
                )
            )

        # Agents under test: simulated as completed with done() call
        for agent_id in scenario.agents_under_test:
            agents.append(
                AgentRunFixture(
                    id=agent_id,
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={
                                "summary": (
                                    f"Agent {agent_id}: "
                                    "Simulated completion (benchmark)."
                                ),
                            },
                            status="completed",
                            result="Agent completed",
                        ),
                    ],
                )
            )

        # Extract intent/project from router's set_intent
        intent, project_name = None, None
        for mocked in scenario.mocked_agents:
            if mocked.agent_id == "router":
                for tc in mocked.tool_calls:
                    if tc.tool == "builtin:set_intent":
                        intent = tc.arguments.get("intent")
                        project_name = tc.arguments.get("project_name")

        return SessionFixture(
            metadata=SessionMetadata(
                id=scenario_id,
                title=scenario.input.user_message,
                status="completed",
                user=scenario.input.user,
                intent=intent,
                project_name=project_name,
                language="en",
                hours_ago=0,
            ),
            agents=agents,
            messages=[MessageFixture(role="user", content=scenario.input.user_message)],
        )


def _git_info() -> tuple[str | None, str | None]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None
