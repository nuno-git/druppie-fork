"""Sandbox session ownership mapping model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class SandboxSession(Base):
    """Maps sandbox control plane session IDs to Druppie users.

    When the MCP coding server creates a sandbox session, it registers
    the mapping here so the events proxy can verify ownership.
    """

    __tablename__ = "sandbox_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sandbox_session_id = Column(String(255), unique=True, nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
