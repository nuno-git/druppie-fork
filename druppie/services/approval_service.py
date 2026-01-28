"""Approval service for business logic."""

from uuid import UUID
import structlog

from ..repositories import ApprovalRepository, SessionRepository
from ..domain import ApprovalDetail, PendingApprovalList
from ..api.errors import NotFoundError, AuthorizationError, ConflictError, ErrorCode

logger = structlog.get_logger()


class ApprovalService:
    """Business logic for approvals."""

    def __init__(
        self,
        approval_repo: ApprovalRepository,
        session_repo: SessionRepository,
    ):
        self.approval_repo = approval_repo
        self.session_repo = session_repo

    def get_pending_for_user(
        self,
        user_id: UUID,
        user_roles: list[str],
    ) -> PendingApprovalList:
        """Get approvals user can act on based on their roles."""
        # Admin sees all, others see only matching roles
        if "admin" in user_roles:
            roles_to_check = ["admin", "architect", "developer"]  # All roles
        else:
            roles_to_check = user_roles

        return self.approval_repo.get_pending_for_roles(roles_to_check)

    def get_detail(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> ApprovalDetail:
        """Get approval detail with access check."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", str(approval_id))

        # Check user can see this approval
        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role",
                required_roles=[required_role],
            )

        return self.approval_repo._to_detail(approval)

    async def approve(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        main_loop,  # MainLoop instance for resumption
        comment: str | None = None,
    ) -> dict:
        """Approve and execute the tool."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", str(approval_id))

        # Check role
        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to approve",
                required_roles=[required_role],
            )

        if approval.status != "pending":
            raise ConflictError(
                f"Approval already {approval.status}",
                error_code=ErrorCode.APPROVAL_ALREADY_PROCESSED,
            )

        # Update status
        self.approval_repo.update_status(
            approval_id=approval_id,
            status="approved",
            resolved_by=user_id,
        )
        self.approval_repo.commit()

        logger.info(
            "approval_approved",
            approval_id=str(approval_id),
            by_user=str(user_id),
            tool=f"{approval.mcp_server}:{approval.tool_name}",
        )

        # Resume execution
        result = await main_loop.resume_from_step_approval(
            session_id=str(approval.session_id),
            approval_id=str(approval_id),
            approved=True,
        )

        return {
            "success": True,
            "status": "approved",
            "tool_result": result,
        }

    async def reject(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        main_loop,  # MainLoop instance for resumption
        reason: str,
    ) -> dict:
        """Reject the approval."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", str(approval_id))

        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(f"Requires {required_role} role to reject")

        if approval.status != "pending":
            raise ConflictError(
                f"Approval already {approval.status}",
                error_code=ErrorCode.APPROVAL_ALREADY_PROCESSED,
            )

        self.approval_repo.update_status(
            approval_id=approval_id,
            status="rejected",
            resolved_by=user_id,
            rejection_reason=reason,
        )
        self.approval_repo.commit()

        logger.info(
            "approval_rejected",
            approval_id=str(approval_id),
            by_user=str(user_id),
            reason=reason,
        )

        # Resume with rejection
        result = await main_loop.resume_from_step_approval(
            session_id=str(approval.session_id),
            approval_id=str(approval_id),
            approved=False,
        )

        return {
            "success": True,
            "status": "rejected",
            "result": result,
        }
