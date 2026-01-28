"""Approval domain models."""

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ApprovalSummary(BaseModel):
    """Lightweight approval for embedding."""
    id: UUID
    status: str  # pending, approved, rejected
    required_role: str
    resolved_by: UUID | None
    resolved_at: datetime | None


class ApprovalDetail(BaseModel):
    """Full approval with context."""
    id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    tool_call_id: UUID | None
    approval_type: str  # tool_call, workflow_step
    mcp_server: str | None
    tool_name: str | None
    arguments: dict
    status: str
    required_role: str
    agent_id: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    rejection_reason: str | None
    created_at: datetime


class PendingApprovalList(BaseModel):
    """Approvals the current user can act on."""
    items: list[ApprovalDetail]
    total: int
