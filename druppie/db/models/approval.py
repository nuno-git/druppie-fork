"""Approval database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class Approval(Base):
    """An approval request for a tool call."""

    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"))
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"))
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id"))

    approval_type = Column(String(20), nullable=False)  # tool_call

    mcp_server = Column(String(100))
    tool_name = Column(String(200))

    title = Column(String(500))
    description = Column(Text)

    required_role = Column(String(50))  # architect, developer, infra_engineer, admin

    @property
    def required_roles(self) -> list[str]:
        """Get required roles as a list (for API compatibility)."""
        if not self.required_role:
            return []
        return [r.strip() for r in self.required_role.split(",") if r.strip()]

    @property
    def approvals_received(self) -> list[str]:
        """Get list of approvals received (for multi-approval API compatibility)."""
        if self.status == "approved" and self.resolved_by:
            return [str(self.resolved_by)]
        return []

    @property
    def approved_by(self) -> str | None:
        """Get the user who approved (for API compatibility)."""
        if self.status == "approved" and self.resolved_by:
            return str(self.resolved_by)
        return None

    @property
    def approved_at(self):
        """Get approval timestamp (for API compatibility)."""
        if self.status == "approved":
            return self.resolved_at
        return None

    @property
    def rejected_by(self) -> str | None:
        """Get the user who rejected (for API compatibility)."""
        if self.status == "rejected" and self.resolved_by:
            return str(self.resolved_by)
        return None

    # Danger level for MCP tools
    danger_level = Column(String(20))  # low, medium, high

    status = Column(String(20), default="pending")  # pending, approved, rejected

    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)

    # Tool arguments for execution after approval
    arguments = Column(JSON)

    # Agent state for resumption after approval
    agent_state = Column(JSON)

    # Agent ID that requested the approval
    agent_id = Column(String(100))

    created_at = Column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id) if self.session_id else None,
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
            "tool_call_id": str(self.tool_call_id) if self.tool_call_id else None,
            "approval_type": self.approval_type,
            "mcp_server": self.mcp_server,
            "tool_name": self.tool_name,
            "title": self.title,
            "description": self.description,
            "required_role": self.required_role,
            "required_roles": self.required_roles,
            "danger_level": self.danger_level,
            "status": self.status,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "rejection_reason": self.rejection_reason,
            "arguments": self.arguments,
            "agent_state": self.agent_state,
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
