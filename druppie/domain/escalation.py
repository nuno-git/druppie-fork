"""Escalation event domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from .common import EscalationEventType


class EscalationEventSummary(BaseModel):
    """Lightweight escalation event for lists."""

    id: UUID
    session_id: UUID
    event_type: EscalationEventType
    actor_user_id: UUID | None = None
    created_at: datetime


class EscalationEventDetail(EscalationEventSummary):
    """Full escalation event with all fields. Inherits from EscalationEventSummary."""

    decision: str | None = None
    feedback: str | None = None
    rejection_count_at_event: int = 0


class EscalationEventList(BaseModel):
    """List of escalation events for a session."""

    items: list[EscalationEventDetail]
