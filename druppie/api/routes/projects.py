"""Projects API routes.

Simple project management - list, view detail, delete.

Architecture:
    Route (this file)
      │
      └──▶ ProjectService ──▶ ProjectRepository ──▶ Database

For deployment management (stop/restart/logs), see deployments.py.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user, get_project_service, get_user_roles
from druppie.services import ProjectService
from druppie.domain import ProjectSummary, ProjectDetail

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS (list wrapper only - items use domain models)
# =============================================================================


class ProjectListResponse(BaseModel):
    """Paginated project list response."""

    items: list[ProjectSummary]
    total: int
    page: int
    limit: int


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    page: int = 1,
    limit: int = 20,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> ProjectListResponse:
    """List projects for the current user.

    Admin users see all projects, others see only their own.

    Args:
        page: Page number (1-indexed)
        limit: Items per page

    Returns:
        Paginated list of projects with token usage stats
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Admin sees all projects, others see their own
    if "admin" in user_roles:
        # For admin, pass None to get all
        items, total = service.list_all(page=page, limit=limit)
    else:
        items, total = service.list_for_user(user_id, page=page, limit=limit)

    return ProjectListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
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
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    return service.get_detail(project_id, user_id, user_roles)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
    user: dict = Depends(get_current_user),
) -> None:
    """Delete a project and its Gitea repository.

    Args:
        project_id: Project UUID

    Raises:
        NotFoundError: Project doesn't exist
        AuthorizationError: User doesn't own the project
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    await service.delete(project_id, user_id, user_roles)
