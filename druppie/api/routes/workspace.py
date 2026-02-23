"""Workspace API routes.

Bridge to Coding MCP - lets the frontend browse files that agents have written.

Architecture:
    Route (this file)
      │
      └──▶ MCP Bridge (Coding MCP list_dir, read_file)

Endpoints:
- GET /workspace/files - List files via Coding MCP
- GET /workspace/file - Get file content via Coding MCP
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user
from druppie.api.errors import NotFoundError, ValidationError
from druppie.core.mcp_config import MCPConfig
from druppie.execution.mcp_http import MCPHttp, MCPHttpError

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# SINGLETON INSTANCES (shared with mcp_bridge.py)
# =============================================================================

_mcp_config: MCPConfig | None = None
_mcp_http: MCPHttp | None = None


def get_mcp_config() -> MCPConfig:
    """Get or create MCP config singleton."""
    global _mcp_config
    if _mcp_config is None:
        _mcp_config = MCPConfig()
    return _mcp_config


def get_mcp_http() -> MCPHttp:
    """Get or create MCP HTTP client singleton."""
    global _mcp_http
    if _mcp_http is None:
        _mcp_http = MCPHttp(get_mcp_config())
    return _mcp_http


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
# ROUTES
# =============================================================================


@router.get("/workspace/files")
async def list_workspace_files(
    session_id: str = Query(..., description="Session ID to get workspace for"),
    path: str = Query("", description="Path within workspace to list"),
    user: dict = Depends(get_current_user),
) -> WorkspaceFilesResponse:
    """List files in a session's workspace via Coding MCP.

    Returns files and directories at the specified path within the
    session's workspace directory.
    """
    mcp_http = get_mcp_http()

    try:
        result = await mcp_http.call(
            server="coding",
            tool="list_dir",
            args={
                "path": path or ".",
                "session_id": session_id,
            },
            timeout_seconds=30.0,
        )

        if not result.get("success", False):
            logger.warning(
                "workspace_list_dir_failed",
                session_id=session_id,
                path=path,
                error=result.get("error"),
            )
            return WorkspaceFilesResponse(
                session_id=session_id,
                path=path or ".",
                files=[],
                directories=[],
            )

        # Parse result from Coding MCP (returns files and directories separately)
        files = [
            FileInfo(
                name=f.get("name", ""),
                path=f.get("path", ""),
                type="file",
                size=f.get("size", 0),
            )
            for f in result.get("files", [])
        ]
        directories = [
            FileInfo(
                name=d.get("name", ""),
                path=d.get("path", ""),
                type="directory",
                size=0,
            )
            for d in result.get("directories", [])
        ]

        return WorkspaceFilesResponse(
            session_id=session_id,
            path=result.get("path", path or "."),
            files=files,
            directories=directories,
        )

    except MCPHttpError as e:
        logger.error(
            "workspace_list_dir_error",
            session_id=session_id,
            path=path,
            error=str(e),
        )
        return WorkspaceFilesResponse(
            session_id=session_id,
            path=path or ".",
            files=[],
            directories=[],
        )


@router.get("/workspace/file")
async def get_workspace_file(
    session_id: str = Query(..., description="Session ID"),
    path: str = Query(..., description="File path within workspace"),
    user: dict = Depends(get_current_user),
) -> FileContentResponse:
    """Get file content from a session's workspace via Coding MCP.

    Returns the text content of a file. Binary files return content=null.
    """
    mcp_http = get_mcp_http()

    try:
        result = await mcp_http.call(
            server="coding",
            tool="read_file",
            args={
                "path": path,
                "session_id": session_id,
            },
            timeout_seconds=30.0,
        )

        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            if "not found" in error.lower():
                raise NotFoundError("file", path)
            raise ValidationError(f"Failed to read file: {error}", field="path")

        return FileContentResponse(
            path=path,
            content=result.get("content"),
            size=len(result.get("content", "")) if result.get("content") else 0,
        )

    except MCPHttpError as e:
        logger.error(
            "workspace_read_file_error",
            session_id=session_id,
            path=path,
            error=str(e),
        )
        raise ValidationError(f"Failed to read file: {e}", field="path")
