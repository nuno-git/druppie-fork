"""Workspace API routes.

Bridge to session workspaces - lets the frontend browse files that agents have written.

Endpoints:
- GET /workspace/files - List files in a session's workspace
- GET /workspace/file - Get file content from a session's workspace
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.api.errors import NotFoundError, ValidationError
from druppie.db.models import Workspace

logger = structlog.get_logger()

router = APIRouter()

# Workspace root directory
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class FileInfo(BaseModel):
    """File or directory information."""
    name: str
    path: str
    type: str  # "file" or "directory"
    size: int = 0


class WorkspaceFilesResponse(BaseModel):
    """Response for listing workspace files."""
    workspace_id: str | None = None
    session_id: str
    path: str
    files: list[FileInfo] = []
    directories: list[FileInfo] = []


class FileContentResponse(BaseModel):
    """Response for file content."""
    path: str
    content: str | None = None
    size: int = 0


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def resolve_safe_path(base_path: Path, relative_path: str) -> Path:
    """Resolve a path safely within the workspace root.

    Prevents path traversal attacks.
    """
    resolved = (base_path / relative_path).resolve()
    try:
        resolved.relative_to(base_path.resolve())
    except ValueError:
        raise ValidationError("Invalid path: path traversal not allowed", field="path")
    return resolved


def list_directory(dir_path: Path, workspace_root: Path) -> tuple[list[FileInfo], list[FileInfo]]:
    """List files and directories in a path."""
    files = []
    directories = []

    if not dir_path.exists() or not dir_path.is_dir():
        return files, directories

    try:
        for item in dir_path.iterdir():
            # Skip hidden files and common ignored directories
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


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/workspace/files")
async def list_workspace_files(
    session_id: str = Query(..., description="Session ID to get workspace for"),
    path: str = Query("", description="Path within workspace to list"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> WorkspaceFilesResponse:
    """List files in a session's workspace.

    Returns files and directories at the specified path within the
    session's workspace directory.
    """
    # Get workspace for session
    workspace = db.query(Workspace).filter(Workspace.session_id == session_id).first()

    if not workspace:
        return WorkspaceFilesResponse(
            workspace_id=None,
            session_id=session_id,
            path=path or ".",
            files=[],
            directories=[],
        )

    # Get workspace path
    workspace_path = Path(workspace.local_path) if workspace.local_path else WORKSPACE_ROOT / session_id

    if not workspace_path.exists():
        return WorkspaceFilesResponse(
            workspace_id=str(workspace.id),
            session_id=session_id,
            path=path or ".",
            files=[],
            directories=[],
        )

    # Resolve the target directory
    target_path = resolve_safe_path(workspace_path, path) if path else workspace_path

    # List directory contents
    files, directories = list_directory(target_path, workspace_path)

    return WorkspaceFilesResponse(
        workspace_id=str(workspace.id),
        session_id=session_id,
        path=path or ".",
        files=files,
        directories=directories,
    )


@router.get("/workspace/file")
async def get_workspace_file(
    session_id: str = Query(..., description="Session ID"),
    path: str = Query(..., description="File path within workspace"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> FileContentResponse:
    """Get file content from a session's workspace.

    Returns the text content of a file. Binary files return content=null.
    Maximum file size is 10MB.
    """
    # Get workspace for session
    workspace = db.query(Workspace).filter(Workspace.session_id == session_id).first()

    if not workspace:
        raise NotFoundError("workspace", session_id, "Workspace not found for session")

    # Get workspace path
    workspace_path = Path(workspace.local_path) if workspace.local_path else WORKSPACE_ROOT / session_id

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
        return FileContentResponse(path=path, content=content, size=size)
    except UnicodeDecodeError:
        # Binary file - return null content
        return FileContentResponse(path=path, content=None, size=size)
