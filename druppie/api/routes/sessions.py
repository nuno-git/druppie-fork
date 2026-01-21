"""Sessions API routes.

Endpoints for managing chat sessions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.db import crud

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class SessionResponse(BaseModel):
    """Session response model."""

    id: str
    user_id: str | None
    status: str
    created_at: str | None
    updated_at: str | None
    # Backwards compatibility with "plan" naming
    name: str | None = None
    description: str | None = None
    result: dict | None = None
    tasks: list[dict] | None = None


class SessionListResponse(BaseModel):
    """List of sessions response.

    Note: Returns as a list directly for backwards compatibility with getPlans.
    """

    sessions: list[SessionResponse]
    total: int


# =============================================================================
# ROUTES
# =============================================================================


def _session_to_response(session) -> SessionResponse:
    """Convert a DB session to response model."""
    state = session.state or {}
    context = state.get("context", {})

    # Extract name from context or first user message
    name = context.get("name") or f"Chat: {context.get('user_message', 'Session')[:30]}"
    description = context.get("user_message", "")

    # Build result from state
    result = {
        "response": context.get("final_response", ""),
        "workflow_events": state.get("workflow_events", []),
        "llm_calls": state.get("llm_calls", []),
    }

    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
        name=name,
        description=description,
        result=result,
        tasks=None,  # Approvals are fetched separately
    )


@router.get("/sessions")
async def list_sessions(
    status: str | None = None,
    limit: int = 50,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List sessions for the current user.

    Returns as a list directly for backwards compatibility with getPlans.
    """
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin can see all sessions
    if "admin" in roles:
        user_id = None

    sessions = crud.list_sessions(db, user_id=user_id, status=status, limit=limit)

    # Return as a list for backwards compatibility with frontend getPlans
    return [_session_to_response(s) for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific session."""
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership (unless admin)
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and session.user_id != user.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized")

    response = _session_to_response(session)

    # Also include pending approvals (tasks) for the frontend
    pending_approvals = crud.list_pending_approvals(db, session_id=session_id)
    response.tasks = [
        {
            "id": a.id,
            "name": a.tool_name,
            "status": "pending_approval" if a.status == "pending" else a.status,
            "mcp_tool": a.tool_name,
            "required_role": (a.required_roles or ["admin"])[0],
            "required_roles": a.required_roles or ["admin"],
            "approval_type": "multi" if len(a.required_roles or []) > 1 else "role",
            "required_approvals": len(a.required_roles or [1]),
            "approvals": a.approvals_received or [],
        }
        for a in pending_approvals
    ]

    return response


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a session."""
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership (unless admin)
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and session.user_id != user.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized")

    crud.delete_session(db, session_id)
    logger.info("session_deleted", session_id=session_id, user_id=user.get("sub"))

    return {"success": True, "message": "Session deleted"}


@router.get("/sessions/{session_id}/state")
async def get_session_state(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the execution state of a session."""
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and session.user_id != user.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "session_id": session_id,
        "status": session.status,
        "state": session.state,
    }
