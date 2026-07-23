"""State-machine tests for the FD-escalation / HITL orchestrator behavior.

Covers: reserved pseudo-agent interception, the deterministic backstop counter,
the sticky supervised BA loop, post-HITL rejection counting, the BA/architect
HITL resume methods, hard termination, and the TERMINATED guards.

These tests assert on OBSERVABLE state (session status transitions, escalation
events written, pending-run cancellations) using stub repos — they never
exercise a real agent or LLM.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from druppie.domain.common import (
    AgentRunStatus,
    EscalationEventType,
    SessionStatus,
)
from druppie.execution.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_orchestrator() -> Orchestrator:
    orch = Orchestrator(
        session_repo=MagicMock(),
        execution_repo=MagicMock(),
        project_repo=MagicMock(),
        question_repo=MagicMock(),
    )
    # escalation repo is constructed lazily from execution_repo.db
    orch._escalation_repo = MagicMock()
    orch._get_escalation_repo = MagicMock(return_value=orch._escalation_repo)
    # stub lazily-built notification repos to isolate escalation tests
    orch._get_notification_repo = MagicMock(return_value=MagicMock())
    orch._get_user_repo = MagicMock(return_value=MagicMock())
    return orch


def _make_session(
    *,
    status: SessionStatus = SessionStatus.ACTIVE,
    fd_rejection_count: int = 0,
    fd_escalation_mode: bool = False,
    fd_post_hitl_rejection_count: int = 0,
):
    session = MagicMock()
    session.id = uuid4()
    session.status = status.value
    session.fd_rejection_count = fd_rejection_count
    session.fd_escalation_mode = fd_escalation_mode
    session.fd_post_hitl_rejection_count = fd_post_hitl_rejection_count
    return session


def _make_run(agent_id: str, run_id=None):
    run = MagicMock()
    run.id = run_id or uuid4()
    run.agent_id = agent_id
    run.status = AgentRunStatus.PENDING.value
    run.planned_prompt = ""
    run.sequence_number = 1
    return run


def _wire_session(orch, session):
    orch.session_repo.get_by_id.return_value = session


def _set_threshold(orch, threshold: int) -> None:
    orch._architect_escalation_threshold = MagicMock(return_value=threshold)


def _set_completed_architect(orch, has_architect: bool) -> None:
    completed = [_make_run("architect")] if has_architect else []
    orch.execution_repo.get_completed_runs.return_value = completed


def _set_pending_ba(orch, present: bool) -> None:
    orch.execution_repo.get_pending_by_agent_id.return_value = (
        _make_run("business_analyst") if present else None
    )


# ---------------------------------------------------------------------------
# Behavior B: backstop counter (via _evaluate_escalation)
# ---------------------------------------------------------------------------


class TestBackstopCounter:
    def test_below_threshold_increments_and_continues(self):
        orch = _make_orchestrator()
        _set_threshold(orch, 3)
        _set_completed_architect(orch, has_architect=True)
        _set_pending_ba(orch, present=True)
        session = _make_session(fd_rejection_count=0, fd_escalation_mode=False)
        _wire_session(orch, session)
        completed = _make_run("architect")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is False
        assert session.fd_rejection_count == 1
        # session status untouched, no escalation event
        orch.session_repo.update_status.assert_not_called()
        orch._escalation_repo.create.assert_not_called()
        # BA run left pending (no cancellation)
        orch.execution_repo.cancel_pending_runs.assert_not_called()

    def test_reaching_threshold_escalates_and_deletes_ba_run(self):
        orch = _make_orchestrator()
        _set_threshold(orch, 3)
        _set_completed_architect(orch, has_architect=True)
        _set_pending_ba(orch, present=True)
        session = _make_session(fd_rejection_count=2, fd_escalation_mode=False)
        _wire_session(orch, session)
        completed = _make_run("architect")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is True
        assert session.fd_rejection_count == 3
        assert session.fd_escalation_mode is True
        orch.execution_repo.cancel_pending_runs.assert_called_once_with(session.id)
        orch.session_repo.update_status.assert_any_call(session.id, SessionStatus.PAUSED_BA_HITL)
        orch._escalation_repo.create.assert_called_once()
        call_kwargs = orch._escalation_repo.create.call_args.kwargs
        assert call_kwargs["event_type"] == EscalationEventType.BA_HITL_ENTERED.value
        assert call_kwargs["rejection_count_at_event"] == 3

    def test_sticky_when_already_escalated_pauses_without_double_setting_mode(self):
        orch = _make_orchestrator()
        _set_threshold(orch, 3)
        _set_completed_architect(orch, has_architect=True)
        _set_pending_ba(orch, present=True)
        session = _make_session(
            fd_rejection_count=5,
            fd_escalation_mode=True,
            fd_post_hitl_rejection_count=0,
        )
        _wire_session(orch, session)
        completed = _make_run("architect")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is True
        assert session.fd_rejection_count == 6
        # post-HITL rejection counter increments (behavior D)
        assert session.fd_post_hitl_rejection_count == 1
        orch.session_repo.update_status.assert_any_call(session.id, SessionStatus.PAUSED_BA_HITL)
        orch.execution_repo.cancel_pending_runs.assert_called_once_with(session.id)

    def test_planner_mediated_routing_also_detected(self):
        """Planner re-plan that creates a pending BA run counts as a rejection
        when an architect has previously completed (the real routing path)."""
        orch = _make_orchestrator()
        _set_threshold(orch, 3)
        _set_completed_architect(orch, has_architect=True)
        _set_pending_ba(orch, present=True)
        session = _make_session(fd_rejection_count=0)
        _wire_session(orch, session)
        completed = _make_run("planner")  # planner just created the BA run

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is False
        assert session.fd_rejection_count == 1

    def test_first_ba_pass_not_counted(self):
        """A pending BA run with no prior architect completion is the first
        elicitation pass, not a rejection — must not be counted."""
        orch = _make_orchestrator()
        _set_threshold(orch, 3)
        _set_completed_architect(orch, has_architect=False)
        _set_pending_ba(orch, present=True)
        session = _make_session(fd_rejection_count=0)
        _wire_session(orch, session)
        completed = _make_run("planner")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is False
        assert session.fd_rejection_count == 0
        orch._escalation_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# Behavior C: sticky supervised BA loop
# ---------------------------------------------------------------------------


class TestStickySupervisedBaLoop:
    def test_ba_completing_in_escalation_mode_pauses(self):
        orch = _make_orchestrator()
        session = _make_session(fd_escalation_mode=True, fd_rejection_count=3)
        _wire_session(orch, session)
        completed = _make_run("business_analyst")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is True
        orch.session_repo.update_status.assert_any_call(session.id, SessionStatus.PAUSED_BA_HITL)
        orch._escalation_repo.create.assert_called_once()
        call_kwargs = orch._escalation_repo.create.call_args.kwargs
        assert call_kwargs["event_type"] == EscalationEventType.BA_HITL_STICKY_REENTER.value

    def test_ba_completing_when_not_in_escalation_does_not_pause(self):
        orch = _make_orchestrator()
        session = _make_session(fd_escalation_mode=False)
        _wire_session(orch, session)
        _set_pending_ba(orch, present=False)
        completed = _make_run("business_analyst")

        stop = orch._evaluate_escalation(session.id, completed)

        assert stop is False


# ---------------------------------------------------------------------------
# Behavior A: reserved pseudo-agent interception in execute_pending_runs
# ---------------------------------------------------------------------------


class TestReservedAgentInterception:
    @pytest.mark.asyncio
    async def test_ba_hitl_run_pauses_without_loading_agent(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.ACTIVE, fd_rejection_count=3)
        _wire_session(orch, session)
        ba_hitl_run = _make_run("ba_hitl")
        orch.execution_repo.get_next_pending.return_value = ba_hitl_run

        with (
            patch.object(Orchestrator, "run_agent", new_callable=AsyncMock) as mock_run,
            patch.object(Orchestrator, "build_project_context", return_value={}),
        ):
            await orch.execute_pending_runs(session.id)

        # Never attempted to load/run an agent for the reserved id
        mock_run.assert_not_called()
        orch.session_repo.update_status.assert_any_call(session.id, SessionStatus.PAUSED_BA_HITL)
        orch._escalation_repo.create.assert_called_once()
        assert (
            orch._escalation_repo.create.call_args.kwargs["event_type"]
            == EscalationEventType.BA_HITL_ENTERED.value
        )

    @pytest.mark.asyncio
    async def test_architect_hitl_run_pauses_without_loading_agent(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.ACTIVE)
        _wire_session(orch, session)
        orch.execution_repo.get_next_pending.return_value = _make_run("architect_hitl")

        with (
            patch.object(Orchestrator, "run_agent", new_callable=AsyncMock) as mock_run,
            patch.object(Orchestrator, "build_project_context", return_value={}),
        ):
            await orch.execute_pending_runs(session.id)

        mock_run.assert_not_called()
        orch.session_repo.update_status.assert_any_call(
            session.id, SessionStatus.PAUSED_ARCHITECT_HITL
        )
        assert (
            orch._escalation_repo.create.call_args.kwargs["event_type"]
            == EscalationEventType.ARCHITECT_HITL_ENTERED.value
        )


# ---------------------------------------------------------------------------
# Behavior E: resume_after_ba_hitl
# ---------------------------------------------------------------------------


class TestResumeAfterBaHitl:
    @pytest.mark.asyncio
    async def test_escalate_without_post_hitl_rejection_raises_conflict(self):
        from druppie.api.errors import ConflictError

        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_BA_HITL, fd_post_hitl_rejection_count=0)
        _wire_session(orch, session)

        with pytest.raises(ConflictError):
            await orch.resume_after_ba_hitl(session.id, decision="escalate", user_id=uuid4())

    @pytest.mark.asyncio
    async def test_escalate_with_post_hitl_rejection_enters_architect_hitl(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_BA_HITL, fd_post_hitl_rejection_count=1)
        _wire_session(orch, session)
        arch_users = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]
        user_repo = MagicMock()
        user_repo.get_by_role.return_value = arch_users
        notif_repo = MagicMock()
        orch._get_user_repo = MagicMock(return_value=user_repo)
        orch._get_notification_repo = MagicMock(return_value=notif_repo)

        await orch.resume_after_ba_hitl(session.id, decision="escalate", user_id=uuid4())

        orch.session_repo.update_status.assert_any_call(
            session.id, SessionStatus.PAUSED_ARCHITECT_HITL
        )
        # The BA->escalate path records the orchestrator-owned architect_hitl_entered
        # event and notifies architects, mirroring the automated-interception path.
        orch._escalation_repo.create.assert_called_once()
        create_kwargs = orch._escalation_repo.create.call_args.kwargs
        assert create_kwargs["event_type"] == EscalationEventType.ARCHITECT_HITL_ENTERED.value
        assert create_kwargs["rejection_count_at_event"] == session.fd_rejection_count
        orch._get_user_repo().get_by_role.assert_called_once_with("architect")
        assert notif_repo.create.call_count == len(arch_users)
        for call in notif_repo.create.call_args_list:
            assert call.kwargs["role"] == "architect"
            assert call.kwargs["kind"] == "architect_hitl"
            assert call.kwargs["session_id"] == session.id

    @pytest.mark.asyncio
    async def test_iterate_creates_ba_run_and_executes(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_BA_HITL)
        _wire_session(orch, session)
        orch.execution_repo.get_next_sequence_number.return_value = 10

        with patch.object(
            Orchestrator, "execute_pending_runs", new_callable=AsyncMock
        ) as mock_exec:
            await orch.resume_after_ba_hitl(
                session.id, decision="iterate", feedback="fix section X"
            )

        orch.execution_repo.create_agent_run.assert_called_once()
        call_kwargs = orch.execution_repo.create_agent_run.call_args.kwargs
        assert call_kwargs["agent_id"] == "business_analyst"
        assert call_kwargs["status"] == AgentRunStatus.PENDING
        assert "fix section X" in call_kwargs["planned_prompt"]
        mock_exec.assert_awaited_once_with(session.id)

    @pytest.mark.asyncio
    async def test_terminate_decision_terminates_session(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_BA_HITL)
        _wire_session(orch, session)

        await orch.resume_after_ba_hitl(session.id, decision="terminate", feedback="done")

        orch.session_repo.update_status.assert_any_call(
            session.id, SessionStatus.TERMINATED, error_message="done"
        )

    @pytest.mark.asyncio
    async def test_wrong_status_raises_conflict(self):
        from druppie.api.errors import ConflictError

        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.ACTIVE)
        _wire_session(orch, session)
        with pytest.raises(ConflictError):
            await orch.resume_after_ba_hitl(session.id, decision="iterate")


# ---------------------------------------------------------------------------
# Behavior E: resume_after_architect_hitl
# ---------------------------------------------------------------------------


class TestResumeAfterArchitectHitl:
    @pytest.mark.asyncio
    async def test_approve_creates_architect_run(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL, fd_escalation_mode=True)
        _wire_session(orch, session)
        orch.execution_repo.get_next_sequence_number.return_value = 7

        with patch.object(
            Orchestrator, "execute_pending_runs", new_callable=AsyncMock
        ) as mock_exec:
            await orch.resume_after_architect_hitl(session.id, decision="approve", user_id=uuid4())

        call_kwargs = orch.execution_repo.create_agent_run.call_args.kwargs
        assert call_kwargs["agent_id"] == "architect"
        mock_exec.assert_awaited_once()
        assert session.fd_escalation_mode is False

    @pytest.mark.asyncio
    async def test_reject_to_ba_hitl(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL)
        _wire_session(orch, session)

        await orch.resume_after_architect_hitl(
            session.id, decision="reject", next_on_reject="ba_hitl"
        )

        orch.session_repo.update_status.assert_any_call(session.id, SessionStatus.PAUSED_BA_HITL)
        create_kwargs = orch._escalation_repo.create.call_args.kwargs
        assert create_kwargs["event_type"] == EscalationEventType.BA_HITL_ENTERED.value
        assert create_kwargs["session_id"] == session.id
        assert create_kwargs["rejection_count_at_event"] == session.fd_rejection_count or 0

    @pytest.mark.asyncio
    async def test_reject_terminate(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL)
        _wire_session(orch, session)

        await orch.resume_after_architect_hitl(
            session.id, decision="reject", next_on_reject="terminate"
        )

        orch.session_repo.update_status.assert_any_call(
            session.id,
            SessionStatus.TERMINATED,
            error_message="Architect HITL rejected",
        )

    @pytest.mark.asyncio
    async def test_reject_unknown_next_on_reject_raises(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL)
        _wire_session(orch, session)
        with pytest.raises(ValueError):
            await orch.resume_after_architect_hitl(
                session.id, decision="reject", next_on_reject="bogus"
            )


# ---------------------------------------------------------------------------
# Behavior F: hard termination + guards
# ---------------------------------------------------------------------------


class TestTermination:
    def test_terminate_cancels_pending_sets_status(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.PAUSED_BA_HITL)
        _wire_session(orch, session)

        orch.terminate_session(session.id, reason="user requested", user_id=uuid4())

        orch.execution_repo.cancel_pending_runs.assert_called_once_with(session.id)
        orch.session_repo.update_status.assert_any_call(
            session.id, SessionStatus.TERMINATED, error_message="user requested"
        )
        # SESSION_TERMINATED audit event is owned by EscalationService; the
        # orchestrator only performs the state transition.
        orch._escalation_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_pending_runs_on_terminated_raises_conflict(self):
        from druppie.api.errors import ConflictError

        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.TERMINATED)
        _wire_session(orch, session)

        with pytest.raises(ConflictError):
            await orch.execute_pending_runs(session.id)

    @pytest.mark.asyncio
    async def test_resume_paused_session_on_terminated_raises_conflict(self):
        from druppie.api.errors import ConflictError

        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.TERMINATED)
        _wire_session(orch, session)

        with pytest.raises(ConflictError):
            await orch.resume_paused_session(session.id)

    @pytest.mark.asyncio
    async def test_resume_after_sandbox_on_terminated_raises_conflict(self):
        from druppie.api.errors import ConflictError

        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.TERMINATED)
        _wire_session(orch, session)

        tool_call = MagicMock()
        tool_call.agent_run_id = uuid4()
        orch.execution_repo.get_tool_call.return_value = tool_call
        agent_run = _make_run("business_analyst")
        agent_run.session_id = session.id
        orch.execution_repo.get_by_id.return_value = agent_run

        with patch.object(orch, "_sync_workspace") as mock_sync:
            with pytest.raises(ConflictError):
                await orch.resume_after_sandbox(tool_call_id=uuid4())

        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Behavior: role-targeted notifications on HITL pause
# ---------------------------------------------------------------------------


class TestHitlRoleNotifications:
    """When a session enters a HITL pause, the responsible role is notified."""

    def _wire_notif(self, orch, *, role_users):
        user_repo = MagicMock()
        user_repo.get_by_role.return_value = role_users
        notif_repo = MagicMock()
        orch._get_user_repo = MagicMock(return_value=user_repo)
        orch._get_notification_repo = MagicMock(return_value=notif_repo)
        return notif_repo

    def test_ba_hitl_notifies_business_analysts(self):
        orch = _make_orchestrator()
        session = _make_session()
        ba_users = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]
        notif_repo = self._wire_notif(orch, role_users=ba_users)

        orch._enter_ba_hitl(session.id, rejection_count=0, cancel_pending=False)

        orch._get_user_repo().get_by_role.assert_called_once_with("business_analyst")
        assert notif_repo.create.call_count == len(ba_users)
        for call in notif_repo.create.call_args_list:
            assert call.kwargs["role"] == "business_analyst"
            assert call.kwargs["kind"] == "ba_hitl"
            assert call.kwargs["session_id"] == session.id
        notif_repo.commit.assert_called_once()

    def test_architect_hitl_notifies_architects(self):
        orch = _make_orchestrator()
        session = _make_session(status=SessionStatus.ACTIVE)
        arch_users = [MagicMock(id=uuid4())]
        notif_repo = self._wire_notif(orch, role_users=arch_users)

        intercepted = orch._intercept_reserved_agent(
            session.id, _make_run("architect_hitl"), session
        )

        assert intercepted is True
        orch._get_user_repo().get_by_role.assert_called_once_with("architect")
        assert notif_repo.create.call_count == len(arch_users)
        call = notif_repo.create.call_args
        assert call.kwargs["role"] == "architect"
        assert call.kwargs["kind"] == "architect_hitl"
        assert call.kwargs["session_id"] == session.id

    def test_no_users_with_role_skips_silently(self):
        orch = _make_orchestrator()
        session = _make_session()
        notif_repo = self._wire_notif(orch, role_users=[])

        orch._enter_ba_hitl(session.id, rejection_count=0, cancel_pending=False)

        notif_repo.create.assert_not_called()
