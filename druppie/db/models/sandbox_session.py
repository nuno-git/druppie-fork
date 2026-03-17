"""Sandbox session ownership mapping model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class SandboxSession(Base):
    """Maps sandbox control plane session IDs to Druppie users.

    When the execute_coding_task builtin creates a sandbox session, it registers
    the mapping here so the events proxy can verify ownership and the webhook
    can look up the corresponding tool call.
    """

    __tablename__ = "sandbox_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sandbox_session_id = Column(String(255), unique=True, nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Webhook signature secret (per-session, replaces global SANDBOX_API_SECRET for webhooks)
    webhook_secret = Column(String(128), nullable=True)

    # Model chain for retry — JSON array of {provider, model} dicts
    model_chain = Column(Text, nullable=True)
    model_chain_index = Column(Integer, default=0)
    task_prompt = Column(Text, nullable=True)
    agent_name = Column(String(100), nullable=True)

    # Per-sandbox Gitea service account ID for cleanup (None for GitHub — tokens expire automatically)
    git_user_id = Column(String(50), nullable=True)
