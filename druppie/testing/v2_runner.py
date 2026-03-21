"""V2 Test Runner -- user-isolated test execution with real LLM agents.

Each test gets its own user with their own sessions, projects, and repos.
Supports multi-HITL and multi-judge matrix execution.

Agent execution flow:
1. Create test user in DB
2. Seed history sessions (world state)
3. Call orchestrator.process_message() with the test message
4. Orchestrator runs agents sequentially; after each agent completes,
   a callback checks if the next agent is outside real_agents and
   cancels remaining pending runs to stop execution early.
5. When an agent pauses for HITL, the runner answers automatically
   using an LLM with the configured HITL profile prompt.
6. After execution, run deterministic assertions and LLM judge checks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import (
    AgentRun,
    BenchmarkRun,
    Question,
    ToolCall,
    User,
    UserRole,
)
from druppie.db.models import TestRun as TestRunModel
from druppie.db.models import TestRunTag
from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_loader import seed_fixture
from druppie.testing.seed_schema import SessionFixture
from druppie.testing.v2_assertions import AssertionResult, match_assertions
from druppie.testing.v2_schema import (
    EvalDefinition,
    EvalFile,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    TestDefinition,
    TestFile,
)

logger = logging.getLogger(__name__)

# Maximum number of HITL interactions before we give up
MAX_HITL_INTERACTIONS = 20


# ---------------------------------------------------------------------------
# Profile Loader
# ---------------------------------------------------------------------------


class ProfileLoader:
    """Loads HITL and judge profiles from YAML files."""

    def __init__(self, profiles_dir: Path | None = None):
        self._profiles_dir = profiles_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "profiles"
        )
        self._hitl: dict[str, HITLProfile] = {}
        self._judges: dict[str, JudgeProfile] = {}
        self._load()

    def _load(self) -> None:
        hitl_path = self._profiles_dir / "hitl.yaml"
        if hitl_path.exists():
            data = yaml.safe_load(hitl_path.read_text())
            parsed = HITLProfilesFile(**data)
            self._hitl = dict(parsed.profiles)

        judges_path = self._profiles_dir / "judges.yaml"
        if judges_path.exists():
            data = yaml.safe_load(judges_path.read_text())
            parsed = JudgeProfilesFile(**data)
            self._judges = dict(parsed.profiles)

    def get_hitl(self, name: str) -> HITLProfile:
        """Get an HITL profile by name. Returns a sensible default for 'default'."""
        if name == "default":
            return HITLProfile(
                model="Qwen/Qwen3-Next-80B-A3B-Instruct",
                provider="deepinfra",
                prompt="You are a helpful user who gives clear, concise answers.",
            )
        if name not in self._hitl:
            raise KeyError(
                f"Unknown HITL profile: {name}. "
                f"Available: {sorted(self._hitl.keys())}"
            )
        return self._hitl[name]

    def get_judge(self, name: str) -> JudgeProfile:
        """Get a judge profile by name. Returns a sensible default for 'default'."""
        if name == "default":
            return JudgeProfile(model="Qwen/Qwen3-Next-80B-A3B-Instruct", provider="deepinfra")
        if name not in self._judges:
            raise KeyError(
                f"Unknown judge profile: {name}. "
                f"Available: {sorted(self._judges.keys())}"
            )
        return self._judges[name]


# ---------------------------------------------------------------------------
# Eval Loader
# ---------------------------------------------------------------------------


class EvalLoader:
    """Loads eval definitions from YAML files."""

    def __init__(self, evals_dir: Path | None = None):
        self._evals_dir = evals_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "evals"
        )
        self._evals: dict[str, EvalDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._evals_dir.exists():
            logger.warning("Evals directory not found: %s", self._evals_dir)
            return
        for path in sorted(self._evals_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = EvalFile(**data)
            self._evals[parsed.eval.name] = parsed.eval

    def get(self, name: str) -> EvalDefinition:
        """Get an eval definition by name."""
        if name not in self._evals:
            raise KeyError(
                f"Unknown eval: {name}. Available: {sorted(self._evals.keys())}"
            )
        return self._evals[name]


# ---------------------------------------------------------------------------
# Session Loader
# ---------------------------------------------------------------------------


class SessionLoader:
    """Loads session definitions and resolves ``after:`` chains."""

    def __init__(self, sessions_dir: Path | None = None):
        self._sessions_dir = sessions_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "seeds"
        )
        self._sessions: dict[str, SessionFixture] = {}
        self._load()

    def _load(self) -> None:
        if not self._sessions_dir.exists():
            logger.warning("Sessions directory not found: %s", self._sessions_dir)
            return
        for path in sorted(self._sessions_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            fixture = SessionFixture(**data)
            # Register by metadata.id
            self._sessions[fixture.metadata.id] = fixture

    def get(self, name: str) -> SessionFixture:
        """Get a session fixture by name (metadata.id)."""
        if name not in self._sessions:
            raise KeyError(
                f"Unknown session: {name}. "
                f"Available: {sorted(self._sessions.keys())}"
            )
        return self._sessions[name]

    def resolve_chain(self, session_names: list[str]) -> list[SessionFixture]:
        """Resolve session chains (``after:`` references) and return ordered list.

        Each session is included at most once, even if referenced multiple times.
        Parents are always seeded before their children.
        """
        resolved: list[SessionFixture] = []
        seen: set[str] = set()
        for name in session_names:
            self._resolve_one(name, resolved, seen)
        return resolved

    def _resolve_one(
        self,
        name: str,
        resolved: list[SessionFixture],
        seen: set[str],
    ) -> None:
        if name in seen:
            return
        seen.add(name)
        session = self.get(name)
        # Recurse into parent if this session chains via after:
        if session.metadata.after:
            self._resolve_one(session.metadata.after, resolved, seen)
        resolved.append(session)


# ---------------------------------------------------------------------------
# Judge Check Result
# ---------------------------------------------------------------------------


@dataclass
class JudgeCheckResult:
    """Result from a single LLM judge check."""

    check: str
    passed: bool
    reasoning: str
    source: str  # "eval" or "inline"


# ---------------------------------------------------------------------------
# Test Run Result
# ---------------------------------------------------------------------------


@dataclass
class TestRunResult:
    """Result from running a single test with a specific HITL profile."""

    test_name: str
    test_user: str
    hitl_profile: str
    judge_profiles: list[str]
    assertion_results: list[AssertionResult]
    judge_results: list[JudgeCheckResult] = field(default_factory=list)
    status: str = "passed"
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "passed"


# ---------------------------------------------------------------------------
# HITL Simulator (lightweight, profile-based)
# ---------------------------------------------------------------------------


class HITLSimulator:
    """Simulates human-in-the-loop answers using an LLM with a profile prompt.

    Much simpler than the full UserSimulator -- just calls an LLM with the
    profile's system prompt and the agent's question.
    """

    def __init__(self, profile: HITLProfile):
        self._profile = profile
        self._interaction_count = 0

    def answer(
        self,
        question_text: str,
        choices: list[dict] | None = None,
    ) -> str:
        """Generate an answer to a HITL question using the configured LLM.

        Args:
            question_text: The question the agent is asking.
            choices: Optional list of choice dicts [{"text": "Option A"}, ...].

        Returns:
            The simulated user answer.
        """
        from druppie.llm.litellm_provider import ChatLiteLLM

        self._interaction_count += 1
        if self._interaction_count > MAX_HITL_INTERACTIONS:
            raise RuntimeError(
                f"Exceeded max HITL interactions ({MAX_HITL_INTERACTIONS})"
            )

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=0.7,
        )

        user_prompt = f"The AI agent asks you:\n\n{question_text}"
        if choices:
            user_prompt += "\n\nChoices:\n" + "\n".join(
                f"  {i + 1}. {c.get('text', c)}" for i, c in enumerate(choices)
            )
        user_prompt += "\n\nRespond with ONLY your answer, no explanation."

        response = llm.chat(
            messages=[
                {"role": "system", "content": self._profile.prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        answer = response.content.strip()
        logger.info(
            "HITL simulator answered (interaction %d): question=%s answer=%s",
            self._interaction_count,
            question_text[:80],
            answer[:80],
        )
        return answer


# ---------------------------------------------------------------------------
# Bounded Orchestrator (stops after real_agents complete)
# ---------------------------------------------------------------------------


class _BoundedOrchestrator:
    """Wraps the real Orchestrator to stop after the last real_agent completes.

    After each agent run completes, checks if the next pending agent is NOT
    in real_agents. If so, cancels all remaining pending runs and marks the
    session as completed to stop execution early.

    Also handles HITL: when the orchestrator pauses for a question, this
    wrapper detects the pause, generates an answer via HITLSimulator, and
    resumes execution.
    """

    def __init__(
        self,
        db: DbSession,
        user_id: UUID,
        real_agents: list[str],
        hitl_simulator: HITLSimulator | None,
    ):
        self._db = db
        self._user_id = user_id
        self._real_agents = real_agents
        self._hitl_simulator = hitl_simulator

    async def run(self, message: str) -> UUID:
        """Run the orchestrator with bounded agent execution.

        Returns the session_id.
        """
        from druppie.execution.orchestrator import Orchestrator
        from druppie.repositories import (
            ExecutionRepository,
            ProjectRepository,
            QuestionRepository,
            SessionRepository,
        )

        session_repo = SessionRepository(self._db)
        execution_repo = ExecutionRepository(self._db)
        project_repo = ProjectRepository(self._db)
        question_repo = QuestionRepository(self._db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
        )

        # If real_agents is empty, run the full pipeline
        if not self._real_agents:
            session_id = await orchestrator.process_message(
                message=message,
                user_id=self._user_id,
            )
            # Handle HITL during full pipeline
            session_id = await self._handle_hitl_loop(
                orchestrator, session_id, question_repo, execution_repo, session_repo
            )
            return session_id

        # Bounded execution: run process_message which creates the session,
        # saves user message, creates router + planner pending runs, then
        # calls execute_pending_runs(). We monkey-patch the orchestrator's
        # _run_agent to intercept after each agent completes.
        original_run_agent = orchestrator._run_agent
        completed_agents: list[str] = []

        async def _bounded_run_agent(
            session_id, agent_run_id, agent_id, prompt, context=None
        ):
            """Run agent, then check if we should stop."""
            result = await original_run_agent(
                session_id=session_id,
                agent_run_id=agent_run_id,
                agent_id=agent_id,
                prompt=prompt,
                context=context,
            )
            if result == "completed":
                completed_agents.append(agent_id)
            return result

        orchestrator._run_agent = _bounded_run_agent

        # Patch execute_pending_runs to stop after last real_agent
        original_execute = orchestrator.execute_pending_runs

        async def _bounded_execute(session_id):
            """Execute pending runs, stopping after the last real_agent."""
            while True:
                # Check for user-initiated pause
                session_repo.db.expire_all()
                session = session_repo.get_by_id(session_id)
                if session and session.status == SessionStatus.PAUSED.value:
                    return

                next_run = execution_repo.get_next_pending(session_id)
                if not next_run:
                    session_repo.update_status(session_id, SessionStatus.COMPLETED)
                    session_repo.commit()
                    return

                # If the next agent is NOT in real_agents and we've already
                # run at least one real agent, stop execution
                if (
                    next_run.agent_id not in self._real_agents
                    and completed_agents
                    # The agent that just completed was the last real_agent,
                    # or we've run all the real_agents we care about
                ):
                    # Check if all real_agents have completed
                    all_real_done = all(
                        a in completed_agents for a in self._real_agents
                    )
                    if all_real_done:
                        # Cancel remaining pending runs
                        pending = execution_repo.get_pending_runs(session_id)
                        for run in pending:
                            execution_repo.update_status(
                                run.id, AgentRunStatus.CANCELLED
                            )
                        execution_repo.commit()

                        session_repo.update_status(
                            session_id, SessionStatus.COMPLETED
                        )
                        session_repo.commit()
                        logger.info(
                            "Bounded execution stopped: session=%s completed=%s cancelled_next=%s",
                            session_id,
                            completed_agents,
                            next_run.agent_id,
                        )
                        return

                # Build context and run the agent
                context = orchestrator._build_project_context(session_id)
                execution_repo.update_status(next_run.id, AgentRunStatus.RUNNING)
                execution_repo.commit()

                status = await orchestrator._run_agent(
                    session_id=session_id,
                    agent_run_id=next_run.id,
                    agent_id=next_run.agent_id,
                    prompt=next_run.planned_prompt or "",
                    context=context,
                )

                if status == "paused":
                    # Determine pause type
                    refreshed = execution_repo.get_by_id(next_run.id)
                    if refreshed and refreshed.status == AgentRunStatus.PAUSED_HITL:
                        session_repo.update_status(
                            session_id, SessionStatus.PAUSED_HITL
                        )
                    elif (
                        refreshed
                        and refreshed.status == AgentRunStatus.PAUSED_SANDBOX
                    ):
                        session_repo.update_status(
                            session_id, SessionStatus.PAUSED_SANDBOX
                        )
                    else:
                        session_repo.update_status(
                            session_id, SessionStatus.PAUSED_APPROVAL
                        )
                    session_repo.commit()
                    return

        orchestrator.execute_pending_runs = _bounded_execute

        session_id = await orchestrator.process_message(
            message=message,
            user_id=self._user_id,
        )

        # Handle HITL loop after initial execution
        session_id = await self._handle_hitl_loop(
            orchestrator, session_id, question_repo, execution_repo, session_repo
        )

        return session_id

    async def _handle_hitl_loop(
        self,
        orchestrator,
        session_id: UUID,
        question_repo,
        execution_repo,
        session_repo,
    ) -> UUID:
        """Detect HITL pauses and answer them automatically.

        Loops until the session is no longer paused for HITL.
        """
        if not self._hitl_simulator:
            return session_id

        for _ in range(MAX_HITL_INTERACTIONS):
            # Refresh session status
            self._db.expire_all()
            from druppie.db.models import Session as DBSession

            session = self._db.query(DBSession).filter(
                DBSession.id == session_id
            ).first()
            if not session:
                break
            if session.status != SessionStatus.PAUSED_HITL.value:
                break

            # Find the pending question
            pending_question = (
                self._db.query(Question)
                .filter(
                    Question.session_id == session_id,
                    Question.status == "pending",
                )
                .order_by(Question.created_at.desc())
                .first()
            )
            if not pending_question:
                logger.warning(
                    "HITL pause but no pending question found: session=%s",
                    session_id,
                )
                break

            # Generate answer
            answer = self._hitl_simulator.answer(
                question_text=pending_question.question,
                choices=pending_question.choices,
            )

            # Resume the orchestrator with the answer
            logger.info(
                "HITL resuming with answer: session=%s question=%s answer=%s",
                session_id,
                pending_question.id,
                answer[:80],
            )
            await orchestrator.resume_after_answer(
                session_id=session_id,
                question_id=pending_question.id,
                answer=answer,
            )

        return session_id


# ---------------------------------------------------------------------------
# Judge Runner
# ---------------------------------------------------------------------------


class JudgeRunner:
    """Runs LLM judge checks against agent execution traces."""

    def __init__(self, profile: JudgeProfile):
        self._profile = profile

    def run_checks(
        self,
        db: DbSession,
        session_id: UUID,
        checks: list[str],
        target_agent: str,
        source: str = "eval",
    ) -> list[JudgeCheckResult]:
        """Run judge checks against an agent's execution trace.

        Args:
            db: Database session
            session_id: Session to evaluate
            checks: List of check descriptions (natural language)
            target_agent: Agent whose behavior to evaluate
            source: "eval" or "inline" (for tracking)

        Returns:
            List of JudgeCheckResult
        """
        # Get the agent trace
        agent_trace = self._extract_agent_trace(db, session_id, target_agent)
        if not agent_trace:
            return [
                JudgeCheckResult(
                    check=check,
                    passed=False,
                    reasoning=f"No execution trace found for agent '{target_agent}'",
                    source=source,
                )
                for check in checks
            ]

        results = []
        for check in checks:
            passed, reasoning = self._run_single_check(check, agent_trace)
            results.append(
                JudgeCheckResult(
                    check=check,
                    passed=passed,
                    reasoning=reasoning,
                    source=source,
                )
            )
        return results

    def _extract_agent_trace(
        self, db: DbSession, session_id: UUID, agent_id: str
    ) -> str:
        """Extract the execution trace for an agent from the DB.

        Includes tool calls with their arguments and results.
        """
        agent_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.agent_id == agent_id,
            )
            .order_by(AgentRun.sequence_number.desc())
            .first()
        )
        if not agent_run:
            return ""

        tool_calls = (
            db.query(ToolCall)
            .filter(ToolCall.agent_run_id == agent_run.id)
            .order_by(ToolCall.tool_call_index)
            .all()
        )

        lines = [f"Agent: {agent_id}", f"Status: {agent_run.status}", ""]
        lines.append("Tool calls:")
        for tc in tool_calls:
            args_str = json.dumps(tc.arguments) if tc.arguments else "{}"
            status = tc.status or "pending"
            result_part = ""
            if tc.result:
                # Truncate very long results
                result_text = tc.result[:500]
                result_part = f' -> "{result_text}"'
            lines.append(
                f"  [{tc.tool_call_index}] {tc.mcp_server}:{tc.tool_name}"
                f"({args_str}) status={status}{result_part}"
            )

        return "\n".join(lines)

    def _run_single_check(
        self, check: str, agent_trace: str
    ) -> tuple[bool, str]:
        """Call the judge LLM to evaluate a single check.

        Returns:
            (passed, reasoning)
        """
        from druppie.llm.litellm_provider import ChatLiteLLM

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=0.0,
        )

        prompt = f"""You are evaluating an AI agent's behavior.

The agent's execution trace (tool calls and results):
{agent_trace}

Evaluate this check:
{check}

Respond with JSON: {{"pass": true/false, "reasoning": "your explanation"}}"""

        try:
            response = llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an evaluation judge. "
                            "Respond ONLY with valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
            )
            return self._parse_judge_response(response.content)
        except Exception as e:
            logger.error("Judge check failed: check=%s error=%s", check[:80], str(e))
            return False, f"Judge call failed: {e}"

    @staticmethod
    def _parse_judge_response(response_text: str) -> tuple[bool, str]:
        """Parse judge JSON response into (passed, reasoning)."""
        try:
            text = response_text.strip()
            # Handle markdown code blocks
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                text = text.rsplit("```", 1)[0]
            data = json.loads(text)
            passed = bool(data.get("pass", False))
            reasoning = data.get("reasoning", "")
            return passed, reasoning
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Judge response parse failed: response=%s",
                response_text[:200],
            )
            return False, f"Failed to parse judge response: {response_text[:200]}"


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------


class TestRunner:
    """Main v2 test orchestrator.

    Creates isolated users per test, seeds sessions, runs real agents with
    LLM calls, handles HITL simulation, evaluates with assertions and LLM
    judge checks.
    """

    def __init__(
        self,
        db: DbSession,
        testing_dir: Path | None = None,
        gitea_url: str | None = None,
    ):
        self._db = db
        self._testing_dir = testing_dir or (
            Path(__file__).resolve().parents[2] / "testing"
        )
        self._gitea_url = gitea_url
        self._profiles = ProfileLoader(self._testing_dir / "profiles")
        self._evals = EvalLoader(self._testing_dir / "evals")
        self._sessions = SessionLoader(self._testing_dir / "seeds")

    def load_test(self, path: Path) -> TestDefinition:
        """Load a single test definition from a YAML file."""
        data = yaml.safe_load(path.read_text())
        return TestFile(**data).test

    def load_all_tests(
        self, tests_dir: Path | None = None
    ) -> list[tuple[Path, TestDefinition]]:
        """Load all test definitions from a directory."""
        d = tests_dir or self._testing_dir / "tests"
        return [(p, self.load_test(p)) for p in sorted(d.glob("*.yaml"))]

    def run_test(self, test: TestDefinition) -> list[TestRunResult]:
        """Run a test. Returns one TestRunResult per HITL profile."""
        results = []
        hitl_profiles = test.get_hitl_profiles()
        judge_profiles = test.get_judge_profiles()

        for hitl_name in hitl_profiles:
            result = self._run_single(test, hitl_name, judge_profiles)
            results.append(result)

        return results

    def _run_single(
        self,
        test: TestDefinition,
        hitl_name: str,
        judge_profiles: list[str],
    ) -> TestRunResult:
        """Run one execution of a test with a specific HITL profile."""
        start = time.time()
        timestamp = int(start)
        test_user = f"test-{test.name}-{hitl_name}-{timestamp}"

        # Create benchmark run
        git_commit, git_branch = _git_info()
        benchmark_run = BenchmarkRun(
            name=f"test-{test.name}",
            run_type="test",
            git_commit=git_commit,
            git_branch=git_branch,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(benchmark_run)
        self._db.flush()

        # Resolve and seed sessions (world state)
        sessions = self._sessions.resolve_chain(test.sessions)
        for session_fixture in sessions:
            # Override the user for isolation
            session_fixture.metadata.user = test_user
            seed_fixture(self._db, session_fixture, gitea_url=self._gitea_url)
        self._db.flush()

        # Create test user in DB (seed_fixture creates users, but ensure one
        # exists for the orchestrator)
        user = self._db.query(User).filter(User.username == test_user).first()
        if not user:
            user_id = uuid4()
            user = User(
                id=user_id,
                username=test_user,
                email=f"{test_user}@druppie.local",
                display_name=test_user.title(),
            )
            self._db.add(user)
            self._db.add(UserRole(user_id=user_id, role="admin"))
            self._db.flush()

        # Resolve HITL profile
        hitl_profile: HITLProfile | None = None
        if hitl_name == "inline" and isinstance(test.hitl, HITLProfile):
            hitl_profile = test.hitl
        else:
            try:
                hitl_profile = self._profiles.get_hitl(hitl_name)
            except KeyError:
                logger.warning("HITL profile not found: %s", hitl_name)

        # Run real agent execution
        execution_session_id: UUID | None = None
        execution_error: str | None = None
        if test.run.message:
            try:
                execution_session_id = self._execute_agents(
                    message=test.run.message,
                    user_id=user.id,
                    real_agents=test.run.real_agents,
                    hitl_profile=hitl_profile,
                )
            except Exception as e:
                execution_error = f"{type(e).__name__}: {e}"
                logger.error(
                    "Agent execution failed: test=%s error=%s",
                    test.name,
                    execution_error,
                    exc_info=True,
                )

        # Determine the session to evaluate against
        # Prefer the execution session (where real agents ran);
        # fall back to the last seeded session for assertion-only tests
        eval_session_id: UUID | None = execution_session_id
        if eval_session_id is None and sessions:
            eval_session_id = fixture_uuid(sessions[-1].metadata.id)

        # Evaluate with assertions
        all_assertion_results: list[AssertionResult] = []
        if eval_session_id is not None:
            for eval_ref in test.evals:
                eval_def = self._evals.get(eval_ref.eval)
                assertion_results = match_assertions(
                    self._db,
                    eval_session_id,
                    eval_def.assertions,
                    eval_ref.expected,
                )
                all_assertion_results.extend(assertion_results)

            # Inline assertions
            if test.evaluate and test.evaluate.assertions:
                inline_results = match_assertions(
                    self._db,
                    eval_session_id,
                    test.evaluate.assertions,
                    {},
                )
                all_assertion_results.extend(inline_results)

        # Run judge checks
        all_judge_results: list[JudgeCheckResult] = []
        if eval_session_id is not None:
            for judge_name in judge_profiles:
                try:
                    judge_profile = self._profiles.get_judge(judge_name)
                except KeyError:
                    logger.warning("Judge profile not found: %s", judge_name)
                    continue

                judge = JudgeRunner(judge_profile)

                # Eval judge checks
                for eval_ref in test.evals:
                    eval_def = self._evals.get(eval_ref.eval)
                    if eval_def.judge and eval_def.judge.checks:
                        # Determine target agent from assertions (first agent mentioned)
                        target_agent = (
                            eval_def.assertions[0].agent
                            if eval_def.assertions
                            else "router"
                        )
                        judge_results = judge.run_checks(
                            db=self._db,
                            session_id=eval_session_id,
                            checks=eval_def.judge.checks,
                            target_agent=target_agent,
                            source="eval",
                        )
                        all_judge_results.extend(judge_results)

                # Inline judge checks
                if test.evaluate and test.evaluate.judge:
                    # Determine target agent from inline assertions
                    target_agent = "router"
                    if test.evaluate.assertions:
                        target_agent = test.evaluate.assertions[0].agent
                    judge_results = judge.run_checks(
                        db=self._db,
                        session_id=eval_session_id,
                        checks=test.evaluate.judge.checks,
                        target_agent=target_agent,
                        source="inline",
                    )
                    all_judge_results.extend(judge_results)

        # Compute status
        duration_ms = int((time.time() - start) * 1000)
        assertions_passed = sum(1 for r in all_assertion_results if r.passed)
        assertions_total = len(all_assertion_results)
        judge_passed = sum(1 for r in all_judge_results if r.passed)
        judge_total = len(all_judge_results)

        if execution_error:
            status = "error"
        elif assertions_total == 0 and judge_total == 0:
            status = "passed"  # No checks = vacuously passed
        elif assertions_passed == assertions_total and judge_passed == judge_total:
            status = "passed"
        else:
            status = "failed"

        # Store test run record
        test_run = TestRunModel(
            benchmark_run_id=benchmark_run.id,
            test_name=test.name,
            test_description=test.description,
            test_user=test_user,
            hitl_profile=hitl_name,
            sessions_seeded=len(sessions),
            assertions_total=assertions_total,
            assertions_passed=assertions_passed,
            judge_checks_total=judge_total,
            judge_checks_passed=judge_passed,
            status=status,
            duration_ms=duration_ms,
        )
        self._db.add(test_run)
        self._db.flush()

        # Store tags (from all referenced evals)
        tags: set[str] = set()
        for eval_ref in test.evals:
            eval_def = self._evals.get(eval_ref.eval)
            tags.update(eval_def.tags)
        for tag in tags:
            self._db.add(TestRunTag(test_run_id=test_run.id, tag=tag))
        self._db.flush()

        benchmark_run.completed_at = datetime.now(timezone.utc)
        self._db.flush()

        return TestRunResult(
            test_name=test.name,
            test_user=test_user,
            hitl_profile=hitl_name,
            judge_profiles=judge_profiles,
            assertion_results=all_assertion_results,
            judge_results=all_judge_results,
            status=status,
            duration_ms=duration_ms,
        )

    def _execute_agents(
        self,
        message: str,
        user_id: UUID,
        real_agents: list[str],
        hitl_profile: HITLProfile | None,
    ) -> UUID:
        """Execute agents with real LLM calls via the orchestrator.

        Creates a bounded orchestrator that stops after the last real_agent
        completes and handles HITL automatically.

        Returns:
            The session_id of the newly created session.
        """
        hitl_sim = HITLSimulator(hitl_profile) if hitl_profile else None
        bounded = _BoundedOrchestrator(
            db=self._db,
            user_id=user_id,
            real_agents=real_agents,
            hitl_simulator=hitl_sim,
        )

        # Run the async orchestrator in a sync context
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            # Already in an async context -- create a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, bounded.run(message))
                return future.result(timeout=300)
        else:
            return asyncio.run(bounded.run(message))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_info() -> tuple[str | None, str | None]:
    """Return (commit, branch) from git, or (None, None) on failure."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None
