"""Approvals API routes.

Endpoints for managing approval requests and merge approvals.
Supports MCP microservices architecture with resume execution.
"""

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import structlog

from druppie.api.deps import get_current_user, get_db, get_loop
from druppie.api.errors import (
    APIError,
    NotFoundError,
    ValidationError,
    ConflictError,
    AuthorizationError,
    ExternalServiceError,
)
from druppie.core.loop import MainLoop
from druppie.core.mcp_client import get_mcp_client, MCPErrorType
from druppie.core.execution_context import ExecutionContext
from druppie.db import crud
from druppie.db.models import Approval, Workspace

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# ERROR TYPES FOR APPROVAL EXECUTION
# =============================================================================


class ApprovalErrorType(str, Enum):
    """Error types specific to approval execution.

    These error types help the frontend distinguish between different
    failure modes and display appropriate messages to users.
    """

    # Workspace/context errors
    WORKSPACE_MISSING = "workspace_missing"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    CONTEXT_INVALID = "context_invalid"

    # MCP/tool execution errors
    MCP_UNAVAILABLE = "mcp_unavailable"
    MCP_CONNECTION_FAILED = "mcp_connection_failed"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"

    # Argument/validation errors
    INVALID_ARGUMENTS = "invalid_arguments"
    MISSING_REQUIRED_ARGS = "missing_required_args"

    # Session/resume errors
    SESSION_RESUME_FAILED = "session_resume_failed"
    SESSION_NOT_FOUND = "session_not_found"

    # General errors
    UNKNOWN_ERROR = "unknown_error"


def classify_approval_error(
    error: Exception,
    tool_name: str | None = None,
    server: str | None = None,
) -> tuple[ApprovalErrorType, bool, str]:
    """Classify an error that occurred during approval execution.

    Args:
        error: The exception that occurred
        tool_name: Name of the tool being executed (for context)
        server: MCP server name (for context)

    Returns:
        Tuple of (error_type, is_retryable, user_message)
    """
    error_str = str(error).lower()

    # Workspace-related errors
    workspace_indicators = [
        "workspace context not found",
        "workspace_id",
        "no workspace",
        "workspace not found",
    ]
    for indicator in workspace_indicators:
        if indicator in error_str:
            return (
                ApprovalErrorType.WORKSPACE_MISSING,
                False,
                "Workspace context is missing. The session may need to be restarted.",
            )

    # MCP connection errors (potentially retryable)
    connection_indicators = [
        "connection refused",
        "connection reset",
        "connection error",
        "timeout",
        "timed out",
        "service unavailable",
        "503",
        "502",
        "504",
        "econnrefused",
        "econnreset",
        "etimedout",
    ]
    for indicator in connection_indicators:
        if indicator in error_str:
            server_info = f" ({server})" if server else ""
            return (
                ApprovalErrorType.MCP_CONNECTION_FAILED,
                True,
                f"Could not connect to MCP server{server_info}. The service may be temporarily unavailable.",
            )

    # MCP unavailable
    if "mcp" in error_str and ("unavailable" in error_str or "not running" in error_str):
        return (
            ApprovalErrorType.MCP_UNAVAILABLE,
            True,
            "The MCP service is not available. Please try again later.",
        )

    # Tool not found
    tool_not_found_indicators = [
        "tool not found",
        "method not found",
        "unknown tool",
        "no such tool",
    ]
    for indicator in tool_not_found_indicators:
        if indicator in error_str:
            tool_info = f" '{tool_name}'" if tool_name else ""
            return (
                ApprovalErrorType.TOOL_NOT_FOUND,
                False,
                f"The requested tool{tool_info} was not found. It may have been removed or renamed.",
            )

    # Invalid arguments
    arg_indicators = [
        "invalid argument",
        "missing required",
        "validation error",
        "required field",
        "missing field",
        "argument must be",
        "parameter must be",
        "expected type",
    ]
    for indicator in arg_indicators:
        if indicator in error_str:
            return (
                ApprovalErrorType.INVALID_ARGUMENTS,
                False,
                "The tool arguments are invalid. This may be a bug in the request.",
            )

    # Session errors
    if "session" in error_str and ("not found" in error_str or "missing" in error_str):
        return (
            ApprovalErrorType.SESSION_NOT_FOUND,
            False,
            "The session was not found. It may have expired or been deleted.",
        )

    # Check if it's a known exception type
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return (
            ApprovalErrorType.MCP_CONNECTION_FAILED,
            True,
            "A connection error occurred. Please try again.",
        )

    if isinstance(error, (ValueError, TypeError)):
        return (
            ApprovalErrorType.INVALID_ARGUMENTS,
            False,
            f"Invalid data provided: {str(error)}",
        )

    if isinstance(error, KeyError):
        return (
            ApprovalErrorType.MISSING_REQUIRED_ARGS,
            False,
            f"A required field is missing: {str(error)}",
        )

    # Default to tool execution failed for unknown errors
    return (
        ApprovalErrorType.TOOL_EXECUTION_FAILED,
        False,
        f"Tool execution failed: {str(error)}",
    )


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
    agent_id: str | None
    created_at: str | None


class ApprovalListResponse(BaseModel):
    """List of approvals response."""

    approvals: list[ApprovalResponse]
    total: int
    page: int
    limit: int


class ApprovalDecision(BaseModel):
    """Approval decision request."""

    approved: bool = Field(..., description="Whether to approve or reject")
    comment: str | None = Field(
        None,
        max_length=2000,
        description="Optional comment (max 2000 characters)",
    )


# =============================================================================
# ROUTES
# =============================================================================


# Maximum limit for pagination to prevent excessive queries
MAX_LIMIT = 100


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    session_id: str | None = None,
    status: str = "pending",
    page: int = 1,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List approval requests with pagination.

    By default, shows pending approvals that the user can approve.

    Args:
        session_id: Optional filter by session ID
        status: Filter by status (default: pending)
        page: Page number (1-indexed, default: 1)
        limit: Number of items per page (default: 20, max: 100)
        user: Current authenticated user
        db: Database session

    Returns:
        ApprovalListResponse with approvals, total count, page, and limit
    """
    # Validate and enforce pagination limits
    if page < 1:
        page = 1
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    user_roles = user.get("realm_access", {}).get("roles", [])
    is_admin = "admin" in user_roles

    # Build base query with filters
    query = db.query(Approval)

    if status == "pending":
        query = query.filter(Approval.status == "pending")
    elif status:
        query = query.filter(Approval.status == status)

    if session_id:
        query = query.filter(Approval.session_id == session_id)

    # Order by creation date (newest first)
    query = query.order_by(Approval.created_at.desc())

    # Optimization: Admin can approve anything, skip filtering
    if is_admin:
        total = query.count()
        offset = (page - 1) * limit
        paginated = query.offset(offset).limit(limit).all()
    else:
        # For non-admin users, we need to filter by role
        # Use streaming to avoid loading all into memory at once
        # Fetch in batches to find approvals user can act on
        BATCH_SIZE = 500
        filtered = []
        total_scanned = 0
        offset = (page - 1) * limit
        target_count = offset + limit  # We need at least this many matching records

        # Stream through results in batches
        batch_offset = 0
        while True:
            batch = query.offset(batch_offset).limit(BATCH_SIZE).all()
            if not batch:
                break

            for a in batch:
                # Security policy: If no required_roles, default to admin only
                required_roles = a.required_roles if a.required_roles else ["admin"]
                if any(r in user_roles for r in required_roles):
                    filtered.append(a)
                    # Stop early if we have enough for this page plus some buffer
                    if len(filtered) >= target_count + BATCH_SIZE:
                        break

            batch_offset += BATCH_SIZE

            # Stop if we have enough records or exhausted the query
            if len(batch) < BATCH_SIZE:
                break

        total = len(filtered)
        paginated = filtered[offset : offset + limit]

    # Build response
    approvals_response = [
        ApprovalResponse(
            id=a.id,
            session_id=a.session_id,
            tool_name=a.tool_name,
            arguments=a.arguments,
            status=a.status,
            required_roles=a.required_roles,
            approvals_received=a.approvals_received,
            danger_level=a.danger_level,
            description=a.description,
            agent_id=a.agent_id,
            created_at=a.created_at.isoformat() if a.created_at else None,
        )
        for a in paginated
    ]

    return ApprovalListResponse(
        approvals=approvals_response,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific approval request."""
    approval = crud.get_approval(db, approval_id)
    if not approval:
        raise NotFoundError("approval", approval_id)

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
        agent_id=approval.agent_id,
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
        raise NotFoundError("approval", approval_id)

    if approval.status != "pending":
        raise ConflictError(f"Approval {approval_id} is not pending (status: {approval.status})")

    user_roles = user.get("realm_access", {}).get("roles", [])
    # Security policy: If no required_roles are specified, default to requiring "admin" role.
    # This prevents approvals without explicit role requirements from being approvable by anyone.
    required_roles = approval.required_roles if approval.required_roles else ["admin"]

    # Check authorization - admin can approve anything, otherwise need a required role
    if "admin" not in user_roles:
        if not any(r in user_roles for r in required_roles):
            raise AuthorizationError(
                f"Requires one of roles: {', '.join(required_roles)}",
                required_roles=required_roles,
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
                    args_keys=list(args.keys()),
                    error_type=ApprovalErrorType.WORKSPACE_MISSING.value,
                )
                # Update approval with error details
                crud.update_approval(
                    db,
                    approval_id,
                    {"status": "execution_failed"},
                )
                return {
                    "success": False,
                    "status": "execution_failed",
                    "session_resumed": False,
                    "error_type": ApprovalErrorType.WORKSPACE_MISSING.value,
                    "error": (
                        f"Cannot execute tool '{approval.tool_name}': workspace context not found. "
                        f"No workspace_id in approval arguments and no workspace associated with "
                        f"session '{approval.session_id}'."
                    ),
                    "user_message": "Workspace context is missing. The session may need to be restarted.",
                    "retryable": False,
                }

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

            # Check if tool execution itself failed
            if not result.get("success", True):
                # Tool executed but returned an error
                mcp_error_type = result.get("error_type", MCPErrorType.FATAL)
                error_msg = result.get("error", "Unknown tool error")
                is_retryable = result.get("retryable", False)

                logger.warning(
                    "tool_execution_returned_error",
                    approval_id=approval_id,
                    tool_name=approval.tool_name,
                    mcp_error_type=mcp_error_type,
                    error=error_msg,
                    retryable=is_retryable,
                )

                # Map MCP error type to approval error type
                if mcp_error_type == MCPErrorType.TRANSIENT:
                    approval_error = ApprovalErrorType.MCP_CONNECTION_FAILED
                elif mcp_error_type == MCPErrorType.VALIDATION:
                    approval_error = ApprovalErrorType.INVALID_ARGUMENTS
                elif mcp_error_type == MCPErrorType.PERMISSION:
                    approval_error = ApprovalErrorType.TOOL_EXECUTION_FAILED
                else:
                    approval_error = ApprovalErrorType.TOOL_EXECUTION_FAILED

                crud.update_approval(
                    db,
                    approval_id,
                    {"status": "execution_failed"},
                )
                return {
                    "success": False,
                    "status": "execution_failed",
                    "session_resumed": False,
                    "error_type": approval_error.value,
                    "error": error_msg,
                    "user_message": f"Tool '{approval.tool_name}' failed: {error_msg}",
                    "retryable": is_retryable,
                    "tool_result": result,
                }

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
                # Classify the session resume error
                error_type, is_retryable, user_message = classify_approval_error(
                    e, tool_name=approval.tool_name
                )
                logger.warning(
                    "session_resume_failed",
                    approval_id=approval_id,
                    session_id=approval.session_id,
                    error=str(e),
                    error_type=ApprovalErrorType.SESSION_RESUME_FAILED.value,
                    original_error_class=type(e).__name__,
                )
                return {
                    "success": True,  # Tool succeeded, but resume failed
                    "status": "approved",
                    "session_resumed": False,
                    "tool_result": result,
                    "error_type": ApprovalErrorType.SESSION_RESUME_FAILED.value,
                    "resume_error": str(e),
                    "user_message": "Tool executed successfully but session could not be resumed.",
                    "retryable": False,
                }

        except APIError:
            # Re-raise API errors as-is
            raise
        except Exception as e:
            # Parse server from tool_name for error context
            server = None
            if approval.tool_name and ":" in approval.tool_name:
                server = approval.tool_name.split(":")[0]

            # Classify the error
            error_type, is_retryable, user_message = classify_approval_error(
                e, tool_name=approval.tool_name, server=server
            )

            # Log with full context
            logger.error(
                "approval_execution_error",
                approval_id=approval_id,
                session_id=approval.session_id,
                tool_name=approval.tool_name,
                server=server,
                workspace_id=workspace_id if "workspace_id" in dir() else None,
                project_id=project_id if "project_id" in dir() else None,
                error=str(e),
                error_type=error_type.value,
                error_class=type(e).__name__,
                retryable=is_retryable,
                exc_info=True,
            )

            # Update approval status to reflect execution failure
            crud.update_approval(
                db,
                approval_id,
                {"status": "execution_failed"},
            )
            return {
                "success": False,
                "status": "execution_failed",
                "session_resumed": False,
                "error_type": error_type.value,
                "error": str(e),
                "user_message": user_message,
                "retryable": is_retryable,
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
    comment: str | None = Field(
        None,
        max_length=2000,
        description="Optional comment (max 2000 characters)",
    )


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
        raise NotFoundError("approval", approval_id)

    if approval.status != "pending":
        raise ConflictError(f"Approval {approval_id} is not pending (status: {approval.status})")

    # Check user has required role
    user_roles = user.get("realm_access", {}).get("roles", [])
    required_roles = approval.required_roles or ["admin"]

    if "admin" not in user_roles:
        if not any(r in user_roles for r in required_roles):
            raise AuthorizationError(
                f"Requires one of roles: {', '.join(required_roles)}",
                required_roles=required_roles,
            )

    # Get workspace for this session
    workspace = db.query(Workspace).filter(Workspace.session_id == approval.session_id).first()
    if not workspace:
        raise NotFoundError("workspace", approval.session_id, "Workspace not found for session")

    if workspace.branch == "main":
        raise ValidationError("Already on main branch, nothing to merge", field="branch")

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
            raise ExternalServiceError("git", "Failed to merge branch to main")

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

    except (NotFoundError, ValidationError, ConflictError, AuthorizationError, ExternalServiceError):
        raise
    except Exception as e:
        logger.error("merge_approval_error", approval_id=approval_id, error=str(e), exc_info=True)
        raise ExternalServiceError("merge", f"Merge operation failed: {str(e)}")


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
        raise NotFoundError("workspace", session_id, "Workspace not found for session")

    if workspace.branch == "main":
        raise ValidationError("Already on main branch, no merge needed", field="branch")

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
    answer: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User's answer text (1-10000 characters)",
    )
    selected: str | None = Field(
        None,
        max_length=500,
        description="Selected option for choice questions",
    )


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

    # Establish Redis connection with error handling
    try:
        redis_client = redis.from_url(redis_url, socket_connect_timeout=5)
        # Test connection before proceeding
        redis_client.ping()
    except redis.ConnectionError as e:
        logger.error(
            "redis_connection_failed",
            error=str(e),
            redis_url=redis_url.split("@")[-1],  # Log URL without credentials
            exc_info=True,
        )
        raise ExternalServiceError(
            "redis",
            "Unable to connect to Redis. The service may be temporarily unavailable.",
        )
    except redis.TimeoutError as e:
        logger.error("redis_timeout", error=str(e), exc_info=True)
        raise ExternalServiceError(
            "redis",
            "Redis connection timed out. Please try again.",
        )

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

    except redis.RedisError as e:
        logger.error(
            "hitl_response_redis_error",
            error=str(e),
            request_id=response.request_id,
            exc_info=True,
        )
        raise ExternalServiceError(
            "redis",
            "Failed to submit response to Redis. Please try again.",
        )
    except Exception as e:
        logger.error("hitl_response_error", error=str(e), exc_info=True)
        raise ExternalServiceError("hitl", f"Failed to process HITL response: {str(e)}")
