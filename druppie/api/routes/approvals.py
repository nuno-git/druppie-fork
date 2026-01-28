"""Approvals API routes.

Tool approvals allow human oversight of agent actions. When an agent tries
to use a tool that requires approval (defined in mcp_config.yaml), execution
pauses until a user with the required role approves or rejects.

Architecture:
    Route (this file)
      │
      ├──▶ ApprovalService ──▶ ApprovalRepository ──▶ Database
      │         (DB operations: list, approve, reject)
      │
      └──▶ WorkflowService ──▶ MainLoop
              (resume workflow after decision)

The route coordinates both services:
1. ApprovalService.approve/reject() - updates DB status
2. WorkflowService.resume_from_approval() - resumes the paused workflow
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import (
    get_current_user,
    get_user_roles,
    get_approval_service,
    get_workflow_service,
)
from druppie.services import ApprovalService, WorkflowService
from druppie.domain import ApprovalDetail, PendingApprovalList

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class RejectRequest(BaseModel):
    """Request body for rejecting an approval."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Reason for rejection",
    )


class ApprovalResponse(BaseModel):
    """Response after approve/reject decision."""

    approval: ApprovalDetail
    workflow_resumed: bool
    workflow_result: dict | None = None


# =============================================================================
# ROUTES
# =============================================================================


@router.get("")
async def list_approvals(
    service: ApprovalService = Depends(get_approval_service),
    user: dict = Depends(get_current_user),
) -> PendingApprovalList:
    """List pending approvals the user can act on.

    Returns approvals that:
    - Have status = pending
    - Require a role that the user has

    Admin users see all pending approvals.

    Each approval includes:
    - Tool being called (mcp_server:tool_name)
    - Arguments being passed
    - Required role to approve
    - Session and agent info
    """
    user_roles = get_user_roles(user)
    return service.get_pending_for_roles(user_roles)


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: UUID,
    approval_service: ApprovalService = Depends(get_approval_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    user: dict = Depends(get_current_user),
) -> ApprovalResponse:
    """Approve a pending tool execution.

    This endpoint does two things:
    1. Records the approval in the database (ApprovalService)
    2. Resumes the paused workflow (WorkflowService)

    The workflow will then execute the approved tool and continue.

    Args:
        approval_id: The approval to approve

    Returns:
        The updated approval and workflow resumption result

    Raises:
        NotFoundError: Approval doesn't exist
        AuthorizationError: User lacks required role
        ConflictError: Approval already processed
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    logger.info(
        "approving",
        approval_id=str(approval_id),
        user_id=str(user_id),
    )

    # Step 1: Record approval in database
    approval = approval_service.approve(
        approval_id=approval_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Step 2: Resume the workflow
    try:
        workflow_result = await workflow_service.resume_from_approval(
            session_id=approval.session_id,
            approval_id=approval_id,
        )
        workflow_resumed = True
    except Exception as e:
        logger.error(
            "workflow_resume_failed",
            approval_id=str(approval_id),
            session_id=str(approval.session_id),
            error=str(e),
        )
        workflow_result = {"error": str(e)}
        workflow_resumed = False

    logger.info(
        "approved",
        approval_id=str(approval_id),
        workflow_resumed=workflow_resumed,
    )

    return ApprovalResponse(
        approval=approval,
        workflow_resumed=workflow_resumed,
        workflow_result=workflow_result,
    )


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: UUID,
    request: RejectRequest,
    approval_service: ApprovalService = Depends(get_approval_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    user: dict = Depends(get_current_user),
) -> ApprovalResponse:
    """Reject a pending tool execution.

    This endpoint does two things:
    1. Records the rejection in the database (ApprovalService)
    2. Resumes the paused workflow with rejection (WorkflowService)

    The workflow will handle the rejection (typically failing the tool call
    and allowing the agent to try a different approach).

    Args:
        approval_id: The approval to reject
        request: Rejection reason

    Returns:
        The updated approval and workflow resumption result

    Raises:
        NotFoundError: Approval doesn't exist
        AuthorizationError: User lacks required role
        ConflictError: Approval already processed
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    logger.info(
        "rejecting",
        approval_id=str(approval_id),
        user_id=str(user_id),
        reason=request.reason,
    )

    # Step 1: Record rejection in database
    approval = approval_service.reject(
        approval_id=approval_id,
        user_id=user_id,
        user_roles=user_roles,
        reason=request.reason,
    )

    # Step 2: Resume the workflow with rejection
    try:
        workflow_result = await workflow_service.resume_from_approval(
            session_id=approval.session_id,
            approval_id=approval_id,
        )
        workflow_resumed = True
    except Exception as e:
        logger.error(
            "workflow_resume_failed",
            approval_id=str(approval_id),
            session_id=str(approval.session_id),
            error=str(e),
        )
        workflow_result = {"error": str(e)}
        workflow_resumed = False

    logger.info(
        "rejected",
        approval_id=str(approval_id),
        workflow_resumed=workflow_resumed,
    )

    return ApprovalResponse(
        approval=approval,
        workflow_resumed=workflow_resumed,
        workflow_result=workflow_result,
    )
