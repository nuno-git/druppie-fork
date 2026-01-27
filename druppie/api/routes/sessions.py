"""Sessions API routes.

Simplified API for session management.
GET /sessions/{id} returns ALL data in one call.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db, check_resource_ownership, get_user_roles
from druppie.api.errors import NotFoundError, AuthorizationError
from druppie.api.schemas import (
    PaginatedResponse,
    SessionSummary,
    SessionDetail,
    TokenUsage,
    ProjectSummary,
    WorkspaceInfo,
    WorkflowInfo,
    WorkflowStepInfo,
    AgentRunInfo,
    MessageInfo,
    ToolCallInfo,
    LLMCallInfo,
    ApprovalInfo,
    HITLQuestionInfo,
    HITLChoiceInfo,
    SessionEventInfo,
)
from druppie.db import crud
from druppie.db.models import (
    Session as SessionModel,
    Approval,
    Project,
    Workspace,
    Workflow,
    WorkflowStep,
    AgentRun,
    Message,
    ToolCall,
    LlmCall,
    HitlQuestion,
    SessionEvent,
    User,
    Build,
)

logger = structlog.get_logger()

router = APIRouter()

MAX_LIMIT = 100


# =============================================================================
# AUTHORIZATION
# =============================================================================


def check_session_access(user: dict, session: SessionModel, db: DBSession) -> None:
    """Check if user can access a session.

    Allows access if:
    - User owns the session
    - User is admin
    - User has a pending approval for this session that matches their role
    """
    user_id = user.get("sub")
    is_owner = str(session.user_id) == user_id if session.user_id else False
    is_admin = "admin" in get_user_roles(user)

    if is_owner or is_admin:
        return

    # Check if user has pending approvals for this session
    user_roles = set(get_user_roles(user))
    pending_approvals = (
        db.query(Approval)
        .filter(Approval.session_id == session.id, Approval.status == "pending")
        .all()
    )

    for approval in pending_approvals:
        required_role = approval.required_role or "admin"
        if required_role in user_roles:
            return

    raise AuthorizationError(
        "You don't have permission to view this session",
        required_roles=["owner", "admin", "approver"],
    )


# =============================================================================
# CONVERTERS
# =============================================================================


def _to_token_usage(prompt: int = 0, completion: int = 0, total: int = 0) -> TokenUsage:
    """Convert token counts to TokenUsage model."""
    return TokenUsage(
        prompt_tokens=prompt or 0,
        completion_tokens=completion or 0,
        total_tokens=total or 0,
    )


def _session_to_summary(session: SessionModel, project_name: str | None = None) -> SessionSummary:
    """Convert session to summary for listing."""
    return SessionSummary(
        id=str(session.id),
        title=session.title,
        status=session.status,
        project_id=str(session.project_id) if session.project_id else None,
        project_name=project_name,
        token_usage=_to_token_usage(
            session.prompt_tokens,
            session.completion_tokens,
            session.total_tokens,
        ),
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )


def _build_session_detail(session: SessionModel, db: DBSession) -> SessionDetail:
    """Build complete session detail with ALL data."""

    # Get project info
    project = None
    if session.project_id:
        proj = db.query(Project).filter(Project.id == session.project_id).first()
        if proj:
            # Get app_url from running build
            app_url = None
            running_build = (
                db.query(Build)
                .filter(Build.project_id == proj.id, Build.status == "running", Build.is_preview == False)
                .first()
            )
            if running_build:
                app_url = running_build.app_url

            project = ProjectSummary(
                id=str(proj.id),
                name=proj.name,
                repo_name=proj.repo_name,
                repo_url=proj.repo_url,
                app_url=app_url,
            )

    # Get workspace
    workspace = None
    ws = db.query(Workspace).filter(Workspace.session_id == session.id).first()
    if ws:
        workspace = WorkspaceInfo(
            id=str(ws.id),
            session_id=str(ws.session_id),
            project_id=str(ws.project_id) if ws.project_id else None,
            branch=ws.branch,
            local_path=ws.local_path,
            created_at=ws.created_at.isoformat() if ws.created_at else None,
        )

    # Get workflow with steps
    workflow = None
    wf = db.query(Workflow).filter(Workflow.session_id == session.id).first()
    if wf:
        steps = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == wf.id)
            .order_by(WorkflowStep.step_index)
            .all()
        )
        workflow = WorkflowInfo(
            id=str(wf.id),
            name=wf.name,
            status=wf.status,
            current_step=wf.current_step or 0,
            steps=[
                WorkflowStepInfo(
                    id=str(s.id),
                    step_index=s.step_index,
                    agent_id=s.agent_id,
                    description=s.description,
                    status=s.status,
                    result_summary=s.result_summary,
                    started_at=s.started_at.isoformat() if s.started_at else None,
                    completed_at=s.completed_at.isoformat() if s.completed_at else None,
                )
                for s in steps
            ],
            created_at=wf.created_at.isoformat() if wf.created_at else None,
        )

    # Get all agent runs
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.session_id == session.id)
        .order_by(AgentRun.started_at)
        .all()
    )

    # Build agent_run_id -> agent_id map
    agent_run_map = {str(r.id): r.agent_id for r in runs}

    # =========================================================================
    # Query all data and group by agent_run_id
    # =========================================================================

    # Get all LLM calls
    llm_calls_raw = (
        db.query(LlmCall)
        .filter(LlmCall.session_id == session.id)
        .order_by(LlmCall.created_at)
        .all()
    )

    # Get all tool calls
    tcs = (
        db.query(ToolCall)
        .filter(ToolCall.session_id == session.id)
        .order_by(ToolCall.created_at)
        .all()
    )

    # Get all approvals with resolver info
    approvals_raw = (
        db.query(Approval)
        .filter(Approval.session_id == session.id)
        .order_by(Approval.created_at)
        .all()
    )

    # Batch load resolver usernames
    resolver_ids = {a.resolved_by for a in approvals_raw if a.resolved_by}
    resolver_map = {}
    if resolver_ids:
        resolvers = db.query(User).filter(User.id.in_(resolver_ids)).all()
        resolver_map = {str(u.id): u.username for u in resolvers}

    # Get all HITL questions
    questions_raw = (
        db.query(HitlQuestion)
        .filter(HitlQuestion.session_id == session.id)
        .order_by(HitlQuestion.created_at)
        .all()
    )

    # =========================================================================
    # Group everything by agent_run_id
    # =========================================================================

    llm_calls_by_run: dict[str, list[LLMCallInfo]] = {}
    all_llm_calls: list[LLMCallInfo] = []

    for lc in llm_calls_raw:
        llm_call_info = LLMCallInfo(
            id=str(lc.id),
            agent_id=agent_run_map.get(str(lc.agent_run_id)) if lc.agent_run_id else None,
            agent_run_id=str(lc.agent_run_id) if lc.agent_run_id else None,
            provider=lc.provider,
            model=lc.model,
            token_usage=_to_token_usage(lc.prompt_tokens, lc.completion_tokens, lc.total_tokens),
            duration_ms=lc.duration_ms,
            request_messages=lc.request_messages,
            response_content=lc.response_content,
            response_tool_calls=lc.response_tool_calls,
            tools_provided=lc.tools_provided,
            created_at=lc.created_at.isoformat() if lc.created_at else None,
        )
        all_llm_calls.append(llm_call_info)
        if lc.agent_run_id:
            run_id_str = str(lc.agent_run_id)
            if run_id_str not in llm_calls_by_run:
                llm_calls_by_run[run_id_str] = []
            llm_calls_by_run[run_id_str].append(llm_call_info)

    tool_calls_by_run: dict[str, list[ToolCallInfo]] = {}
    all_tool_calls: list[ToolCallInfo] = []

    for tc in tcs:
        tool_call_info = ToolCallInfo(
            id=str(tc.id),
            agent_run_id=str(tc.agent_run_id) if tc.agent_run_id else None,
            mcp_server=tc.mcp_server,
            tool_name=tc.tool_name,
            arguments={a.arg_name: a.arg_value for a in tc.arguments} if tc.arguments else {},
            status=tc.status,
            result=tc.result,
            error_message=tc.error_message,
            created_at=tc.created_at.isoformat() if tc.created_at else None,
            executed_at=tc.executed_at.isoformat() if tc.executed_at else None,
        )
        all_tool_calls.append(tool_call_info)
        if tc.agent_run_id:
            run_id_str = str(tc.agent_run_id)
            if run_id_str not in tool_calls_by_run:
                tool_calls_by_run[run_id_str] = []
            tool_calls_by_run[run_id_str].append(tool_call_info)

    approvals_by_run: dict[str, list[ApprovalInfo]] = {}
    all_approvals: list[ApprovalInfo] = []

    for a in approvals_raw:
        approval_info = ApprovalInfo(
            id=str(a.id),
            session_id=str(a.session_id),
            agent_run_id=str(a.agent_run_id) if a.agent_run_id else None,
            tool_call_id=str(a.tool_call_id) if a.tool_call_id else None,
            workflow_step_id=str(a.workflow_step_id) if a.workflow_step_id else None,
            approval_type=a.approval_type,
            mcp_server=a.mcp_server,
            tool_name=a.tool_name,
            title=a.title,
            description=a.description,
            required_roles=a.required_roles,
            danger_level=a.danger_level,
            status=a.status,
            arguments=a.arguments if isinstance(a.arguments, dict) else None,
            resolved_by=str(a.resolved_by) if a.resolved_by else None,
            resolved_by_username=resolver_map.get(str(a.resolved_by)) if a.resolved_by else None,
            resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
            rejection_reason=a.rejection_reason,
            agent_id=a.agent_id,
            created_at=a.created_at.isoformat() if a.created_at else None,
        )
        all_approvals.append(approval_info)
        if a.agent_run_id:
            run_id_str = str(a.agent_run_id)
            if run_id_str not in approvals_by_run:
                approvals_by_run[run_id_str] = []
            approvals_by_run[run_id_str].append(approval_info)

    hitl_by_run: dict[str, list[HITLQuestionInfo]] = {}
    all_hitl_questions: list[HITLQuestionInfo] = []

    for q in questions_raw:
        hitl_info = HITLQuestionInfo(
            id=str(q.id),
            session_id=str(q.session_id),
            agent_run_id=str(q.agent_run_id) if q.agent_run_id else None,
            agent_id=q.agent_id,
            question=q.question,
            question_type=q.question_type or "text",
            choices=[
                HITLChoiceInfo(
                    index=c.choice_index,
                    text=c.choice_text,
                    is_selected=c.is_selected or False,
                )
                for c in sorted(q.choices, key=lambda x: x.choice_index)
            ] if q.choices else [],
            status=q.status,
            answer=q.answer,
            created_at=q.created_at.isoformat() if q.created_at else None,
            answered_at=q.answered_at.isoformat() if q.answered_at else None,
        )
        all_hitl_questions.append(hitl_info)
        if q.agent_run_id:
            run_id_str = str(q.agent_run_id)
            if run_id_str not in hitl_by_run:
                hitl_by_run[run_id_str] = []
            hitl_by_run[run_id_str].append(hitl_info)

    # =========================================================================
    # Build agent runs with ALL nested data
    # =========================================================================

    agent_runs = [
        AgentRunInfo(
            id=str(r.id),
            agent_id=r.agent_id,
            workflow_step_id=str(r.workflow_step_id) if r.workflow_step_id else None,
            parent_run_id=str(r.parent_run_id) if r.parent_run_id else None,
            status=r.status,
            iteration_count=r.iteration_count or 0,
            token_usage=_to_token_usage(r.prompt_tokens, r.completion_tokens, r.total_tokens),
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            llm_calls=llm_calls_by_run.get(str(r.id), []),
            tool_calls=tool_calls_by_run.get(str(r.id), []),
            approvals=approvals_by_run.get(str(r.id), []),
            hitl_questions=hitl_by_run.get(str(r.id), []),
        )
        for r in runs
    ]

    # Calculate tokens by agent
    tokens_by_agent = {}
    for r in runs:
        if r.agent_id and r.total_tokens:
            tokens_by_agent[r.agent_id] = tokens_by_agent.get(r.agent_id, 0) + r.total_tokens

    # Get all messages
    msgs = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.sequence_number)
        .all()
    )
    messages = [
        MessageInfo(
            id=str(m.id),
            role=m.role,
            content=m.content,
            agent_id=m.agent_id,
            tool_name=m.tool_name,
            tool_call_id=m.tool_call_id,
            sequence_number=m.sequence_number,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in msgs
    ]

    # Get all timeline events
    events_raw = (
        db.query(SessionEvent)
        .filter(SessionEvent.session_id == session.id)
        .order_by(SessionEvent.timestamp)
        .all()
    )

    events = [
        SessionEventInfo(
            id=str(e.id),
            event_type=e.event_type,
            agent_id=e.agent_id,
            title=e.title,
            tool_name=e.tool_name,
            event_data=e.event_data,
            timestamp=e.timestamp.isoformat() if e.timestamp else None,
            agent_run_id=str(e.agent_run_id) if e.agent_run_id else None,
            tool_call_id=str(e.tool_call_id) if e.tool_call_id else None,
            approval_id=str(e.approval_id) if e.approval_id else None,
            hitl_question_id=str(e.hitl_question_id) if e.hitl_question_id else None,
        )
        for e in events_raw
    ]

    return SessionDetail(
        id=str(session.id),
        user_id=str(session.user_id) if session.user_id else None,
        title=session.title,
        status=session.status,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
        token_usage=_to_token_usage(
            session.prompt_tokens,
            session.completion_tokens,
            session.total_tokens,
        ),
        tokens_by_agent=tokens_by_agent,
        project=project,
        workspace=workspace,
        workflow=workflow,
        agent_runs=agent_runs,
        messages=messages,
        tool_calls=all_tool_calls,
        llm_calls=all_llm_calls,
        approvals=all_approvals,
        hitl_questions=all_hitl_questions,
        events=events,
    )


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/sessions", response_model=PaginatedResponse[SessionSummary])
async def list_sessions(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    project_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List sessions with pagination.

    Returns compact session summaries for sidebar/listing.
    """
    # Validate pagination
    page = max(1, page)
    limit = max(1, min(limit, MAX_LIMIT))

    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Admin can see all sessions
    if "admin" in roles:
        user_id = None

    # Build query
    query = db.query(SessionModel)
    if user_id:
        query = query.filter(SessionModel.user_id == user_id)
    if status:
        query = query.filter(SessionModel.status == status)
    if project_id:
        query = query.filter(SessionModel.project_id == project_id)

    total = query.count()
    offset = (page - 1) * limit
    sessions = query.order_by(SessionModel.created_at.desc()).offset(offset).limit(limit).all()

    # Batch load project names
    project_ids = {s.project_id for s in sessions if s.project_id}
    project_names = {}
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        project_names = {p.id: p.name for p in projects}

    return PaginatedResponse[SessionSummary](
        items=[_session_to_summary(s, project_names.get(s.project_id)) for s in sessions],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get complete session with ALL data.

    Returns everything in one call:
    - Basic session info and token usage
    - Project and workspace info
    - Workflow with all steps
    - All agent runs (router, planner, architect, developer, etc.)
    - Full message history
    - All tool calls with arguments
    - All LLM calls with full request/response (for debugging)
    - All approvals (pending and resolved)
    - All HITL questions (pending and answered)
    - Timeline events
    """
    session = crud.get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    check_session_access(user, session, db)

    logger.info("session_retrieved", session_id=session_id, user_id=user.get("sub"))

    return _build_session_detail(session, db)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Delete a session and all related data."""
    session = crud.get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    check_resource_ownership(user, str(session.user_id) if session.user_id else None)

    crud.delete_session(db, session_id)
    logger.info("session_deleted", session_id=session_id, user_id=user.get("sub"))

    return {"success": True, "message": "Session deleted"}
