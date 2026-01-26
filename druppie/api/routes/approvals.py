"""Approvals API routes.

Endpoints for managing approval requests and merge approvals.
Supports MCP microservices architecture with resume execution.
"""

from datetime import datetime, timezone
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
from druppie.api.websocket import emit_approval_decision
from druppie.api.routes.chat import create_emit_event
from druppie.core.loop import MainLoop
from druppie.core.mcp_client import get_mcp_client, MCPErrorType
from druppie.core.execution_context import ExecutionContext
from druppie.db import crud
from druppie.db.models import Approval, Workspace, Build

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _create_build_record_from_docker_run(
    db: Session,
    tool_result: dict,
    approval_args: dict,
    session_id: str,
) -> Build | None:
    """Create a Build record when docker:run succeeds.

    This allows the Running Apps dashboard to track containers started via MCP.

    Args:
        db: Database session
        tool_result: Result from docker:run MCP call
        approval_args: Original approval arguments
        session_id: Session ID for linking

    Returns:
        Created Build instance or None if project_id not found
    """
    import uuid

    # Extract info from the tool result
    container_name = tool_result.get("container_name")
    port = tool_result.get("port")
    app_url = tool_result.get("url")

    # Get project_id from approval arguments
    project_id = approval_args.get("project_id")
    if not project_id:
        # Try to get from session's workspace
        workspace = db.query(Workspace).filter(
            Workspace.session_id == session_id
        ).first()
        if workspace:
            project_id = workspace.project_id

    if not project_id:
        logger.warning(
            "cannot_create_build_record_no_project",
            session_id=session_id,
            container_name=container_name,
        )
        return None

    # Check if a build record already exists for this container
    existing = db.query(Build).filter(
        Build.container_name == container_name,
        Build.status == "running",
    ).first()

    if existing:
        # Update existing record
        existing.port = port
        existing.app_url = app_url
        existing.status = "running"
        db.commit()
        logger.info(
            "build_record_updated",
            build_id=existing.id,
            container_name=container_name,
        )
        return existing

    # Create new build record
    build_id = str(uuid.uuid4())
    build = Build(
        id=build_id,
        project_id=project_id,
        branch="main",  # Default to main
        status="running",
        container_name=container_name,
        port=port,
        app_url=app_url,
        is_preview=False,
    )
    db.add(build)
    db.commit()

    logger.info(
        "build_record_created",
        build_id=build_id,
        project_id=project_id,
        container_name=container_name,
        app_url=app_url,
    )
    return build


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
    session_id: str | None  # May be None for some approvals
    tool_name: str | None  # May be None for step approvals
    arguments: dict | None
    status: str
    required_roles: list[str] | None
    approvals_received: list[str] | None  # List of user IDs who approved
    danger_level: str | None  # May be None for step approvals
    description: str | None
    agent_id: str | None
    created_at: str | None
    # Approval decision info (for history)
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None


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
            id=str(a.id),
            session_id=str(a.session_id) if a.session_id else None,
            tool_name=a.tool_name,
            arguments=a.arguments,
            status=a.status,
            required_roles=a.required_roles,
            approvals_received=a.approvals_received,
            danger_level=a.danger_level,
            description=a.description,
            agent_id=a.agent_id,
            created_at=a.created_at.isoformat() if a.created_at else None,
            # History fields
            approved_by=a.approved_by,
            approved_at=a.approved_at.isoformat() if a.approved_at else None,
            rejected_by=a.rejected_by,
            rejection_reason=a.rejection_reason,
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
    username = user.get("preferred_username") or user.get("username") or user.get("name") or "User"
    approver_role = next(iter(user_roles), "user")

    if decision.approved:
        # Update approval status to approved
        # Note: Use actual column names (resolved_by, resolved_at), not property names
        crud.update_approval(
            db,
            approval_id,
            {
                "status": "approved",
                "resolved_by": user_id,
                "resolved_at": datetime.now(timezone.utc),
            },
        )

        logger.info(
            "approval_approved",
            approval_id=approval_id,
            user_id=user_id,
            username=username,
            tool=approval.tool_name,
        )

        # Save approval message to database for history
        approval_message = f"✅ **{username}** ({approver_role}) approved: `{approval.tool_name}`"
        crud.create_message(
            db=db,
            session_id=approval.session_id,
            role="system",
            content=approval_message,
            agent_id="system",
            tool_name=approval.tool_name,
        )

        # Broadcast approval decision to WebSocket subscribers
        await emit_approval_decision(
            approval_id=approval_id,
            session_id=str(approval.session_id),  # Convert UUID to string for JSON serialization
            approved=True,
            approver_id=user_id,
            approver_role=approver_role,
            approver_username=username,
            tool_name=approval.tool_name,
            agent_id=approval.agent_id,  # Include which agent executed the tool
        )

        # Check if this is a step approval checkpoint (vs MCP tool approval)
        # Step approvals have approval_type="workflow_step" or tool_name like "approval:step_2"
        is_step_approval = (
            approval.approval_type == "workflow_step"
            or (approval.tool_name and approval.tool_name.startswith("approval:"))
        )
        if is_step_approval:
            # This is a workflow step approval checkpoint - resume plan execution from next step
            logger.info(
                "resuming_from_workflow_step_approval",
                approval_id=approval_id,
                approval_type=approval.approval_type,
                tool_name=approval.tool_name,
                session_id=approval.session_id,
            )

            try:
                # Create emit callback for WebSocket updates
                emit_event = create_emit_event(str(approval.session_id))

                # Get the saved agent_state from the approval (if any)
                agent_state = approval.agent_state

                if agent_state:
                    # If we have agent_state, use resume_from_step_approval
                    # This handles mid-agent pauses with saved context
                    resume_result = await loop.resume_from_step_approval(
                        session_id=str(approval.session_id),
                        agent_state=agent_state,
                        emit_event=emit_event,
                    )
                else:
                    # No agent_state - this is a pure workflow checkpoint
                    # Use resume_from_approval to continue from next step
                    resume_result = await loop.resume_from_approval(
                        session_id=str(approval.session_id),
                        approval_id=approval_id,
                        emit_event=emit_event,
                    )

                return {
                    "success": True,
                    "status": "approved",
                    "session_resumed": True,
                    "resume_result": resume_result,
                }

            except Exception as e:
                logger.error(
                    "step_approval_resume_error",
                    approval_id=approval_id,
                    error=str(e),
                    exc_info=True,
                )
                return {
                    "success": False,
                    "status": "execution_failed",
                    "error_type": ApprovalErrorType.SESSION_RESUME_FAILED.value,
                    "error": str(e),
                    "user_message": f"Failed to resume execution: {str(e)}",
                    "retryable": False,
                }

        # This is an MCP tool approval - execute the approved tool
        # Check if we have saved agent state for resumption
        agent_state = approval.agent_state

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

            # Create Build record if docker:run succeeded (for Running Apps tracking)
            if approval.tool_name == "docker:run" and result.get("success", True):
                _create_build_record_from_docker_run(
                    db=db,
                    tool_result=result,
                    approval_args=args,
                    session_id=approval.session_id,
                )

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
            # If we have agent_state, use resume_from_step_approval to continue the plan
            # This handles MCP tool approvals mid-agent execution properly
            try:
                if agent_state and isinstance(agent_state, dict):
                    # Store the tool result in the context so the agent can use it
                    # when we re-run the current step
                    agent_state_with_result = dict(agent_state)
                    agent_state_with_result["last_tool_result"] = {
                        "tool": approval.tool_name,
                        "result": result,
                        "approval_id": approval_id,
                    }

                    logger.info(
                        "resuming_mcp_tool_approval_with_state",
                        approval_id=approval_id,
                        session_id=approval.session_id,
                        current_step=agent_state.get("current_step"),
                        agent_id=agent_state.get("agent_id"),
                    )

                    # Create emit callback for WebSocket updates
                    emit_event = create_emit_event(str(approval.session_id))

                    resume_result = await loop.resume_from_step_approval(
                        session_id=str(approval.session_id),
                        agent_state=agent_state_with_result,
                        emit_event=emit_event,
                    )
                else:
                    # Fallback to old behavior if no agent_state
                    logger.warning(
                        "mcp_tool_approval_no_agent_state",
                        approval_id=approval_id,
                        session_id=approval.session_id,
                    )
                    # Create emit callback for WebSocket updates
                    emit_event = create_emit_event(str(approval.session_id))

                    resume_result = await loop.resume_session(
                        session_id=str(approval.session_id),
                        response=result,
                        emit_event=emit_event,
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
        # Note: Use actual column names (resolved_by, resolved_at, rejection_reason)
        crud.update_approval(
            db,
            approval_id,
            {
                "status": "rejected",
                "resolved_by": user_id,
                "resolved_at": datetime.now(timezone.utc),
                "rejection_reason": decision.comment,
            },
        )

        logger.info(
            "approval_rejected",
            approval_id=approval_id,
            user_id=user_id,
            username=username,
            reason=decision.comment,
        )

        # Save rejection message to database for history
        reason_text = f": {decision.comment}" if decision.comment else ""
        rejection_message = f"🚫 **{username}** ({approver_role}) rejected: `{approval.tool_name}`{reason_text}"
        crud.create_message(
            db=db,
            session_id=approval.session_id,
            role="system",
            content=rejection_message,
            agent_id="system",
            tool_name=approval.tool_name,
        )

        # Broadcast rejection decision to WebSocket subscribers
        await emit_approval_decision(
            approval_id=approval_id,
            session_id=str(approval.session_id),  # Convert UUID to string for JSON serialization
            approved=False,
            approver_id=user_id,
            approver_role=approver_role,
            approver_username=username,
            tool_name=approval.tool_name,
            agent_id=approval.agent_id,  # Include which agent executed the tool
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
    # Note: Use actual column names (resolved_by, resolved_at)
    crud.update_approval(
        db,
        approval_id,
        {
            "status": "approved",
            "resolved_by": user.get("sub"),
            "resolved_at": datetime.now(timezone.utc),
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
# NOTE: HITL RESPONSE ROUTES REMOVED
# =============================================================================
# HITL questions are now handled by the built-in HITL tools in agents/hitl.py
# and the /api/questions/{id}/answer endpoint in routes/questions.py
# Redis is no longer needed for HITL - questions are stored in the database


# =============================================================================
# USERS BY ROLE ENDPOINT
# =============================================================================


class UserContact(BaseModel):
    """User contact information for approval coordination."""

    id: str
    username: str
    email: str | None
    display_name: str | None


class UsersByRoleResponse(BaseModel):
    """Response with users who have the specified role."""

    role: str
    users: list[UserContact]


@router.get("/approvals/users-by-role/{role}", response_model=UsersByRoleResponse)
async def get_users_by_role(
    role: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UsersByRoleResponse:
    """Get users who have a specific role.

    Queries Keycloak Admin API to get users with the specified role.
    Falls back to local database if Keycloak is unavailable.

    Args:
        role: The role to search for (e.g., 'architect', 'developer', 'admin')

    Returns:
        List of users with contact information who have the specified role
    """
    import httpx
    import os

    keycloak_url = os.getenv("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
    realm = os.getenv("KEYCLOAK_REALM", "druppie")
    admin_user = os.getenv("KEYCLOAK_ADMIN", "admin")
    admin_password = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")

    users_list = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get admin token
            token_response = await client.post(
                f"{keycloak_url}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": admin_user,
                    "password": admin_password,
                },
            )
            if token_response.status_code != 200:
                logger.warning("keycloak_admin_auth_failed", status=token_response.status_code)
                raise Exception("Failed to get admin token")

            admin_token = token_response.json().get("access_token")

            # Get users with the specified role
            # First get the role ID
            role_response = await client.get(
                f"{keycloak_url}/admin/realms/{realm}/roles/{role}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if role_response.status_code != 200:
                logger.warning("keycloak_role_not_found", role=role, status=role_response.status_code)
                # Role doesn't exist, return empty list
                return UsersByRoleResponse(role=role, users=[])

            # Get users with this role
            users_response = await client.get(
                f"{keycloak_url}/admin/realms/{realm}/roles/{role}/users",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if users_response.status_code == 200:
                keycloak_users = users_response.json()
                for ku in keycloak_users:
                    users_list.append(UserContact(
                        id=ku.get("id", ""),
                        username=ku.get("username", ""),
                        email=ku.get("email"),
                        display_name=f"{ku.get('firstName', '')} {ku.get('lastName', '')}".strip() or ku.get("username"),
                    ))
                logger.info("keycloak_users_fetched", role=role, count=len(users_list))
            else:
                logger.warning("keycloak_users_fetch_failed", role=role, status=users_response.status_code)

    except Exception as e:
        logger.warning("keycloak_query_failed", error=str(e), role=role)
        # Fall back to local database
        local_users = crud.get_users_by_role(db, role)
        users_list = [
            UserContact(
                id=str(u.id),
                username=u.username,
                email=u.email,
                display_name=u.display_name,
            )
            for u in local_users
        ]

    return UsersByRoleResponse(role=role, users=users_list)
