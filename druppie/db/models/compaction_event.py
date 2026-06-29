"""Compaction event database model.

Tracks every context compression that occurs during an agent run,
providing a first-class audit trail of LLM summarization events.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class CompactionEvent(Base):
    """Records a single context compaction event during an agent run.

    phase values:
      - "skip":               Below threshold, no compression needed
      - "summarized":          LLM summarization succeeded
      - "summarized_fallback": LLM failed, fell back to reduced recent window
      - "overflow":            Context overflow detected
    """

    __tablename__ = "compaction_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    llm_call_id = Column(UUID(as_uuid=True), ForeignKey("llm_calls.id", ondelete="SET NULL"), nullable=True)
    phase = Column(String(50), nullable=False)
    tokens_before = Column(Integer, default=0)
    tokens_after = Column(Integer, default=0)
    turns_compressed = Column(Integer, default=0)
    summary_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
