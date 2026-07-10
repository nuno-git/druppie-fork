"""Escalation event database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class EscalationEvent(Base):
    """An audit record for escalation state-machine transitions."""

    __tablename__ = "escalation_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    event_type = Column(String(50), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decision = Column(String(200), nullable=True)
    feedback = Column(Text, nullable=True)
    rejection_count_at_event = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
