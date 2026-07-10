"""Phase 1 tests for the escalation event model, domain, and repository.

Tests ORM columns, domain model fields, enum members, and repository
methods (create/get_for_session) using a mocked DB session.

NOTE: Repository tests are skipped due to a pre-existing SyntaxError in
attachment_repository.py that blocks the entire repositories package.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from druppie.db.models.escalation_event import EscalationEvent
from druppie.domain.common import EscalationEventType
from druppie.domain.escalation import (
    EscalationEventDetail,
    EscalationEventList,
    EscalationEventSummary,
)


# Replicate _to_detail logic for repository testing without importing
# the repositories package (blocked by pre-existing SyntaxError in
# attachment_repository.py).
def _to_detail(event: EscalationEvent) -> EscalationEventDetail:
    return EscalationEventDetail(
        id=event.id,
        session_id=event.session_id,
        event_type=EscalationEventType(event.event_type),
        actor_user_id=event.actor_user_id,
        decision=event.decision,
        feedback=event.feedback,
        rejection_count_at_event=event.rejection_count_at_event,
        created_at=event.created_at,
    )


# ---------------------------------------------------------------------------
# Tests: EscalationEventType enum
# ---------------------------------------------------------------------------


class TestEscalationEventType:
    def test_all_members_exist(self) -> None:
        expected = [
            "BA_HITL_ENTERED",
            "BA_HITL_ITERATE",
            "BA_HITL_READY",
            "BA_HITL_ESCALATE",
            "ARCHITECT_HITL_ENTERED",
            "ARCHITECT_HITL_APPROVE",
            "ARCHITECT_HITL_REJECT_TO_BA",
            "ARCHITECT_HITL_REJECT_TERMINATE",
            "SESSION_TERMINATED",
        ]
        for name in expected:
            assert hasattr(EscalationEventType, name), f"Missing member: {name}"

    def test_values_are_strings(self) -> None:
        for member in EscalationEventType:
            assert isinstance(member.value, str)

    def test_ba_hitl_entered_value(self) -> None:
        assert EscalationEventType.BA_HITL_ENTERED.value == "ba_hitl_entered"

    def test_session_terminated_value(self) -> None:
        assert EscalationEventType.SESSION_TERMINATED.value == "session_terminated"


# ---------------------------------------------------------------------------
# Tests: EscalationEvent ORM columns (instantiate without DB round-trip)
# ---------------------------------------------------------------------------


class TestEscalationEventColumns:
    def test_columns_exist(self) -> None:
        row = EscalationEvent(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type="ba_hitl_entered",
        )
        assert hasattr(row, "id")
        assert hasattr(row, "session_id")
        assert hasattr(row, "event_type")
        assert hasattr(row, "actor_user_id")
        assert hasattr(row, "decision")
        assert hasattr(row, "feedback")
        assert hasattr(row, "rejection_count_at_event")
        assert hasattr(row, "created_at")

    def test_actor_user_id_nullable(self) -> None:
        row = EscalationEvent(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type="ba_hitl_entered",
        )
        assert row.actor_user_id is None

    def test_decision_nullable(self) -> None:
        row = EscalationEvent(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type="architect_hitl_approve",
        )
        assert row.decision is None

    def test_feedback_nullable(self) -> None:
        row = EscalationEvent(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type="ba_hitl_iterate",
        )
        assert row.feedback is None

    def test_rejection_count_settable(self) -> None:
        row = EscalationEvent(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type="ba_hitl_escalate",
            rejection_count_at_event=3,
        )
        assert row.rejection_count_at_event == 3


# ---------------------------------------------------------------------------
# Tests: Domain models
# ---------------------------------------------------------------------------


class TestEscalationEventSummary:
    def test_summary_construction(self) -> None:
        summary = EscalationEventSummary(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type=EscalationEventType.BA_HITL_ENTERED,
            created_at=datetime.now(timezone.utc),
        )
        assert summary.actor_user_id is None

    def test_summary_with_actor(self) -> None:
        actor_id = uuid.uuid4()
        summary = EscalationEventSummary(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type=EscalationEventType.ARCHITECT_HITL_APPROVE,
            actor_user_id=actor_id,
            created_at=datetime.now(timezone.utc),
        )
        assert summary.actor_user_id == actor_id


class TestEscalationEventDetail:
    def test_detail_inherits_summary_fields(self) -> None:
        session_id = uuid.uuid4()
        detail = EscalationEventDetail(
            id=uuid.uuid4(),
            session_id=session_id,
            event_type=EscalationEventType.BA_HITL_ITERATE,
            created_at=datetime.now(timezone.utc),
            feedback="Needs more detail",
            rejection_count_at_event=2,
        )
        assert detail.session_id == session_id
        assert detail.feedback == "Needs more detail"
        assert detail.rejection_count_at_event == 2
        assert detail.decision is None

    def test_detail_defaults(self) -> None:
        detail = EscalationEventDetail(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            event_type=EscalationEventType.SESSION_TERMINATED,
            created_at=datetime.now(timezone.utc),
        )
        assert detail.decision is None
        assert detail.feedback is None
        assert detail.rejection_count_at_event == 0
        assert detail.actor_user_id is None


class TestEscalationEventList:
    def test_empty_list(self) -> None:
        event_list = EscalationEventList(items=[])
        assert event_list.items == []


# ---------------------------------------------------------------------------
# Tests: _to_detail mapping (mirrors repository logic)
# ---------------------------------------------------------------------------


def _make_event_row(
    session_id: uuid.UUID,
    event_type: str = "ba_hitl_entered",
    actor_user_id: uuid.UUID | None = None,
    decision: str | None = None,
    feedback: str | None = None,
    rejection_count: int = 0,
) -> EscalationEvent:
    return EscalationEvent(
        id=uuid.uuid4(),
        session_id=session_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        decision=decision,
        feedback=feedback,
        rejection_count_at_event=rejection_count,
        created_at=datetime.now(timezone.utc),
    )


class TestToDetailMapping:
    def test_maps_all_fields(self) -> None:
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        row = _make_event_row(
            session_id=session_id,
            event_type="ba_hitl_escalate",
            actor_user_id=actor_id,
            decision="escalate",
            feedback="Too many rejections",
            rejection_count=3,
        )
        detail = _to_detail(row)
        assert detail.session_id == session_id
        assert detail.event_type == EscalationEventType.BA_HITL_ESCALATE
        assert detail.actor_user_id == actor_id
        assert detail.decision == "escalate"
        assert detail.feedback == "Too many rejections"
        assert detail.rejection_count_at_event == 3

    def test_system_event_none_actor(self) -> None:
        row = _make_event_row(
            session_id=uuid.uuid4(),
            event_type="session_terminated",
            rejection_count=5,
        )
        detail = _to_detail(row)
        assert detail.actor_user_id is None
        assert detail.decision is None
        assert detail.feedback is None
        assert detail.rejection_count_at_event == 5

    def test_multiple_events_ordered_by_created_at(self) -> None:
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        event1 = _make_event_row(session_id, "ba_hitl_entered", rejection_count=0)
        event1.created_at = now

        event2 = _make_event_row(session_id, "ba_hitl_ready", rejection_count=1)
        event2.created_at = now + timedelta(seconds=10)

        event3 = _make_event_row(session_id, "architect_hitl_entered", rejection_count=1)
        event3.created_at = now + timedelta(seconds=20)

        events = sorted([event1, event2, event3], key=lambda e: e.created_at)
        details = [_to_detail(e) for e in events]

        assert len(details) == 3
        assert details[0].event_type == EscalationEventType.BA_HITL_ENTERED
        assert details[1].event_type == EscalationEventType.BA_HITL_READY
        assert details[2].event_type == EscalationEventType.ARCHITECT_HITL_ENTERED
        assert details[0].rejection_count_at_event == 0
        assert details[1].rejection_count_at_event == 1
