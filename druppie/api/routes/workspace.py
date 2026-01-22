"""Workspace API routes.

Endpoints for accessing workspace files and directories.
Workspaces are the local git-based sandboxes where agents write code.
"""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.api.errors import NotFoundError, ValidationError
from druppie.db import crud
from druppie.db.models import Workspace, Project

logger = structlog.get_logger()

router = APIRouter()

# Workspace root directory
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class FileInfo(BaseModel):
    """File information."""

    name: str
    path: str
    type: str  # "file" or "directory"
    size: int = 0


class WorkspaceResponse(BaseModel):
    """Workspace response model."""

    id: str
    session_id: str
    project_id: str | None = None
    branch: str
    local_path: str | None = None
    is_new_project: bool = False
    created_at: str | None = None
    # Project info if available
    project_name: str | None = None
    project_repo_url: str | None = None


class WorkspaceFilesResponse(BaseModel):
    """Workspace files listing response."""

    workspace_id: str | None = None
    session_id: str | None = None
    path: str
    files: list[FileInfo] = []
    directories: list[FileInfo] = []
    count: int = 0


class FileContentResponse(BaseModel):
    """File content response."""

    path: str
    content: str | None = None
    binary: bool = False
    size: int = 0


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def workspace_to_response(workspace: Workspace, project: Project | None = None) -> WorkspaceResponse:
    """Convert Workspace model to response."""
    return WorkspaceResponse(
        id=workspace.id,
        session_id=workspace.session_id,
        project_id=workspace.project_id,
        branch=workspace.branch,
        local_path=workspace.local_path,
        is_new_project=workspace.is_new_project,
        created_at=workspace.created_at.isoformat() if workspace.created_at else None,
        project_name=project.name if project else None,
        project_repo_url=project.repo_url if project else None,
    )


def get_workspace_path(workspace: Workspace) -> Path:
    """Get the local path for a workspace."""
    if workspace.local_path:
        return Path(workspace.local_path)
    # Fallback to session-based path
    return WORKSPACE_ROOT / workspace.session_id


def list_directory(
    dir_path: Path,
    workspace_root: Path,
    recursive: bool = False,
) -> tuple[list[FileInfo], list[FileInfo]]:
    """List files and directories in a path.

    Returns:
        Tuple of (files, directories)
    """
    files = []
    directories = []

    if not dir_path.exists() or not dir_path.is_dir():
        return files, directories

    try:
        if recursive:
            for item in dir_path.rglob("*"):
                # Skip hidden and common ignored directories
                if any(part.startswith(".") for part in item.parts):
                    continue
                if any(part in ["__pycache__", "node_modules", ".git"] for part in item.parts):
                    continue

                rel_path = str(item.relative_to(workspace_root))
                if item.is_file():
                    files.append(FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="file",
                        size=item.stat().st_size,
                    ))
                elif item.is_dir():
                    directories.append(FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="directory",
                    ))
        else:
            for item in dir_path.iterdir():
                # Skip hidden files/directories
                if item.name.startswith("."):
                    continue
                if item.name in ["__pycache__", "node_modules"]:
                    continue

                rel_path = str(item.relative_to(workspace_root))
                if item.is_file():
                    files.append(FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="file",
                        size=item.stat().st_size,
                    ))
                elif item.is_dir():
                    directories.append(FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="directory",
                    ))
    except PermissionError:
        logger.warning("permission_denied", path=str(dir_path))

    return files, directories


def resolve_safe_path(base_path: Path, relative_path: str) -> Path:
    """Resolve a path safely within the workspace root.

    Prevents path traversal attacks.
    """
    # Normalize the path
    resolved = (base_path / relative_path).resolve()

    # Ensure it's still under the base path
    try:
        resolved.relative_to(base_path.resolve())
    except ValueError:
        raise ValidationError("Invalid path: path traversal not allowed", field="path")

    return resolved


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/workspace")
async def get_workspace_files(
    session_id: str | None = Query(None, description="Session ID to get workspace for"),
    path: str = Query("", description="Path within workspace to list"),
    recursive: bool = Query(False, description="List recursively"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceFilesResponse:
    """Get workspace files for a session.

    If session_id is provided, returns files from that session's workspace.
    Otherwise, returns an empty workspace structure.
    """
    if not session_id:
        # No session specified - return empty response
        return WorkspaceFilesResponse(
            workspace_id=None,
            session_id=None,
            path=path or ".",
            files=[],
            directories=[],
            count=0,
        )

    # Get workspace for session
    workspace = crud.get_workspace_by_session(db, session_id)

    if not workspace:
        # Session might exist but have no workspace yet
        return WorkspaceFilesResponse(
            workspace_id=None,
            session_id=session_id,
            path=path or ".",
            files=[],
            directories=[],
            count=0,
        )

    # Get workspace path
    workspace_path = get_workspace_path(workspace)

    if not workspace_path.exists():
        return WorkspaceFilesResponse(
            workspace_id=workspace.id,
            session_id=session_id,
            path=path or ".",
            files=[],
            directories=[],
            count=0,
        )

    # Resolve the target directory
    if path:
        target_path = resolve_safe_path(workspace_path, path)
    else:
        target_path = workspace_path

    # List directory contents
    files, directories = list_directory(target_path, workspace_path, recursive)

    logger.info(
        "workspace_files_listed",
        session_id=session_id,
        workspace_id=workspace.id,
        path=path or ".",
        file_count=len(files),
        dir_count=len(directories),
    )

    return WorkspaceFilesResponse(
        workspace_id=workspace.id,
        session_id=session_id,
        path=path or ".",
        files=files,
        directories=directories,
        count=len(files) + len(directories),
    )


@router.get("/workspace/file")
async def get_workspace_file(
    path: str = Query(..., description="File path within workspace"),
    session_id: str | None = Query(None, description="Session ID"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> FileContentResponse:
    """Get file content from a workspace.

    Returns the content of a file within the session's workspace.
    """
    if not session_id:
        raise ValidationError("session_id is required", field="session_id")

    # Get workspace for session
    workspace = crud.get_workspace_by_session(db, session_id)

    if not workspace:
        raise NotFoundError("workspace", session_id, "Workspace not found for session")

    # Get workspace path
    workspace_path = get_workspace_path(workspace)

    if not workspace_path.exists():
        raise NotFoundError("workspace", str(workspace_path), "Workspace directory not found")

    # Resolve file path safely
    file_path = resolve_safe_path(workspace_path, path)

    if not file_path.exists():
        raise NotFoundError("file", path)

    if not file_path.is_file():
        raise ValidationError(f"Path is not a file: {path}", field="path")

    # Check file size (limit to 10MB)
    size = file_path.stat().st_size
    if size > 10 * 1024 * 1024:
        raise ValidationError("File too large (max 10MB)", field="path")

    # Try to read as text
    try:
        content = file_path.read_text(encoding="utf-8")
        return FileContentResponse(
            path=path,
            content=content,
            binary=False,
            size=size,
        )
    except UnicodeDecodeError:
        # File is binary
        return FileContentResponse(
            path=path,
            content=None,
            binary=True,
            size=size,
        )


@router.get("/workspace/download")
async def download_workspace_file(
    path: str = Query(..., description="File path within workspace"),
    session_id: str | None = Query(None, description="Session ID"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Download a file from a workspace.

    Returns the file as a download response.
    """
    if not session_id:
        raise ValidationError("session_id is required", field="session_id")

    # Get workspace for session
    workspace = crud.get_workspace_by_session(db, session_id)

    if not workspace:
        raise NotFoundError("workspace", session_id, "Workspace not found for session")

    # Get workspace path
    workspace_path = get_workspace_path(workspace)

    if not workspace_path.exists():
        raise NotFoundError("workspace", str(workspace_path), "Workspace directory not found")

    # Resolve file path safely
    file_path = resolve_safe_path(workspace_path, path)

    if not file_path.exists():
        raise NotFoundError("file", path)

    if not file_path.is_file():
        raise ValidationError(f"Path is not a file: {path}", field="path")

    logger.info(
        "workspace_file_download",
        session_id=session_id,
        path=path,
    )

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@router.get("/workspace/{workspace_id}")
async def get_workspace_by_id(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceResponse:
    """Get workspace details by ID."""
    workspace = crud.get_workspace(db, workspace_id)

    if not workspace:
        raise NotFoundError("workspace", workspace_id)

    # Get associated project if any
    project = None
    if workspace.project_id:
        project = crud.get_project(db, workspace.project_id)

    return workspace_to_response(workspace, project)


@router.get("/workspaces")
async def list_workspaces(
    project_id: str | None = Query(None, description="Filter by project ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[WorkspaceResponse]:
    """List workspaces.

    Optionally filter by project_id.
    """
    workspaces = crud.list_workspaces(db, project_id=project_id, limit=limit)

    # Get associated projects
    result = []
    for workspace in workspaces:
        project = None
        if workspace.project_id:
            project = crud.get_project(db, workspace.project_id)
        result.append(workspace_to_response(workspace, project))

    return result
