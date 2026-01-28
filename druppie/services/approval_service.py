"""Approval service for business logic.

This service handles database operations for tool approvals.
It does NOT handle workflow resumption - that's the WorkflowService's job.

Architecture:
    Route
      │
      ├──▶ ApprovalService (this) ──▶ ApprovalRepository ──▶ Database
      │         (DB operations)
      │
      └──▶ WorkflowService ──▶ MainLoop
              (resumption)

The route coordinates both services:
1. ApprovalService.approve/reject() - updates DB status
2. WorkflowService.resume_from_approval() - resumes the workflow
"""

from uuid import UUID
import structlog

from ..repositories import ApprovalRepository
from ..domain import ApprovalDetail, PendingApprovalList, ApprovalStatus
from ..api.errors import NotFoundError, AuthorizationError, ConflictError

logger = structlog.get_logger()


class ApprovalService:
    """Business logic for approvals.

    This service handles:
    - Listing pending approvals for user's roles
    - Recording approve/reject decisions in the database

    It does NOT handle workflow resumption. After calling approve/reject(),
    the route should call WorkflowService.resume_from_approval().
    """

    def __init__(self, approval_repo: ApprovalRepository):
        self.approval_repo = approval_repo

    def get_pending_for_roles(
        self,
        user_roles: list[str],
    ) -> PendingApprovalList:
        """Get approvals user can act on based on their roles.

        Admin users see all pending approvals.
        Other users see only approvals matching their roles.
        """
        if "admin" in user_roles:
            # Admin sees all - check all common roles
            roles_to_check = ["admin", "architect", "developer"]
        else:
            roles_to_check = user_roles

        return self.approval_repo.get_pending_for_roles(roles_to_check)

    def approve(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> ApprovalDetail:
        """Record approval decision in database.

        This method ONLY updates the database. It does NOT resume the workflow
        - that's handled by WorkflowService.

        Args:
            approval_id: The approval to approve
            user_id: The user approving
            user_roles: User's roles (must include required_role)

        Returns:
            Updated ApprovalDetail

        Raises:
            NotFoundError: Approval doesn't exist
            AuthorizationError: User lacks required role
            ConflictError: Approval already processed

        Usage in route:
            # 1. Record approval in DB
            approval = approval_service.approve(approval_id, user_id, user_roles)

            # 2. Resume workflow (separate concern)
            result = await workflow_service.resume_from_approval(
                session_id=approval.session_id,
                approval_id=approval_id,
            )
        """
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", str(approval_id))

        # Check role authorization
        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to approve",
                required_roles=[required_role],
            )

        # Check not already processed
        if approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError(f"Approval already {approval.status}")

        # Update status in database
        self.approval_repo.update_status(
            approval_id=approval_id,
            status=ApprovalStatus.APPROVED,
            resolved_by=user_id,
        )
        self.approval_repo.commit()

        logger.info(
            "approval_approved",
            approval_id=str(approval_id),
            by_user=str(user_id),
            tool=f"{approval.mcp_server}:{approval.tool_name}",
        )

        # Return updated approval
        updated = self.approval_repo.get_by_id(approval_id)
        return self.approval_repo._to_detail(updated)

    def reject(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        reason: str,
    ) -> ApprovalDetail:
        """Record rejection decision in database.

        This method ONLY updates the database. It does NOT resume the workflow
        - that's handled by WorkflowService.

        Args:
            approval_id: The approval to reject
            user_id: The user rejecting
            user_roles: User's roles (must include required_role)
            reason: Rejection reason

        Returns:
            Updated ApprovalDetail

        Raises:
            NotFoundError: Approval doesn't exist
            AuthorizationError: User lacks required role
            ConflictError: Approval already processed
        """
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", str(approval_id))

        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to reject",
                required_roles=[required_role],
            )

        if approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError(f"Approval already {approval.status}")

        self.approval_repo.update_status(
            approval_id=approval_id,
            status=ApprovalStatus.REJECTED,
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

        updated = self.approval_repo.get_by_id(approval_id)
        return self.approval_repo._to_detail(updated)
