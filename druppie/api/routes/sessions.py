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
    get_bearer_token,
    get_current_user,
    get_user_roles,
    get_session_service,
)
from druppie.services import SessionService
from druppie.domain import SessionDetail
from druppie.core.background_tasks import create_session_task, run_session_task, SessionTaskConflict

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


class DeleteSessionsRequest(BaseModel):
    """Body for session deletion."""
    session_ids: list[UUID] | None = None


@router.delete("/sessions")
async def delete_sessions(
    body: DeleteSessionsRequest | None = Body(None),
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Delete sessions.

    Unified endpoint for single and batch deletion:
    - If session_ids is provided, deletes those specific sessions.
    - If session_ids is omitted/null, deletes all sessions for the user (admins: all sessions).

    Returns:
        Success confirmation with count of deleted sessions
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    if body and body.session_ids is not None:
        count = service.delete_many(body.session_ids, user_id, user_roles)
    else:
        if "admin" in user_roles:
            user_id = None
        count = service.delete_all_for_user(user_id)

    logger.info("sessions_deleted", user_id=str(user["sub"]), count=count)
    return {"success": True, "deleted_count": count}


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

        # Step 2: Execute pending runs (the recreated ones)
        # If user paused during revert, execute_pending_runs detects PAUSED and returns
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

    # skip_lock=True: lock_for_retry already atomically set status to ACTIVE.
    # The DB lock there prevents concurrent retries.
    try:
        create_session_task(
            session_id,
            _run_retry_background(
                session_id=session_id,
                agent_run_id=agent_run_id,
                planned_prompt=body.planned_prompt if body else None,
            ),
            name=f"retry-{session_id}",
            skip_lock=True,
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start retry background task")
        raise

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

    # skip_lock=True: lock_for_resume already atomically set status to ACTIVE.
    try:
        create_session_task(
            session_id,
            _run_resume_background(session_id=session_id),
            name=f"resume-{session_id}",
            skip_lock=True,
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start resume background task")
        raise

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session resuming",
    }


# =============================================================================
# ENTRA ID AUTHORIZATION
# =============================================================================


async def _run_entra_auth_background(session_id: UUID, user_kc_token: str) -> None:
    """Resume workflow after Entra auth in background."""

    async def task(ctx):
        await ctx.orchestrator.resume_after_entra_auth(
            session_id=session_id,
            user_kc_token=user_kc_token,
        )

    await run_session_task(session_id, task, "resume_after_entra_auth")


@router.post("/sessions/{session_id}/authorize-entra")
async def authorize_entra(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
    bearer_token: str = Depends(get_bearer_token),
):
    """Provide Entra ID authorization for a paused session.

    Called automatically by the frontend when it detects a session in
    waiting_entra_auth status. The backend uses the caller's KC token
    to retrieve an Entra ID token via the Keycloak broker endpoint.

    Security: Only the session owner can authorize (no admin override).
    This prevents a different user's Entra token from being used.
    """
    user_id = UUID(user["sub"])

    # H1: Enforce session owner — no admin override
    detail = service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=get_user_roles(user),
    )
    if str(detail.user_id) != str(user_id):
        raise HTTPException(
            status_code=403,
            detail="Only the session owner can authorize Entra ID access",
        )

    # Verify session is in the right state
    if detail.status != "paused_entra_auth":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not waiting for Entra authorization (status: {detail.status})",
        )

    logger.info(
        "authorize_entra_requested",
        session_id=str(session_id),
        user_id=str(user_id),
    )

    # Pre-check: verify the Keycloak broker can return an Entra token.
    # If the user's KC session didn't go through the Entra broker (e.g.
    # after a session refresh), the stored token won't be available and
    # the user must re-authenticate via Entra.
    from druppie.core.entra_token import get_entra_token

    token_result = await get_entra_token(bearer_token)
    if token_result.get("needs_reauth"):
        return {
            "success": False,
            "needs_reauth": True,
            "message": token_result.get("error", "Please sign in with Microsoft again."),
        }

    # Fetch user avatar from Graph API (fire-and-forget, non-blocking)
    graph_token = token_result.get("access_token")
    if graph_token:
        import asyncio
        from druppie.services.avatar_service import fetch_and_cache_avatar
        asyncio.create_task(fetch_and_cache_avatar(str(user_id), graph_token))

    # Transition session to active
    try:
        service.lock_for_resume(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    try:
        create_session_task(
            session_id,
            _run_entra_auth_background(
                session_id=session_id,
                user_kc_token=bearer_token,
            ),
            name=f"entra-auth-{session_id}",
            skip_lock=True,
        )
    except SessionTaskConflict:
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )
    except Exception:
        service.mark_failed(session_id, "Failed to start Entra auth background task")
        raise

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Entra ID authorization in progress",
    }
