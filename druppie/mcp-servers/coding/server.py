"""Coding MCP Server.

Combined file operations and git functionality for workspace sandbox.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os
from typing import Any

from fastmcp import FastMCP

from module import CodingModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("coding-mcp")

mcp = FastMCP("Coding MCP Server")

WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", "/workspaces")
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")

module = CodingModule(
    workspace_root=WORKSPACE_ROOT,
    gitea_url=GITEA_URL,
    gitea_org=GITEA_ORG,
    gitea_token=GITEA_TOKEN,
    gitea_user=GITEA_USER,
    gitea_password=GITEA_PASSWORD,
)


@mcp.tool()
async def register_workspace(
    workspace_id: str,
    workspace_path: str,
    project_id: str,
    branch: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Register an existing workspace (created by backend)."""
    return module.register_workspace(
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        project_id=project_id,
        branch=branch,
        user_id=user_id,
        session_id=session_id,
    )


@mcp.tool()
async def initialize_workspace(
    user_id: str,
    session_id: str,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Initialize workspace for a conversation."""
    return await module.initialize_workspace(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        project_name=project_name,
    )


@mcp.tool()
async def read_file(workspace_id: str, path: str) -> dict:
    """Read file from workspace."""
    return module.read_file(workspace_id=workspace_id, path=path)


@mcp.tool()
async def write_file(
    workspace_id: str,
    path: str,
    content: str,
    auto_commit: bool = True,
    commit_message: str | None = None,
) -> dict:
    """Write file to workspace (auto-commits to git)."""
    return await module.write_file(
        workspace_id=workspace_id,
        path=path,
        content=content,
        auto_commit=auto_commit,
        commit_message=commit_message,
    )


@mcp.tool()
async def list_dir(
    workspace_id: str,
    path: str = ".",
    recursive: bool = False,
) -> dict:
    """List directory contents."""
    return module.list_dir(
        workspace_id=workspace_id,
        path=path,
        recursive=recursive,
    )


@mcp.tool()
async def delete_file(
    workspace_id: str,
    path: str,
    auto_commit: bool = True,
) -> dict:
    """Delete file from workspace."""
    return await module.delete_file(
        workspace_id=workspace_id,
        path=path,
        auto_commit=auto_commit,
    )


@mcp.tool()
async def run_command(
    workspace_id: str,
    command: str,
    timeout: int = 60,
) -> dict:
    """Execute shell command in workspace (requires approval)."""
    return module.run_command(
        workspace_id=workspace_id,
        command=command,
        timeout=timeout,
    )


@mcp.tool()
async def run_tests(
    workspace_id: str,
    test_command: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run tests in the workspace and return structured results."""
    return await module.run_tests(
        workspace_id=workspace_id,
        test_command=test_command,
        timeout=timeout,
    )


@mcp.tool()
async def batch_write_files(
    workspace_id: str,
    files: dict[str, str],
    commit_message: str = "Create multiple files",
) -> dict:
    """Write multiple files to workspace in a single operation with one git commit."""
    return await module.batch_write_files(
        workspace_id=workspace_id,
        files=files,
        commit_message=commit_message,
    )


@mcp.tool()
async def commit_and_push(workspace_id: str, message: str) -> dict:
    """Commit all changes and push to Gitea."""
    return await module.commit_and_push(
        workspace_id=workspace_id,
        message=message,
    )


@mcp.tool()
async def create_branch(workspace_id: str, branch_name: str) -> dict:
    """Create and checkout a new git branch."""
    return module.create_branch(
        workspace_id=workspace_id,
        branch_name=branch_name,
    )


@mcp.tool()
async def merge_to_main(workspace_id: str) -> dict:
    """Merge current branch to main (requires approval)."""
    return await module.merge_to_main(workspace_id=workspace_id)


@mcp.tool()
async def get_git_status(workspace_id: str) -> dict:
    """Get git status for workspace."""
    return module.get_git_status(workspace_id=workspace_id)


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "coding-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9001"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
