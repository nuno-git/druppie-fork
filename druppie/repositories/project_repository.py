"""Project repository for database access."""

from uuid import UUID
from sqlalchemy import func

from .base import BaseRepository
from ..domain import (
    ProjectSummary,
    ProjectDetail,
    TokenUsage,
    SessionSummary,
    SessionStatus,
)
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

    def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ProjectSummary], int]:
        """List all projects (for admin)."""
        query = self.db.query(Project)
        total = query.count()
        projects = (
            query.order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(p) for p in projects], total

    def get_detail(self, project_id: UUID, session_limit: int = 10) -> ProjectDetail | None:
        """Get full project detail with stats and recent sessions."""
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

        # Get recent sessions
        sessions = self._get_recent_sessions(project_id, session_limit)

        return ProjectDetail(
            # Inherited from ProjectSummary
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url,
            created_at=project.created_at,
            # ProjectDetail specific
            owner_id=project.owner_id,
            repo_name=project.repo_name,
            token_usage=TokenUsage(
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                total_tokens=stats.total_tokens,
            ),
            session_count=stats.session_count,
            deployment=None,  # Filled by service via Docker MCP
            sessions=sessions,
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
            created_at=project.created_at,
        )

    def _get_recent_sessions(self, project_id: UUID, limit: int) -> list[SessionSummary]:
        """Get recent sessions for a project."""
        sessions = (
            self.db.query(SessionModel)
            .filter_by(project_id=project_id)
            .order_by(SessionModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._session_to_summary(s) for s in sessions]

    def _session_to_summary(self, session: SessionModel) -> SessionSummary:
        """Convert session model to summary."""
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            project_id=session.project_id,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
