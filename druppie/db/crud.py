"""CRUD operations for Druppie database.

Simple database operations without complex ORM patterns.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from .models import Approval, Build, HitlQuestion, Project, Session, Workspace


# =============================================================================
# SESSION CRUD
# =============================================================================


def create_session(
    db: DBSession,
    session_id: str,
    user_id: str | None = None,
    status: str = "active",
) -> Session:
    """Create a new session."""
    session = Session(
        id=session_id,
        user_id=user_id,
        status=status,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: str) -> Session | None:
    """Get a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()


def update_session(
    db: DBSession,
    session_id: str,
    status: str | None = None,
    state: dict | None = None,
) -> Session | None:
    """Update a session."""
    session = get_session(db, session_id)
    if not session:
        return None

    if status is not None:
        session.status = status
    if state is not None:
        session.state = state
    session.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(session)
    return session


def delete_session(db: DBSession, session_id: str) -> bool:
    """Delete a session."""
    session = get_session(db, session_id)
    if not session:
        return False

    db.delete(session)
    db.commit()
    return True


def get_session_state(db: DBSession, session_id: str) -> dict | None:
    """Get execution state for a session."""
    session = get_session(db, session_id)
    if not session:
        return None
    return session.state


def save_session_state(db: DBSession, session_id: str, state: dict) -> bool:
    """Save execution state for a session."""
    session = get_session(db, session_id)
    if not session:
        # Create session if it doesn't exist
        session = create_session(db, session_id)

    session.state = state
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def delete_session_state(db: DBSession, session_id: str) -> bool:
    """Delete session state (but not the session itself)."""
    session = get_session(db, session_id)
    if not session:
        return False

    session.state = None
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def list_sessions(
    db: DBSession,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[Session]:
    """List sessions with optional filters."""
    query = db.query(Session)

    if user_id:
        query = query.filter(Session.user_id == user_id)
    if status:
        query = query.filter(Session.status == status)

    return query.order_by(Session.created_at.desc()).limit(limit).all()


def upsert_session(
    db: DBSession,
    session_id: str,
    user_id: str | None = None,
    status: str = "active",
    state: dict | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
) -> Session:
    """Create or update a session.

    This is the preferred method for saving sessions from the main loop.

    Args:
        db: Database session
        session_id: Session ID
        user_id: User ID
        status: Session status
        state: Session state dict
        project_id: Optional project ID to link session to
        workspace_id: Optional workspace ID to link session to
    """
    session = get_session(db, session_id)

    if session:
        # Update existing session
        if user_id is not None:
            session.user_id = user_id
        session.status = status
        if state is not None:
            session.state = state
        # Only update project_id/workspace_id if provided (don't overwrite with None)
        if project_id is not None:
            session.project_id = project_id
        if workspace_id is not None:
            session.workspace_id = workspace_id
        session.updated_at = datetime.now(timezone.utc)
    else:
        # Create new session
        session = Session(
            id=session_id,
            user_id=user_id,
            status=status,
            state=state,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        db.add(session)

    db.flush()
    return session


# =============================================================================
# APPROVAL CRUD
# =============================================================================


def create_approval(db: DBSession, data: dict[str, Any]) -> Approval:
    """Create a new approval request."""
    approval = Approval(
        id=data.get("id"),
        session_id=data.get("session_id"),
        tool_name=data.get("tool_name"),
        arguments=data.get("arguments"),
        status=data.get("status", "pending"),
        required_roles=data.get("required_roles"),
        approvals_received=data.get("approvals_received", []),
        danger_level=data.get("danger_level", "low"),
        description=data.get("description"),
        agent_id=data.get("agent_id"),
        agent_state=data.get("agent_state"),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_approval(db: DBSession, approval_id: str) -> Approval | None:
    """Get an approval by ID."""
    return db.query(Approval).filter(Approval.id == approval_id).first()


def update_approval(db: DBSession, approval_id: str, data: dict[str, Any]) -> Approval | None:
    """Update an approval."""
    approval = get_approval(db, approval_id)
    if not approval:
        return None

    if "status" in data:
        approval.status = data["status"]
    if "approvals_received" in data:
        approval.approvals_received = data["approvals_received"]
    if "approved_by" in data:
        approval.approved_by = data["approved_by"]
    if "approved_at" in data:
        approval.approved_at = data["approved_at"]
    if "rejected_by" in data:
        approval.rejected_by = data["rejected_by"]
    if "rejection_reason" in data:
        approval.rejection_reason = data["rejection_reason"]
    if "agent_state" in data:
        approval.agent_state = data["agent_state"]

    db.commit()
    db.refresh(approval)
    return approval


def list_pending_approvals(
    db: DBSession,
    session_id: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List pending approvals."""
    query = db.query(Approval).filter(Approval.status == "pending")

    if session_id:
        query = query.filter(Approval.session_id == session_id)

    return query.order_by(Approval.created_at.desc()).limit(limit).all()


def list_approvals_for_session(db: DBSession, session_id: str) -> list[Approval]:
    """List all approvals for a session."""
    return (
        db.query(Approval)
        .filter(Approval.session_id == session_id)
        .order_by(Approval.created_at.desc())
        .all()
    )


def list_approvals(
    db: DBSession,
    status: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List all approvals with optional status filter."""
    query = db.query(Approval)

    if status:
        query = query.filter(Approval.status == status)

    return query.order_by(Approval.created_at.desc()).limit(limit).all()


def list_approvals_for_roles(
    db: DBSession,
    user_roles: list[str],
    status: str | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List approvals that a user with given roles can approve.

    Filters approvals where required_roles overlaps with user_roles.
    """
    query = db.query(Approval)

    if status:
        query = query.filter(Approval.status == status)

    approvals = query.order_by(Approval.created_at.desc()).limit(limit).all()

    # Filter by roles (JSON array comparison not easy in SQL, do it in Python)
    filtered = []
    for approval in approvals:
        required = approval.required_roles or []
        if not required or any(r in user_roles for r in required):
            filtered.append(approval)

    return filtered


# =============================================================================
# PROJECT CRUD
# =============================================================================


def create_project(
    db: DBSession,
    project_id: str,
    name: str,
    repo_name: str,
    description: str | None = None,
    repo_url: str | None = None,
    clone_url: str | None = None,
    owner_id: str | None = None,
) -> Project:
    """Create a new project."""
    project = Project(
        id=project_id,
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


def get_project(db: DBSession, project_id: str) -> Project | None:
    """Get a project by ID."""
    return db.query(Project).filter(Project.id == project_id).first()


def get_project_by_repo(db: DBSession, repo_name: str) -> Project | None:
    """Get a project by repository name."""
    return db.query(Project).filter(Project.repo_name == repo_name).first()


def list_projects(
    db: DBSession,
    owner_id: str | None = None,
    status: str | None = "active",
    limit: int = 50,
) -> list[Project]:
    """List projects with optional filters."""
    query = db.query(Project)

    if owner_id:
        query = query.filter(Project.owner_id == owner_id)
    if status:
        query = query.filter(Project.status == status)

    return query.order_by(Project.created_at.desc()).limit(limit).all()


def update_project(
    db: DBSession,
    project_id: str,
    data: dict[str, Any],
) -> Project | None:
    """Update a project."""
    project = get_project(db, project_id)
    if not project:
        return None

    for key, value in data.items():
        if hasattr(project, key):
            setattr(project, key, value)

    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: DBSession, project_id: str) -> bool:
    """Delete a project (or archive it)."""
    project = get_project(db, project_id)
    if not project:
        return False

    project.status = "archived"
    db.commit()
    return True


# =============================================================================
# BUILD CRUD
# =============================================================================


def create_build(
    db: DBSession,
    build_id: str,
    project_id: str,
    branch: str = "main",
    is_preview: bool = False,
) -> Build:
    """Create a new build."""
    build = Build(
        id=build_id,
        project_id=project_id,
        branch=branch,
        status="pending",
        is_preview=is_preview,
    )
    db.add(build)
    db.commit()
    db.refresh(build)
    return build


def get_build(db: DBSession, build_id: str) -> Build | None:
    """Get a build by ID."""
    return db.query(Build).filter(Build.id == build_id).first()


def list_builds(
    db: DBSession,
    project_id: str | None = None,
    status: str | None = None,
    is_preview: bool | None = None,
    limit: int = 50,
) -> list[Build]:
    """List builds with optional filters."""
    query = db.query(Build)

    if project_id:
        query = query.filter(Build.project_id == project_id)
    if status:
        query = query.filter(Build.status == status)
    if is_preview is not None:
        query = query.filter(Build.is_preview == is_preview)

    return query.order_by(Build.created_at.desc()).limit(limit).all()


def update_build(
    db: DBSession,
    build_id: str,
    data: dict[str, Any],
) -> Build | None:
    """Update a build."""
    build = get_build(db, build_id)
    if not build:
        return None

    for key, value in data.items():
        if hasattr(build, key):
            setattr(build, key, value)

    build.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(build)
    return build


def get_running_build(
    db: DBSession,
    project_id: str,
    is_preview: bool = False,
) -> Build | None:
    """Get the running build for a project."""
    return (
        db.query(Build)
        .filter(
            Build.project_id == project_id,
            Build.status == "running",
            Build.is_preview == is_preview,
        )
        .first()
    )


# =============================================================================
# WORKSPACE CRUD
# =============================================================================


def create_workspace(
    db: DBSession,
    workspace_id: str,
    session_id: str,
    project_id: str | None = None,
    branch: str = "main",
    local_path: str | None = None,
    is_new_project: bool = False,
) -> Workspace:
    """Create a new workspace."""
    workspace = Workspace(
        id=workspace_id,
        session_id=session_id,
        project_id=project_id,
        branch=branch,
        local_path=local_path,
        is_new_project=is_new_project,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def get_workspace(db: DBSession, workspace_id: str) -> Workspace | None:
    """Get a workspace by ID."""
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def get_workspace_by_session(db: DBSession, session_id: str) -> Workspace | None:
    """Get a workspace by session ID."""
    return db.query(Workspace).filter(Workspace.session_id == session_id).first()


def list_workspaces(
    db: DBSession,
    project_id: str | None = None,
    limit: int = 50,
) -> list[Workspace]:
    """List workspaces with optional filters."""
    query = db.query(Workspace)

    if project_id:
        query = query.filter(Workspace.project_id == project_id)

    return query.order_by(Workspace.created_at.desc()).limit(limit).all()


def update_workspace(
    db: DBSession,
    workspace_id: str,
    data: dict[str, Any],
) -> Workspace | None:
    """Update a workspace."""
    workspace = get_workspace(db, workspace_id)
    if not workspace:
        return None

    for key, value in data.items():
        if hasattr(workspace, key):
            setattr(workspace, key, value)

    db.commit()
    db.refresh(workspace)
    return workspace


def delete_workspace(db: DBSession, workspace_id: str) -> bool:
    """Delete a workspace."""
    workspace = get_workspace(db, workspace_id)
    if not workspace:
        return False

    db.delete(workspace)
    db.commit()
    return True


# =============================================================================
# HITL QUESTION CRUD
# =============================================================================


def create_hitl_question(
    db: DBSession,
    question_id: str,
    session_id: str,
    agent_id: str,
    question: str,
    question_type: str = "text",
    choices: list[str] | None = None,
) -> HitlQuestion:
    """Create a new HITL question."""
    hitl_question = HitlQuestion(
        id=question_id,
        session_id=session_id,
        agent_id=agent_id,
        question=question,
        question_type=question_type,
        choices=choices,
        status="pending",
    )
    db.add(hitl_question)
    db.commit()
    db.refresh(hitl_question)
    return hitl_question


def get_hitl_question(db: DBSession, question_id: str) -> HitlQuestion | None:
    """Get a HITL question by ID."""
    return db.query(HitlQuestion).filter(HitlQuestion.id == question_id).first()


def get_hitl_questions_for_session(
    db: DBSession,
    session_id: str,
    status: str | None = None,
) -> list[HitlQuestion]:
    """Get all HITL questions for a session."""
    query = db.query(HitlQuestion).filter(HitlQuestion.session_id == session_id)

    if status:
        query = query.filter(HitlQuestion.status == status)

    return query.order_by(HitlQuestion.created_at.desc()).all()


def list_pending_hitl_questions(
    db: DBSession,
    user_id: str | None = None,
    limit: int = 50,
) -> list[HitlQuestion]:
    """List all pending HITL questions.

    If user_id is provided, filter by sessions owned by that user.
    """
    query = db.query(HitlQuestion).filter(HitlQuestion.status == "pending")

    if user_id:
        # Join with sessions to filter by user
        query = query.join(Session, HitlQuestion.session_id == Session.id).filter(
            Session.user_id == user_id
        )

    return query.order_by(HitlQuestion.created_at.desc()).limit(limit).all()


def answer_hitl_question(
    db: DBSession,
    question_id: str,
    answer: str,
) -> HitlQuestion | None:
    """Answer a HITL question."""
    question = get_hitl_question(db, question_id)
    if not question:
        return None

    question.answer = answer
    question.answered_at = datetime.now(timezone.utc)
    question.status = "answered"

    db.commit()
    db.refresh(question)
    return question


def expire_hitl_question(db: DBSession, question_id: str) -> HitlQuestion | None:
    """Mark a HITL question as expired."""
    question = get_hitl_question(db, question_id)
    if not question:
        return None

    question.status = "expired"

    db.commit()
    db.refresh(question)
    return question


def list_hitl_questions(
    db: DBSession,
    status: str | None = None,
    limit: int = 50,
) -> list[HitlQuestion]:
    """List all HITL questions with optional status filter."""
    query = db.query(HitlQuestion)

    if status:
        query = query.filter(HitlQuestion.status == status)

    return query.order_by(HitlQuestion.created_at.desc()).limit(limit).all()
