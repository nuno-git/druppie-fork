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
    ToolCallDecision,
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
    # Build lookup maps for approvals and HITL questions
    # =========================================================================

    # Helper to normalize tool names for matching
    # LLM returns: coding_write_file, approval stores: coding:write_file
    def normalize_tool_name(name: str) -> set[str]:
        """Return all variations of a tool name for matching."""
        variations = {name}
        # Replace underscore with colon and vice versa
        variations.add(name.replace("_", ":"))
        variations.add(name.replace(":", "_"))
        # Also try just the tool part (after : or first _)
        if ":" in name:
            variations.add(name.split(":")[1])
        if "_" in name:
            parts = name.split("_", 1)
            if len(parts) > 1:
                variations.add(parts[1])
        return variations

    # Build approval lookup - index by multiple keys for flexible matching
    approval_by_key: dict[str, Approval] = {}
    for a in approvals_raw:
        # Index by agent_id + all tool name variations
        if a.agent_id and a.tool_name:
            for variant in normalize_tool_name(a.tool_name):
                key = f"{a.agent_id}:{variant}"
                approval_by_key[key] = a
        # Also index by agent_run_id + tool name
        if a.agent_run_id and a.tool_name:
            for variant in normalize_tool_name(a.tool_name):
                key = f"run:{a.agent_run_id}:{variant}"
                approval_by_key[key] = a

    # Build HITL question lookup by (agent_run_id, question_text prefix) for matching
    hitl_by_run: dict[str, list[HitlQuestion]] = {}
    for q in questions_raw:
        if q.agent_run_id:
            run_id_str = str(q.agent_run_id)
            if run_id_str not in hitl_by_run:
                hitl_by_run[run_id_str] = []
            hitl_by_run[run_id_str].append(q)

    # Build tool_call lookup by (agent_run_id, tool_name) for execution results
    tool_calls_by_run_and_name: dict[str, ToolCall] = {}
    for tc in tcs:
        if tc.agent_run_id:
            # Index by multiple tool name variations
            for variant in normalize_tool_name(tc.tool_name):
                key = f"{tc.agent_run_id}:{variant}"
                tool_calls_by_run_and_name[key] = tc

    # =========================================================================
    # Group everything by agent_run_id with enhanced tool calls
    # =========================================================================

    llm_calls_by_run: dict[str, list[LLMCallInfo]] = {}
    all_llm_calls: list[LLMCallInfo] = []

    for lc in llm_calls_raw:
        agent_id = agent_run_map.get(str(lc.agent_run_id)) if lc.agent_run_id else None
        run_id_str = str(lc.agent_run_id) if lc.agent_run_id else None

        # Enhance response_tool_calls with embedded approval/HITL/execution data
        enhanced_tool_calls: list[ToolCallDecision] = []
        raw_tool_calls = lc.response_tool_calls or []

        for raw_tc in raw_tool_calls:
            tool_name = raw_tc.get("name", "")
            tool_args = raw_tc.get("args", {}) or raw_tc.get("arguments", {})
            tool_id = raw_tc.get("id")

            # Check if this is a HITL question tool
            is_hitl = tool_name in ("hitl_ask_question", "hitl_ask_multiple_choice_question")

            # Check if this is the done tool
            is_done = tool_name == "done"

            # Find matching approval - try multiple key variations
            approval_info = None
            approval_required = False
            matching_approval = None
            if not is_hitl and not is_done:
                # Try agent_id + tool_name variations
                if agent_id:
                    for variant in normalize_tool_name(tool_name):
                        key = f"{agent_id}:{variant}"
                        if key in approval_by_key:
                            matching_approval = approval_by_key[key]
                            break
                # Also try agent_run_id + tool_name
                if not matching_approval and run_id_str:
                    for variant in normalize_tool_name(tool_name):
                        key = f"run:{run_id_str}:{variant}"
                        if key in approval_by_key:
                            matching_approval = approval_by_key[key]
                            break
                if matching_approval:
                    approval_required = True
                    approval_info = ApprovalInfo(
                        id=str(matching_approval.id),
                        session_id=str(matching_approval.session_id),
                        agent_run_id=str(matching_approval.agent_run_id) if matching_approval.agent_run_id else None,
                        tool_call_id=str(matching_approval.tool_call_id) if matching_approval.tool_call_id else None,
                        workflow_step_id=str(matching_approval.workflow_step_id) if matching_approval.workflow_step_id else None,
                        approval_type=matching_approval.approval_type,
                        mcp_server=matching_approval.mcp_server,
                        tool_name=matching_approval.tool_name,
                        title=matching_approval.title,
                        description=matching_approval.description,
                        required_roles=matching_approval.required_roles or [],
                        danger_level=matching_approval.danger_level,
                        status=matching_approval.status,
                        arguments=matching_approval.arguments if isinstance(matching_approval.arguments, dict) else None,
                        resolved_by=str(matching_approval.resolved_by) if matching_approval.resolved_by else None,
                        resolved_by_username=resolver_map.get(str(matching_approval.resolved_by)) if matching_approval.resolved_by else None,
                        resolved_at=matching_approval.resolved_at.isoformat() if matching_approval.resolved_at else None,
                        rejection_reason=matching_approval.rejection_reason,
                        agent_id=matching_approval.agent_id,
                        created_at=matching_approval.created_at.isoformat() if matching_approval.created_at else None,
                    )

            # Find matching HITL question
            hitl_question_info = None
            if is_hitl and run_id_str:
                run_questions = hitl_by_run.get(run_id_str, [])
                # Match by question text from arguments
                question_text = tool_args.get("question", "")
                for q in run_questions:
                    if q.question and question_text and q.question.strip() == question_text.strip():
                        hitl_question_info = HITLQuestionInfo(
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
                        break

            # Find execution result - try all normalized variants of tool_name
            executed = False
            execution_status = None
            execution_result = None
            execution_error = None
            executed_at = None
            if run_id_str and not is_hitl:
                # Try all name variants to find a match
                matching_tc = None
                for variant in normalize_tool_name(tool_name):
                    tc_key = f"{run_id_str}:{variant}"
                    matching_tc = tool_calls_by_run_and_name.get(tc_key)
                    if matching_tc:
                        break
                if matching_tc:
                    executed = matching_tc.status in ("completed", "failed")
                    execution_status = matching_tc.status
                    execution_result = matching_tc.result
                    execution_error = matching_tc.error_message
                    executed_at = matching_tc.executed_at.isoformat() if matching_tc.executed_at else None

            enhanced_tool_calls.append(ToolCallDecision(
                id=tool_id,
                name=tool_name,
                arguments=tool_args,
                executed=executed,
                execution_status=execution_status,
                execution_result=execution_result,
                execution_error=execution_error,
                executed_at=executed_at,
                approval_required=approval_required,
                approval=approval_info,
                is_hitl_question=is_hitl,
                hitl_question=hitl_question_info,
                is_done_tool=is_done,
            ))

        llm_call_info = LLMCallInfo(
            id=str(lc.id),
            agent_id=agent_id,
            agent_run_id=run_id_str,
            provider=lc.provider,
            model=lc.model,
            token_usage=_to_token_usage(lc.prompt_tokens, lc.completion_tokens, lc.total_tokens),
            duration_ms=lc.duration_ms,
            request_messages=lc.request_messages,
            response_content=lc.response_content,
            response_tool_calls=enhanced_tool_calls,
            tools_provided=lc.tools_provided,
            created_at=lc.created_at.isoformat() if lc.created_at else None,
        )
        all_llm_calls.append(llm_call_info)
        if lc.agent_run_id:
            if run_id_str not in llm_calls_by_run:
                llm_calls_by_run[run_id_str] = []
            llm_calls_by_run[run_id_str].append(llm_call_info)

    # Build a map of tool_call_id -> approval for linking (for ToolCallInfo)
    approval_by_tool_call: dict[str, Any] = {}
    for a in approvals_raw:
        if a.tool_call_id:
            approval_by_tool_call[str(a.tool_call_id)] = a

    tool_calls_by_run: dict[str, list[ToolCallInfo]] = {}
    all_tool_calls: list[ToolCallInfo] = []

    for tc in tcs:
        # Check if there's an approval for this tool call
        approval = approval_by_tool_call.get(str(tc.id))
        approval_required = approval is not None
        approval_given = None
        approval_id = None
        approved_by = None
        rejected_reason = None

        if approval:
            approval_id = str(approval.id)
            if approval.status == "approved":
                approval_given = True
                approved_by = resolver_map.get(str(approval.resolved_by)) if approval.resolved_by else None
            elif approval.status == "rejected":
                approval_given = False
                rejected_reason = approval.rejection_reason
            # status == "pending" means approval_given stays None (waiting)

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
            approval_required=approval_required,
            approval_given=approval_given,
            approval_id=approval_id,
            approved_by=approved_by,
            rejected_reason=rejected_reason,
        )
        all_tool_calls.append(tool_call_info)
        if tc.agent_run_id:
            run_id_str = str(tc.agent_run_id)
            if run_id_str not in tool_calls_by_run:
                tool_calls_by_run[run_id_str] = []
            tool_calls_by_run[run_id_str].append(tool_call_info)

    # Build approvals_by_run for agent runs
    approvals_by_run: dict[str, list[ApprovalInfo]] = {}
    for a in approvals_raw:
        if a.agent_run_id:
            run_id_str = str(a.agent_run_id)
            if run_id_str not in approvals_by_run:
                approvals_by_run[run_id_str] = []
            approvals_by_run[run_id_str].append(ApprovalInfo(
                id=str(a.id),
                session_id=str(a.session_id),
                agent_run_id=run_id_str,
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
            ))

    # Build hitl_questions_by_run for agent runs
    hitl_questions_by_run: dict[str, list[HITLQuestionInfo]] = {}
    for q in questions_raw:
        if q.agent_run_id:
            run_id_str = str(q.agent_run_id)
            if run_id_str not in hitl_questions_by_run:
                hitl_questions_by_run[run_id_str] = []
            hitl_questions_by_run[run_id_str].append(HITLQuestionInfo(
                id=str(q.id),
                session_id=str(q.session_id),
                agent_run_id=run_id_str,
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
            ))

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
            hitl_questions=hitl_questions_by_run.get(str(r.id), []),
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
