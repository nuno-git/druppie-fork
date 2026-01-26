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
    workspace_id: str | None
    status: str
    state: dict | None = None
    created_at: str | None
    updated_at: str | None


class SessionListResponse(BaseModel):
    """Response for session listing."""

    sessions: list[SessionItem]
    pagination: PaginationInfo


class ApprovalItem(BaseModel):
    """Approval item for admin listing."""

    id: str
    session_id: str
    tool_name: str
    arguments: dict | None = None
    status: str
    required_roles: list[str] | None = None
    approvals_received: list[dict] | None = None
    danger_level: str
    description: str | None
    agent_id: str | None
    agent_state: dict | None = None
    approved_by: str | None
    approved_at: str | None
    rejected_by: str | None
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
    session_id: str
    agent_id: str
    question: str
    question_type: str
    choices: list[str] | None = None
    answer: str | None
    answered_at: str | None
    status: str
    created_at: str | None


class HitlQuestionListResponse(BaseModel):
    """Response for HITL question listing."""

    questions: list[HitlQuestionItem]
    pagination: PaginationInfo


class BuildItem(BaseModel):
    """Build item for admin listing."""

    id: str
    project_id: str
    branch: str
    status: str
    container_name: str | None
    port: int | None
    app_url: str | None
    is_preview: bool
    build_logs: str | None
    created_at: str | None
    updated_at: str | None


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
    search: str | None = Query(None, description="Search in user_id"),
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
        query = query.filter(Session.user_id.ilike(f"%{search}%"))

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
                id=s.id,
                user_id=s.user_id,
                project_id=s.project_id,
                workspace_id=s.workspace_id,
                status=s.status,
                state=s.state,
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
                id=a.id,
                session_id=a.session_id,
                tool_name=a.tool_name,
                arguments=a.arguments,
                status=a.status,
                required_roles=a.required_roles,
                approvals_received=a.approvals_received,
                danger_level=a.danger_level,
                description=a.description,
                agent_id=a.agent_id,
                agent_state=a.agent_state,
                approved_by=a.approved_by,
                approved_at=a.approved_at.isoformat() if a.approved_at else None,
                rejected_by=a.rejected_by,
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
                id=p.id,
                name=p.name,
                description=p.description,
                repo_name=p.repo_name,
                repo_url=p.repo_url,
                clone_url=p.clone_url,
                owner_id=p.owner_id,
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
    search: str | None = Query(None, description="Search in session_id or local_path"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all workspaces with pagination.

    Requires admin role.
    """
    page, limit = validate_pagination(page, limit)

    query = db.query(Workspace)

    if search:
        query = query.filter(
            (Workspace.session_id.ilike(f"%{search}%"))
            | (Workspace.local_path.ilike(f"%{search}%"))
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
                id=q.id,
                session_id=q.session_id,
                agent_id=q.agent_id,
                question=q.question,
                question_type=q.question_type,
                choices=q.choices,
                answer=q.answer,
                answered_at=q.answered_at.isoformat() if q.answered_at else None,
                status=q.status,
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
    search: str | None = Query(None, description="Search in container_name"),
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
        query = query.filter(Build.container_name.ilike(f"%{search}%"))

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
                id=b.id,
                project_id=b.project_id,
                branch=b.branch,
                status=b.status,
                container_name=b.container_name,
                port=b.port,
                app_url=b.app_url,
                is_preview=b.is_preview,
                build_logs=b.build_logs,
                created_at=b.created_at.isoformat() if b.created_at else None,
                updated_at=b.updated_at.isoformat() if b.updated_at else None,
            )
            for b in builds
        ],
        pagination=get_pagination(page, limit, total),
    )
