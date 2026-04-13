"""V2 Test Runner -- user-isolated test execution with two test types.

Test types:
- Tool tests (testing/tools/): Replay tool call chains through real MCP services.
- Agent tests (testing/agents/): Run real LLM agents with assertions + judge.

Execution flow for tool tests:
1. Create test user in DB
2. Run setup tool tests (real MCP execution, each creates a session)
3. Replay the main tool chain through real MCP handlers
4. Run inline assertions on chain steps

Execution flow for agent tests:
1. Create test user in DB
2. Run setup tool tests (real MCP execution, each creates a session)
3. Call orchestrator.process_message() with the test message
4. Orchestrator runs agents; bounded to stop after specified agents complete
5. When an agent pauses for HITL, answer automatically via HITLSimulator
6. Run assertions and LLM judge checks
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
    Message,
    Question,
    ToolCall,
    User,
    UserRole,
)
from druppie.db.models import TestRun as TestRunModel
from druppie.db.models import TestRunTag
from druppie.domain.common import AgentRunStatus, SessionStatus
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_schema import SessionFixture
from druppie.testing.v2_assertions import AssertionResult, match_assertions
from druppie.testing.v2_schema import (
    AgentTestDefinition,
    AgentTestFile,
    CheckAssertion,
    CheckDefinition,
    CheckFile,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    ToolTestDefinition,
    ToolTestFile,
)

logger = logging.getLogger(__name__)

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
        if name == "default":
            return HITLProfile(
                model="glm-5",
                provider="zai",
                prompt="You are a helpful user who gives clear, concise answers.",
            )
        if name not in self._hitl:
            raise KeyError(
                f"Unknown HITL profile: {name}. "
                f"Available: {sorted(self._hitl.keys())}"
            )
        return self._hitl[name]

    def get_judge(self, name: str) -> JudgeProfile:
        if name == "default":
            return JudgeProfile(model="glm-5", provider="zai")
        if name not in self._judges:
            raise KeyError(
                f"Unknown judge profile: {name}. "
                f"Available: {sorted(self._judges.keys())}"
            )
        return self._judges[name]


# ---------------------------------------------------------------------------
# Check Loader (was EvalLoader)
# ---------------------------------------------------------------------------


class CheckLoader:
    """Loads check definitions from YAML files."""

    def __init__(self, checks_dir: Path | None = None):
        self._checks_dir = checks_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "checks"
        )
        self._checks: dict[str, CheckDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._checks_dir.exists():
            logger.warning("Checks directory not found: %s", self._checks_dir)
            return
        for path in sorted(self._checks_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = CheckFile(**data)
            self._checks[parsed.check.name] = parsed.check

    def get(self, name: str) -> CheckDefinition:
        if name not in self._checks:
            raise KeyError(
                f"Unknown check: {name}. Available: {sorted(self._checks.keys())}"
            )
        return self._checks[name]


# Backwards compat alias
EvalLoader = CheckLoader



# ---------------------------------------------------------------------------
# Tool Test Loader
# ---------------------------------------------------------------------------


class ToolTestLoader:
    """Loads tool test definitions from YAML files."""

    def __init__(self, tools_dir: Path | None = None):
        self._tools_dir = tools_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "tools"
        )
        self._tests: dict[str, ToolTestDefinition] = {}
        self._load()

    def _load(self) -> None:
        if not self._tools_dir.exists():
            logger.warning("Tools directory not found: %s", self._tools_dir)
            return
        for path in sorted(self._tools_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            parsed = ToolTestFile(**data)
            self._tests[parsed.tool_test.name] = parsed.tool_test

    def get(self, name: str) -> ToolTestDefinition:
        if name not in self._tests:
            raise KeyError(
                f"Unknown tool test: {name}. Available: {sorted(self._tests.keys())}"
            )
        return self._tests[name]

    def all(self) -> list[ToolTestDefinition]:
        return list(self._tests.values())


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class JudgeCheckResult:
    check: str
    passed: bool
    reasoning: str
    source: str  # "check" or "inline"
    raw_input: str = ""   # prompt sent to judge LLM
    raw_output: str = ""  # raw response from judge LLM


@dataclass
class TestRunResult:
    test_name: str
    test_user: str
    test_type: str  # "tool" or "agent"
    hitl_profile: str = "none"
    judge_profiles: list[str] = field(default_factory=list)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    judge_results: list[JudgeCheckResult] = field(default_factory=list)
    status: str = "passed"
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "passed"


# ---------------------------------------------------------------------------
# HITL Simulator
# ---------------------------------------------------------------------------


class HITLSimulator:
    """Simulates human-in-the-loop answers using an LLM with a profile prompt."""

    def __init__(self, profile: HITLProfile, test_context: str = ""):
        self._profile = profile
        self._test_context = test_context
        self._interaction_count = 0

    def answer(self, question_text: str, choices: list[dict] | None = None) -> str:
        from druppie.llm.litellm_provider import ChatLiteLLM

        self._interaction_count += 1
        if self._interaction_count > MAX_HITL_INTERACTIONS:
            raise RuntimeError(f"Exceeded max HITL interactions ({MAX_HITL_INTERACTIONS})")

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=0.7,
        )

        system_parts = [self._profile.prompt.strip()]
        if self._test_context:
            system_parts.append(f'\nContext: The user originally requested: "{self._test_context}"')
        system_parts.append(
            "\nWhen asked multiple choice questions, respond with the FULL TEXT of your chosen option, NOT a number."
            "\nWhen asked open-ended questions, give a clear 1-2 sentence answer."
        )
        system_prompt = "\n".join(system_parts)

        is_choice_question = bool(choices)
        if is_choice_question:
            choice_lines = []
            for i, c in enumerate(choices):
                text = c.get("text", c) if isinstance(c, dict) else str(c)
                choice_lines.append(f"{i + 1}. {text}")
            user_prompt = (
                f'The agent asks you a multiple choice question:\n\n'
                f'"{question_text}"\n\n'
                f'Options:\n'
                + "\n".join(choice_lines)
                + "\n\nRespond with the FULL TEXT of your chosen option, NOT a number."
            )
        else:
            user_prompt = (
                f'The agent asks you:\n\n'
                f'"{question_text}"\n\n'
                f'Respond with ONLY your answer, no explanation.'
            )

        # Retry on rate limits
        for attempt in range(5):
            try:
                response = llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                )
                answer = response.content.strip()
                logger.info("HITL simulator answered (interaction %d): question=%s answer=%s",
                             self._interaction_count, question_text[:80], answer[:80])
                return answer
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 4:
                    import time
                    wait = 2 ** attempt
                    logger.warning("HITL simulator rate limited, retrying in %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                else:
                    raise


# ---------------------------------------------------------------------------
# Bounded Orchestrator
# ---------------------------------------------------------------------------


class _BoundedOrchestrator:
    """Wraps the real Orchestrator to stop after the last real_agent completes."""

    def __init__(self, db: DbSession, user_id: UUID, real_agents: list[str],
                 hitl_simulator: HITLSimulator | None):
        self._db = db
        self._user_id = user_id
        self._real_agents = real_agents
        self._hitl_simulator = hitl_simulator

    def _all_real_agents_done(self, session_id: UUID, execution_repo) -> bool:
        if not self._real_agents:
            return False
        self._db.expire_all()
        completed_runs = execution_repo.get_completed_runs(session_id)
        completed_ids = {r.agent_id for r in completed_runs}
        done = all(a in completed_ids for a in self._real_agents)
        if done:
            logger.info("All real_agents completed: real=%s completed=%s",
                        self._real_agents, sorted(completed_ids))
        return done

    def _cancel_remaining_runs(self, session_id: UUID, execution_repo, session_repo) -> None:
        cancelled_count = execution_repo.cancel_pending_runs(session_id)
        execution_repo.commit()
        running = execution_repo.get_running_run(session_id)
        if running:
            execution_repo.update_status(running.id, AgentRunStatus.CANCELLED)
            execution_repo.commit()
            cancelled_count += 1
        session_repo.update_status(session_id, SessionStatus.COMPLETED)
        session_repo.commit()
        logger.info("Bounded cleanup: cancelled %d remaining runs, session=%s marked COMPLETED",
                     cancelled_count, session_id)

    async def run(self, message: str, session_id: UUID | None = None) -> UUID:
        from druppie.execution.orchestrator import Orchestrator
        from druppie.repositories import (
            ExecutionRepository, ProjectRepository, QuestionRepository, SessionRepository,
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

        if not self._real_agents:
            session_id = await orchestrator.process_message(
                message=message, user_id=self._user_id, session_id=session_id,
            )
            session_id = await self._handle_pause_loop(
                orchestrator, session_id, question_repo, execution_repo, session_repo
            )
            return session_id

        async def _bounded_execute(session_id):
            while True:
                session_repo.db.expire_all()
                session = session_repo.get_by_id(session_id)
                if session and session.status == SessionStatus.PAUSED.value:
                    return

                next_run = execution_repo.get_next_pending(session_id)
                if not next_run:
                    session_repo.update_status(session_id, SessionStatus.COMPLETED)
                    session_repo.commit()
                    return

                if next_run.agent_id not in self._real_agents:
                    if self._all_real_agents_done(session_id, execution_repo):
                        self._cancel_remaining_runs(session_id, execution_repo, session_repo)
                        return

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
                    refreshed = execution_repo.get_by_id(next_run.id)
                    if refreshed and refreshed.status == AgentRunStatus.PAUSED_HITL:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                    elif refreshed and refreshed.status == AgentRunStatus.PAUSED_SANDBOX:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                    else:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                    session_repo.commit()
                    return

        orchestrator.execute_pending_runs = _bounded_execute

        if session_id:
            # Continue existing session: create agent runs directly
            # instead of going through process_message (which creates router+planner)
            result_session_id = session_id

            # Reset session to active
            session_repo.update_status(session_id, SessionStatus.ACTIVE)
            session_repo.commit()

            # Add user message
            from druppie.db.models.base import utcnow
            next_seq = execution_repo.get_next_sequence_number(session_id)
            self._db.add(Message(
                session_id=session_id,
                role="user",
                content=message,
                sequence_number=next_seq,
                created_at=utcnow(),
            ))
            self._db.flush()

            # Build context from the session's project
            context = orchestrator._build_project_context(session_id)

            # Get the last done summary for prompt context
            completed_runs = execution_repo.get_completed_runs(session_id)
            previous_summary = ""
            for run in completed_runs:
                s = execution_repo.get_done_summary_for_run(run.id)
                if s:
                    previous_summary += s + "\n"

            # Create and run each specified agent directly
            for i, agent_id in enumerate(self._real_agents):
                prompt = f"PREVIOUS AGENT SUMMARY:\n{previous_summary}\n---\n\nUSER REQUEST:\n{message}"

                agent_run = execution_repo.create_agent_run(
                    session_id=session_id,
                    agent_id=agent_id,
                    status=AgentRunStatus.PENDING,
                    planned_prompt=prompt,
                    sequence_number=next_seq + 1 + i,
                )
                execution_repo.commit()

                execution_repo.update_status(agent_run.id, AgentRunStatus.RUNNING)
                execution_repo.commit()

                status = await orchestrator._run_agent(
                    session_id=session_id,
                    agent_run_id=agent_run.id,
                    agent_id=agent_id,
                    prompt=prompt,
                    context=context,
                )

                if status == "paused":
                    refreshed = execution_repo.get_by_id(agent_run.id)
                    if refreshed and refreshed.status == AgentRunStatus.PAUSED_HITL:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
                    elif refreshed and refreshed.status == AgentRunStatus.PAUSED_SANDBOX:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_SANDBOX)
                    else:
                        session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
                    session_repo.commit()

                    # Handle pauses (HITL + approvals)
                    result_session_id = await self._handle_pause_loop(
                        orchestrator, session_id, question_repo, execution_repo, session_repo
                    )

                # Update summary for next agent
                run_summary = execution_repo.get_done_summary_for_run(agent_run.id)
                if run_summary:
                    previous_summary += run_summary + "\n"

            session_repo.update_status(session_id, SessionStatus.COMPLETED)
            session_repo.commit()
        else:
            # New session: use normal process_message flow
            result_session_id = await orchestrator.process_message(
                message=message, user_id=self._user_id,
            )
            result_session_id = await self._handle_pause_loop(
                orchestrator, result_session_id, question_repo, execution_repo, session_repo
            )

            if self._all_real_agents_done(result_session_id, execution_repo):
                self._cancel_remaining_runs(result_session_id, execution_repo, session_repo)

        return result_session_id

    async def _handle_pause_loop(self, orchestrator, session_id, question_repo,
                                 execution_repo, session_repo) -> UUID:
        """Handle HITL questions and approval gates during agent execution.

        Loops until the session is no longer paused (completed, failed, or
        all real agents done).
        """
        from druppie.db.models import Session as DBSession
        from druppie.db.models import Approval
        from druppie.db.models.base import utcnow

        for iteration in range(MAX_HITL_INTERACTIONS * 2):
            self._db.expire_all()
            session = self._db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session:
                break

            status = session.status
            logger.info("Pause loop iteration %d: session status=%s", iteration, status)

            if self._real_agents and self._all_real_agents_done(session_id, execution_repo):
                break

            # Handle HITL pause
            if status == SessionStatus.PAUSED_HITL.value:
                if not self._hitl_simulator:
                    logger.warning("No HITL simulator — cannot answer questions")
                    break

                pending_question = (
                    self._db.query(Question)
                    .filter(Question.session_id == session_id, Question.status == "pending")
                    .order_by(Question.created_at.desc())
                    .first()
                )
                if not pending_question:
                    break

                if self._real_agents and pending_question.agent_run_id:
                    agent_run = self._db.query(AgentRun).filter(
                        AgentRun.id == pending_question.agent_run_id
                    ).first()
                    if agent_run and agent_run.agent_id not in self._real_agents:
                        break

                raw_answer = self._hitl_simulator.answer(
                    question_text=pending_question.question,
                    choices=pending_question.choices,
                )

                answer = raw_answer
                if pending_question.choices and pending_question.question_type in (
                    "single_choice", "multiple_choice",
                ):
                    answer, _ = self._resolve_choice_answer(raw_answer, pending_question.choices)

                logger.info("HITL auto-answer (iteration %d): answer=%s", iteration, answer[:80])
                await orchestrator.resume_after_answer(
                    session_id=session_id,
                    question_id=pending_question.id,
                    answer=answer,
                )
                continue

            # Handle approval pause
            if status == SessionStatus.PAUSED_APPROVAL.value:
                pending_approval = (
                    self._db.query(Approval)
                    .filter(Approval.session_id == session_id, Approval.status == "pending")
                    .order_by(Approval.created_at.desc())
                    .first()
                )
                if not pending_approval:
                    break

                # Auto-approve with the test user
                pending_approval.status = "approved"
                pending_approval.resolved_by = session.user_id
                pending_approval.resolved_at = utcnow()
                self._db.commit()

                logger.info("Approval auto-approved (iteration %d): tool=%s:%s",
                            iteration, pending_approval.mcp_server, pending_approval.tool_name)
                await orchestrator.resume_after_approval(
                    session_id=session_id,
                    approval_id=pending_approval.id,
                )
                continue

            # Not paused — done
            break

        return session_id

    @staticmethod
    def _resolve_choice_answer(raw_answer: str, choices: list[dict]) -> tuple[str, list[int] | None]:
        text = raw_answer.strip().rstrip(".")
        choice_texts = []
        for c in choices:
            ct = c.get("text", str(c)) if isinstance(c, dict) else str(c)
            choice_texts.append(ct)

        text_lower = text.lower()
        for idx, ct in enumerate(choice_texts):
            if ct.lower() == text_lower:
                return ct, [idx]
        for idx, ct in enumerate(choice_texts):
            if ct.lower() in text_lower or text_lower in ct.lower():
                return ct, [idx]

        try:
            choice_num = int(text)
        except ValueError:
            return raw_answer, None

        idx = choice_num - 1
        if 0 <= idx < len(choices):
            return choice_texts[idx], [idx]
        return raw_answer, None


# ---------------------------------------------------------------------------
# Judge Runner
# ---------------------------------------------------------------------------


class JudgeRunner:
    """Runs LLM judge checks against agent execution traces."""

    def __init__(self, profile: JudgeProfile):
        self._profile = profile

    def run_checks(self, db: DbSession, session_id: UUID,
                   judge_checks: list,
                   context: str | list[str] = "all", source: str = "check") -> list[JudgeCheckResult]:
        """Run judge checks. judge_checks is a list of JudgeCheck objects."""
        agent_trace = self._extract_agent_trace(db, session_id, context)
        if not agent_trace:
            return [
                JudgeCheckResult(check=jc.check, passed=False,
                                 reasoning=f"No execution trace found",
                                 source=source)
                for jc in judge_checks
            ]

        results = []
        for jc in judge_checks:
            judge_passed, reasoning, raw_input, raw_output = self._run_single_check(jc.check, agent_trace)

            if jc.is_eval:
                # Judge Eval — we're testing the judge itself
                final_passed = (judge_passed == jc.expected)
                expected_label = "PASS" if jc.expected else "FAIL"
                actual_label = "PASS" if judge_passed else "FAIL"
                reasoning = f"[Judge Eval: expected {expected_label}, got {actual_label}] {reasoning}"
                result_source = "judge_eval"
            else:
                # LLM Judge — verdict IS the result
                final_passed = judge_passed
                result_source = source

            results.append(JudgeCheckResult(
                check=jc.check, passed=final_passed, reasoning=reasoning, source=result_source,
                raw_input=raw_input, raw_output=raw_output,
            ))
        return results

    def _extract_agent_trace(self, db: DbSession, session_id: UUID,
                             context: str | list[str] = "all") -> str:
        """Extract execution trace for the judge.

        context can be:
        - "all": all agent runs in the session
        - "business_analyst": all runs of that agent
        - ["business_analyst", "architect"]: all runs of those agents
        """
        user_message = (
            db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.sequence_number.asc())
            .first()
        )

        # Determine which agent runs to include
        if context == "all":
            agent_runs = (
                db.query(AgentRun)
                .filter(AgentRun.session_id == session_id)
                .order_by(AgentRun.sequence_number.asc())
                .all()
            )
        else:
            agent_ids = [context] if isinstance(context, str) else context
            agent_runs = (
                db.query(AgentRun)
                .filter(
                    AgentRun.session_id == session_id,
                    AgentRun.agent_id.in_(agent_ids),
                )
                .order_by(AgentRun.sequence_number.asc())
                .all()
            )

        if not agent_runs:
            return ""

        lines = []
        if user_message:
            lines.append(f'User message: "{user_message.content}"')
            lines.append("")

        for agent_run in agent_runs:
            tool_calls = (
                db.query(ToolCall)
                .filter(ToolCall.agent_run_id == agent_run.id)
                .order_by(ToolCall.created_at.asc())
                .all()
            )

            lines.append(f"Agent: {agent_run.agent_id} (run #{agent_run.sequence_number}, status: {agent_run.status})")
            if tool_calls:
                lines.append("Tool calls (in execution order):")
                for idx, tc in enumerate(tool_calls):
                    args_str = json.dumps(tc.arguments) if tc.arguments else "{}"
                    result_part = f" -> {tc.status or 'pending'}"
                    if tc.result:
                        result_part = f" -> {tc.result[:500]}"
                    if tc.error_message:
                        result_part += f" [error: {tc.error_message[:200]}]"
                    lines.append(f"  [{idx}] {tc.mcp_server}:{tc.tool_name}({args_str}){result_part}")
            else:
                lines.append("  (no tool calls)")
            lines.append("")

        return "\n".join(lines)

    def _run_single_check(self, check: str, agent_trace: str) -> tuple[bool, str, str, str]:
        from druppie.llm.litellm_provider import ChatLiteLLM

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=0.0,
        )

        prompt = f"""You are evaluating an AI agent's behavior.

The following trace shows the user's original message and the agent's execution (tool calls and results):

---
{agent_trace}
---

Evaluate this check:
{check}

Respond with JSON: {{"pass": true/false, "reasoning": "your explanation"}}"""

        messages = [
            {"role": "system", "content": "You are an evaluation judge. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(5):
            try:
                response = llm.chat(messages=messages)
                passed, reasoning = self._parse_judge_response(response.content)
                return passed, reasoning, prompt, response.content
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 4:
                    import time
                    wait = 2 ** attempt
                    logger.warning("Judge rate limited, retrying in %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                else:
                    logger.error("Judge check failed: check=%s error=%s", check[:80], str(e))
                    return False, f"Judge call failed: {e}", prompt, ""
        return False, "Judge call failed after retries", prompt, ""

    @staticmethod
    def _parse_judge_response(response_text: str) -> tuple[bool, str]:
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                text = text.rsplit("```", 1)[0]
            data = json.loads(text)
            passed = bool(data.get("pass", False))
            reasoning = data.get("reasoning", "")
            return passed, reasoning
        except (json.JSONDecodeError, ValueError):
            logger.warning("Judge response parse failed: response=%s", response_text[:200])
            return False, f"Failed to parse judge response: {response_text[:200]}"


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------


class TestRunner:
    """Main v2 test orchestrator.

    Handles both tool tests and agent tests with user isolation.
    """

    def __init__(self, db: DbSession, testing_dir: Path | None = None, gitea_url: str | None = None):
        self._db = db
        self._testing_dir = testing_dir or (Path(__file__).resolve().parents[2] / "testing")
        self._gitea_url = gitea_url
        self._profiles = ProfileLoader(self._testing_dir / "profiles")
        self._checks = CheckLoader(self._testing_dir / "checks")
        self._tool_tests = ToolTestLoader(self._testing_dir / "tools")

    # Keep old attribute name for API route compatibility
    @property
    def _evals(self):
        return self._checks

    def load_agent_test(self, path: Path) -> AgentTestDefinition:
        data = yaml.safe_load(path.read_text())
        return AgentTestFile(**data).agent_test

    def load_tool_test(self, path: Path) -> ToolTestDefinition:
        data = yaml.safe_load(path.read_text())
        return ToolTestFile(**data).tool_test

    def load_test(self, path: Path) -> AgentTestDefinition | ToolTestDefinition:
        """Load a test from any path, detecting type from content."""
        data = yaml.safe_load(path.read_text())
        if "tool-test" in data:
            return ToolTestFile(**data).tool_test
        elif "agent-test" in data:
            return AgentTestFile(**data).agent_test
        else:
            # Backwards compat: old format with test: root key
            from druppie.testing.v2_schema import TestFile
            return TestFile(**data).test

    def load_all_tests(self, tests_dir: Path | None = None) -> list[tuple[Path, AgentTestDefinition | ToolTestDefinition]]:
        """Load all test definitions from tools/, agents/, and agents/manual/."""
        results = []
        for subdir in ["tools", "agents", "agents/manual"]:
            d = (tests_dir or self._testing_dir) / subdir if tests_dir else self._testing_dir / subdir
            if d.exists():
                for p in sorted(d.glob("*.yaml")):
                    try:
                        results.append((p, self.load_test(p)))
                    except Exception as e:
                        logger.warning("Failed to load test %s: %s", p, e)
        return results

    def run_test(self, test: AgentTestDefinition | ToolTestDefinition,
                 execute: bool = True, judge: bool = True,
                 batch_id: str | None = None) -> list[TestRunResult]:
        """Run a test. Returns one TestRunResult per HITL profile."""
        if isinstance(test, ToolTestDefinition):
            return [self._run_tool_test(test, batch_id=batch_id)]
        else:
            results = []
            hitl_profiles = test.get_hitl_profiles()
            for hitl_name in hitl_profiles:
                result = self._run_agent_test(
                    test, hitl_name, execute=execute, judge=judge, batch_id=batch_id,
                )
                results.append(result)
            return results

    # ------------------------------------------------------------------
    # Tool Test Runner
    # ------------------------------------------------------------------

    def _run_tool_test(self, test: ToolTestDefinition, batch_id: str | None = None) -> TestRunResult:
        start = time.time()
        timestamp = int(start)

        import hashlib
        short_hash = hashlib.md5(f"{test.name}-tool-{timestamp}".encode()).hexdigest()[:8]
        test_user = f"t-{short_hash}"

        git_commit, git_branch = _git_info()
        benchmark_run = BenchmarkRun(
            name=f"tool-{test.name}", run_type="test",
            git_commit=git_commit, git_branch=git_branch,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(benchmark_run)
        self._db.flush()

        # Create test user
        user = self._db.query(User).filter(User.username == test_user).first()
        if not user:
            user_id = uuid4()
            user = User(id=user_id, username=test_user, email=f"{test_user}@druppie.local",
                        display_name=test_user.title())
            self._db.add(user)
            self._db.add(UserRole(user_id=user_id, role="admin"))
            self._db.flush()

        # Phase 1: Run setup tool tests (real tool execution)
        run_namespace = test_user
        for setup_name in test.setup:
            setup_test = self._tool_tests.get(setup_name)
            self._replay_chain(setup_test, user.id, run_namespace)

        # Phase 1b: Run extended tool chain if specified
        if test.extends:
            extended = self._tool_tests.get(test.extends)
            self._replay_chain(extended, user.id, run_namespace)

        # Phase 2: Replay the tool call chain
        all_assertion_results: list[AssertionResult] = []
        replay_session_id = None
        try:
            replay_session_id, chain_results = self._replay_chain(test, user.id, run_namespace)
            all_assertion_results.extend(chain_results)
        except Exception as e:
            logger.error("Tool chain replay failed: test=%s error=%s", test.name, e, exc_info=True)

        # Phase 3: Run top-level check assertions
        if replay_session_id and test.assert_:
            for check_ref in test.assert_:
                check_def = self._checks.get(check_ref.check)
                results = match_assertions(self._db, replay_session_id, check_def.assert_, check_ref.expected)
                all_assertion_results.extend(results)

        # Phase 4: Judge checks (if configured)
        all_judge_results: list[JudgeCheckResult] = []
        if replay_session_id and test.judge:
            try:
                judge_profile = self._profiles.get_judge("default")
                judge_runner = JudgeRunner(judge_profile)
                judge_checks, judge_context = self._resolve_judge_config(test.judge)
                if judge_checks:
                    judge_results = judge_runner.run_checks(
                        db=self._db, session_id=replay_session_id,
                        judge_checks=judge_checks, context=judge_context, source="inline",
                    )
                    all_judge_results.extend(judge_results)
            except Exception as e:
                logger.error("Tool test judge failed: test=%s error=%s", test.name, e, exc_info=True)

        # Compute status
        duration_ms = int((time.time() - start) * 1000)
        assertions_passed = sum(1 for r in all_assertion_results if r.passed)
        assertions_total = len(all_assertion_results)
        judge_passed = sum(1 for r in all_judge_results if r.passed)
        judge_total = len(all_judge_results)

        if assertions_total == 0 and judge_total == 0:
            status = "passed"
        elif assertions_passed == assertions_total and judge_passed == judge_total:
            status = "passed"
        else:
            status = "failed"

        # Store results
        test_run = TestRunModel(
            benchmark_run_id=benchmark_run.id, batch_id=batch_id,
            test_name=test.name, test_description=test.description,
            test_user=test_user, hitl_profile="none", judge_profile=None,
            session_id=replay_session_id,
            sessions_seeded=len(test.setup),
            assertions_total=assertions_total, assertions_passed=assertions_passed,
            judge_checks_total=judge_total, judge_checks_passed=judge_passed,
            status=status, duration_ms=duration_ms,
            agent_id=None, mode="tool",
        )
        self._db.add(test_run)
        self._db.flush()

        from druppie.db.models import TestAssertionResult
        for ar in all_assertion_results:
            self._db.add(TestAssertionResult(
                test_run_id=test_run.id,
                assertion_type="tool" if "tool(" in ar.name else "completed",
                agent_id=ar.name.split(".")[0] if "." in ar.name else None,
                passed=ar.passed, message=ar.message,
            ))

        for jr in all_judge_results:
            self._db.add(TestAssertionResult(
                test_run_id=test_run.id,
                assertion_type="judge_eval" if jr.source == "judge_eval" else "judge_check",
                passed=jr.passed, message=jr.check,
                judge_reasoning=jr.reasoning,
                judge_raw_input=jr.raw_input,
                judge_raw_output=jr.raw_output,
            ))

        for tag in test.tags:
            self._db.add(TestRunTag(test_run_id=test_run.id, tag=tag))
        self._db.add(TestRunTag(test_run_id=test_run.id, tag="type:tool"))
        self._db.flush()

        benchmark_run.completed_at = datetime.now(timezone.utc)
        self._db.flush()

        return TestRunResult(
            test_name=test.name, test_user=test_user, test_type="tool",
            assertion_results=all_assertion_results, status=status, duration_ms=duration_ms,
        )

    def _replay_chain(self, test: ToolTestDefinition, user_id: UUID,
                      run_namespace: str) -> tuple[UUID | None, list[AssertionResult]]:
        """Replay a tool test chain through real MCP. Returns (session_id, assertion_results)."""
        from druppie.testing.replay_executor import ReplayExecutor
        from druppie.testing.seed_schema import (
            AgentRunFixture, SessionFixture, SessionMetadata, ToolCallFixture, MessageFixture,
        )

        replay_exec = ReplayExecutor(self._db)

        # Build a SessionFixture from the chain steps.
        # Create a new agent run each time the agent changes (preserves
        # the real flow where planner runs multiple times).
        agent_runs: list[AgentRunFixture] = []
        current_agent: str | None = None
        current_tools: list[ToolCallFixture] = []

        for step in test.chain:
            # Convert ChainStepApproval to dict for replay
            approval_action = None
            if step.approval:
                approval_action = {
                    "status": step.approval.status,
                    "by": step.approval.by,
                    "reason": step.approval.reason,
                }

            tc_fixture = ToolCallFixture(
                tool=step.tool,
                arguments=step.arguments,
                status=step.status,
                result=step.mock_result if step.mock else step.result,
                error_message=step.error_message,
                execute=False if step.mock else None,
                outcome=step.outcome,
                approval_action=approval_action,
            )

            if step.agent != current_agent:
                # Flush previous agent run
                if current_agent is not None and current_tools:
                    # Agent status: completed only if last tool is done
                    last_tool = current_tools[-1].tool if current_tools else ""
                    status = "completed" if last_tool == "builtin:done" else "running"
                    agent_runs.append(AgentRunFixture(
                        id=current_agent, status=status, tool_calls=current_tools,
                    ))
                current_agent = step.agent
                current_tools = []

            current_tools.append(tc_fixture)

        # Flush last agent run
        if current_agent is not None and current_tools:
            last_tool = current_tools[-1].tool if current_tools else ""
            status = "completed" if last_tool == "builtin:done" else "running"
            agent_runs.append(AgentRunFixture(
                id=current_agent, status=status, tool_calls=current_tools,
            ))

        session_id_str = f"{run_namespace}:chain-{test.name}"
        fixture = SessionFixture(
            metadata=SessionMetadata(
                id=session_id_str,
                title=f"Tool test: {test.name}",
                status="completed",
                user=run_namespace,
            ),
            agents=agent_runs,
            messages=[MessageFixture(role="user", content=f"Tool test: {test.name}")],
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                replay_exec.replay_session(fixture, user_id, self._gitea_url)
            )
        finally:
            loop.close()

        session_id = UUID(result["session_id"])

        # Check inline assertions on chain steps
        assertion_results: list[AssertionResult] = []

        # Track how many times we've seen each (agent, tool) combo
        # so we can find the Nth occurrence in the DB
        tool_call_counts: dict[str, int] = {}

        for step in test.chain:
            # Track occurrence count for this (agent, tool) pair
            key = f"{step.agent}:{step.tool}"
            tool_call_counts[key] = tool_call_counts.get(key, 0) + 1
            occurrence = tool_call_counts[key]

            if step.assert_ is None:
                continue

            # Check result validators
            if step.assert_.result:
                from druppie.testing.result_validators import validate_result
                # Find the Nth tool call of this type in DB
                parts = step.tool.split(":", 1)
                mcp_server, tool_name = parts[0], parts[1] if len(parts) > 1 else parts[0]

                tc_records = (
                    self._db.query(ToolCall)
                    .join(AgentRun)
                    .filter(
                        AgentRun.session_id == session_id,
                        AgentRun.agent_id == step.agent,
                        ToolCall.mcp_server == mcp_server,
                        ToolCall.tool_name == tool_name,
                    )
                    .order_by(ToolCall.created_at.asc())
                    .all()
                )
                # Pick the Nth occurrence (1-indexed)
                tc_record = tc_records[occurrence - 1] if len(tc_records) >= occurrence else None

                if tc_record:
                    # Combine result + error_message for validation
                    # Failed tool calls store useful text in error_message, not result
                    combined_result = tc_record.result or ""
                    if tc_record.error_message:
                        combined_result = (combined_result + "\n" + tc_record.error_message).strip()
                    validations = validate_result(combined_result or None, step.assert_.result)
                    for vr in validations:
                        assertion_results.append(AssertionResult(
                            name=f"{step.agent}.tool({step.tool}).{vr.validator}",
                            passed=vr.passed, message=vr.message,
                        ))
                else:
                    assertion_results.append(AssertionResult(
                        name=f"{step.agent}.tool({step.tool})",
                        passed=False, message=f"Tool call not found in DB",
                    ))

            # Check completed status
            if step.assert_.completed is not None:
                check_assertion = CheckAssertion(agent=step.agent, completed=step.assert_.completed)
                completed_results = match_assertions(self._db, session_id, [check_assertion], {})
                assertion_results.extend(completed_results)

        return session_id, assertion_results

    # ------------------------------------------------------------------
    # Agent Test Runner
    # ------------------------------------------------------------------

    def _run_agent_test(self, test: AgentTestDefinition, hitl_name: str,
                        execute: bool = True, judge: bool = True,
                        batch_id: str | None = None) -> TestRunResult:
        start = time.time()
        timestamp = int(start)

        import hashlib
        short_hash = hashlib.md5(f"{test.name}-{hitl_name}-{timestamp}".encode()).hexdigest()[:8]
        test_user = f"t-{short_hash}"
        run_namespace = test_user

        git_commit, git_branch = _git_info()
        benchmark_run = BenchmarkRun(
            name=f"test-{test.name}", run_type="test",
            git_commit=git_commit, git_branch=git_branch,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(benchmark_run)
        self._db.flush()

        execution_session_id: UUID | None = None
        execution_error: str | None = None

        # Create test user
        user = self._db.query(User).filter(User.username == test_user).first()
        if not user:
            user_id = uuid4()
            user = User(id=user_id, username=test_user, email=f"{test_user}@druppie.local",
                        display_name=test_user.title())
            self._db.add(user)
            self._db.add(UserRole(user_id=user_id, role="admin"))
            self._db.flush()

        # Phase 1: Run setup tool tests (real tool execution)
        last_setup_session_id: UUID | None = None
        for setup_name in test.setup:
            setup_test = self._tool_tests.get(setup_name)
            session_id, _ = self._replay_chain(setup_test, user.id, run_namespace)
            if session_id:
                last_setup_session_id = session_id

        # Phase 1b: Run extended tool chain if specified
        if test.extends:
            extended = self._tool_tests.get(test.extends)
            session_id, _ = self._replay_chain(extended, user.id, run_namespace)
            if session_id:
                last_setup_session_id = session_id

        self._db.flush()

        if execute and test.message:
            # Phase 2: Execute real agents
            hitl_profile: HITLProfile | None = None
            if hitl_name == "inline" and isinstance(test.hitl, HITLProfile):
                hitl_profile = test.hitl
            else:
                try:
                    hitl_profile = self._profiles.get_hitl(hitl_name)
                except KeyError:
                    logger.warning("HITL profile not found: %s", hitl_name)

            # If continue_session, reuse the last setup session
            continue_session_id = last_setup_session_id if test.continue_session else None

            try:
                execution_session_id = self._execute_agents(
                    message=test.message, user_id=user.id,
                    real_agents=test.agents, hitl_profile=hitl_profile,
                    test_context=test.message,
                    session_id=continue_session_id,
                )
            except Exception as e:
                execution_error = f"{type(e).__name__}: {e}"
                logger.error("Agent execution failed: test=%s error=%s",
                             test.name, execution_error, exc_info=True)

        # Determine eval session
        eval_session_id: UUID | None = execution_session_id

        # Phase 3: Assertions
        all_assertion_results: list[AssertionResult] = []
        if eval_session_id is not None:
            for check_ref in test.assert_:
                check_def = self._checks.get(check_ref.check)
                results = match_assertions(self._db, eval_session_id, check_def.assert_, check_ref.expected)
                all_assertion_results.extend(results)

        # Phase 4: Judge checks (agent tests only)
        all_judge_results: list[JudgeCheckResult] = []
        judge_profiles = test.get_judge_profiles()
        run_judge = judge and eval_session_id is not None

        if run_judge:
            for judge_name in judge_profiles:
                try:
                    judge_profile = self._profiles.get_judge(judge_name)
                except KeyError:
                    logger.warning("Judge profile not found: %s", judge_name)
                    continue

                judge_runner = JudgeRunner(judge_profile)

                # Judge checks from referenced checks
                for check_ref in test.assert_:
                    check_def = self._checks.get(check_ref.check)
                    if check_def.judge:
                        judge_checks, judge_context = self._resolve_judge_config(check_def.judge)
                        if judge_checks:
                            judge_results = judge_runner.run_checks(
                                db=self._db, session_id=eval_session_id,
                                judge_checks=judge_checks, context=judge_context, source="check",
                            )
                            all_judge_results.extend(judge_results)

                # Inline judge checks (on the test itself)
                if test.judge:
                    inline_checks, inline_context = self._resolve_judge_config(test.judge)
                    if inline_checks:
                        judge_results = judge_runner.run_checks(
                            db=self._db, session_id=eval_session_id,
                            judge_checks=inline_checks, context=inline_context, source="inline",
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
            status = "passed"
        elif assertions_passed == assertions_total and judge_passed == judge_total:
            status = "passed"
        else:
            status = "failed"

        # Determine primary agent
        primary_agent = None
        if test.agents:
            primary_agent = test.agents[0]
        elif test.assert_:
            check_def = self._checks.get(test.assert_[0].check)
            if check_def.assert_:
                primary_agent = check_def.assert_[0].agent

        # Store test run
        stored_session_id = execution_session_id or eval_session_id
        test_run = TestRunModel(
            benchmark_run_id=benchmark_run.id, batch_id=batch_id,
            test_name=test.name, test_description=test.description,
            test_user=test_user, hitl_profile=hitl_name,
            judge_profile=", ".join(judge_profiles) if judge_profiles else None,
            session_id=stored_session_id,
            sessions_seeded=len(test.setup),
            assertions_total=assertions_total, assertions_passed=assertions_passed,
            judge_checks_total=judge_total, judge_checks_passed=judge_passed,
            status=status, duration_ms=duration_ms,
            agent_id=primary_agent, mode="agent",
        )
        self._db.add(test_run)
        self._db.flush()

        from druppie.db.models import TestAssertionResult

        for ar in all_assertion_results:
            ar_agent = ar.name.split(".")[0] if "." in ar.name else None
            ar_tool = None
            if "tool(" in ar.name:
                ar_tool = ar.name.split("tool(")[1].split(")")[0]
            self._db.add(TestAssertionResult(
                test_run_id=test_run.id,
                assertion_type="tool" if "tool(" in ar.name else "completed",
                agent_id=ar_agent, tool_name=ar_tool,
                passed=ar.passed, message=ar.message,
            ))

        for jr in all_judge_results:
            self._db.add(TestAssertionResult(
                test_run_id=test_run.id,
                assertion_type="judge_eval" if jr.source == "judge_eval" else "judge_check",
                agent_id=primary_agent,
                passed=jr.passed, message=jr.check,
                judge_reasoning=jr.reasoning,
                judge_raw_input=jr.raw_input,
                judge_raw_output=jr.raw_output,
            ))

        self._db.flush()

        # Store tags
        tags: set[str] = set()
        for check_ref in test.assert_:
            check_def = self._checks.get(check_ref.check)
            tags.update(check_def.tags)
        tags.update(test.tags)
        tags.add("type:agent")
        for tag in tags:
            self._db.add(TestRunTag(test_run_id=test_run.id, tag=tag))
        self._db.flush()

        benchmark_run.completed_at = datetime.now(timezone.utc)
        self._db.flush()

        return TestRunResult(
            test_name=test.name, test_user=test_user, test_type="agent",
            hitl_profile=hitl_name, judge_profiles=judge_profiles,
            assertion_results=all_assertion_results, judge_results=all_judge_results,
            status=status, duration_ms=duration_ms,
        )

    @staticmethod
    def _resolve_judge_config(judge_config) -> tuple[list, str | list[str]]:
        """Resolve judge config to (list of JudgeCheck, context).

        Supports:
        - Legacy: list of strings → JudgeCheck(check=s, expected=True) with context="all"
        - New: JudgeDefinition with context and checks (strings or dicts)
        """
        from druppie.testing.v2_schema import JudgeCheck, JudgeDefinition

        if isinstance(judge_config, JudgeDefinition):
            return judge_config.resolved_checks(), judge_config.context
        elif isinstance(judge_config, list):
            return [JudgeCheck.from_value(c) for c in judge_config], "all"
        elif judge_config is None:
            return [], "all"
        return [], "all"

    def _execute_agents(self, message: str, user_id: UUID, real_agents: list[str],
                        hitl_profile: HITLProfile | None, test_context: str = "",
                        session_id: UUID | None = None) -> UUID:
        hitl_sim = HITLSimulator(hitl_profile, test_context=test_context) if hitl_profile else None
        bounded = _BoundedOrchestrator(
            db=self._db, user_id=user_id,
            real_agents=real_agents, hitl_simulator=hitl_sim,
        )

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, bounded.run(message, session_id=session_id))
                return future.result(timeout=300)
        else:
            return asyncio.run(bounded.run(message, session_id=session_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_info() -> tuple[str | None, str | None]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None
