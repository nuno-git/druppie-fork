"""Approval repository for database access."""

from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import or_, and_

from .base import BaseRepository
from ..domain import ApprovalDetail, ApprovalSummary, ApprovalHistoryList, PendingApprovalList, ApprovalStatus
from ..db.models import Approval
from ..db.models.session import Session as SessionModel


class ApprovalRepository(BaseRepository):
    """Database access for approvals."""

    def create(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        tool_call_id: UUID,
        mcp_server: str,
        tool_name: str,
        arguments: dict,
        required_role: str,
    ) -> Approval:
        """Create a new approval record.

        Args:
            session_id: Session this approval belongs to
            agent_run_id: Agent run requesting approval
            tool_call_id: ToolCall this approval is for
            mcp_server: MCP server name (e.g., "coding")
            tool_name: Tool name (e.g., "write_file")
            arguments: Tool arguments
            required_role: Role required to approve (e.g., "developer")

        Returns:
            Created Approval model
        """
        approval = Approval(
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            mcp_server=mcp_server,
            tool_name=tool_name,
            required_role=required_role,
            arguments=arguments,
            status=ApprovalStatus.PENDING.value,
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def get_by_id(self, approval_id: UUID) -> Approval | None:
        """Get raw approval model."""
        return self.db.query(Approval).filter_by(id=approval_id).first()

    def get_pending_for_roles(
        self, roles: list[str] | None, user_id: UUID | None = None
    ) -> PendingApprovalList:
        """Get pending approvals that the user's roles can approve.

        Args:
            roles: List of roles to filter by, or None to return all pending.
            user_id: Current user's ID — used to include session_owner approvals
                for sessions this user owns.
        """
        query = (
            self.db.query(Approval)
            .filter(Approval.status == ApprovalStatus.PENDING.value)
        )
        if roles is not None:
            conditions = [Approval.required_role.in_(roles)]
            if user_id:
                conditions.append(
                    and_(
                        Approval.required_role == "session_owner",
                        Approval.session_id.in_(
                            self.db.query(SessionModel.id).filter(SessionModel.user_id == user_id)
                        ),
                    )
                )
            query = query.filter(or_(*conditions))
        approvals = query.order_by(Approval.created_at.desc()).all()
        return PendingApprovalList(
            items=[self._to_detail(a) for a in approvals],
            total=len(approvals),
        )

    def get_resolved_for_roles(
        self, roles: list[str] | None, page: int = 1, limit: int = 20,
        user_id: UUID | None = None,
    ) -> ApprovalHistoryList:
        """Get resolved approvals (approved/rejected) filtered by roles, paginated.

        Args:
            roles: List of roles to filter by, or None to return all resolved.
            user_id: Current user's ID — used to include session_owner approvals.
        """
        base_query = (
            self.db.query(Approval)
            .filter(
                Approval.status.in_([
                    ApprovalStatus.APPROVED.value,
                    ApprovalStatus.REJECTED.value,
                ])
            )
        )
        if roles is not None:
            conditions = [Approval.required_role.in_(roles)]
            if user_id:
                conditions.append(
                    and_(
                        Approval.required_role == "session_owner",
                        Approval.session_id.in_(
                            self.db.query(SessionModel.id).filter(SessionModel.user_id == user_id)
                        ),
                    )
                )
            base_query = base_query.filter(or_(*conditions))

        total = base_query.count()

        approvals = (
            base_query
            .order_by(Approval.resolved_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return ApprovalHistoryList(
            items=[self._to_detail(a) for a in approvals],
            total=total,
            page=page,
            limit=limit,
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
        # Look up session owner for session_owner approvals (needed by frontend)
        session_user_id = None
        if approval.required_role == "session_owner" and approval.session_id:
            row = self.db.query(SessionModel.user_id).filter_by(id=approval.session_id).first()
            if row:
                session_user_id = row.user_id

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
            session_user_id=session_user_id,
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
