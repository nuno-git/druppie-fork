"""Projects API routes.

Simple project management - list, view detail, delete.

Architecture:
    Route (this file)
      │
      └──▶ Database (SQLAlchemy)
              (projects, sessions for token usage)

For deployment management (stop/restart/logs), see deployments.py.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func
import structlog

from druppie.api.deps import get_current_user, get_db, check_resource_ownership
from druppie.api.errors import NotFoundError
from druppie.db.models import Project, Session, Build, User

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class TokenUsage(BaseModel):
    """Token usage for transparency."""

    total_tokens: int = 0
    session_count: int = 0


class DeploymentInfo(BaseModel):
    """Deployment information embedded in project detail."""

    status: str
    app_url: str | None = None
    container_name: str | None = None
    started_at: str | None = None


class ProjectSummary(BaseModel):
    """Project summary for list view."""

    id: str
    name: str
    description: str | None = None
    repo_url: str | None = None
    status: str = "active"
    token_usage: TokenUsage
    created_at: str | None = None


class ProjectDetail(BaseModel):
    """Full project detail."""

    id: str
    name: str
    description: str | None = None
    repo_url: str | None = None
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    token_usage: TokenUsage
    deployment: DeploymentInfo | None = None


class ProjectListResponse(BaseModel):
    """Paginated project list response."""

    items: list[ProjectSummary]
    total: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_project_token_usage(db: DBSession, project_id: str) -> TokenUsage:
    """Get token usage for a project from its sessions."""
    result = db.query(
        func.coalesce(func.sum(Session.total_tokens), 0).label("total_tokens"),
        func.count(Session.id).label("session_count"),
    ).filter(Session.project_id == project_id).first()

    return TokenUsage(
        total_tokens=result.total_tokens or 0,
        session_count=result.session_count or 0,
    )


def get_deployment_info(db: DBSession, project_id: str) -> DeploymentInfo | None:
    """Get current deployment info from running build."""
    build = db.query(Build).filter(
        Build.project_id == project_id,
        Build.status == "running",
        Build.is_preview == False,
    ).first()

    if not build:
        return None

    return DeploymentInfo(
        status="running",
        app_url=build.app_url,
        container_name=build.container_name,
        started_at=build.created_at.isoformat() if build.created_at else None,
    )


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectListResponse:
    """List all projects for the current user.

    Admin users see all projects, others see only their own.

    Returns:
        List of projects with token usage stats
    """
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Query projects
    query = db.query(Project).filter(Project.status == "active")

    # Admin can see all, others only their own
    if "admin" not in roles:
        query = query.filter(Project.owner_id == user_id)

    projects = query.order_by(Project.created_at.desc()).all()

    # Batch load token usage (avoids N+1)
    project_ids = [str(p.id) for p in projects]
    token_results = db.query(
        Session.project_id,
        func.coalesce(func.sum(Session.total_tokens), 0).label("total_tokens"),
        func.count(Session.id).label("session_count"),
    ).filter(Session.project_id.in_(project_ids)).group_by(Session.project_id).all()

    tokens_by_project = {
        str(r.project_id): TokenUsage(
            total_tokens=r.total_tokens or 0,
            session_count=r.session_count or 0,
        )
        for r in token_results
    }

    items = [
        ProjectSummary(
            id=str(p.id),
            name=p.name,
            description=p.description,
            repo_url=p.repo_url,
            status=p.status,
            token_usage=tokens_by_project.get(str(p.id), TokenUsage()),
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in projects
    ]

    return ProjectListResponse(items=items, total=len(items))


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectDetail:
    """Get project detail.

    Includes token usage and current deployment status.

    Args:
        project_id: Project UUID

    Returns:
        Full project detail with deployment info

    Raises:
        NotFoundError: Project doesn't exist
        AuthorizationError: User doesn't own the project
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise NotFoundError("project", project_id)

    # Check ownership (admin can see all)
    check_resource_ownership(user, project.owner_id)

    token_usage = get_project_token_usage(db, project_id)
    deployment = get_deployment_info(db, project_id)

    return ProjectDetail(
        id=str(project.id),
        name=project.name,
        description=project.description,
        repo_url=project.repo_url,
        status=project.status,
        created_at=project.created_at.isoformat() if project.created_at else None,
        updated_at=project.updated_at.isoformat() if project.updated_at else None,
        token_usage=token_usage,
        deployment=deployment,
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> None:
    """Delete (archive) a project.

    Archives the project rather than deleting it to preserve data.
    Does not delete the Gitea repository.

    Args:
        project_id: Project UUID

    Raises:
        NotFoundError: Project doesn't exist
        AuthorizationError: User doesn't own the project
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise NotFoundError("project", project_id)

    # Check ownership
    check_resource_ownership(user, project.owner_id)

    # Archive (soft delete)
    project.status = "archived"
    db.commit()

    logger.info("project_archived", project_id=project_id)
