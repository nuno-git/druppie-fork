"""Approvals API routes.

Endpoints for managing approval requests and merge approvals.
Supports MCP microservices architecture with resume execution.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import structlog

from druppie.api.deps import get_current_user, get_db, get_loop
from druppie.core.loop import MainLoop
from druppie.core.mcp_client import get_mcp_client
from druppie.core.execution_context import ExecutionContext
from druppie.db import crud
from druppie.db.models import Approval, Workspace

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
        # Security policy: If no required_roles are specified, default to requiring "admin" role.
        # This prevents approvals without explicit role requirements from being approvable by anyone.
        required_roles = a.required_roles if a.required_roles else ["admin"]
        # Admin can approve anything, or user has one of the required roles
        if "admin" in user_roles or any(r in user_roles for r in required_roles):
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
    """Approve or reject an approval request and resume execution."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval is not pending")

    user_roles = user.get("realm_access", {}).get("roles", [])
    # Security policy: If no required_roles are specified, default to requiring "admin" role.
    # This prevents approvals without explicit role requirements from being approvable by anyone.
    required_roles = approval.required_roles if approval.required_roles else ["admin"]

    # Check authorization - admin can approve anything, otherwise need a required role
    if "admin" not in user_roles:
        if not any(r in user_roles for r in required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(required_roles)}",
            )

    user_id = user.get("sub")

    if decision.approved:
        # Update approval status to approved
        crud.update_approval(
            db,
            approval_id,
            {
                "status": "approved",
                "approved_by": user_id,
                "approved_at": datetime.utcnow(),
                "approvals_received": (approval.approvals_received or [])
                + [
                    {
                        "user_id": user_id,
                        "role": user_roles[0] if user_roles else "user",
                        "approved": True,
                        "comment": decision.comment,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ],
            },
        )

        logger.info(
            "approval_approved",
            approval_id=approval_id,
            user_id=user_id,
            tool=approval.tool_name,
        )

        # Execute the approved tool via MCP client
        try:
            mcp_client = get_mcp_client(db)

            # Extract workspace context from approval arguments
            args = approval.arguments or {}
            workspace_id = args.get("workspace_id")
            project_id = args.get("project_id")
            workspace_path = args.get("workspace_path")
            branch = args.get("branch")

            # Fallback: if workspace_id not in args, try to get from session's workspace
            # This handles backwards compatibility with approvals created before the fix
            if not workspace_id:
                workspace = db.query(Workspace).filter(
                    Workspace.session_id == approval.session_id
                ).first()
                if workspace:
                    workspace_id = workspace.id
                    project_id = project_id or workspace.project_id
                    workspace_path = workspace_path or workspace.local_path
                    branch = branch or workspace.branch
                    logger.info(
                        "workspace_context_loaded_from_session",
                        approval_id=approval_id,
                        workspace_id=workspace_id,
                        session_id=approval.session_id,
                    )

            # Validate that we have workspace context - required for tool execution
            if not workspace_id:
                logger.error(
                    "workspace_context_missing",
                    approval_id=approval_id,
                    session_id=approval.session_id,
                    tool_name=approval.tool_name,
                )
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Cannot execute tool '{approval.tool_name}': workspace context not found. "
                        f"No workspace_id in approval arguments and no workspace associated with "
                        f"session '{approval.session_id}'. The approval may have been created "
                        "before workspace tracking was implemented."
                    ),
                )

            logger.info(
                "creating_execution_context_for_approval",
                approval_id=approval_id,
                workspace_id=workspace_id,
                project_id=project_id,
                branch=branch,
            )

            context = ExecutionContext(
                session_id=approval.session_id,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                workspace_path=workspace_path,
                branch=branch,
            )

            # Execute the tool that was waiting for approval
            result = await mcp_client.execute_approved_tool(approval_id, context)

            # Resume session with the result
            try:
                resume_result = await loop.resume_session(
                    session_id=approval.session_id,
                    response=result,
                )
                return {
                    "success": True,
                    "status": "approved",
                    "session_resumed": True,
                    "tool_result": result,
                    "resume_result": resume_result,
                }
            except Exception as e:
                logger.warning("session_resume_failed", error=str(e))
                return {
                    "success": True,
                    "status": "approved",
                    "session_resumed": False,
                    "tool_result": result,
                    "resume_error": str(e),
                }

        except Exception as e:
            logger.error("approval_execution_error", error=str(e))
            # Update approval status to reflect execution failure
            crud.update_approval(
                db,
                approval_id,
                {
                    "status": "execution_failed",
                },
            )
            return {
                "success": False,
                "status": "execution_failed",
                "session_resumed": False,
                "error": str(e),
            }

    else:
        # Rejected
        crud.update_approval(
            db,
            approval_id,
            {
                "status": "rejected",
                "rejected_by": user_id,
                "rejection_reason": decision.comment,
                "approvals_received": (approval.approvals_received or [])
                + [
                    {
                        "user_id": user_id,
                        "role": user_roles[0] if user_roles else "user",
                        "approved": False,
                        "comment": decision.comment,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ],
            },
        )

        logger.info(
            "approval_rejected",
            approval_id=approval_id,
            user_id=user_id,
            reason=decision.comment,
        )

        # Update session status
        crud.update_session(
            db,
            approval.session_id,
            status="rejected",
        )

        return {
            "success": True,
            "status": "rejected",
            "session_resumed": False,
        }


# =============================================================================
# MERGE APPROVAL ROUTES
# =============================================================================


class MergeApprovalRequest(BaseModel):
    """Merge approval request body."""

    session_id: str = Field(..., description="Session ID with the feature branch to merge")
    comment: str | None = Field(None, description="Optional comment")


@router.post("/approvals/{approval_id}/merge")
async def approve_merge(
    approval_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve merge request - merges feature branch to main and rebuilds.

    This is used when a feature branch approval is accepted. It:
    1. Merges the feature branch to main
    2. Rebuilds the main branch
    3. Deploys the new main build
    """
    from druppie.core.workspace import get_workspace_service
    from druppie.core.builder import get_builder_service

    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval is not pending")

    # Check user has required role
    user_roles = user.get("realm_access", {}).get("roles", [])
    required_roles = approval.required_roles or ["admin"]

    if "admin" not in user_roles:
        if not any(r in user_roles for r in required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(required_roles)}",
            )

    # Get workspace for this session
    workspace = db.query(Workspace).filter(Workspace.session_id == approval.session_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found for session")

    if workspace.branch == "main":
        raise HTTPException(status_code=400, detail="Already on main branch, nothing to merge")

    # Mark approval as approved
    crud.update_approval(
        db,
        approval_id,
        {
            "status": "approved",
            "approvals_received": (approval.approvals_received or [])
            + [
                {
                    "user_id": user.get("sub"),
                    "role": user_roles[0] if user_roles else "user",
                    "approved": True,
                    "action": "merge",
                }
            ],
        },
    )

    try:
        # Merge feature branch to main
        workspace_service = get_workspace_service(db)
        merge_success = await workspace_service.merge_to_main(workspace)

        if not merge_success:
            raise HTTPException(status_code=500, detail="Failed to merge branch to main")

        logger.info(
            "branch_merged",
            workspace_id=workspace.id,
            branch=workspace.branch,
            project_id=workspace.project_id,
        )

        # Rebuild and deploy main branch
        builder = get_builder_service(db)
        build = await builder.build_project(workspace.project_id, "main", is_preview=False)
        build = await builder.run_project(build.id)

        logger.info(
            "main_rebuilt_after_merge",
            project_id=workspace.project_id,
            build_id=build.id,
            app_url=build.app_url,
        )

        return {
            "success": True,
            "message": "Branch merged and main rebuilt",
            "merged_branch": workspace.branch,
            "build_id": build.id,
            "app_url": build.app_url,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("merge_approval_error", approval_id=approval_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/request-merge")
async def request_merge(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request merge of feature branch to main.

    Creates an approval request for merging the session's feature branch.
    Used when work on a feature branch is complete and ready for review.
    """
    import uuid
    from datetime import datetime

    # Get workspace
    workspace = db.query(Workspace).filter(Workspace.session_id == session_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found for session")

    if workspace.branch == "main":
        raise HTTPException(status_code=400, detail="Already on main branch, no merge needed")

    # Check if there's already a pending merge request
    existing = (
        db.query(Approval)
        .filter(
            Approval.session_id == session_id,
            Approval.tool_name == "merge_to_main",
            Approval.status == "pending",
        )
        .first()
    )

    if existing:
        return {
            "success": True,
            "message": "Merge request already pending",
            "approval_id": existing.id,
        }

    # Create merge approval request
    approval_data = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "tool_name": "merge_to_main",
        "arguments": {
            "workspace_id": workspace.id,
            "project_id": workspace.project_id,
            "branch": workspace.branch,
        },
        "status": "pending",
        "required_roles": ["admin", "architect", "developer"],  # Who can approve merges
        "danger_level": "medium",
        "description": f"Merge feature branch '{workspace.branch}' to main and rebuild",
    }

    approval = crud.create_approval(db, approval_data)

    logger.info(
        "merge_requested",
        session_id=session_id,
        workspace_id=workspace.id,
        branch=workspace.branch,
        approval_id=approval.id,
    )

    return {
        "success": True,
        "message": "Merge request created",
        "approval_id": approval.id,
        "branch": workspace.branch,
    }


# =============================================================================
# HITL RESPONSE ROUTES
# =============================================================================


class HITLResponseRequest(BaseModel):
    """HITL response request body."""

    request_id: str = Field(..., description="The request ID from the question")
    answer: str = Field(..., description="User's answer text")
    selected: str | None = Field(None, description="Selected option for choice questions")


@router.post("/hitl/response")
async def submit_hitl_response(
    response: HITLResponseRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit user response to a HITL question.

    This endpoint is called by the frontend when the user answers
    a question from an agent. It forwards the response to the HITL
    MCP server via Redis.
    """
    import redis
    import json
    import os

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_client = redis.from_url(redis_url)

    try:
        # Push response to Redis (HITL MCP is waiting on this)
        redis_client.lpush(
            f"hitl:response:{response.request_id}",
            json.dumps({
                "answer": response.answer,
                "selected": response.selected,
                "user_id": user.get("sub"),
                "timestamp": datetime.utcnow().isoformat(),
            }),
        )

        logger.info(
            "hitl_response_submitted",
            request_id=response.request_id,
            user_id=user.get("sub"),
        )

        return {
            "success": True,
            "message": "Response submitted",
            "request_id": response.request_id,
        }

    except Exception as e:
        logger.error("hitl_response_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
