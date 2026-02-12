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

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from uuid import UUID
import structlog

from druppie.api.deps import (
    get_current_user,
    get_user_roles,
    get_session_service,
    get_session_repository,
)
from druppie.api.errors import NotFoundError, AuthorizationError
from druppie.services import SessionService
from druppie.repositories import SessionRepository
from druppie.domain import SessionDetail, SessionSummary
from druppie.domain.common import SessionStatus

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
# RETRY
# =============================================================================


class RetryRequest(BaseModel):
    """Request body for session retry."""
    from_run_id: str = Field(..., description="Agent run ID to retry from")


async def _retry_session_background(session_id: UUID, from_run_id: UUID) -> None:
    """Run retry in background with its own DB session."""
    from druppie.db.database import SessionLocal
    from druppie.repositories import (
        SessionRepository,
        ExecutionRepository,
        ProjectRepository,
        QuestionRepository,
    )
    from druppie.execution import Orchestrator

    db = SessionLocal()
    try:
        orchestrator = Orchestrator(
            session_repo=SessionRepository(db),
            execution_repo=ExecutionRepository(db),
            project_repo=ProjectRepository(db),
            question_repo=QuestionRepository(db),
        )
        await orchestrator.retry_from_run(session_id, from_run_id)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            "retry_session_background_error",
            session_id=str(session_id),
            error=error_msg,
            exc_info=True,
        )
        try:
            sr = SessionRepository(db)
            sr.update_status(session_id, SessionStatus.FAILED, error_message=error_msg[:2000])
            db.commit()
        except Exception:
            logger.error("failed_to_update_session_status_on_retry", session_id=str(session_id))
    finally:
        db.close()


@router.post("/sessions/{session_id}/retry")
async def retry_session(
    session_id: UUID,
    body: RetryRequest,
    session_repo: SessionRepository = Depends(get_session_repository),
    user: dict = Depends(get_current_user),
):
    """Retry a session from a specific agent run onwards.

    Marks the target run and all subsequent runs as SUPERSEDED,
    creates new PENDING copies, and re-executes in the background.

    The session must not be currently ACTIVE (to prevent double-run).
    """
    from druppie.db.models import AgentRun

    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    from_run_id = UUID(body.from_run_id)

    # Validate session exists and user has access
    session = session_repo.get_by_id(session_id)
    if not session:
        raise NotFoundError("Session not found")
    if str(session.user_id) != str(user_id) and "admin" not in user_roles:
        raise AuthorizationError("Not authorized to retry this session")

    # Prevent double-run
    if session.status == SessionStatus.ACTIVE.value:
        return {"success": False, "message": "Session is already active"}

    # Validate from_run_id belongs to this session and is top-level
    agent_run = session_repo.db.query(AgentRun).filter_by(id=from_run_id).first()
    if not agent_run or str(agent_run.session_id) != str(session_id):
        return {"success": False, "message": "Agent run not found in this session"}
    if agent_run.parent_run_id is not None:
        return {"success": False, "message": "Can only retry from top-level agent runs"}

    logger.info(
        "retry_session_requested",
        session_id=str(session_id),
        from_run_id=str(from_run_id),
        user_id=str(user_id),
    )

    # Fire and forget
    asyncio.create_task(_retry_session_background(session_id, from_run_id))

    return {
        "success": True,
        "session_id": str(session_id),
        "status": "active",
        "message": "Retry started",
    }
