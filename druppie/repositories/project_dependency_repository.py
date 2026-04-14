"""Repository for project dependency tracking."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from druppie.db.models.project_dependency import ProjectDependency

from .base import BaseRepository


class ProjectDependencyRepository(BaseRepository):
    """Data access for project_dependencies table."""

    def upsert_packages(self, project_id: UUID, packages: list[dict]) -> int:
        """Insert or update package dependencies for a project.

        Args:
            project_id: The project UUID.
            packages: List of {"manager": str, "name": str, "version": str}.

        Returns:
            Number of rows upserted.
        """
        if not packages:
            return 0

        now = datetime.now(timezone.utc)
        count = 0

        for pkg in packages:
            manager = pkg.get("manager", "").strip()
            name = pkg.get("name", "").strip()
            version = pkg.get("version", "").strip()
            if not manager or not name or not version:
                continue

            stmt = insert(ProjectDependency).values(
                project_id=project_id,
                manager=manager,
                name=name,
                version=version,
                first_seen_at=now,
                last_seen_at=now,
            ).on_conflict_do_update(
                constraint="uq_project_dep",
                set_={"last_seen_at": now},
            )
            self.db.execute(stmt)
            count += 1

        return count

    def list_for_project(self, project_id: UUID) -> list[ProjectDependency]:
        """Get all dependencies for a project, ordered by manager then name."""
        return (
            self.db.query(ProjectDependency)
            .filter_by(project_id=project_id)
            .order_by(ProjectDependency.manager, ProjectDependency.name)
            .all()
        )

    def find_projects_using(self, manager: str, name: str) -> list[dict]:
        """Find which projects use a specific package.

        Returns list of {project_id, project_name, version, last_seen_at}.
        """
        from druppie.db.models.project import Project

        rows = (
            self.db.query(
                ProjectDependency.project_id,
                Project.name.label("project_name"),
                ProjectDependency.version,
                ProjectDependency.last_seen_at,
            )
            .join(Project, ProjectDependency.project_id == Project.id)
            .filter(
                ProjectDependency.manager == manager,
                ProjectDependency.name == name,
            )
            .order_by(ProjectDependency.last_seen_at.desc())
            .all()
        )

        return [
            {
                "project_id": str(r.project_id),
                "project_name": r.project_name,
                "version": r.version,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
            for r in rows
        ]
