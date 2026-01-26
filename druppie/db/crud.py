"""CRUD operations for Druppie database.

Simple database operations matching schema.sql.
NO JSON operations - everything is properly normalized.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .models import (
    AgentRun,
    Approval,
    Build,
    Deployment,
    HitlQuestion,
    HitlQuestionChoice,
    LlmCall,
    Message,
    Project,
    Session,
    ToolCall,
    ToolCallArgument,
    User,
    UserRole,
    UserToken,
    Workflow,
    WorkflowStep,
    Workspace,
)


def utcnow() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


# =============================================================================
# USER CRUD
# =============================================================================


def get_or_create_user(
    db: DBSession,
    user_id: UUID,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
    roles: list[str] | None = None,
) -> User:
    """Get or create a user (for Keycloak sync)."""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        user = User(
            id=user_id,
            username=username,
            email=email,
            display_name=display_name,
        )
        db.add(user)
        db.flush()
    else:
        user.username = username
        user.email = email
        user.display_name = display_name
        user.updated_at = utcnow()

    # Sync roles
    if roles is not None:
        # Remove old roles
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        # Add new roles
        for role in roles:
            db.add(UserRole(user_id=user_id, role=role))

    db.commit()
    return user


def get_user(db: DBSession, user_id: UUID) -> User | None:
    """Get a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_roles(db: DBSession, user_id: UUID) -> list[str]:
    """Get roles for a user."""
    roles = db.query(UserRole.role).filter(UserRole.user_id == user_id).all()
    return [r[0] for r in roles]


# =============================================================================
# SESSION CRUD
# =============================================================================


def create_session(
    db: DBSession,
    user_id: UUID | None = None,
    project_id: UUID | None = None,
    title: str | None = None,
) -> Session:
    """Create a new session."""
    session = Session(
        id=uuid4(),
        user_id=user_id,
        project_id=project_id,
        title=title,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: UUID) -> Session | None:
    """Get a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()


def update_session(
    db: DBSession,
    session_id: UUID,
    status: str | None = None,
    title: str | None = None,
    project_id: UUID | None = None,
) -> Session | None:
    """Update a session."""
    session = get_session(db, session_id)
    if not session:
        return None

    if status is not None:
        session.status = status
    if title is not None:
        session.title = title
    if project_id is not None:
        session.project_id = project_id
    session.updated_at = utcnow()

    db.commit()
    db.refresh(session)
    return session


def update_session_tokens(
    db: DBSession,
    session_id: UUID,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Add tokens to session totals."""
    session = get_session(db, session_id)
    if session:
        session.prompt_tokens = (session.prompt_tokens or 0) + prompt_tokens
        session.completion_tokens = (session.completion_tokens or 0) + completion_tokens
        session.total_tokens = (session.total_tokens or 0) + prompt_tokens + completion_tokens
        session.updated_at = utcnow()
        db.commit()


def list_sessions(
    db: DBSession,
    user_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Session]:
    """List sessions with optional filters."""
    query = db.query(Session)

    if user_id:
        query = query.filter(Session.user_id == user_id)
    if status:
        query = query.filter(Session.status == status)

    return query.order_by(Session.created_at.desc()).offset(offset).limit(limit).all()


def count_sessions(
    db: DBSession,
    user_id: UUID | None = None,
    status: str | None = None,
) -> int:
    """Count sessions with optional filters."""
    query = db.query(func.count(Session.id))

    if user_id:
        query = query.filter(Session.user_id == user_id)
    if status:
        query = query.filter(Session.status == status)

    return query.scalar() or 0


# =============================================================================
# WORKFLOW CRUD
# =============================================================================


def create_workflow(
    db: DBSession,
    session_id: UUID,
    name: str | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> Workflow:
    """Create a workflow with steps."""
    workflow = Workflow(
        id=uuid4(),
        session_id=session_id,
        name=name,
        status="pending",
        current_step=0,
    )
    db.add(workflow)
    db.flush()

    # Add steps
    if steps:
        for i, step_data in enumerate(steps):
            step = WorkflowStep(
                id=uuid4(),
                workflow_id=workflow.id,
                step_index=i,
                agent_id=step_data.get("agent_id", "unknown"),
                description=step_data.get("description"),
                status="pending",
            )
            db.add(step)

    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow(db: DBSession, workflow_id: UUID) -> Workflow | None:
    """Get a workflow by ID."""
    return db.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflow_for_session(db: DBSession, session_id: UUID) -> Workflow | None:
    """Get the active workflow for a session."""
    return (
        db.query(Workflow)
        .filter(Workflow.session_id == session_id)
        .order_by(Workflow.created_at.desc())
        .first()
    )


def update_workflow(
    db: DBSession,
    workflow_id: UUID,
    status: str | None = None,
    current_step: int | None = None,
) -> Workflow | None:
    """Update a workflow."""
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    if status is not None:
        workflow.status = status
    if current_step is not None:
        workflow.current_step = current_step

    db.commit()
    db.refresh(workflow)
    return workflow


def update_workflow_step(
    db: DBSession,
    step_id: UUID,
    status: str | None = None,
    result_summary: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> WorkflowStep | None:
    """Update a workflow step."""
    step = db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()
    if not step:
        return None

    if status is not None:
        step.status = status
    if result_summary is not None:
        step.result_summary = result_summary
    if started_at is not None:
        step.started_at = started_at
    if completed_at is not None:
        step.completed_at = completed_at

    db.commit()
    db.refresh(step)
    return step


# =============================================================================
# AGENT RUN CRUD
# =============================================================================


def create_agent_run(
    db: DBSession,
    session_id: UUID,
    agent_id: str,
    workflow_step_id: UUID | None = None,
    parent_run_id: UUID | None = None,
) -> AgentRun:
    """Create a new agent run."""
    agent_run = AgentRun(
        id=uuid4(),
        session_id=session_id,
        workflow_step_id=workflow_step_id,
        agent_id=agent_id,
        parent_run_id=parent_run_id,
        status="running",
        iteration_count=0,
    )
    db.add(agent_run)
    db.commit()
    db.refresh(agent_run)
    return agent_run


def get_agent_run(db: DBSession, run_id: UUID) -> AgentRun | None:
    """Get an agent run by ID."""
    return db.query(AgentRun).filter(AgentRun.id == run_id).first()


def get_active_agent_run(db: DBSession, session_id: UUID) -> AgentRun | None:
    """Get the active (running or paused) agent run for a session."""
    return (
        db.query(AgentRun)
        .filter(
            AgentRun.session_id == session_id,
            AgentRun.status.in_(["running", "paused_tool", "paused_hitl"]),
        )
        .order_by(AgentRun.started_at.desc())
        .first()
    )


def update_agent_run(
    db: DBSession,
    run_id: UUID,
    status: str | None = None,
    iteration_count: int | None = None,
    completed_at: datetime | None = None,
) -> AgentRun | None:
    """Update an agent run."""
    run = get_agent_run(db, run_id)
    if not run:
        return None

    if status is not None:
        run.status = status
    if iteration_count is not None:
        run.iteration_count = iteration_count
    if completed_at is not None:
        run.completed_at = completed_at

    db.commit()
    db.refresh(run)
    return run


def update_agent_run_tokens(
    db: DBSession,
    run_id: UUID,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Add tokens to agent run totals."""
    run = get_agent_run(db, run_id)
    if run:
        run.prompt_tokens = (run.prompt_tokens or 0) + prompt_tokens
        run.completion_tokens = (run.completion_tokens or 0) + completion_tokens
        run.total_tokens = (run.total_tokens or 0) + prompt_tokens + completion_tokens
        db.commit()


# =============================================================================
# MESSAGE CRUD
# =============================================================================


def create_message(
    db: DBSession,
    session_id: UUID,
    role: str,
    content: str,
    agent_run_id: UUID | None = None,
    agent_id: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
) -> Message:
    """Create a new message."""
    # Get next sequence number
    max_seq = (
        db.query(func.max(Message.sequence_number))
        .filter(Message.session_id == session_id)
        .scalar()
    )
    sequence_number = (max_seq or 0) + 1

    message = Message(
        id=uuid4(),
        session_id=session_id,
        agent_run_id=agent_run_id,
        role=role,
        content=content,
        agent_id=agent_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        sequence_number=sequence_number,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_messages_for_session(
    db: DBSession,
    session_id: UUID,
    limit: int | None = None,
) -> list[Message]:
    """Get all messages for a session in order."""
    query = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.sequence_number.asc())
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def get_messages_for_agent_run(
    db: DBSession,
    agent_run_id: UUID,
) -> list[Message]:
    """Get messages for a specific agent run."""
    return (
        db.query(Message)
        .filter(Message.agent_run_id == agent_run_id)
        .order_by(Message.sequence_number.asc())
        .all()
    )


# =============================================================================
# TOOL CALL CRUD
# =============================================================================


def create_tool_call(
    db: DBSession,
    session_id: UUID,
    agent_run_id: UUID,
    mcp_server: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> ToolCall:
    """Create a tool call with arguments."""
    tool_call = ToolCall(
        id=uuid4(),
        session_id=session_id,
        agent_run_id=agent_run_id,
        mcp_server=mcp_server,
        tool_name=tool_name,
        status="pending",
    )
    db.add(tool_call)
    db.flush()

    # Add arguments (normalized)
    if arguments:
        for arg_name, arg_value in arguments.items():
            arg = ToolCallArgument(
                tool_call_id=tool_call.id,
                arg_name=arg_name,
                arg_value=str(arg_value) if arg_value is not None else None,
            )
            db.add(arg)

    db.commit()
    db.refresh(tool_call)
    return tool_call


def get_tool_call(db: DBSession, tool_call_id: UUID) -> ToolCall | None:
    """Get a tool call by ID."""
    return db.query(ToolCall).filter(ToolCall.id == tool_call_id).first()


def update_tool_call(
    db: DBSession,
    tool_call_id: UUID,
    status: str | None = None,
    result: str | None = None,
    error_message: str | None = None,
) -> ToolCall | None:
    """Update a tool call."""
    tool_call = get_tool_call(db, tool_call_id)
    if not tool_call:
        return None

    if status is not None:
        tool_call.status = status
    if result is not None:
        tool_call.result = result
    if error_message is not None:
        tool_call.error_message = error_message
    if status in ["completed", "failed"]:
        tool_call.executed_at = utcnow()

    db.commit()
    db.refresh(tool_call)
    return tool_call


# =============================================================================
# APPROVAL CRUD
# =============================================================================


def create_approval(
    db: DBSession,
    session_id: UUID,
    approval_type: str,
    agent_run_id: UUID | None = None,
    tool_call_id: UUID | None = None,
    workflow_step_id: UUID | None = None,
    mcp_server: str | None = None,
    tool_name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    required_role: str | None = None,
) -> Approval:
    """Create an approval request."""
    approval = Approval(
        id=uuid4(),
        session_id=session_id,
        agent_run_id=agent_run_id,
        tool_call_id=tool_call_id,
        workflow_step_id=workflow_step_id,
        approval_type=approval_type,
        mcp_server=mcp_server,
        tool_name=tool_name,
        title=title,
        description=description,
        required_role=required_role,
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_approval(db: DBSession, approval_id: UUID) -> Approval | None:
    """Get an approval by ID."""
    return db.query(Approval).filter(Approval.id == approval_id).first()


def get_pending_approval_for_tool_call(db: DBSession, tool_call_id: UUID) -> Approval | None:
    """Get pending approval for a tool call."""
    return (
        db.query(Approval)
        .filter(Approval.tool_call_id == tool_call_id, Approval.status == "pending")
        .first()
    )


def resolve_approval(
    db: DBSession,
    approval_id: UUID,
    resolved_by: UUID,
    approved: bool,
    rejection_reason: str | None = None,
) -> Approval | None:
    """Approve or reject an approval."""
    approval = get_approval(db, approval_id)
    if not approval:
        return None

    approval.status = "approved" if approved else "rejected"
    approval.resolved_by = resolved_by
    approval.resolved_at = utcnow()
    if rejection_reason:
        approval.rejection_reason = rejection_reason

    db.commit()
    db.refresh(approval)
    return approval


def list_pending_approvals(
    db: DBSession,
    session_id: UUID | None = None,
    required_role: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List pending approvals."""
    query = db.query(Approval).filter(Approval.status == "pending")

    if session_id:
        query = query.filter(Approval.session_id == session_id)
    if required_role:
        query = query.filter(Approval.required_role == required_role)

    return query.order_by(Approval.created_at.desc()).limit(limit).all()


def list_approvals(
    db: DBSession,
    status: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List all approvals."""
    query = db.query(Approval)

    if status:
        query = query.filter(Approval.status == status)

    return query.order_by(Approval.created_at.desc()).limit(limit).all()


# =============================================================================
# HITL QUESTION CRUD
# =============================================================================


def create_hitl_question(
    db: DBSession,
    session_id: UUID,
    agent_run_id: UUID,
    question: str,
    question_type: str = "text",
    choices: list[str] | None = None,
) -> HitlQuestion:
    """Create a HITL question."""
    hitl_question = HitlQuestion(
        id=uuid4(),
        session_id=session_id,
        agent_run_id=agent_run_id,
        question=question,
        question_type=question_type,
        status="pending",
    )
    db.add(hitl_question)
    db.flush()

    # Add choices (normalized)
    if choices:
        for i, choice_text in enumerate(choices):
            choice = HitlQuestionChoice(
                question_id=hitl_question.id,
                choice_index=i,
                choice_text=choice_text,
                is_selected=False,
            )
            db.add(choice)

    db.commit()
    db.refresh(hitl_question)
    return hitl_question


def get_hitl_question(db: DBSession, question_id: UUID) -> HitlQuestion | None:
    """Get a HITL question by ID."""
    return db.query(HitlQuestion).filter(HitlQuestion.id == question_id).first()


def get_pending_hitl_question(db: DBSession, session_id: UUID) -> HitlQuestion | None:
    """Get the pending HITL question for a session."""
    return (
        db.query(HitlQuestion)
        .filter(HitlQuestion.session_id == session_id, HitlQuestion.status == "pending")
        .order_by(HitlQuestion.created_at.desc())
        .first()
    )


def answer_hitl_question(
    db: DBSession,
    question_id: UUID,
    answer: str,
    selected_choices: list[int] | None = None,
) -> HitlQuestion | None:
    """Answer a HITL question."""
    question = get_hitl_question(db, question_id)
    if not question:
        return None

    question.answer = answer
    question.answered_at = utcnow()
    question.status = "answered"

    # Mark selected choices
    if selected_choices:
        for choice in question.choices:
            choice.is_selected = choice.choice_index in selected_choices

    db.commit()
    db.refresh(question)
    return question


def list_pending_hitl_questions(
    db: DBSession,
    user_id: UUID | None = None,
    limit: int = 50,
) -> list[HitlQuestion]:
    """List pending HITL questions."""
    query = db.query(HitlQuestion).filter(HitlQuestion.status == "pending")

    if user_id:
        query = query.join(Session, HitlQuestion.session_id == Session.id).filter(
            Session.user_id == user_id
        )

    return query.order_by(HitlQuestion.created_at.desc()).limit(limit).all()


def get_hitl_questions_for_session(
    db: DBSession,
    session_id: UUID,
    status: str | None = None,
) -> list[HitlQuestion]:
    """Get all HITL questions for a session."""
    query = db.query(HitlQuestion).filter(HitlQuestion.session_id == session_id)

    if status:
        query = query.filter(HitlQuestion.status == status)

    return query.order_by(HitlQuestion.created_at.asc()).all()


# =============================================================================
# PROJECT CRUD
# =============================================================================


def create_project(
    db: DBSession,
    name: str,
    repo_name: str,
    description: str | None = None,
    repo_url: str | None = None,
    clone_url: str | None = None,
    owner_id: UUID | None = None,
) -> Project:
    """Create a new project."""
    project = Project(
        id=uuid4(),
        name=name,
        description=description,
        repo_name=repo_name,
        repo_url=repo_url,
        clone_url=clone_url,
        owner_id=owner_id,
        status="active",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: DBSession, project_id: UUID) -> Project | None:
    """Get a project by ID."""
    return db.query(Project).filter(Project.id == project_id).first()


def get_project_by_repo(db: DBSession, repo_name: str) -> Project | None:
    """Get a project by repository name."""
    return db.query(Project).filter(Project.repo_name == repo_name).first()


def list_projects(
    db: DBSession,
    owner_id: UUID | None = None,
    status: str | None = "active",
    limit: int = 50,
) -> list[Project]:
    """List projects."""
    query = db.query(Project)

    if owner_id:
        query = query.filter(Project.owner_id == owner_id)
    if status:
        query = query.filter(Project.status == status)

    return query.order_by(Project.created_at.desc()).limit(limit).all()


def update_project(
    db: DBSession,
    project_id: UUID,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> Project | None:
    """Update a project."""
    project = get_project(db, project_id)
    if not project:
        return None

    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if status is not None:
        project.status = status
    project.updated_at = utcnow()

    db.commit()
    db.refresh(project)
    return project


# =============================================================================
# WORKSPACE CRUD
# =============================================================================


def create_workspace(
    db: DBSession,
    session_id: UUID,
    project_id: UUID | None = None,
    branch: str = "main",
    local_path: str | None = None,
) -> Workspace:
    """Create a workspace."""
    workspace = Workspace(
        id=uuid4(),
        session_id=session_id,
        project_id=project_id,
        branch=branch,
        local_path=local_path,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def get_workspace(db: DBSession, workspace_id: UUID) -> Workspace | None:
    """Get a workspace by ID."""
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def get_workspace_for_session(db: DBSession, session_id: UUID) -> Workspace | None:
    """Get the workspace for a session."""
    return db.query(Workspace).filter(Workspace.session_id == session_id).first()


# =============================================================================
# BUILD CRUD
# =============================================================================


def create_build(
    db: DBSession,
    project_id: UUID,
    session_id: UUID | None = None,
    branch: str = "main",
) -> Build:
    """Create a build."""
    build = Build(
        id=uuid4(),
        project_id=project_id,
        session_id=session_id,
        branch=branch,
        status="pending",
    )
    db.add(build)
    db.commit()
    db.refresh(build)
    return build


def get_build(db: DBSession, build_id: UUID) -> Build | None:
    """Get a build by ID."""
    return db.query(Build).filter(Build.id == build_id).first()


def update_build(
    db: DBSession,
    build_id: UUID,
    status: str | None = None,
    build_logs: str | None = None,
) -> Build | None:
    """Update a build."""
    build = get_build(db, build_id)
    if not build:
        return None

    if status is not None:
        build.status = status
    if build_logs is not None:
        build.build_logs = build_logs

    db.commit()
    db.refresh(build)
    return build


def list_builds(
    db: DBSession,
    project_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[Build]:
    """List builds."""
    query = db.query(Build)

    if project_id:
        query = query.filter(Build.project_id == project_id)
    if status:
        query = query.filter(Build.status == status)

    return query.order_by(Build.created_at.desc()).limit(limit).all()


# =============================================================================
# DEPLOYMENT CRUD
# =============================================================================


def create_deployment(
    db: DBSession,
    project_id: UUID,
    build_id: UUID | None = None,
    container_name: str | None = None,
    container_id: str | None = None,
    host_port: int | None = None,
    app_url: str | None = None,
    is_preview: bool = True,
) -> Deployment:
    """Create a deployment."""
    deployment = Deployment(
        id=uuid4(),
        build_id=build_id,
        project_id=project_id,
        container_name=container_name,
        container_id=container_id,
        host_port=host_port,
        app_url=app_url,
        status="starting",
        is_preview=is_preview,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


def get_deployment(db: DBSession, deployment_id: UUID) -> Deployment | None:
    """Get a deployment by ID."""
    return db.query(Deployment).filter(Deployment.id == deployment_id).first()


def update_deployment(
    db: DBSession,
    deployment_id: UUID,
    status: str | None = None,
    container_id: str | None = None,
    host_port: int | None = None,
    app_url: str | None = None,
) -> Deployment | None:
    """Update a deployment."""
    deployment = get_deployment(db, deployment_id)
    if not deployment:
        return None

    if status is not None:
        deployment.status = status
        if status == "stopped":
            deployment.stopped_at = utcnow()
    if container_id is not None:
        deployment.container_id = container_id
    if host_port is not None:
        deployment.host_port = host_port
    if app_url is not None:
        deployment.app_url = app_url

    db.commit()
    db.refresh(deployment)
    return deployment


def get_running_deployments(
    db: DBSession,
    project_id: UUID | None = None,
) -> list[Deployment]:
    """Get running deployments."""
    query = db.query(Deployment).filter(Deployment.status == "running")

    if project_id:
        query = query.filter(Deployment.project_id == project_id)

    return query.all()


# =============================================================================
# LLM CALL CRUD
# =============================================================================


def create_llm_call(
    db: DBSession,
    session_id: UUID,
    agent_run_id: UUID,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: int | None = None,
) -> LlmCall:
    """Record an LLM API call."""
    llm_call = LlmCall(
        id=uuid4(),
        session_id=session_id,
        agent_run_id=agent_run_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        duration_ms=duration_ms,
    )
    db.add(llm_call)
    db.commit()
    db.refresh(llm_call)
    return llm_call


def get_llm_calls_for_session(db: DBSession, session_id: UUID) -> list[LlmCall]:
    """Get all LLM calls for a session."""
    return (
        db.query(LlmCall)
        .filter(LlmCall.session_id == session_id)
        .order_by(LlmCall.created_at.asc())
        .all()
    )
