"""Cache API routes.

Proxies to the sandbox manager to list cached dependency packages.

Endpoints:
- GET /cache/packages - List all cached packages grouped by package manager
"""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import httpx
import structlog

from druppie.api.deps import get_current_user
from druppie.core.sandbox_auth import generate_control_plane_token
from druppie.db.database import get_db

logger = structlog.get_logger()

router = APIRouter()

SANDBOX_MANAGER_URL = os.getenv("SANDBOX_MANAGER_URL", "http://sandbox-manager:8000")


@router.get("/cache/packages")
async def get_cached_packages(user: dict = Depends(get_current_user)):
    """List all cached dependency packages from the shared sandbox cache."""
    token = generate_control_plane_token()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{SANDBOX_MANAGER_URL}/api/cache/packages",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
    except httpx.ConnectError:
        logger.warning("sandbox_manager_unreachable", url=SANDBOX_MANAGER_URL)
        return {"managers": {}, "total_count": 0, "error": "Sandbox manager unreachable"}
    except Exception as e:
        logger.error("cache_packages_fetch_failed", error=str(e))
        return {"managers": {}, "total_count": 0, "error": str(e)}


@router.get("/cache/dependencies")
async def get_all_project_dependencies(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get all project-package mappings for the dependency cache view."""
    from druppie.db.models.project import Project
    from druppie.db.models.project_dependency import ProjectDependency

    rows = (
        db.query(
            ProjectDependency.manager,
            ProjectDependency.name,
            ProjectDependency.version,
            Project.id.label("project_id"),
            Project.name.label("project_name"),
        )
        .join(Project, ProjectDependency.project_id == Project.id)
        .order_by(Project.name, ProjectDependency.manager, ProjectDependency.name)
        .all()
    )

    # Group by project
    by_project: dict = {}
    for r in rows:
        pid = str(r.project_id)
        if pid not in by_project:
            by_project[pid] = {"project_id": pid, "project_name": r.project_name, "packages": []}
        by_project[pid]["packages"].append({
            "manager": r.manager,
            "name": r.name,
            "version": r.version,
        })

    return list(by_project.values())


@router.get("/cache/packages/{manager}/{name}/projects")
async def get_package_projects(
    manager: str,
    name: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Find which projects use a specific cached package."""
    from druppie.repositories import ProjectDependencyRepository

    dep_repo = ProjectDependencyRepository(db)
    return dep_repo.find_projects_using(manager, name)
