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

from fastapi import APIRouter, Depends, Query
from uuid import UUID
import structlog

from druppie.api.deps import (
    get_current_user,
    get_user_roles,
    get_session_service,
)
from druppie.api.errors import NotFoundError, AuthorizationError
from druppie.services import SessionService
from druppie.domain import SessionDetail, SessionSummary

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
