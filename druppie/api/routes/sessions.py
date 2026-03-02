"""Sessions API routes.

Clean architecture version - routes are thin and delegate to services.

Routes handle:
- HTTP request/response
- Authentication extraction
- Calling services

Services handle:
- Permission checks
- Business logic
- Calling repositories

This file went from 776 lines to ~80 lines by moving logic to services/repositories.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from uuid import UUID
import structlog

from druppie.api.deps import (
    get_current_user,
    get_user_roles,
    get_session_service,
)
from druppie.services import SessionService
from druppie.domain import SessionDetail
from druppie.domain.common import SessionStatus
from druppie.core.background_tasks import create_session_task, SessionTaskConflict, run_session_task

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/sessions")
async def list_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """List sessions for current user.

    Returns paginated list of session summaries for the sidebar/listing.
    Admins can see all sessions; regular users only see their own.

    Query Parameters:
        page: Page number (default 1)
        limit: Items per page (default 20, max 100)
        status: Optional status filter (active, completed, failed, etc.)

    Returns:
        Paginated list of SessionSummary objects
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Admin can see all sessions
    if "admin" in user_roles:
        user_id = None  # Don't filter by user

    sessions, total = service.list_for_user(
        user_id=user_id,
        page=page,
        limit=limit,
        status=status,
    )

    return {
        "items": sessions,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
) -> SessionDetail:
    """Get complete session detail with chat timeline.

    Returns the full session including:
    - Basic session info (title, status, token usage)
    - Project info if associated
    - Chat timeline with messages and agent runs

    The chat timeline is a chronological list of:
    - system_message: Initial system prompt
    - user_message: User inputs
    - agent_run: Agent executions with LLM calls and tool executions
    - assistant_message: Final agent responses

    Authorization:
    - Session owner can view
    - Admins can view any session
    - Users with pending approvals for this session can view

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User cannot access this session
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    detail = service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    logger.info("session_retrieved", session_id=str(session_id), user_id=str(user_id))
    return detail


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Delete a session and all related data.

    Only the session owner or an admin can delete a session.
    This cascades to delete all related data:
    - Messages
    - Agent runs
    - Tool calls
    - LLM calls
    - Approvals
    - HITL questions

    Returns:
        Success confirmation

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User cannot delete this session
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    service.delete(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    logger.info("session_deleted", session_id=str(session_id), user_id=str(user_id))
    return {"success": True, "message": "Session deleted"}


# =============================================================================
# RETRY FROM RUN
# =============================================================================


class RetryRequest(BaseModel):
    """Optional body for retry endpoint."""
    planned_prompt: str | None = None


async def _run_retry_background(
    session_id: UUID,
    agent_run_id: UUID,
    planned_prompt: str | None = None,
) -> None:
    """Revert and re-execute from a specific agent run."""

    async def task(ctx):
        from druppie.core.mcp_config import get_mcp_config
        from druppie.execution.mcp_http import MCPHttp
        from druppie.services import RevertService

        # Step 1: Revert (delete old runs, revert git, recreate as pending)
        mcp_http = MCPHttp(get_mcp_config())
        revert_service = RevertService(ctx.execution_repo, ctx.session_repo, mcp_http)
        result = await revert_service.retry_from_run(
            session_id, agent_run_id, planned_prompt=planned_prompt,
        )

        logger.info("retry_revert_complete", session_id=str(session_id), result=result)

        for warning in result.get("warnings", []):
            logger.warning("retry_revert_warning", session_id=str(session_id), warning=warning)

        # Check if session was cancelled during the revert phase
        ctx.db.expire_all()
        session = ctx.session_repo.get_by_id(session_id)
        if session and session.status == SessionStatus.CANCELLED.value:
            logger.info("retry_cancelled_after_revert", session_id=str(session_id))
            ctx.execution_repo.cancel_pending_runs(session_id)
            ctx.db.commit()
            return

        # Step 2: Execute pending runs (the recreated ones)
        await ctx.orchestrator.execute_pending_runs(session_id)

    await run_session_task(session_id, task, "retry_background")


@router.post("/sessions/{session_id}/retry-from/{agent_run_id}")
async def retry_from_run(
    session_id: UUID,
    agent_run_id: UUID,
    body: RetryRequest | None = Body(None),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Retry a session from a specific agent run.

    Reverts the target agent run and all subsequent runs, then re-executes
    them with the same planned prompts. Works for any agent run status.

    This endpoint:
    1. Validates session ownership and status (must not be active)
    2. Sets session to active immediately
    3. Spawns background task to revert + re-execute
    4. Returns immediately

    Args:
        session_id: Session to retry
        agent_run_id: Agent run to retry from (this run and all after it)

    Returns:
        Success response with session_id
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Validate session exists and user has access (raises on failure)
    service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Reject if a background task is already running for this session.
    # Must check BEFORE lock_for_retry (which changes DB status to active).
    from druppie.core.background_tasks import is_session_task_running
    if is_session_task_running(session_id):
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )

    # Atomically lock and transition session to ACTIVE
    try:
        service.lock_for_retry(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "retry_from_run_requested",
        session_id=str(session_id),
        agent_run_id=str(agent_run_id),
        user_id=str(user_id),
    )

    # Spawn background task
    create_session_task(
        session_id,
        _run_retry_background(
            session_id=session_id,
            agent_run_id=agent_run_id,
            planned_prompt=body.planned_prompt if body else None,
        ),
        name=f"retry-{session_id}",
    )

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Retry started",
    }


# =============================================================================
# RESUME PAUSED SESSION
# =============================================================================


async def _run_resume_background(session_id: UUID) -> None:
    """Resume a paused session in background."""

    async def task(ctx):
        await ctx.orchestrator.resume_paused_session(session_id)

    await run_session_task(session_id, task, "resume_background")


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Resume a paused session.

    Spawns a background task that continues the paused agent run
    and then executes remaining pending runs.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Validate session exists and user has access
    service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    # Reject if a background task is already running for this session.
    # Must check BEFORE lock_for_resume (which changes DB status to active).
    from druppie.core.background_tasks import is_session_task_running
    if is_session_task_running(session_id):
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )

    # Atomically lock and transition session to ACTIVE
    try:
        service.lock_for_resume(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        "resume_session_requested",
        session_id=str(session_id),
        user_id=str(user_id),
    )

    # Spawn background task
    create_session_task(
        session_id,
        _run_resume_background(session_id=session_id),
        name=f"resume-{session_id}",
    )

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session resuming",
    }
