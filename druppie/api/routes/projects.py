"""Projects API routes.

Git-first architecture: Projects have Gitea repos, files are fetched from Gitea.
"""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.db import crud
from druppie.db.models import Project, Build, Workspace
from druppie.core.gitea import get_gitea_client, GiteaClient
from druppie.core.builder import get_builder_service, BuilderService

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class ProjectResponse(BaseModel):
    """Project response model."""

    id: str
    name: str
    description: str | None = None
    repo_name: str
    repo_url: str | None = None
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    # Build info
    main_build: dict | None = None
    preview_builds: list[dict] = []


class BuildResponse(BaseModel):
    """Build response model."""

    id: str
    project_id: str
    branch: str
    status: str
    container_name: str | None = None
    port: int | None = None
    app_url: str | None = None
    is_preview: bool = False
    created_at: str | None = None


class FileInfo(BaseModel):
    """File information from Gitea."""

    name: str
    path: str
    type: str  # "file" or "dir"
    size: int = 0
    sha: str | None = None


class ProjectFilesResponse(BaseModel):
    """Project files response."""

    project_id: str
    branch: str
    path: str
    files: list[FileInfo] = []


class FileContentResponse(BaseModel):
    """File content response."""

    project_id: str
    branch: str
    path: str
    content: str | None = None
    binary: bool = False
    size: int = 0
    sha: str | None = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def project_to_response(
    project: Project,
    main_build: Build | None = None,
    preview_builds: list[Build] | None = None,
) -> ProjectResponse:
    """Convert Project model to response."""
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        repo_name=project.repo_name,
        repo_url=project.repo_url,
        status=project.status,
        created_at=project.created_at.isoformat() if project.created_at else None,
        updated_at=project.updated_at.isoformat() if project.updated_at else None,
        main_build=main_build.to_dict() if main_build else None,
        preview_builds=[b.to_dict() for b in (preview_builds or [])],
    )


def build_to_response(build: Build) -> BuildResponse:
    """Convert Build model to response."""
    return BuildResponse(
        id=build.id,
        project_id=build.project_id,
        branch=build.branch,
        status=build.status,
        container_name=build.container_name,
        port=build.port,
        app_url=build.app_url,
        is_preview=build.is_preview,
        created_at=build.created_at.isoformat() if build.created_at else None,
    )


# =============================================================================
# PROJECT ROUTES
# =============================================================================


@router.get("/projects")
async def list_projects(
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[ProjectResponse]:
    """List all projects for the current user."""
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])

    # Query projects from database
    query = db.query(Project)

    # Admin can see all, others only see their own
    if "admin" not in roles:
        query = query.filter(Project.owner_id == user_id)

    projects = query.filter(Project.status == "active").order_by(Project.created_at.desc()).all()

    # Batch load all builds for all projects in one query (avoids N+1)
    builder = get_builder_service(db)
    project_ids = [p.id for p in projects]
    builds_by_project = builder.get_builds_for_projects(project_ids)

    # Build response using pre-loaded builds
    result = []
    for project in projects:
        build_info = builds_by_project.get(project.id, {"main": None, "previews": []})
        result.append(project_to_response(
            project,
            build_info["main"],
            build_info["previews"],
        ))

    return result


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectResponse:
    """Get a specific project."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership (admin can see all)
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this project")

    builder = get_builder_service(db)
    main_build = builder.get_main_build(project.id)
    preview_builds = builder.get_preview_builds(project.id)

    return project_to_response(project, main_build, preview_builds)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a project (archives it, doesn't delete repo)."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this project")

    # Stop any running builds
    builder = get_builder_service(db)
    builds = builder.get_builds_for_project(project_id)
    for build in builds:
        if build.status == "running":
            await builder.stop_project(build.id)

    # Archive project (don't delete repo for safety)
    project.status = "archived"
    db.commit()

    logger.info("project_archived", project_id=project_id)

    return {"success": True, "message": "Project archived"}


# =============================================================================
# FILE ROUTES (from Gitea)
# =============================================================================


@router.get("/projects/{project_id}/files")
async def list_project_files(
    project_id: str,
    path: str = "",
    branch: str = "main",
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectFilesResponse:
    """List files in a project from Gitea repo."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    gitea = get_gitea_client()
    result = await gitea.list_files(project.repo_name, path, branch)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list files: {result.get('error', 'Unknown error')}",
        )

    files = [
        FileInfo(
            name=f.get("name", ""),
            path=f.get("path", ""),
            type=f.get("type", "file"),
            size=f.get("size", 0),
            sha=f.get("sha"),
        )
        for f in result.get("files", [])
    ]

    return ProjectFilesResponse(
        project_id=project_id,
        branch=branch,
        path=path,
        files=files,
    )


@router.get("/projects/{project_id}/file")
async def get_project_file(
    project_id: str,
    path: str,
    branch: str = "main",
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> FileContentResponse:
    """Get file content from Gitea repo."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    gitea = get_gitea_client()
    result = await gitea.get_file(project.repo_name, path, branch)

    if not result.get("success"):
        raise HTTPException(
            status_code=404 if result.get("status_code") == 404 else 500,
            detail=f"Failed to get file: {result.get('error', 'Unknown error')}",
        )

    return FileContentResponse(
        project_id=project_id,
        branch=branch,
        path=path,
        content=result.get("content"),
        binary=result.get("binary", False),
        size=result.get("size", 0),
        sha=result.get("sha"),
    )


@router.get("/projects/{project_id}/branches")
async def list_project_branches(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """List branches for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    gitea = get_gitea_client()
    result = await gitea.list_branches(project.repo_name)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list branches: {result.get('error', 'Unknown error')}",
        )

    return {
        "project_id": project_id,
        "branches": result.get("branches", []),
        "count": result.get("count", 0),
    }


# =============================================================================
# BUILD ROUTES
# =============================================================================


@router.get("/projects/{project_id}/builds")
async def list_project_builds(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[BuildResponse]:
    """List all builds for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    builder = get_builder_service(db)
    builds = builder.get_builds_for_project(project_id)

    return [build_to_response(b) for b in builds]


@router.post("/projects/{project_id}/build")
async def build_project(
    project_id: str,
    branch: str = "main",
    is_preview: bool = False,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BuildResponse:
    """Build a project's Docker image."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to build this project")

    try:
        builder = get_builder_service(db)
        build = await builder.build_project(project_id, branch, is_preview)
        return build_to_response(build)
    except Exception as e:
        logger.error("build_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/run")
async def run_project(
    project_id: str,
    build_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BuildResponse:
    """Run a project's Docker container.

    If build_id is not provided, builds and runs the main branch.
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to run this project")

    try:
        builder = get_builder_service(db)

        if build_id:
            build = builder.get_build(build_id)
            if not build or build.project_id != project_id:
                raise HTTPException(status_code=404, detail="Build not found")
        else:
            # Build first if no build_id provided
            build = await builder.build_project(project_id, "main", is_preview=False)

        # Run the build
        build = await builder.run_project(build.id)
        return build_to_response(build)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("run_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/stop")
async def stop_project(
    project_id: str,
    build_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Stop a running project container.

    If build_id is not provided, stops the main (non-preview) build.
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to stop this project")

    try:
        builder = get_builder_service(db)

        if build_id:
            build = builder.get_build(build_id)
            if not build or build.project_id != project_id:
                raise HTTPException(status_code=404, detail="Build not found")
        else:
            # Stop main build
            build = builder.get_main_build(project_id)
            if not build:
                raise HTTPException(status_code=404, detail="No running build found")

        success = await builder.stop_project(build.id)

        return {"success": success, "message": "Project stopped" if success else "Failed to stop"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("stop_failed", project_id=project_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/status")
async def get_project_status(
    project_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Get project build/run status."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    builder = get_builder_service(db)
    main_build = builder.get_main_build(project_id)
    preview_builds = builder.get_preview_builds(project_id)

    return {
        "project_id": project_id,
        "main": {
            "status": main_build.status if main_build else "not_built",
            "url": main_build.app_url if main_build else None,
            "port": main_build.port if main_build else None,
        },
        "previews": [
            {
                "id": b.id,
                "branch": b.branch,
                "status": b.status,
                "url": b.app_url,
            }
            for b in preview_builds
        ],
    }


# =============================================================================
# GITEA DATA ROUTES (Commits, Branches)
# =============================================================================


@router.get("/projects/{project_id}/commits")
async def get_project_commits(
    project_id: str,
    branch: str = "main",
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Get recent commits from Gitea for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    gitea = get_gitea_client()

    # Gitea API: GET /repos/{owner}/{repo}/commits
    result = await gitea._request(
        "GET",
        f"/repos/{gitea.org}/{project.repo_name}/commits",
        params={"sha": branch, "limit": limit},
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch commits: {result.get('error', 'Unknown error')}",
        )

    commits = []
    for commit_data in result.get("data", []):
        commit = commit_data.get("commit", {})
        author = commit.get("author", {})
        committer = commit.get("committer", {})
        commits.append({
            "sha": commit_data.get("sha"),
            "short_sha": commit_data.get("sha", "")[:7],
            "message": commit.get("message", ""),
            "author": {
                "name": author.get("name"),
                "email": author.get("email"),
                "date": author.get("date"),
            },
            "committer": {
                "name": committer.get("name"),
                "email": committer.get("email"),
                "date": committer.get("date"),
            },
            "url": commit_data.get("html_url"),
        })

    return {
        "project_id": project_id,
        "branch": branch,
        "commits": commits,
        "count": len(commits),
    }


# =============================================================================
# SESSIONS LINKED TO PROJECT
# =============================================================================


@router.get("/projects/{project_id}/sessions")
async def get_project_sessions(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Get sessions (conversations) linked to a project."""
    from druppie.db.models import Session

    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Query sessions that have this project_id
    sessions = (
        db.query(Session)
        .filter(Session.project_id == project_id)
        .order_by(Session.updated_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "project_id": project_id,
        "sessions": [
            {
                "id": s.id,
                "status": s.status,
                "preview": s.preview,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ],
        "count": len(sessions),
    }


# =============================================================================
# PROJECT SETTINGS UPDATE
# =============================================================================


class ProjectUpdateRequest(BaseModel):
    """Request model for updating project settings."""

    name: str | None = None
    description: str | None = None


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    update_data: ProjectUpdateRequest,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectResponse:
    """Update project settings (name, description)."""
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check ownership
    user_id = user.get("sub")
    roles = user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles and project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this project")

    # Update fields if provided
    if update_data.name is not None:
        project.name = update_data.name
    if update_data.description is not None:
        project.description = update_data.description

    db.commit()
    db.refresh(project)

    logger.info("project_updated", project_id=project_id)

    builder = get_builder_service(db)
    main_build = builder.get_main_build(project.id)
    preview_builds = builder.get_preview_builds(project.id)

    return project_to_response(project, main_build, preview_builds)
