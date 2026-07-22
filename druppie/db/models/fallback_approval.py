"""Fallback approval database model.

Stores user-approved fallback LLM switches so the state is shared across
all backend workers (multi-worker / multi-replica deployments).
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Boolean, UniqueConstraint, Index

from .base import Base, utcnow


class FallbackApproval(Base):
    """Records a user-approved fallback LLM switch.

    Two approval levels:
    - Session-wide: agent_id IS NULL — all agents auto-switch in this session
    - Per-agent: agent_id IS SET — only this agent type auto-switches
    """

    __tablename__ = "fallback_approvals"
    __table_args__ = (
        UniqueConstraint("session_id", "agent_id", name="uq_fallback_approvals_session_agent"),
        Index("idx_fallback_approvals_session", "session_id"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String(36), nullable=False)
    agent_id = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), default=utcnow)