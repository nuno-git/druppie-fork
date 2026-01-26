"""Admin API routes for database exploration.

Admin-only endpoints for viewing and exploring database tables.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func
import structlog

from druppie.api.deps import get_db, require_admin
from druppie.db.models import Session, Approval, Project, Workspace, HitlQuestion, Build

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class PaginationInfo(BaseModel):
    """Pagination info for list responses."""

    page: int
    limit: int
    total: int
    total_pages: int


class SessionItem(BaseModel):
    """Session item for admin listing."""

    id: str
    user_id: str | None
    project_id: str | None
    title: str | None
    status: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: str | None
    updated_at: str | None


class SessionListResponse(BaseModel):
    """Response for session listing."""

    sessions: list[SessionItem]
    pagination: PaginationInfo


class ApprovalItem(BaseModel):
    """Approval item for admin listing."""

    id: str
    session_id: str | None
    agent_run_id: str | None
    tool_call_id: str | None
    workflow_step_id: str | None
    approval_type: str
    mcp_server: str | None
    tool_name: str | None
    title: str | None
    description: str | None
    required_role: str | None
    status: str
    resolved_by: str | None
    resolved_at: str | None
    rejection_reason: str | None
    created_at: str | None


class ApprovalListResponse(BaseModel):
    """Response for approval listing."""

    approvals: list[ApprovalItem]
    pagination: PaginationInfo


class ProjectItem(BaseModel):
    """Project item for admin listing."""

    id: str
    name: str
    description: str | None
    repo_name: str
    repo_url: str | None
    clone_url: str | None
    owner_id: str | None
    status: str
    created_at: str | None
    updated_at: str | None


class ProjectListResponse(BaseModel):
    """Response for project listing."""

    projects: list[ProjectItem]
    pagination: PaginationInfo


class WorkspaceItem(BaseModel):
    """Workspace item for admin listing."""

    id: str
    session_id: str
    project_id: str | None
    branch: str
    local_path: str | None
    created_at: str | None


class WorkspaceListResponse(BaseModel):
    """Response for workspace listing."""

    workspaces: list[WorkspaceItem]
    pagination: PaginationInfo


class HitlQuestionItem(BaseModel):
    """HITL question item for admin listing."""

    id: str
    session_id: str | None
    agent_run_id: str | None
    question: str
    question_type: str
    status: str
    answer: str | None
    answered_at: str | None
    created_at: str | None


class HitlQuestionListResponse(BaseModel):
    """Response for HITL question listing."""

    questions: list[HitlQuestionItem]
    pagination: PaginationInfo


class BuildItem(BaseModel):
    """Build item for admin listing."""

    id: str
    project_id: str | None
    session_id: str | None
    branch: str
    status: str
    build_logs: str | None
    created_at: str | None


class BuildListResponse(BaseModel):
    """Response for build listing."""

    builds: list[BuildItem]
    pagination: PaginationInfo


class TableStats(BaseModel):
    """Statistics for a database table."""

    name: str
    count: int


class DatabaseStatsResponse(BaseModel):
    """Response for database stats."""

    tables: list[TableStats]
    total_records: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


MAX_LIMIT = 100


def get_pagination(page: int, limit: int, total: int) -> PaginationInfo:
    """Create pagination info."""
    return PaginationInfo(
        page=page,
        limit=limit,
        total=total,
        total_pages=(total + limit - 1) // limit if limit > 0 else 0,
    )


def validate_pagination(page: int, limit: int) -> tuple[int, int]:
    """Validate and constrain pagination parameters."""
    if page < 1:
        page = 1
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    return page, limit


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/stats", response_model=DatabaseStatsResponse)
async def get_database_stats(
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Get database statistics (record counts per table).

    Requires admin role.
    """
    tables = [
        TableStats(name="sessions", count=db.query(func.count(Session.id)).scalar() or 0),
        TableStats(name="approvals", count=db.query(func.count(Approval.id)).scalar() or 0),
        TableStats(name="projects", count=db.query(func.count(Project.id)).scalar() or 0),
        TableStats(name="workspaces", count=db.query(func.count(Workspace.id)).scalar() or 0),
        TableStats(name="hitl_questions", count=db.query(func.count(HitlQuestion.id)).scalar() or 0),
        TableStats(name="builds", count=db.query(func.count(Build.id)).scalar() or 0),
    ]

    total_records = sum(t.count for t in tables)

    logger.info("admin_stats_retrieved", user_id=user.get("sub"), total_records=total_records)

    return DatabaseStatsResponse(tables=tables, total_records=total_records)


@router.get("/sessions", response_model=SessionListResponse)
async def list_all_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in title"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all sessions with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Session)

    if status:
        query = query.filter(Session.status == status)

    if search:
        # Search in title (user_id is UUID, can't ilike)
        query = query.filter(Session.title.ilike(f"%{search}%"))

    total = query.count()
    offset = (page - 1) * limit

    sessions = (
        query.order_by(Session.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_sessions_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return SessionListResponse(
        sessions=[
            SessionItem(
                id=str(s.id),
                user_id=str(s.user_id) if s.user_id else None,
                project_id=str(s.project_id) if s.project_id else None,
                title=s.title,
                status=s.status,
                prompt_tokens=s.prompt_tokens or 0,
                completion_tokens=s.completion_tokens or 0,
                total_tokens=s.total_tokens or 0,
                created_at=s.created_at.isoformat() if s.created_at else None,
                updated_at=s.updated_at.isoformat() if s.updated_at else None,
            )
            for s in sessions
        ],
        pagination=get_pagination(page, limit, total),
    )


@router.get("/approvals", response_model=ApprovalListResponse)
async def list_all_approvals(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in tool_name"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all approvals with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Approval)

    if status:
        query = query.filter(Approval.status == status)

    if search:
        query = query.filter(Approval.tool_name.ilike(f"%{search}%"))

    total = query.count()
    offset = (page - 1) * limit

    approvals = (
        query.order_by(Approval.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_approvals_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return ApprovalListResponse(
        approvals=[
            ApprovalItem(
                id=str(a.id),
                session_id=str(a.session_id) if a.session_id else None,
                agent_run_id=str(a.agent_run_id) if a.agent_run_id else None,
                tool_call_id=str(a.tool_call_id) if a.tool_call_id else None,
                workflow_step_id=str(a.workflow_step_id) if a.workflow_step_id else None,
                approval_type=a.approval_type,
                mcp_server=a.mcp_server,
                tool_name=a.tool_name,
                title=a.title,
                description=a.description,
                required_role=a.required_role,
                status=a.status,
                resolved_by=str(a.resolved_by) if a.resolved_by else None,
                resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
                rejection_reason=a.rejection_reason,
                created_at=a.created_at.isoformat() if a.created_at else None,
            )
            for a in approvals
        ],
        pagination=get_pagination(page, limit, total),
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_all_projects(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in name or repo_name"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all projects with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Project)

    if status:
        query = query.filter(Project.status == status)

    if search:
        query = query.filter(
            (Project.name.ilike(f"%{search}%")) | (Project.repo_name.ilike(f"%{search}%"))
        )

    total = query.count()
    offset = (page - 1) * limit

    projects = (
        query.order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_projects_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return ProjectListResponse(
        projects=[
            ProjectItem(
                id=str(p.id),
                name=p.name,
                description=p.description,
                repo_name=p.repo_name,
                repo_url=p.repo_url,
                clone_url=p.clone_url,
                owner_id=str(p.owner_id) if p.owner_id else None,
                status=p.status,
                created_at=p.created_at.isoformat() if p.created_at else None,
                updated_at=p.updated_at.isoformat() if p.updated_at else None,
            )
            for p in projects
        ],
        pagination=get_pagination(page, limit, total),
    )


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_all_workspaces(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    search: str | None = Query(None, description="Search in local_path or branch"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all workspaces with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Workspace)

    if search:
        # Search in local_path and branch (session_id is UUID, can't ilike)
        query = query.filter(
            (Workspace.local_path.ilike(f"%{search}%"))
            | (Workspace.branch.ilike(f"%{search}%"))
        )

    total = query.count()
    offset = (page - 1) * limit

    workspaces = (
        query.order_by(Workspace.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_workspaces_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return WorkspaceListResponse(
        workspaces=[
            WorkspaceItem(
                id=str(w.id),
                session_id=str(w.session_id) if w.session_id else None,
                project_id=str(w.project_id) if w.project_id else None,
                branch=w.branch,
                local_path=w.local_path,
                created_at=w.created_at.isoformat() if w.created_at else None,
            )
            for w in workspaces
        ],
        pagination=get_pagination(page, limit, total),
    )


@router.get("/hitl-questions", response_model=HitlQuestionListResponse)
async def list_all_hitl_questions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in question text"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all HITL questions with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(HitlQuestion)

    if status:
        query = query.filter(HitlQuestion.status == status)

    if search:
        query = query.filter(HitlQuestion.question.ilike(f"%{search}%"))

    total = query.count()
    offset = (page - 1) * limit

    questions = (
        query.order_by(HitlQuestion.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_hitl_questions_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return HitlQuestionListResponse(
        questions=[
            HitlQuestionItem(
                id=str(q.id),
                session_id=str(q.session_id) if q.session_id else None,
                agent_run_id=str(q.agent_run_id) if q.agent_run_id else None,
                question=q.question,
                question_type=q.question_type,
                status=q.status,
                answer=q.answer,
                answered_at=q.answered_at.isoformat() if q.answered_at else None,
                created_at=q.created_at.isoformat() if q.created_at else None,
            )
            for q in questions
        ],
        pagination=get_pagination(page, limit, total),
    )


@router.get("/builds", response_model=BuildListResponse)
async def list_all_builds(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT, description="Items per page"),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in branch"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all builds with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Build)

    if status:
        query = query.filter(Build.status == status)

    if search:
        query = query.filter(Build.branch.ilike(f"%{search}%"))

    total = query.count()
    offset = (page - 1) * limit

    builds = (
        query.order_by(Build.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.info(
        "admin_builds_listed",
        user_id=user.get("sub"),
        page=page,
        limit=limit,
        total=total,
    )

    return BuildListResponse(
        builds=[
            BuildItem(
                id=str(b.id),
                project_id=str(b.project_id) if b.project_id else None,
                session_id=str(b.session_id) if b.session_id else None,
                branch=b.branch,
                status=b.status,
                build_logs=b.build_logs,
                created_at=b.created_at.isoformat() if b.created_at else None,
            )
            for b in builds
        ],
        pagination=get_pagination(page, limit, total),
    )
