"""Test Runner -- user-isolated test execution with two test types.

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
import logging
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
    ToolCall,
    User,
    UserRole,
)
from druppie.db.models import TestRun as TestRunModel
from druppie.db.models import TestRunTag
from druppie.testing.assertions import AssertionResult, match_assertions
from druppie.testing.bounded_orchestrator import BoundedOrchestrator
from druppie.testing.hitl_simulator import HITLSimulator
from druppie.testing.judge_runner import JudgeCheckResult, JudgeRunner
from druppie.testing.loaders import CheckLoader, ProfileLoader, ToolTestLoader
from druppie.testing.schema import (
    AgentTestDefinition,
    AgentTestFile,
    CheckAssertion,
    HITLProfile,
    ToolTestDefinition,
    ToolTestFile,
)
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.utils import git_info

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


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
# Test Runner
# ---------------------------------------------------------------------------


class TestRunner:
    """Main test orchestrator.

    Handles both tool tests and agent tests with user isolation.
    """

    def __init__(self, db: DbSession, testing_dir: Path | None = None, gitea_url: str | None = None):
        self._db = db
        self._testing_dir = testing_dir or (Path(__file__).resolve().parents[2] / "testing")
        self._gitea_url = gitea_url
        self._profiles = ProfileLoader(self._testing_dir / "profiles")
        self._checks = CheckLoader(self._testing_dir / "checks")
        self._tool_tests = ToolTestLoader(self._testing_dir / "tools")

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
            raise ValueError(f"Unknown test format in {path}: expected 'tool-test' or 'agent-test' key")

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

        test_user = f"t-{uuid4().hex[:12]}"

        git_commit, git_branch = git_info()
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
            self._db.commit()  # Commit each setup replay so subsequent steps can see the data

        # Phase 1b: Run extended tool chain if specified
        if test.extends:
            extended = self._tool_tests.get(test.extends)
            self._replay_chain(extended, user.id, run_namespace)
            self._db.commit()

        # Phase 2: Replay the tool call chain
        all_assertion_results: list[AssertionResult] = []
        replay_session_id = None
        chain_error: str | None = None
        try:
            replay_session_id, chain_results = self._replay_chain(test, user.id, run_namespace)
            self._db.commit()  # Commit the full replay so assertions can query committed data
            all_assertion_results.extend(chain_results)
        except Exception as e:
            self._db.rollback()  # Roll back partial replay state on failure
            chain_error = f"{type(e).__name__}: {e}"
            logger.error("Tool chain replay failed: test=%s error=%s", test.name, e, exc_info=True)

        # Phase 3: Run top-level check assertions
        if replay_session_id:
            self._db.expire_all()  # Clear stale ORM cache before querying assertions
        if replay_session_id and test.assert_:
            for check_ref in test.assert_:
                check_def = self._checks.get(check_ref.check)
                results = match_assertions(self._db, replay_session_id, check_def.assert_, check_ref.expected)
                all_assertion_results.extend(results)

        # Phase 4: Verify checks (side-effect verification)
        if replay_session_id and test.verify:
            from druppie.testing.verifiers import run_verifiers
            verify_results = run_verifiers(
                test.verify, replay_session_id, self._db, self._gitea_url,
            )
            for vr in verify_results:
                all_assertion_results.append(AssertionResult(
                    name=f"verify.{vr.verifier}",
                    passed=vr.passed, message=vr.message,
                ))

        # Phase 5: Judge checks (if configured)
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
                chain_error = chain_error or f"Judge failed: {type(e).__name__}: {e}"
                logger.error("Tool test judge failed: test=%s error=%s", test.name, e, exc_info=True)

        # Compute status
        duration_ms = int((time.time() - start) * 1000)
        assertions_passed = sum(1 for r in all_assertion_results if r.passed)
        assertions_total = len(all_assertion_results)
        judge_passed = sum(1 for r in all_judge_results if r.passed)
        judge_total = len(all_judge_results)

        # A test that defines assertions/judges but produced none is broken, not passing
        expects_assertions = bool(test.assert_) or bool(test.verify)
        expects_judges = bool(test.judge)
        ran_nothing = assertions_total == 0 and judge_total == 0

        if chain_error:
            status = "error"
        elif ran_nothing and (expects_assertions or expects_judges):
            status = "error"  # Expected checks didn't run — likely a crash
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
        if not test.chain:
            logger.warning("Empty chain in test '%s' — skipping replay", test.name)
            return None, []

        from druppie.testing.replay_executor import ReplayExecutor, _gitea_singleton_lock
        from druppie.testing.seed_schema import (
            AgentRunFixture, SessionFixture, SessionMetadata, ToolCallFixture, MessageFixture,
        )

        replay_exec = ReplayExecutor(self._db)
        # Acquire the Gitea singleton lock for the entire replay so that
        # the freshly-created client isn't reset by a concurrent thread
        # before we finish using it.
        _gitea_lock = _gitea_singleton_lock

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

        with _gitea_lock:
            result = asyncio.run(
                replay_exec.replay_session(fixture, user_id, self._gitea_url)
            )

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

        test_user = f"t-{uuid4().hex[:12]}"
        run_namespace = test_user

        git_commit, git_branch = git_info()
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
            self._db.commit()  # Commit each setup replay so subsequent steps can see the data
            if session_id:
                last_setup_session_id = session_id

        # Phase 1b: Run extended tool chain if specified
        if test.extends:
            extended = self._tool_tests.get(test.extends)
            session_id, _ = self._replay_chain(extended, user.id, run_namespace)
            self._db.commit()
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
                    raise ValueError(
                        f"HITL profile '{hitl_name}' not found in {self._testing_dir / 'profiles'}"
                    )

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
            self._db.expire_all()  # Clear stale ORM cache before querying assertions
            for check_ref in test.assert_:
                check_def = self._checks.get(check_ref.check)
                results = match_assertions(self._db, eval_session_id, check_def.assert_, check_ref.expected)
                all_assertion_results.extend(results)

        # Phase 3b: Verify checks (side-effect verification)
        if eval_session_id is not None and test.verify:
            from druppie.testing.verifiers import run_verifiers
            verify_results = run_verifiers(
                test.verify, eval_session_id, self._db, self._gitea_url,
            )
            for vr in verify_results:
                all_assertion_results.append(AssertionResult(
                    name=f"verify.{vr.verifier}",
                    passed=vr.passed, message=vr.message,
                ))

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

        # A test that defines assertions/judges but produced none is broken, not passing
        expects_assertions = bool(test.assert_)
        expects_judges = bool(test.judge)
        ran_nothing = assertions_total == 0 and judge_total == 0

        if execution_error:
            status = "error"
        elif ran_nothing and (expects_assertions or expects_judges):
            status = "error"  # Expected checks didn't run — likely a crash
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
        - Legacy: list of strings -> JudgeCheck(check=s, expected=True) with context="all"
        - New: JudgeDefinition with context and checks (strings or dicts)
        """
        from druppie.testing.schema import JudgeCheck, JudgeDefinition

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

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            # Running inside an existing event loop (e.g., from background thread).
            # Create a new DB session for the new thread to avoid cross-thread
            # SQLAlchemy session usage, which is not thread-safe.
            import concurrent.futures
            from druppie.db.database import SessionLocal

            def _run_in_thread():
                thread_db = SessionLocal()
                try:
                    bounded = BoundedOrchestrator(
                        db=thread_db, user_id=user_id,
                        real_agents=real_agents, hitl_simulator=hitl_sim,
                    )
                    result = asyncio.run(bounded.run(message, session_id=session_id))
                    thread_db.commit()
                    return result
                except Exception:
                    thread_db.rollback()
                    raise
                finally:
                    thread_db.close()

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_run_in_thread)
                result_id = future.result(timeout=300)
            # Refresh the main session to see records created in the thread
            self._db.expire_all()
            return result_id
        else:
            bounded = BoundedOrchestrator(
                db=self._db, user_id=user_id,
                real_agents=real_agents, hitl_simulator=hitl_sim,
            )
            return asyncio.run(bounded.run(message, session_id=session_id))


