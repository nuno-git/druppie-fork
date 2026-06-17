"""Project service for business logic."""

from uuid import UUID
import structlog

from ..repositories import ProjectRepository
from ..core.gitea import get_gitea_client
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

    def list_all(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ProjectSummary], int]:
        """List all projects (admin only)."""
        offset = (page - 1) * limit
        return self.project_repo.list_all(limit, offset)

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

    async def delete(
        self,
        project_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Delete project and its Gitea repo (owner or admin only)."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("project", str(project_id))

        is_owner = project.owner_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        # Delete Gitea repository if one exists
        if project.repo_name:
            gitea = get_gitea_client()
            result = await gitea.delete_repo(project.repo_name, owner=project.repo_owner)
            if not result.get("success"):
                logger.warning(
                    "gitea_repo_delete_failed",
                    project_id=str(project_id),
                    repo_name=project.repo_name,
                    error=result.get("error"),
                )

        self.project_repo.delete(project_id)
        self.project_repo.commit()

        logger.info("project_deleted", project_id=str(project_id), by_user=str(user_id))

    async def delete_many(
        self,
        project_ids: list[UUID] | None,
        user_id: UUID,
        user_roles: list[str],
    ) -> int:
        """Delete multiple projects (or all for user). Cleans up Gitea repos."""
        is_admin = "admin" in user_roles

        if project_ids is not None:
            projects = self.project_repo.get_many_by_ids(project_ids)
            if not is_admin:
                projects = [p for p in projects if p.owner_id == user_id]
        else:
            projects = self.project_repo.get_all_for_user(None if is_admin else user_id)

        if not projects:
            return 0

        gitea = get_gitea_client()
        for project in projects:
            if project.repo_name:
                result = await gitea.delete_repo(project.repo_name, owner=project.repo_owner)
                if not result.get("success"):
                    logger.warning(
                        "gitea_repo_delete_failed",
                        project_id=str(project.id),
                        repo_name=project.repo_name,
                        error=result.get("error"),
                    )

        ids = [p.id for p in projects]
        count = self.project_repo.delete_many(ids)
        self.project_repo.commit()
        logger.info("projects_batch_deleted", count=count, by_user=str(user_id))
        return count
