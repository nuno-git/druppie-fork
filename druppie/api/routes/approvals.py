"""Approvals API routes.

Tool approvals allow human oversight of agent actions. When an agent tries
to use a tool that requires approval (defined in mcp_config.yaml), execution
pauses until a user with the required role approves or rejects.

Architecture:
    POST /approvals/{id}/approve or /reject
      │
      ├── Save decision to DB (fast)
      ├── Spawn background task
      └── Return immediately

    Background task:
      └──▶ Orchestrator.resume_after_approval()
              (executes tool, continues workflow)

The endpoint returns immediately. The client polls
GET /api/sessions/{id} to track progress.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_current_user, get_user_roles, get_approval_service
from druppie.services import ApprovalService
from druppie.domain import ApprovalDetail, ApprovalHistoryList, PendingApprovalList
from druppie.core.background_tasks import create_session_task, run_session_task, SessionTaskConflict

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
    message: str = "Processing started"


# =============================================================================
# BACKGROUND TASK
# =============================================================================


async def _resume_workflow_after_approval(
    session_id: UUID,
    approval_id: UUID,
) -> None:
    """Resume workflow in background using run_session_task for DB lifecycle."""

    async def task(ctx):
        await ctx.orchestrator.resume_after_approval(
            session_id=session_id,
            approval_id=approval_id,
        )

    await run_session_task(session_id, task, "resume_after_approval")


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
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return service.get_pending_for_roles(user_roles, user_id=user_id)


@router.get("/history")
async def approval_history(
    page: int = 1,
    limit: int = 20,
    service: ApprovalService = Depends(get_approval_service),
    user: dict = Depends(get_current_user),
) -> ApprovalHistoryList:
    """List resolved approvals (approved/rejected) the user can see.

    Returns paginated history of approvals that have been resolved,
    filtered by the user's roles. Admin users see all history.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return service.get_history_for_roles(user_roles, user_id=user_id, page=page, limit=limit)


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: UUID,
    approval_service: ApprovalService = Depends(get_approval_service),
    user: dict = Depends(get_current_user),
) -> ApprovalResponse:
    """Approve a pending tool execution.

    Saves the approval and starts workflow resumption in the background.
    Returns immediately - poll GET /api/sessions/{id} for progress.

    Args:
        approval_id: The approval to approve

    Returns:
        The updated approval (workflow continues in background)

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

    # Step 1: Record approval in database (fast)
    approval = approval_service.approve(
        approval_id=approval_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Step 2: Spawn background task to resume workflow
    try:
        create_session_task(
            approval.session_id,
            _resume_workflow_after_approval(
                session_id=approval.session_id,
                approval_id=approval_id,
            ),
            name=f"resume-approve-{approval_id}",
        )
    except SessionTaskConflict:
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )

    logger.info(
        "approval_recorded_resuming_in_background",
        approval_id=str(approval_id),
        session_id=str(approval.session_id),
    )

    return ApprovalResponse(
        approval=approval,
        message="Approved - workflow resuming",
    )


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: UUID,
    request: RejectRequest,
    approval_service: ApprovalService = Depends(get_approval_service),
    user: dict = Depends(get_current_user),
) -> ApprovalResponse:
    """Reject a pending tool execution.

    Saves the rejection and starts workflow resumption in the background.
    The workflow will handle the rejection (typically failing the tool call
    and allowing the agent to try a different approach).

    Returns immediately - poll GET /api/sessions/{id} for progress.

    Args:
        approval_id: The approval to reject
        request: Rejection reason

    Returns:
        The updated approval (workflow continues in background)

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

    # Step 1: Record rejection in database (fast)
    approval = approval_service.reject(
        approval_id=approval_id,
        user_id=user_id,
        user_roles=user_roles,
        reason=request.reason,
    )

    # Step 2: Spawn background task to resume workflow
    try:
        create_session_task(
            approval.session_id,
            _resume_workflow_after_approval(
                session_id=approval.session_id,
                approval_id=approval_id,
            ),
            name=f"resume-reject-{approval_id}",
        )
    except SessionTaskConflict:
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )

    logger.info(
        "rejection_recorded_resuming_in_background",
        approval_id=str(approval_id),
        session_id=str(approval.session_id),
    )

    return ApprovalResponse(
        approval=approval,
        message="Rejected - workflow resuming",
    )
