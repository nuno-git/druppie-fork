"""Approval repository for database access."""

from uuid import UUID
from datetime import datetime, timezone

from .base import BaseRepository
from ..domain import ApprovalDetail, ApprovalSummary, PendingApprovalList, ApprovalStatus
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
            .filter(Approval.status == ApprovalStatus.PENDING.value)
            .filter(Approval.required_role.in_(roles))
            .order_by(Approval.created_at.desc())
            .all()
        )
        return PendingApprovalList(
            items=[self._to_detail(a) for a in approvals],
            total=len(approvals),
        )

    def update_status(
        self,
        approval_id: UUID,
        status: ApprovalStatus,
        resolved_by: UUID | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        """Update approval status."""
        updates = {
            "status": status.value,
            "resolved_by": resolved_by,
            "resolved_at": datetime.now(timezone.utc) if resolved_by else None,
        }
        if rejection_reason:
            updates["rejection_reason"] = rejection_reason
        self.db.query(Approval).filter_by(id=approval_id).update(updates)

    def _to_detail(self, approval: Approval) -> ApprovalDetail:
        """Convert approval model to detail domain object."""
        return ApprovalDetail(
            # From ApprovalSummary
            id=approval.id,
            status=ApprovalStatus(approval.status),
            required_role=approval.required_role or "admin",
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
            # ApprovalDetail specific
            session_id=approval.session_id,
            agent_run_id=approval.agent_run_id,
            tool_call_id=approval.tool_call_id,
            mcp_server=approval.mcp_server or "",
            tool_name=approval.tool_name or "",
            arguments=approval.arguments or {},
            agent_id=approval.agent_id,
            rejection_reason=approval.rejection_reason,
            created_at=approval.created_at,
        )

    def _to_summary(self, approval: Approval) -> ApprovalSummary:
        """Convert approval model to summary domain object."""
        return ApprovalSummary(
            id=approval.id,
            status=ApprovalStatus(approval.status),
            required_role=approval.required_role or "admin",
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
        )
