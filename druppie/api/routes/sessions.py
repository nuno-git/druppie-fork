"""Sessions API routes.

Endpoints for managing chat sessions.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db, check_resource_ownership
from druppie.api.errors import NotFoundError, AuthorizationError
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


class MessageResponse(BaseModel):
    """Message in conversation history."""

    role: str
    content: str
    agent_id: str | None = None  # Which agent produced this message
    timestamp: str | None = None
    workflow_events: list[dict] | None = None
    llm_calls: list[dict] | None = None
    deployment_url: str | None = None
    container_name: str | None = None


class TokenUsage(BaseModel):
    """Token usage tracking for transparency."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class HITLQuestionResponse(BaseModel):
    """HITL question in session response."""

    id: str
    question: str
    choices: list[str] = []
    context: str | None = None
    agent_id: str | None = None
    status: str  # pending, answered
    answer: str | None = None
    created_at: str | None = None
    answered_at: str | None = None


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
    # Full conversation history
    messages: list[MessageResponse] | None = None
    # HITL questions (pending and answered)
    pending_questions: list[HITLQuestionResponse] | None = None
    hitl_questions: list[HITLQuestionResponse] | None = None
    # Token usage for transparency
    token_usage: TokenUsage | None = None


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
    total_tokens: int = 0  # Token usage for transparency


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


def _session_to_response(session, project=None, db=None) -> SessionResponse:
    """Convert a DB session to response model.

    Args:
        session: Session DB model
        project: Optional project DB model for project info
        db: Database session for fetching related data
    """
    # Get first user message for name/description
    first_message = session.title or "Session"
    name = f"Chat: {first_message[:30]}"
    description = first_message

    # Build project info if available
    project_info = None
    if project:
        project_info = ProjectInfo(
            id=str(project.id),
            name=project.name,
            repo_name=project.repo_name,
            repo_url=project.repo_url,
        )

    # Get messages from database if db is provided
    messages = None
    if db:
        from druppie.db.models import Message
        db_messages = (
            db.query(Message)
            .filter(Message.session_id == session.id)
            .order_by(Message.sequence_number.asc())
            .all()
        )
        if db_messages:
            messages = [
                MessageResponse(
                    role=msg.role,
                    content=msg.content,
                    agent_id=msg.agent_id,  # Include agent_id for agent attribution
                    timestamp=msg.created_at.isoformat() if msg.created_at else None,
                    workflow_events=None,  # Not stored per-message anymore
                    llm_calls=None,
                    deployment_url=None,
                    container_name=None,
                )
                for msg in db_messages
            ]

    # Get workspace from database if db is provided
    workspace_id = None
    if db:
        from druppie.db.models import Workspace
        workspace = (
            db.query(Workspace)
            .filter(Workspace.session_id == session.id)
            .first()
        )
        if workspace:
            workspace_id = str(workspace.id)

    # Token usage (transparency)
    token_usage = TokenUsage(
        prompt_tokens=session.prompt_tokens or 0,
        completion_tokens=session.completion_tokens or 0,
        total_tokens=session.total_tokens or 0,
    )

    return SessionResponse(
        id=str(session.id),
        user_id=str(session.user_id) if session.user_id else None,
        status=session.status,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
        project_id=str(session.project_id) if session.project_id else None,
        workspace_id=workspace_id,
        project=project_info,
        name=name,
        description=description,
        result=None,  # No longer stored in JSON state
        tasks=None,  # Approvals are fetched separately
        messages=messages,
        token_usage=token_usage,
    )


def _session_to_summary(session, project_name: str | None = None, workspace_id: str | None = None) -> SessionSummary:
    """Convert a DB session to a compact summary for sidebar listing.

    Args:
        session: Session DB model
        project_name: Optional project name (fetched separately for efficiency)
        workspace_id: Optional workspace ID (fetched separately)
    """
    # Use title as preview (set when session created)
    preview = session.title[:50] if session.title else "No message"

    return SessionSummary(
        id=str(session.id),
        created_at=session.created_at.isoformat() if session.created_at else None,
        status=session.status,
        preview=preview,
        project_id=str(session.project_id) if session.project_id else None,
        project_name=project_name,
        workspace_id=workspace_id,
        total_tokens=session.total_tokens or 0,
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
            _session_to_response(s, project=projects_map.get(s.project_id), db=db)
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
    from druppie.db.models import HitlQuestion, AgentRun

    session = crud.get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    # Check ownership (unless admin)
    check_resource_ownership(user, str(session.user_id) if session.user_id else None)

    # Fetch project info if session has a project_id
    project = None
    if session.project_id:
        project = crud.get_project(db, session.project_id)

    response = _session_to_response(session, project=project, db=db)

    # Also include pending approvals (tasks) for the frontend
    pending_approvals = crud.list_pending_approvals(db, session_id=session_id)
    response.tasks = [
        {
            "id": str(a.id),
            "name": a.tool_name,
            "status": "pending_approval" if a.status == "pending" else a.status,
            "mcp_tool": a.tool_name,
            "required_role": a.required_role or "admin",
            "required_roles": [a.required_role] if a.required_role else ["admin"],
            "approval_type": "role",
            "required_approvals": 1,
            "approvals": [],
        }
        for a in pending_approvals
    ]

    # Fetch HITL questions (both pending and answered) for conversation reconstruction
    hitl_questions = (
        db.query(HitlQuestion)
        .filter(HitlQuestion.session_id == session.id)
        .order_by(HitlQuestion.created_at.asc())
        .all()
    )

    def hitl_to_response(q):
        # Get agent_id from agent_run if available
        agent_id = None
        if q.agent_run_id:
            agent_run = db.query(AgentRun).filter(AgentRun.id == q.agent_run_id).first()
            if agent_run:
                agent_id = agent_run.agent_id

        return HITLQuestionResponse(
            id=str(q.id),
            question=q.question,
            choices=[c.choice_text for c in q.choices] if q.choices else [],
            context=None,
            agent_id=agent_id,
            status=q.status,
            answer=q.answer,
            created_at=q.created_at.isoformat() if q.created_at else None,
            answered_at=q.answered_at.isoformat() if q.answered_at else None,
        )

    # Separate pending and all questions
    response.pending_questions = [
        hitl_to_response(q) for q in hitl_questions if q.status == "pending"
    ]
    response.hitl_questions = [hitl_to_response(q) for q in hitl_questions]

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
        raise NotFoundError("session", session_id)

    # Check ownership (unless admin)
    check_resource_ownership(user, str(session.user_id) if session.user_id else None)

    crud.delete_session(db, session_id)
    logger.info("session_deleted", session_id=session_id, user_id=user.get("sub"))

    return {"success": True, "message": "Session deleted"}


@router.get("/sessions/{session_id}/state")
async def get_session_state(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the execution state of a session.

    Note: With the normalized schema, state is reconstructed from tables.
    """
    from druppie.db.models import Message, Workflow, AgentRun

    session = crud.get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    # Check ownership
    check_resource_ownership(user, str(session.user_id) if session.user_id else None)

    # Reconstruct state from normalized tables
    messages = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.sequence_number.asc())
        .all()
    )

    workflow = (
        db.query(Workflow)
        .filter(Workflow.session_id == session.id)
        .first()
    )

    agent_runs = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session.id)
        .order_by(AgentRun.started_at.asc())
        .all()
    )

    return {
        "session_id": session_id,
        "status": session.status,
        "state": {
            "messages": [m.to_dict() for m in messages],
            "workflow": workflow.to_dict() if workflow else None,
            "agent_runs": [r.to_dict() for r in agent_runs],
        },
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
    # Token usage for transparency
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RawLLMCall(BaseModel):
    """Raw LLM call with full request/response data for debugging."""

    agent_id: str | None = None
    iteration: int | None = None
    timestamp: str | None = None
    duration_ms: int | None = None
    # Model transparency
    model: str | None = None  # Which model was used (e.g., "Qwen/Qwen3-Next-80B-A3B-Instruct")
    provider: str | None = None  # Which provider was used (e.g., "deepinfra")
    # Full request data
    messages: list[dict] = []  # Full message history sent to LLM
    tools: list[dict] | None = None  # Full tool schemas
    # Full response data
    response: dict | None = None  # Full response with content and tool_calls
    usage: dict | None = None  # Token usage


class TraceData(BaseModel):
    """Full trace data with events and summary."""

    events: list[TraceEvent]
    summary: TraceSummary
    raw_llm_calls: list[RawLLMCall] = []  # Full raw LLM data for debugging


class SessionTraceResponse(BaseModel):
    """Response model for session trace endpoint."""

    session_id: str
    status: str
    trace: TraceData


def _build_trace_events_from_db(db, session_id) -> list[TraceEvent]:
    """Build a list of trace events from normalized tables.

    Combines agent_runs, tool_calls, and llm_calls into a unified timeline.
    """
    from druppie.db.models import AgentRun, ToolCall, LlmCall

    events = []
    event_counter = 0

    # Get agent runs
    agent_runs = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session_id)
        .order_by(AgentRun.started_at.asc())
        .all()
    )

    for run in agent_runs:
        event_counter += 1
        # Agent start event
        events.append(TraceEvent(
            id=f"evt-{event_counter}",
            type="agent_start",
            agent=run.agent_id,
            timestamp=run.started_at.isoformat() if run.started_at else "",
            data={
                "agent_run_id": str(run.id),
                "status": run.status,
                "iteration_count": run.iteration_count,
            },
        ))

        if run.completed_at:
            event_counter += 1
            events.append(TraceEvent(
                id=f"evt-{event_counter}",
                type="agent_complete",
                agent=run.agent_id,
                timestamp=run.completed_at.isoformat(),
                data={
                    "agent_run_id": str(run.id),
                    "status": run.status,
                },
            ))

    # Get tool calls
    tool_calls = (
        db.query(ToolCall)
        .filter(ToolCall.session_id == session_id)
        .order_by(ToolCall.created_at.asc())
        .all()
    )

    for tc in tool_calls:
        event_counter += 1
        # Get agent_id from agent_run if available
        agent_id = None
        if tc.agent_run_id:
            agent_run = db.query(AgentRun).filter(AgentRun.id == tc.agent_run_id).first()
            if agent_run:
                agent_id = agent_run.agent_id

        events.append(TraceEvent(
            id=f"evt-{event_counter}",
            type="tool_call",
            agent=agent_id,
            timestamp=tc.created_at.isoformat() if tc.created_at else "",
            tool=f"{tc.mcp_server}:{tc.tool_name}",
            args={a.arg_name: a.arg_value[:100] if a.arg_value else None for a in tc.arguments} if tc.arguments else {},
            result={"status": tc.status, "error": tc.error_message} if tc.error_message else {"status": tc.status},
            duration_ms=int((tc.executed_at - tc.created_at).total_seconds() * 1000) if tc.executed_at and tc.created_at else None,
            data={"tool_call_id": str(tc.id), "mcp_server": tc.mcp_server},
        ))

    # Get LLM calls
    llm_calls = (
        db.query(LlmCall)
        .filter(LlmCall.session_id == session_id)
        .order_by(LlmCall.created_at.asc())
        .all()
    )

    for call in llm_calls:
        event_counter += 1
        # Get agent_id from agent_run if available
        agent_id = None
        if call.agent_run_id:
            agent_run = db.query(AgentRun).filter(AgentRun.id == call.agent_run_id).first()
            if agent_run:
                agent_id = agent_run.agent_id

        events.append(TraceEvent(
            id=f"evt-{event_counter}",
            type="llm_call",
            agent=agent_id,
            timestamp=call.created_at.isoformat() if call.created_at else "",
            duration_ms=call.duration_ms,
            data={
                "provider": call.provider,
                "model": call.model,
                "usage": {
                    "prompt_tokens": call.prompt_tokens,
                    "completion_tokens": call.completion_tokens,
                    "total_tokens": call.total_tokens,
                },
            },
        ))

    # Sort events by timestamp
    events.sort(key=lambda e: e.timestamp or "")

    return events


def _build_trace_summary_from_db(events: list[TraceEvent], session) -> TraceSummary:
    """Build summary statistics from trace events."""
    from datetime import datetime

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

    # Calculate total duration from timestamps
    total_duration_ms = 0
    if events:
        try:
            first_ts = events[0].timestamp
            last_ts = events[-1].timestamp
            if first_ts and last_ts:
                first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                total_duration_ms = int((last_dt - first_dt).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    return TraceSummary(
        total_events=len(events),
        agents_used=sorted(list(agents_used)),
        tools_called=tools_called,
        llm_calls=llm_calls_count,
        total_duration_ms=total_duration_ms,
        prompt_tokens=session.prompt_tokens or 0,
        completion_tokens=session.completion_tokens or 0,
        total_tokens=session.total_tokens or 0,
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
    - All agent_runs (agent starts, completions)
    - All llm_calls (model calls with provider/model info)
    - All tool_calls (MCP tool executions with args)
    - Timeline data (timestamps for each event)
    - Agent information (which agent executed what)
    """
    from druppie.db.models import LlmCall, AgentRun

    session = crud.get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    # Check ownership (unless admin)
    check_resource_ownership(user, str(session.user_id) if session.user_id else None)

    # Build trace events from normalized tables
    events = _build_trace_events_from_db(db, session.id)

    # Build summary
    summary = _build_trace_summary_from_db(events, session)

    logger.info(
        "session_trace_retrieved",
        session_id=session_id,
        total_events=summary.total_events,
        agents_used=summary.agents_used,
    )

    # Build raw LLM calls list from database
    llm_calls = (
        db.query(LlmCall)
        .filter(LlmCall.session_id == session.id)
        .order_by(LlmCall.created_at.asc())
        .all()
    )

    raw_llm_calls = []
    for i, call in enumerate(llm_calls):
        # Get agent_id from agent_run if available
        agent_id = None
        if call.agent_run_id:
            agent_run = db.query(AgentRun).filter(AgentRun.id == call.agent_run_id).first()
            if agent_run:
                agent_id = agent_run.agent_id

        # Build response dict from stored data
        response = None
        if call.response_content or call.response_tool_calls:
            response = {
                "content": call.response_content,
                "tool_calls": call.response_tool_calls or [],
            }

        raw_llm_calls.append(RawLLMCall(
            agent_id=agent_id,
            iteration=i + 1,  # Use 1-based index as iteration
            timestamp=call.created_at.isoformat() if call.created_at else None,
            duration_ms=call.duration_ms,
            model=call.model,
            provider=call.provider,
            messages=call.request_messages or [],  # Full messages from database
            tools=call.tools_provided,  # Tools from database
            response=response,  # Response content and tool calls
            usage={
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "total_tokens": call.total_tokens,
            },
        ))

    return SessionTraceResponse(
        session_id=session_id,
        status=session.status,
        trace=TraceData(
            events=events,
            summary=summary,
            raw_llm_calls=raw_llm_calls,
        ),
    )
