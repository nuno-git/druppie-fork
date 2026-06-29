"""Resume context event database model.

Records user-injected context when resuming a paused agent run,
storing the position (llm_call_index) at which it was inserted.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class ResumeContextEvent(Base):
    """A user-injected context message at resume time."""

    __tablename__ = "resume_context_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    llm_call_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
