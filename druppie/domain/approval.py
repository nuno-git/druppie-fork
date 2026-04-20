"""Approval domain models."""

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import ApprovalStatus


class ApprovalSummary(BaseModel):
    """Lightweight approval for embedding in tool calls."""
    id: UUID
    status: ApprovalStatus
    required_role: str
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


class ApprovalDetail(ApprovalSummary):
    """Full approval with context. Inherits from ApprovalSummary."""
    session_id: UUID
    agent_run_id: UUID | None
    tool_call_id: UUID
    # Tool info
    mcp_server: str
    tool_name: str
    arguments: dict
    # Context
    agent_id: str | None
    rejection_reason: str | None = None
    created_at: datetime
    # Session owner ID — populated for session_owner approvals so the frontend
    # can determine if the current user is the session owner.
    session_user_id: UUID | None = None


class PendingApprovalList(BaseModel):
    """Approvals the current user can act on."""
    items: list[ApprovalDetail]
    total: int


class ApprovalHistoryList(BaseModel):
    """Paginated list of resolved approvals."""
    items: list[ApprovalDetail]
    total: int
    page: int
    limit: int
