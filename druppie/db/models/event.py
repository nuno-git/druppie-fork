"""Session event database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class SessionEvent(Base):
    """Unified event log for session timeline display.

    This provides a single source of truth for session history,
    instead of reconstructing events from multiple tables.
    """

    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))

    # Event classification
    event_type = Column(String(50), nullable=False)
    # Types: agent_started, agent_completed, tool_call, tool_result,
    #        approval_pending, approval_granted, approval_rejected,
    #        hitl_question, hitl_answered, deployment_started,
    #        deployment_complete, error

    # Actor identification
    agent_id = Column(String(100))  # Which agent triggered this event

    # Event details (denormalized for easy display)
    title = Column(String(500))  # Human-readable event title
    tool_name = Column(String(200))  # For tool events: coding:write_file

    # References to detailed records (optional, for drill-down)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id"))
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approvals.id"))
    hitl_question_id = Column(UUID(as_uuid=True), ForeignKey("hitl_questions.id"))

    # Event-specific data (minimal, for display only)
    event_data = Column(JSON)

    timestamp = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "title": self.title,
            "tool_name": self.tool_name,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "approval_id": str(self.approval_id) if self.approval_id else None,
            "hitl_question_id": str(self.hitl_question_id) if self.hitl_question_id else None,
            "event_data": self.event_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
