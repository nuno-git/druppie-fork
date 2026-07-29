"""Project repository for database access."""

import os
from urllib.parse import urljoin
from uuid import UUID

from sqlalchemy import func

from .base import BaseRepository
from ..db.models import Project, Session as SessionModel
from ..db.models.user import User as UserModel
from ..domain import (
    DocumentHouseStyle,
    ProjectDetail,
    ProjectSummary,
    SessionStatus,
    SessionSummary,
    TokenUsage,
)


def _derive_repo_url(repo_url: str | None, repo_owner: str | None, repo_name: str | None) -> str | None:
    """Construct repo_url from current GITEA_URL + repo_owner/repo_name.

    This ensures repo_url is always correct regardless of domain changes.
    Falls back to the stored repo_url if owner/name are missing.
    """
    if repo_owner and repo_name:
        gitea_url = os.getenv("GITEA_URL", "").rstrip("/")
        if gitea_url:
            return f"{gitea_url}/{repo_owner}/{repo_name}"
    return repo_url


def _project_repo_url(project: Project) -> str | None:
    """Convenience wrapper for Project model objects."""
    return _derive_repo_url(project.repo_url, project.repo_owner, project.repo_name)


class ProjectRepository(BaseRepository):
    """Database access for projects."""

    def get_by_id(self, project_id: UUID) -> Project | None:
        """Get raw project model."""
        return self.db.query(Project).filter_by(id=project_id).first()

    def get_by_user(self, user_id: UUID) -> list[Project]:
        """Get all projects for a user (for router injection)."""
        return (
            self.db.query(Project)
            .filter_by(owner_id=user_id)
            .order_by(Project.created_at.desc())
            .all()
        )

    def create(self, name: str, user_id: UUID, description: str | None = None) -> Project:
        """Create a new project."""
        project = Project(
            name=name,
            owner_id=user_id,
            description=description,
        )
        self.db.add(project)
        self.db.flush()
        return project

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
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=_project_repo_url(project),
            repo_name=project.repo_name,
            repo_owner=project.repo_owner,
            created_at=project.created_at,
            # ProjectDetail specific
            owner_id=project.owner_id,
            house_style=project.house_style,
            token_usage=TokenUsage(
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                total_tokens=stats.total_tokens,
            ),
            session_count=stats.session_count,
            deployment=None,  # Filled by service via Docker MCP
            sessions=sessions,
        )

    def update_repo(
        self,
        project_id: UUID,
        repo_name: str,
        repo_owner: str | None = None,
    ) -> None:
        """Update project with Gitea repository info.

        Only writes repo_name and repo_owner. The repo_url is resolved
        dynamically at read time using GiteaClient.get_public_url().
        """
        updates = {"repo_name": repo_name}
        if repo_owner:
            updates["repo_owner"] = repo_owner
        self.db.query(Project).filter_by(id=project_id).update(updates)

    def set_house_style(self, project_id: UUID, house_style: DocumentHouseStyle) -> None:
        """Update the corporate identity used for this project's documents."""
        self.db.query(Project).filter_by(id=project_id).update({"house_style": house_style})

    def delete(self, project_id: UUID) -> None:
        """Delete project."""
        self.db.query(Project).filter_by(id=project_id).delete()

    def delete_many(self, project_ids: list[UUID]) -> int:
        """Delete projects by IDs. Returns count deleted."""
        if not project_ids:
            return 0
        return self.db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session="fetch")

    def get_many_by_ids(self, project_ids: list[UUID]) -> list[Project]:
        """Get multiple projects by IDs."""
        if not project_ids:
            return []
        return self.db.query(Project).filter(Project.id.in_(project_ids)).all()

    def get_all_for_user(self, user_id: UUID | None) -> list[Project]:
        """Get all projects, optionally filtered by user."""
        query = self.db.query(Project)
        if user_id is not None:
            query = query.filter_by(owner_id=user_id)
        return query.all()

    def _to_summary(self, project: Project) -> ProjectSummary:
        """Convert project model to summary domain object."""
        # Look up username from users table
        username = None
        if project.owner_id:
            user = self.db.query(UserModel).filter_by(id=project.owner_id).first()
            if user:
                username = user.username

        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=_project_repo_url(project),
            repo_name=project.repo_name,
            repo_owner=project.repo_owner,
            username=username,
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
        # Look up username from users table
        username = None
        if session.user_id:
            user = self.db.query(UserModel).filter_by(id=session.user_id).first()
            if user:
                username = user.username
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=SessionStatus(session.status),
            project_id=session.project_id,
            username=username,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
