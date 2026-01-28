"""Project repository for database access."""

from uuid import UUID
from sqlalchemy import func

from .base import BaseRepository
from ..domain import ProjectSummary, ProjectDetail, TokenUsage
from ..db.models import Project, Session as SessionModel


class ProjectRepository(BaseRepository):
    """Database access for projects."""

    def get_by_id(self, project_id: UUID) -> Project | None:
        """Get raw project model."""
        return self.db.query(Project).filter_by(id=project_id).first()

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ProjectSummary], int]:
        """List projects for a user."""
        query = self.db.query(Project).filter_by(owner_id=user_id)
        total = query.count()
        projects = (
            query.order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(p) for p in projects], total

    def get_detail(self, project_id: UUID) -> ProjectDetail | None:
        """Get full project detail with stats."""
        project = self.get_by_id(project_id)
        if not project:
            return None

        # Get token stats from sessions
        stats = (
            self.db.query(
                func.coalesce(func.sum(SessionModel.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(SessionModel.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(SessionModel.completion_tokens), 0).label("completion_tokens"),
                func.count(SessionModel.id).label("session_count"),
            )
            .filter(SessionModel.project_id == project_id)
            .first()
        )

        return ProjectDetail(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            description=project.description,
            repo_name=project.repo_name,
            repo_url=project.repo_url,
            status=project.status,
            token_usage=TokenUsage(
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                total_tokens=stats.total_tokens,
            ),
            session_count=stats.session_count,
            deployment=None,  # Filled by service via Docker MCP
            created_at=project.created_at,
        )

    def delete(self, project_id: UUID) -> None:
        """Delete project."""
        self.db.query(Project).filter_by(id=project_id).delete()

    def _to_summary(self, project: Project) -> ProjectSummary:
        """Convert project model to summary domain object."""
        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url,
            status=project.status,
            created_at=project.created_at,
        )
