"""Phase 2 tests for EscalationService.

Verifies the RBAC authorization matrix across the three HITL auth levels and
the decision->event_type mapping for each record method, plus terminate and
list_history. Uses mocked repositories (no DB round-trip).

Scope: authorization + audit recording only. The orchestrator (session state
transitions) is covered by a separate phase and is intentionally absent here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from druppie.api.errors import AuthorizationError, ConflictError, NotFoundError
from druppie.domain.common import EscalationEventType, SessionStatus
from druppie.domain.escalation import EscalationEventDetail, EscalationEventList
from druppie.services.escalation_service import EscalationService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_session(
    user_id=None,
    fd_rejection_count=0,
    fd_post_hitl_rejection_count=0,
    status=SessionStatus.PAUSED_BA_HITL.value,
):
    """A mock Session ORM row with the fields the service inspects."""
    session = MagicMock()
    session.id = uuid4()
    session.user_id = user_id or uuid4()
    session.fd_rejection_count = fd_rejection_count
    session.fd_post_hitl_rejection_count = fd_post_hitl_rejection_count
    session.status = status
    return session


def _make_service(session=None):
    """Build an EscalationService backed by mock repositories.

    session_repo.get_by_id() returns `session` (None simulates not-found).
    escalation_repo.create() returns a sentinel detail.
    """
    escalation_repo = MagicMock()
    escalation_repo.create.return_value = MagicMock()
    session_repo = MagicMock()
    session_repo.get_by_id.return_value = session
    return EscalationService(escalation_repo, session_repo), escalation_repo


OWNER_ID = uuid4()


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "is_owner", "level", "should_allow"),
    [
        # business_analyst (not owner)
        (["business_analyst"], False, "ba_hitl", True),
        (["business_analyst"], False, "architect_hitl", False),
        (["business_analyst"], False, "terminate", False),
        # architect (not owner)
        (["architect"], False, "ba_hitl", False),
        (["architect"], False, "architect_hitl", True),
        (["architect"], False, "terminate", False),
        # admin (not owner) — allowed everywhere
        (["admin"], False, "ba_hitl", True),
        (["admin"], False, "architect_hitl", True),
        (["admin"], False, "terminate", True),
        # session owner (no special role)
        ([], True, "ba_hitl", True),
        ([], True, "architect_hitl", False),
        ([], True, "terminate", True),
        # unrelated user (no role, not owner)
        ([], False, "ba_hitl", False),
        ([], False, "architect_hitl", False),
        ([], False, "terminate", False),
    ],
    ids=[
        "ba_allows_ba_hitl",
        "ba_denies_architect_hitl",
        "ba_denies_terminate",
        "architect_denies_ba_hitl",
        "architect_allows_architect_hitl",
        "architect_denies_terminate",
        "admin_allows_ba_hitl",
        "admin_allows_architect_hitl",
        "admin_allows_terminate",
        "owner_allows_ba_hitl",
        "owner_denies_architect_hitl",
        "owner_allows_terminate",
        "stranger_denies_ba_hitl",
        "stranger_denies_architect_hitl",
        "stranger_denies_terminate",
    ],
)
def test_check_authorization_matrix(roles, is_owner, level, should_allow):
    session = _make_session(user_id=OWNER_ID, fd_rejection_count=2)
    svc, _ = _make_service(session=session)
    acting_user = OWNER_ID if is_owner else uuid4()

    if should_allow:
        # Must not raise.
        svc._check_authorization(session, acting_user, roles, level)
    else:
        with pytest.raises(AuthorizationError):
            svc._check_authorization(session, acting_user, roles, level)


# ---------------------------------------------------------------------------
# record_ba_hitl_decision
# ---------------------------------------------------------------------------


class TestRecordBaHitlDecision:
    @pytest.mark.parametrize(
        ("decision", "expected_event"),
        [
            ("iterate", EscalationEventType.BA_HITL_ITERATE),
            ("ready", EscalationEventType.BA_HITL_READY),
            ("escalate", EscalationEventType.BA_HITL_ESCALATE),
            ("terminate", EscalationEventType.SESSION_TERMINATED),
        ],
        ids=["iterate", "ready", "escalate", "terminate"],
    )
    def test_maps_decision_to_event_type(self, decision, expected_event):
        session = _make_session(
            user_id=OWNER_ID,
            fd_rejection_count=3,
            fd_post_hitl_rejection_count=1,
        )
        svc, escalation_repo = _make_service(session=session)

        result = svc.record_ba_hitl_decision(
            session_id=session.id,
            user_id=OWNER_ID,
            user_roles=[],
            decision=decision,
            feedback="needs work",
        )

        kwargs = escalation_repo.create.call_args.kwargs
        assert kwargs["event_type"] == expected_event.value
        assert kwargs["session_id"] == session.id
        assert kwargs["actor_user_id"] == OWNER_ID
        assert kwargs["decision"] == decision
        assert kwargs["feedback"] == "needs work"
        assert kwargs["rejection_count_at_event"] == 3
        assert result is escalation_repo.create.return_value
        escalation_repo.commit.assert_called_once()

    def test_invalid_decision_raises_value_error(self):
        session = _make_session(user_id=OWNER_ID)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(ValueError):
            svc.record_ba_hitl_decision(
                session_id=session.id,
                user_id=OWNER_ID,
                user_roles=[],
                decision="bogus",
            )
        escalation_repo.create.assert_not_called()

    def test_unauthorized_raises_before_record(self):
        session = _make_session(user_id=OWNER_ID)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(AuthorizationError):
            svc.record_ba_hitl_decision(
                session_id=session.id,
                user_id=uuid4(),
                user_roles=[],
                decision="iterate",
            )
        escalation_repo.create.assert_not_called()

    def test_missing_session_raises_not_found(self):
        svc, escalation_repo = _make_service(session=None)
        with pytest.raises(NotFoundError):
            svc.record_ba_hitl_decision(
                session_id=uuid4(),
                user_id=OWNER_ID,
                user_roles=["admin"],
                decision="iterate",
            )
        escalation_repo.create.assert_not_called()

    def test_escalate_without_post_hitl_rejection_raises_conflict(self):
        session = _make_session(user_id=OWNER_ID, fd_post_hitl_rejection_count=0)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(ConflictError):
            svc.record_ba_hitl_decision(
                session_id=session.id,
                user_id=OWNER_ID,
                user_roles=["business_analyst"],
                decision="escalate",
            )
        escalation_repo.create.assert_not_called()

    def test_wrong_status_raises_conflict(self):
        session = _make_session(user_id=OWNER_ID, status=SessionStatus.ACTIVE.value)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(ConflictError):
            svc.record_ba_hitl_decision(
                session_id=session.id,
                user_id=OWNER_ID,
                user_roles=["business_analyst"],
                decision="iterate",
            )
        escalation_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# record_architect_hitl_decision
# ---------------------------------------------------------------------------


class TestRecordArchitectHitlDecision:
    def test_approve_maps(self):
        session = _make_session(fd_rejection_count=1, status=SessionStatus.PAUSED_ARCHITECT_HITL.value)
        svc, escalation_repo = _make_service(session=session)
        svc.record_architect_hitl_decision(
            session_id=session.id,
            user_id=uuid4(),
            user_roles=["architect"],
            decision="approve",
        )
        kwargs = escalation_repo.create.call_args.kwargs
        assert kwargs["event_type"] == EscalationEventType.ARCHITECT_HITL_APPROVE.value
        assert kwargs["decision"] == "approve"

    @pytest.mark.parametrize(
        ("next_on_reject", "expected_event"),
        [
            ("ba_hitl", EscalationEventType.ARCHITECT_HITL_REJECT_TO_BA),
            ("terminate", EscalationEventType.ARCHITECT_HITL_REJECT_TERMINATE),
        ],
        ids=["reject_to_ba", "reject_terminate"],
    )
    def test_reject_maps_by_next_on_reject(self, next_on_reject, expected_event):
        session = _make_session(fd_rejection_count=2, status=SessionStatus.PAUSED_ARCHITECT_HITL.value)
        svc, escalation_repo = _make_service(session=session)
        svc.record_architect_hitl_decision(
            session_id=session.id,
            user_id=uuid4(),
            user_roles=["architect"],
            decision="reject",
            next_on_reject=next_on_reject,
        )
        kwargs = escalation_repo.create.call_args.kwargs
        assert kwargs["event_type"] == expected_event.value
        assert kwargs["decision"] == "reject"

    @pytest.mark.parametrize("next_on_reject", [None, "bogus"])
    def test_reject_requires_valid_next_on_reject(self, next_on_reject):
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL.value)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(ValueError):
            svc.record_architect_hitl_decision(
                session_id=session.id,
                user_id=uuid4(),
                user_roles=["architect"],
                decision="reject",
                next_on_reject=next_on_reject,
            )
        escalation_repo.create.assert_not_called()

    def test_invalid_decision_raises_value_error(self):
        session = _make_session(status=SessionStatus.PAUSED_ARCHITECT_HITL.value)
        svc, _ = _make_service(session=session)
        with pytest.raises(ValueError):
            svc.record_architect_hitl_decision(
                session_id=session.id,
                user_id=uuid4(),
                user_roles=["architect"],
                decision="bogus",
            )

    def test_non_architect_denied(self):
        session = _make_session(user_id=OWNER_ID)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(AuthorizationError):
            svc.record_architect_hitl_decision(
                session_id=session.id,
                user_id=OWNER_ID,
                user_roles=[],  # owner is NOT enough for architect_hitl
                decision="approve",
            )
        escalation_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_records_session_terminated_with_reason(self):
        session = _make_session(user_id=OWNER_ID, fd_rejection_count=4)
        svc, escalation_repo = _make_service(session=session)

        returned = svc.terminate(
            session_id=session.id,
            user_id=OWNER_ID,
            user_roles=[],
            reason="done",
        )

        kwargs = escalation_repo.create.call_args.kwargs
        assert kwargs["event_type"] == EscalationEventType.SESSION_TERMINATED.value
        assert kwargs["feedback"] == "done"
        assert kwargs["decision"] == "terminate"
        assert kwargs["rejection_count_at_event"] == 4
        assert returned is escalation_repo.create.return_value
        escalation_repo.commit.assert_called_once()

    def test_terminate_by_stranger_denied(self):
        session = _make_session(user_id=OWNER_ID)
        svc, escalation_repo = _make_service(session=session)
        with pytest.raises(AuthorizationError):
            svc.terminate(
                session_id=session.id,
                user_id=uuid4(),
                user_roles=[],
                reason="nope",
            )
        escalation_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# list_history
# ---------------------------------------------------------------------------


class TestListHistory:
    def test_returns_events_in_repo_order(self):
        session = _make_session()
        svc, escalation_repo = _make_service(session=session)
        now = datetime.now(timezone.utc)
        first = EscalationEventDetail(
            id=uuid4(),
            session_id=session.id,
            event_type=EscalationEventType.BA_HITL_ITERATE,
            created_at=now,
        )
        second = EscalationEventDetail(
            id=uuid4(),
            session_id=session.id,
            event_type=EscalationEventType.BA_HITL_READY,
            created_at=now,
        )
        escalation_repo.get_for_session.return_value = [first, second]

        result = svc.list_history(
            session_id=session.id,
            user_id=session.user_id,
            user_roles=["user"],
        )

        escalation_repo.get_for_session.assert_called_once_with(session.id)
        assert isinstance(result, EscalationEventList)
        assert [e.id for e in result.items] == [first.id, second.id]

    def test_empty_history(self):
        session = _make_session()
        svc, escalation_repo = _make_service(session=session)
        escalation_repo.get_for_session.return_value = []

        result = svc.list_history(
            session_id=session.id,
            user_id=session.user_id,
            user_roles=["user"],
        )

        assert result.items == []
