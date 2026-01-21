"""Coding MCP Server.

Combined file operations and git functionality for workspace sandbox.
Uses FastMCP framework for HTTP transport.
"""

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Coding MCP Server")

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")

# In-memory workspace registry (in production, use Redis/DB)
workspaces: dict[str, dict] = {}


async def create_gitea_repo(repo_name: str, description: str) -> dict:
    """Create repository in Gitea."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{GITEA_URL}/api/v1/orgs/{GITEA_ORG}/repos",
                json={
                    "name": repo_name,
                    "description": description,
                    "private": False,
                    "auto_init": True,
                },
                headers={"Authorization": f"token {GITEA_TOKEN}"},
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
            else:
                return {"error": response.text, "status_code": response.status_code}
        except Exception as e:
            return {"error": str(e)}


def get_workspace(workspace_id: str) -> dict:
    """Get workspace by ID."""
    if workspace_id not in workspaces:
        raise ValueError(f"Workspace not found: {workspace_id}")
    return workspaces[workspace_id]


def resolve_path(path: str, workspace_path: Path) -> Path:
    """Resolve a path relative to workspace root.

    Security: blocks path traversal attempts.
    """
    p = Path(path)

    # Block absolute paths (except if under workspace)
    if p.is_absolute():
        try:
            p.relative_to(workspace_path)
            return p
        except ValueError:
            return workspace_path / p.name

    # Resolve relative path within workspace
    resolved = (workspace_path / p).resolve()

    # Security: ensure it's still under workspace root
    try:
        resolved.relative_to(workspace_path.resolve())
    except ValueError:
        raise ValueError(f"Path traversal not allowed: {path}")

    return resolved


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def register_workspace(
    workspace_id: str,
    workspace_path: str,
    project_id: str,
    branch: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Register an existing workspace (created by backend).

    This is used when the backend has already initialized the workspace
    (cloned repo, created branch, etc.) and just needs to register it
    with the MCP server so tools can access it.

    Args:
        workspace_id: Workspace ID (from backend)
        workspace_path: Absolute path to the workspace
        project_id: Project ID
        branch: Current git branch
        user_id: Optional user ID for context
        session_id: Optional session ID for context

    Returns:
        Dict with success status
    """
    # Validate the path exists
    path = Path(workspace_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"Workspace path does not exist: {workspace_path}",
        }

    # Register workspace in memory
    workspaces[workspace_id] = {
        "path": str(path),
        "project_id": project_id,
        "branch": branch,
        "user_id": user_id,
        "session_id": session_id,
    }

    return {
        "success": True,
        "workspace_id": workspace_id,
        "workspace_path": str(path),
        "message": f"Workspace registered: {workspace_id}",
    }


@mcp.tool()
async def initialize_workspace(
    user_id: str,
    session_id: str,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Initialize workspace for a conversation.

    - New project (project_id=None): Create repo on main branch
    - Existing project: Clone and create feature branch

    Note: Prefer using register_workspace if the backend has already
    set up the workspace with git operations.

    Args:
        user_id: User ID
        session_id: Session ID
        project_id: Optional existing project ID
        project_name: Optional name for new project

    Returns:
        Dict with workspace_id, workspace_path, project_id, branch
    """
    workspace_id = f"{user_id}-{session_id}"

    if project_id is None:
        # New project
        project_id = str(uuid.uuid4())
        repo_name = f"project-{project_id[:8]}"

        # Create Gitea repo
        if GITEA_TOKEN:
            await create_gitea_repo(repo_name, project_name or "New Project")
        branch = "main"
    else:
        repo_name = f"project-{project_id[:8]}"
        branch = f"session-{session_id[:8]}"

    # Create workspace directory
    workspace_path = WORKSPACE_ROOT / user_id / project_id / session_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Clone repo if Gitea is configured
    if GITEA_TOKEN:
        repo_url = f"{GITEA_URL}/{GITEA_ORG}/{repo_name}.git"
        try:
            subprocess.run(
                ["git", "clone", repo_url, str(workspace_path)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.CalledProcessError:
            # Repo might be empty, init locally
            subprocess.run(["git", "init"], cwd=workspace_path, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", repo_url],
                cwd=workspace_path,
                check=True,
            )

        # Create feature branch if not main
        if branch != "main":
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=workspace_path,
                check=True,
            )
    else:
        # No Gitea - just init local git
        subprocess.run(["git", "init"], cwd=workspace_path, check=True)

    # Register workspace
    workspaces[workspace_id] = {
        "path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
        "repo_name": repo_name,
        "user_id": user_id,
        "session_id": session_id,
    }

    return {
        "success": True,
        "workspace_id": workspace_id,
        "workspace_path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
    }


@mcp.tool()
async def read_file(workspace_id: str, path: str) -> dict:
    """Read file from workspace.

    Args:
        workspace_id: Workspace ID
        path: File path relative to workspace

    Returns:
        Dict with success, content, path, size
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not file_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check size limit (10MB)
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            return {"success": False, "error": f"File too large: {size} bytes"}

        try:
            content = file_path.read_text(encoding="utf-8")
            return {
                "success": True,
                "content": content,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
            }
        except UnicodeDecodeError:
            return {
                "success": True,
                "binary": True,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
                "message": "File is binary",
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def write_file(
    workspace_id: str,
    path: str,
    content: str,
    auto_commit: bool = True,
    commit_message: str | None = None,
) -> dict:
    """Write file to workspace (auto-commits to git).

    Args:
        workspace_id: Workspace ID
        path: File path relative to workspace
        content: File content
        auto_commit: Whether to auto-commit (default: True)
        commit_message: Optional commit message

    Returns:
        Dict with success, path, committed
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_text(content, encoding="utf-8")

        result = {
            "success": True,
            "path": str(file_path.relative_to(workspace_path)),
            "size": len(content),
        }

        # Auto-commit
        if auto_commit:
            commit_result = await _do_commit_and_push(
                workspace_id,
                commit_message or f"Update {path}",
            )
            result["committed"] = commit_result.get("success", False)
            if commit_result.get("success"):
                result["commit_message"] = commit_message or f"Update {path}"

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_dir(
    workspace_id: str,
    path: str = ".",
    recursive: bool = False,
) -> dict:
    """List directory contents.

    Args:
        workspace_id: Workspace ID
        path: Directory path (default: ".")
        recursive: Whether to list recursively

    Returns:
        Dict with files and directories
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        dir_path = resolve_path(path, workspace_path)

        if not dir_path.exists():
            return {"success": False, "error": f"Directory not found: {path}"}

        if not dir_path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        files = []
        directories = []

        if recursive:
            for item in dir_path.rglob("*"):
                if item.name.startswith(".git"):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "directory",
                    })
        else:
            for item in dir_path.iterdir():
                if item.name.startswith(".git"):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(workspace_path)),
                        "type": "directory",
                    })

        return {
            "success": True,
            "path": str(dir_path.relative_to(workspace_path)) if dir_path != workspace_path else ".",
            "files": files,
            "directories": directories,
            "count": len(files) + len(directories),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def delete_file(
    workspace_id: str,
    path: str,
    auto_commit: bool = True,
) -> dict:
    """Delete file from workspace.

    Args:
        workspace_id: Workspace ID
        path: File path to delete
        auto_commit: Whether to auto-commit (default: True)

    Returns:
        Dict with success, deleted path
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = Path(ws["path"])
        file_path = resolve_path(path, workspace_path)

        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if file_path.is_dir():
            return {"success": False, "error": f"Path is a directory: {path}"}

        file_path.unlink()

        result = {
            "success": True,
            "deleted": str(file_path.relative_to(workspace_path)),
        }

        if auto_commit:
            commit_result = await _do_commit_and_push(workspace_id, f"Delete {path}")
            result["committed"] = commit_result.get("success", False)

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def run_command(
    workspace_id: str,
    command: str,
    timeout: int = 60,
) -> dict:
    """Execute shell command in workspace (requires approval).

    Args:
        workspace_id: Workspace ID
        command: Shell command to execute
        timeout: Timeout in seconds (default: 60)

    Returns:
        Dict with success, stdout, stderr, return_code
    """
    try:
        ws = get_workspace(workspace_id)
        workspace_path = ws["path"]

        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "cwd": workspace_path,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _do_commit_and_push(workspace_id: str, message: str) -> dict:
    """Internal function to commit all changes and push to Gitea.

    This is separate from the MCP tool to allow internal calls.
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]
        branch = ws["branch"]

        # Configure git user
        subprocess.run(
            ["git", "config", "user.email", "agent@druppie.local"],
            cwd=cwd,
            check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "Druppie Agent"],
            cwd=cwd,
            check=False,
        )

        # Stage all changes
        subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)

        # Check for changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        if not result.stdout.strip():
            return {"success": True, "message": "No changes to commit"}

        # Commit
        subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

        # Push (only if Gitea is configured)
        if GITEA_TOKEN:
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", branch],
                    cwd=cwd,
                    check=True,
                    timeout=60,
                )
                return {"success": True, "message": f"Committed and pushed: {message}", "pushed": True}
            except subprocess.CalledProcessError as e:
                return {"success": True, "message": f"Committed: {message}", "pushed": False, "push_error": str(e)}

        return {"success": True, "message": f"Committed: {message}", "pushed": False}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def commit_and_push(workspace_id: str, message: str) -> dict:
    """Commit all changes and push to Gitea.

    Args:
        workspace_id: Workspace ID
        message: Commit message

    Returns:
        Dict with success, message
    """
    return await _do_commit_and_push(workspace_id, message)


@mcp.tool()
async def create_branch(workspace_id: str, branch_name: str) -> dict:
    """Create and checkout a new git branch.

    Args:
        workspace_id: Workspace ID
        branch_name: Name of the new branch

    Returns:
        Dict with success, branch name
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]

        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=cwd,
            check=True,
        )

        # Update workspace record
        ws["branch"] = branch_name

        return {"success": True, "branch": branch_name}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def merge_to_main(workspace_id: str) -> dict:
    """Merge current branch to main (requires approval).

    Args:
        workspace_id: Workspace ID

    Returns:
        Dict with success, merged branch
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]
        current_branch = ws["branch"]

        if current_branch == "main":
            return {"success": False, "error": "Already on main branch"}

        # Checkout main and merge
        subprocess.run(["git", "checkout", "main"], cwd=cwd, check=True)
        subprocess.run(["git", "merge", current_branch], cwd=cwd, check=True)

        # Push if Gitea is configured
        if GITEA_TOKEN:
            subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True)

        # Update workspace
        ws["branch"] = "main"

        return {"success": True, "merged": current_branch}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_git_status(workspace_id: str) -> dict:
    """Get git status for workspace.

    Args:
        workspace_id: Workspace ID

    Returns:
        Dict with branch, status, files
    """
    try:
        ws = get_workspace(workspace_id)
        cwd = ws["path"]

        # Get current branch
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        branch = branch_result.stdout.strip() or ws["branch"]

        # Get status
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        # Parse status
        files = []
        for line in status_result.stdout.strip().split("\n"):
            if line:
                status = line[:2].strip()
                filename = line[3:]
                files.append({"status": status, "file": filename})

        return {
            "success": True,
            "branch": branch,
            "files": files,
            "has_changes": len(files) > 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
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
