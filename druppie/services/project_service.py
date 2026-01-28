"""Project service for business logic."""

from uuid import UUID
import structlog

from ..repositories import ProjectRepository
from ..domain import ProjectDetail, ProjectSummary
from ..api.errors import NotFoundError, AuthorizationError

logger = structlog.get_logger()


class ProjectService:
    """Business logic for projects."""

    def __init__(self, project_repo: ProjectRepository):
        self.project_repo = project_repo

    def list_for_user(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ProjectSummary], int]:
        """List projects for a user."""
        offset = (page - 1) * limit
        return self.project_repo.list_for_user(user_id, limit, offset)

    def get_detail(
        self,
        project_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> ProjectDetail:
        """Get project detail with access check."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("project", str(project_id))

        is_owner = project.owner_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can view project")

        detail = self.project_repo.get_detail(project_id)
        if not detail:
            raise NotFoundError("project", str(project_id))

        return detail

    def delete(
        self,
        project_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Delete project (owner or admin only)."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("project", str(project_id))

        is_owner = project.owner_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        self.project_repo.delete(project_id)
        self.project_repo.commit()

        logger.info("project_deleted", project_id=str(project_id), by_user=str(user_id))
