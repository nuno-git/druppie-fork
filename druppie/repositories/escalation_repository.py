"""Escalation event repository for database access."""

from uuid import UUID

from ..db.models.escalation_event import EscalationEvent
from ..domain import EscalationEventDetail, EscalationEventSummary
from ..domain.common import EscalationEventType
from .base import BaseRepository


class EscalationRepository(BaseRepository):
    """Database access for escalation events."""

    def create(
        self,
        session_id: UUID,
        event_type: str,
        actor_user_id: UUID | None = None,
        decision: str | None = None,
        feedback: str | None = None,
        rejection_count_at_event: int = 0,
    ) -> EscalationEventDetail:
        event = EscalationEvent(
            session_id=session_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            decision=decision,
            feedback=feedback,
            rejection_count_at_event=rejection_count_at_event,
        )
        self.db.add(event)
        self.db.flush()
        return self._to_detail(event)

    def get_for_session(self, session_id: UUID) -> list[EscalationEventDetail]:
        events = (
            self.db.query(EscalationEvent)
            .filter(EscalationEvent.session_id == session_id)
            .order_by(EscalationEvent.created_at.asc())
            .all()
        )
        return [self._to_detail(e) for e in events]

    def _to_detail(self, event: EscalationEvent) -> EscalationEventDetail:
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

    def _to_summary(self, event: EscalationEvent) -> EscalationEventSummary:
        return EscalationEventSummary(
            id=event.id,
            session_id=event.session_id,
            event_type=EscalationEventType(event.event_type),
            actor_user_id=event.actor_user_id,
            created_at=event.created_at,
        )
