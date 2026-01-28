"""Approval repository for database access."""

from uuid import UUID
from datetime import datetime, timezone

from .base import BaseRepository
from ..domain import ApprovalDetail, ApprovalSummary, PendingApprovalList
from ..db.models import Approval


class ApprovalRepository(BaseRepository):
    """Database access for approvals."""

    def get_by_id(self, approval_id: UUID) -> Approval | None:
        """Get raw approval model."""
        return self.db.query(Approval).filter_by(id=approval_id).first()

    def get_pending_for_roles(self, roles: list[str]) -> PendingApprovalList:
        """Get pending approvals that the user's roles can approve."""
        approvals = (
            self.db.query(Approval)
            .filter(Approval.status == "pending")
            .filter(Approval.required_role.in_(roles))
            .order_by(Approval.created_at.desc())
            .all()
        )
        return PendingApprovalList(
            items=[self._to_detail(a) for a in approvals],
            total=len(approvals),
        )

    def get_for_session(self, session_id: UUID) -> list[ApprovalDetail]:
        """Get all approvals for a session."""
        approvals = (
            self.db.query(Approval)
            .filter_by(session_id=session_id)
            .order_by(Approval.created_at)
            .all()
        )
        return [self._to_detail(a) for a in approvals]

    def update_status(
        self,
        approval_id: UUID,
        status: str,
        resolved_by: UUID | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        """Update approval status."""
        updates = {
            "status": status,
            "resolved_by": resolved_by,
            "resolved_at": datetime.now(timezone.utc) if resolved_by else None,
        }
        if rejection_reason:
            updates["rejection_reason"] = rejection_reason
        self.db.query(Approval).filter_by(id=approval_id).update(updates)

    def _to_detail(self, approval: Approval) -> ApprovalDetail:
        """Convert approval model to detail domain object."""
        return ApprovalDetail(
            id=approval.id,
            session_id=approval.session_id,
            agent_run_id=approval.agent_run_id,
            tool_call_id=approval.tool_call_id,
            approval_type=approval.approval_type or "tool_call",
            mcp_server=approval.mcp_server,
            tool_name=approval.tool_name,
            arguments=approval.arguments or {},
            status=approval.status,
            required_role=approval.required_role or "admin",
            agent_id=approval.agent_id,
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
            rejection_reason=approval.rejection_reason,
            created_at=approval.created_at,
        )

    def _to_summary(self, approval: Approval) -> ApprovalSummary:
        """Convert approval model to summary domain object."""
        return ApprovalSummary(
            id=approval.id,
            status=approval.status,
            required_role=approval.required_role or "admin",
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
        )
