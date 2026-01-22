"""Sessions API routes.

Endpoints for managing chat sessions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.db import crud
from druppie.db.models import Session as SessionModel

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class ProjectInfo(BaseModel):
    """Project info for session responses."""

    id: str
    name: str
    repo_name: str | None = None
    repo_url: str | None = None


class SessionResponse(BaseModel):
    """Session response model."""

    id: str
    user_id: str | None
    status: str
    created_at: str | None
    updated_at: str | None
    # Project/workspace tracking
    project_id: str | None = None
    workspace_id: str | None = None
    project: ProjectInfo | None = None
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


class SessionSummary(BaseModel):
    """Compact session summary for sidebar listing."""

    id: str
    created_at: str | None
    status: str
    preview: str  # First 50 chars of initial message
    project_id: str | None = None  # If linked to a project
    project_name: str | None = None  # If linked to a project
    workspace_id: str | None = None  # If linked to a workspace


class PaginatedSessionsResponse(BaseModel):
    """Paginated sessions response for session history sidebar."""

    sessions: list[SessionSummary]
    total: int
    page: int
    limit: int


class SessionListLegacyResponse(BaseModel):
    """Paginated sessions response for legacy endpoint."""

    sessions: list[SessionResponse]
    total: int
    page: int
    limit: int


# Maximum limit for pagination to prevent excessive queries
MAX_LIMIT = 100


# =============================================================================
# ROUTES
# =============================================================================


def _session_to_response(session, project=None) -> SessionResponse:
    """Convert a DB session to response model.

    Args:
        session: Session DB model
        project: Optional project DB model for project info
    """
    state = session.state or {}
    context = state.get("context", {})

    # Extract name from context or first user message
    # Support both "message" (new) and "user_message" (legacy)
    message = context.get("message") or context.get("user_message", "Session")
    name = context.get("name") or f"Chat: {message[:30]}"
    description = message

    # Build result from state
    result = {
        "response": context.get("response") or context.get("final_response", ""),
        "workflow_events": state.get("workflow_events", []),
        "llm_calls": state.get("llm_calls", []),
        "intent": state.get("intent"),
        "plan": state.get("plan"),
    }

    # Build project info if available
    project_info = None
    if project:
        project_info = ProjectInfo(
            id=project.id,
            name=project.name,
            repo_name=project.repo_name,
            repo_url=project.repo_url,
        )

    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        project=project_info,
        name=name,
        description=description,
        result=result,
        tasks=None,  # Approvals are fetched separately
    )


def _session_to_summary(session, project_name: str | None = None) -> SessionSummary:
    """Convert a DB session to a compact summary for sidebar listing.

    Args:
        session: Session DB model
        project_name: Optional project name (fetched separately for efficiency)
    """
    state = session.state or {}
    context = state.get("context", {})

    # Extract preview from initial message (first 50 chars)
    message = context.get("message") or context.get("user_message", "")
    preview = message[:50] if message else "No message"

    # Use provided project_name or fallback to state
    resolved_project_name = project_name or context.get("project_name") or state.get("project_name")

    return SessionSummary(
        id=session.id,
        created_at=session.created_at.isoformat() if session.created_at else None,
        status=session.status,
        preview=preview,
        project_id=session.project_id,
        project_name=resolved_project_name,
        workspace_id=session.workspace_id,
    )


@router.get("/sessions", response_model=PaginatedSessionsResponse)
async def list_sessions_paginated(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    project_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List sessions for the current user with pagination.

    Returns paginated sessions with preview and project info for sidebar display.

    Args:
        page: Page number (1-indexed, default: 1)
        limit: Number of sessions per page (default: 20, max: 100)
        status: Optional status filter
        project_id: Optional project ID filter to list sessions for a specific project
        user: Current authenticated user
        db: Database session
    """
    from druppie.db.models import Project

    # Validate and enforce pagination limits
    if page < 1:
        page = 1
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin can see all sessions
    if "admin" in roles:
        user_id = None

    # Get total count
    query = db.query(SessionModel)
    if user_id:
        query = query.filter(SessionModel.user_id == user_id)
    if status:
        query = query.filter(SessionModel.status == status)
    if project_id:
        query = query.filter(SessionModel.project_id == project_id)
    total = query.count()

    # Get paginated sessions
    offset = (page - 1) * limit
    sessions = (
        query.order_by(SessionModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Fetch project names for sessions with project_id (batch query)
    project_ids = {s.project_id for s in sessions if s.project_id}
    project_names = {}
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        project_names = {p.id: p.name for p in projects}

    return PaginatedSessionsResponse(
        sessions=[
            _session_to_summary(s, project_name=project_names.get(s.project_id))
            for s in sessions
        ],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/sessions/list", response_model=SessionListLegacyResponse)
async def list_sessions_legacy(
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    project_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List sessions for the current user with pagination.

    Args:
        status: Optional status filter
        page: Page number (1-indexed, default: 1)
        limit: Number of sessions per page (default: 20, max: 100)
        project_id: Optional project ID filter
        user: Current authenticated user
        db: Database session

    Returns:
        SessionListLegacyResponse with sessions, total count, page, and limit
    """
    from druppie.db.models import Project

    # Validate and enforce pagination limits
    if page < 1:
        page = 1
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin can see all sessions
    if "admin" in roles:
        user_id = None

    # Build query for total count and pagination
    query = db.query(SessionModel)
    if user_id:
        query = query.filter(SessionModel.user_id == user_id)
    if status:
        query = query.filter(SessionModel.status == status)
    if project_id:
        query = query.filter(SessionModel.project_id == project_id)

    # Get total count
    total = query.count()

    # Get paginated sessions
    offset = (page - 1) * limit
    sessions = (
        query.order_by(SessionModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Fetch projects for all sessions with project_id (batch query)
    project_ids = {s.project_id for s in sessions if s.project_id}
    projects_map = {}
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        projects_map = {p.id: p for p in projects}

    # Build response with pagination info
    return SessionListLegacyResponse(
        sessions=[
            _session_to_response(s, project=projects_map.get(s.project_id))
            for s in sessions
        ],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get a specific session."""
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership (unless admin)
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and session.user_id != user.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Fetch project info if session has a project_id
    project = None
    if session.project_id:
        project = crud.get_project(db, session.project_id)

    response = _session_to_response(session, project=project)

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
    db: DBSession = Depends(get_db),
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
    db: DBSession = Depends(get_db),
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


# =============================================================================
# TRACE RESPONSE MODELS
# =============================================================================


class TraceEvent(BaseModel):
    """A single event in the execution trace."""

    id: str
    type: str
    agent: str | None = None
    timestamp: str
    data: dict = {}
    # For tool_call events
    tool: str | None = None
    args: dict | None = None
    result: dict | None = None
    duration_ms: int | None = None


class TraceSummary(BaseModel):
    """Summary statistics for an execution trace."""

    total_events: int
    agents_used: list[str]
    tools_called: int
    llm_calls: int
    total_duration_ms: int


class TraceData(BaseModel):
    """Full trace data with events and summary."""

    events: list[TraceEvent]
    summary: TraceSummary


class SessionTraceResponse(BaseModel):
    """Response model for session trace endpoint."""

    session_id: str
    status: str
    trace: TraceData


def _build_trace_events(state: dict) -> list[TraceEvent]:
    """Build a list of trace events from session state.

    Combines workflow_events and llm_calls into a unified timeline.
    """
    events = []
    event_counter = 0

    workflow_events = state.get("workflow_events", [])
    llm_calls = state.get("llm_calls", [])

    # Process workflow events
    for evt in workflow_events:
        event_counter += 1
        event_type = evt.get("type", "unknown")

        # Extract agent info from various event fields
        agent = evt.get("agent_id") or evt.get("agent")

        trace_event = TraceEvent(
            id=f"evt-{event_counter}",
            type=event_type,
            agent=agent,
            timestamp=evt.get("timestamp", ""),
            data={k: v for k, v in evt.items() if k not in ["type", "timestamp", "session_id", "agent_id", "agent"]},
        )

        # Enrich tool_call events
        if event_type == "tool_call":
            trace_event.tool = evt.get("tool_name")
            trace_event.args = {"preview": evt.get("args_preview", "")}

        events.append(trace_event)

    # Process LLM calls as separate events
    for call in llm_calls:
        event_counter += 1
        trace_event = TraceEvent(
            id=f"evt-{event_counter}",
            type="llm_call",
            agent=call.get("agent_id"),
            timestamp=call.get("timestamp", ""),
            duration_ms=call.get("duration_ms", 0),
            data={
                "iteration": call.get("iteration"),
                "has_tool_calls": bool(call.get("response", {}).get("tool_calls")),
                "message_count": len(call.get("messages", [])),
                "tools_provided": len(call.get("tools", []) or []),
                "usage": call.get("usage", {}),
                "response_preview": (call.get("response", {}).get("content") or "")[:200],
            },
        )
        events.append(trace_event)

    # Sort events by timestamp
    events.sort(key=lambda e: e.timestamp or "")

    return events


def _build_trace_summary(events: list[TraceEvent], state: dict) -> TraceSummary:
    """Build summary statistics from trace events."""
    agents_used = set()
    tools_called = 0
    llm_calls_count = 0

    for evt in events:
        if evt.agent:
            agents_used.add(evt.agent)
        if evt.type == "tool_call":
            tools_called += 1
        if evt.type == "llm_call":
            llm_calls_count += 1

    # Calculate total duration from timestamps or stored value
    total_duration_ms = 0
    if events:
        try:
            from datetime import datetime

            first_ts = events[0].timestamp
            last_ts = events[-1].timestamp
            if first_ts and last_ts:
                first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                total_duration_ms = int((last_dt - first_dt).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    # Use stored duration if available and larger
    stored_duration = state.get("duration_ms", 0)
    if stored_duration > total_duration_ms:
        total_duration_ms = stored_duration

    return TraceSummary(
        total_events=len(events),
        agents_used=sorted(list(agents_used)),
        tools_called=tools_called,
        llm_calls=llm_calls_count,
        total_duration_ms=total_duration_ms,
    )


@router.get("/sessions/{session_id}/trace", response_model=SessionTraceResponse)
async def get_session_trace(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the full execution trace for a session.

    Returns a structured trace with all workflow events, LLM calls,
    and tool executions in a format suitable for the frontend Debug Panel.

    The trace includes:
    - All workflow_events (agent starts, completions, errors)
    - All llm_calls (model calls with inputs/outputs)
    - All tool_calls (MCP tool executions with args)
    - Timeline data (timestamps for each event)
    - Agent information (which agent executed what)
    """
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership (unless admin)
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and session.user_id != user.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized")

    state = session.state or {}

    # Build trace events from state
    events = _build_trace_events(state)

    # Build summary
    summary = _build_trace_summary(events, state)

    logger.info(
        "session_trace_retrieved",
        session_id=session_id,
        total_events=summary.total_events,
        agents_used=summary.agents_used,
    )

    return SessionTraceResponse(
        session_id=session_id,
        status=session.status,
        trace=TraceData(
            events=events,
            summary=summary,
        ),
    )
