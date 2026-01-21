"""Approvals API routes.

Endpoints for managing approval requests.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import structlog

from druppie.api.deps import get_current_user, get_db, get_loop
from druppie.core.loop import MainLoop
from druppie.db import crud

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class ApprovalResponse(BaseModel):
    """Approval response model."""

    id: str
    session_id: str
    tool_name: str
    arguments: dict | None
    status: str
    required_roles: list[str] | None
    approvals_received: list[dict] | None
    danger_level: str
    description: str | None
    created_at: str | None


class ApprovalListResponse(BaseModel):
    """List of approvals response."""

    approvals: list[ApprovalResponse]
    total: int


class ApprovalDecision(BaseModel):
    """Approval decision request."""

    approved: bool = Field(..., description="Whether to approve or reject")
    comment: str | None = Field(None, description="Optional comment")


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/approvals")
async def list_approvals(
    session_id: str | None = None,
    status: str = "pending",
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List approval requests.

    By default, shows pending approvals that the user can approve.
    Returns as a list directly for backwards compatibility with getTasks.
    """
    user_roles = user.get("realm_access", {}).get("roles", [])

    if status == "pending":
        approvals = crud.list_pending_approvals(db, session_id=session_id)
    elif session_id:
        approvals = crud.list_approvals_for_session(db, session_id)
    else:
        # For non-pending, need to add more crud methods
        approvals = crud.list_pending_approvals(db)

    # Filter to approvals user can act on
    filtered = []
    for a in approvals:
        required_roles = a.required_roles or []
        # Admin can approve anything, or user has required role
        if "admin" in user_roles or not required_roles or any(r in user_roles for r in required_roles):
            filtered.append(a)

    # Return as a list for backwards compatibility with frontend getTasks
    return [
        {
            "id": a.id,
            "session_id": a.session_id,
            # Frontend expects 'name' for display
            "name": a.tool_name,
            "tool_name": a.tool_name,
            "arguments": a.arguments,
            "status": a.status,
            "required_roles": a.required_roles,
            # Frontend expects 'required_role' (singular)
            "required_role": (a.required_roles or ["admin"])[0],
            "approvals_received": a.approvals_received,
            "danger_level": a.danger_level,
            "description": a.description,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in filtered
    ]


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific approval request."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    return ApprovalResponse(
        id=approval.id,
        session_id=approval.session_id,
        tool_name=approval.tool_name,
        arguments=approval.arguments,
        status=approval.status,
        required_roles=approval.required_roles,
        approvals_received=approval.approvals_received,
        danger_level=approval.danger_level,
        description=approval.description,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
    )


@router.post("/approvals/{approval_id}/approve")
async def approve_request(
    approval_id: str,
    decision: ApprovalDecision,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    loop: MainLoop = Depends(get_loop),
):
    """Approve or reject an approval request."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval is not pending")

    user_roles = user.get("realm_access", {}).get("roles", [])
    required_roles = approval.required_roles or []

    # Check authorization
    if required_roles and "admin" not in user_roles:
        if not any(r in user_roles for r in required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(required_roles)}",
            )

    # Update approval status
    new_status = "approved" if decision.approved else "rejected"
    crud.update_approval(
        db,
        approval_id,
        {
            "status": new_status,
            "approvals_received": (approval.approvals_received or [])
            + [
                {
                    "user_id": user.get("sub"),
                    "role": user_roles[0] if user_roles else "user",
                    "approved": decision.approved,
                    "comment": decision.comment,
                }
            ],
        },
    )

    logger.info(
        "approval_decision",
        approval_id=approval_id,
        approved=decision.approved,
        user_id=user.get("sub"),
    )

    # Resume the session if approved
    if decision.approved:
        try:
            result = await loop.resume_session(
                session_id=approval.session_id,
                approval=True,
                user_id=user.get("sub"),
            )
            return {
                "success": True,
                "status": "approved",
                "session_resumed": True,
                "result": result,
            }
        except Exception as e:
            logger.error("approval_resume_error", error=str(e))
            return {
                "success": True,
                "status": "approved",
                "session_resumed": False,
                "error": str(e),
            }

    return {
        "success": True,
        "status": "rejected",
        "session_resumed": False,
    }
