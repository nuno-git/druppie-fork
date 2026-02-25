"""Coding MCP Server.

Combined file operations and git functionality for workspace sandbox.
Uses FastMCP framework for HTTP transport.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastmcp import FastMCP
from testing_module import TestingModule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("coding-mcp")

# Initialize FastMCP server
mcp = FastMCP("Coding MCP Server")

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")

# Initialize testing module
testing_module = TestingModule(str(WORKSPACE_ROOT))

# In-memory workspace registry (in production, use DB)
workspaces: dict[str, dict] = {}


def _state_file_path(workspace_path: str | Path) -> Path:
    """Return the path to the workspace state file."""
    return Path(workspace_path) / ".druppie_state.json"


def _save_workspace_state(ws: dict) -> None:
    """Persist workspace branch state to disk."""
    try:
        state_path = _state_file_path(ws["path"])
        state_path.write_text(json.dumps({"branch": ws["branch"]}), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save workspace state: %s", e)


def _load_workspace_state(workspace_path: str | Path) -> dict | None:
    """Load persisted workspace state from disk, or None if missing."""
    try:
        state_path = _state_file_path(workspace_path)
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load workspace state: %s", e)
    return None


def get_or_create_workspace(
    session_id: str,
    project_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> tuple[str, Path]:
    """Get or create a workspace from session_id.

    This enables standalone operation - callers can just provide session_id
    and the workspace will be auto-created if it doesn't exist.

    Args:
        session_id: Session ID (required)
        project_id: Optional project ID
        user_id: Optional user ID
        workspace_id: Optional explicit workspace ID (for backward compat)
        repo_name: Optional Gitea repo name (for cloning and git remote)
        repo_owner: Optional Gitea repo owner (for cloning and git remote)

    Returns:
        Tuple of (workspace_id, workspace_path)
    """
    # If workspace_id provided and registered, use it
    if workspace_id and workspace_id in workspaces:
        ws = workspaces[workspace_id]
        # Update repo info if provided and not already set
        if repo_name and not ws.get("repo_name"):
            ws["repo_name"] = repo_name
            ws["repo_owner"] = repo_owner
        return workspace_id, Path(ws["path"])

    # Derive workspace_id from session_id if not provided
    derived_workspace_id = workspace_id or f"session-{session_id}"

    # Check if already registered
    if derived_workspace_id in workspaces:
        ws = workspaces[derived_workspace_id]
        workspace_path = Path(ws["path"])
        # Update repo info if provided and not already set
        if repo_name and not ws.get("repo_name"):
            ws["repo_name"] = repo_name
            ws["repo_owner"] = repo_owner
            logger.debug(
                "Updated repo info for workspace %s: %s/%s",
                derived_workspace_id, repo_owner, repo_name,
            )
        logger.debug(
            "Reusing existing workspace %s (repo=%s/%s, path=%s)",
            derived_workspace_id, ws.get("repo_owner"), ws.get("repo_name"), workspace_path,
        )
        return derived_workspace_id, workspace_path

    # Auto-create workspace path
    # Path structure: /workspaces/{user_id or "default"}/{project_id or "scratch"}/{session_id}
    user_part = user_id or "default"
    project_part = project_id or "scratch"
    workspace_path = WORKSPACE_ROOT / user_part / project_part / session_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Initialize git: Clone from Gitea if repo exists, otherwise git init
    git_dir = workspace_path / ".git"
    if not git_dir.exists():
        cloned = False
        logger.debug(
            "Initializing new workspace %s: repo_name=%s, repo_owner=%s, gitea_configured=%s",
            derived_workspace_id, repo_name, repo_owner, is_gitea_configured(),
        )
        if not repo_name:
            logger.warning(
                "No repo_name provided for workspace %s — workspace will be empty (git init only). "
                "Check that the tool has repo_name in the injection config.",
                derived_workspace_id,
            )
        if repo_name and is_gitea_configured():
            # Clone from Gitea to ensure we have the same history
            remote_url = get_gitea_clone_url(repo_name, repo_owner)
            try:
                # Clone into a temp dir first, then move contents
                # (Can't clone into non-empty dir)
                with tempfile.TemporaryDirectory() as tmp_dir:
                    clone_result = subprocess.run(
                        ["git", "clone", remote_url, tmp_dir],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if clone_result.returncode == 0:
                        # Move .git and any files from clone to workspace
                        tmp_path = Path(tmp_dir)
                        for item in tmp_path.iterdir():
                            dest = workspace_path / item.name
                            if dest.exists():
                                if dest.is_dir():
                                    shutil.rmtree(dest)
                                else:
                                    dest.unlink()
                            shutil.move(str(item), str(dest))
                        cloned = True
                        logger.info("Cloned from Gitea: %s", remote_url.replace(GITEA_PASSWORD, "***"))
                    else:
                        logger.warning(
                            "Failed to clone from Gitea, falling back to git init: %s",
                            clone_result.stderr,
                        )
            except Exception as e:
                logger.warning("Clone failed, falling back to git init: %s", e)

        if not cloned:
            # Fall back to git init
            subprocess.run(["git", "init"], cwd=workspace_path, check=True, capture_output=True)
            # Set up remote if repo info provided
            if repo_name and is_gitea_configured():
                remote_url = get_gitea_clone_url(repo_name, repo_owner)
                subprocess.run(
                    ["git", "remote", "add", "origin", remote_url],
                    cwd=workspace_path,
                    check=False,
                    capture_output=True,
                )
                logger.info("Set up git remote: %s", remote_url.replace(GITEA_PASSWORD, "***"))
            logger.info("Auto-initialized git repo at %s", workspace_path)

        # Exclude state file from git (local-only, won't pollute .gitignore)
        exclude_path = workspace_path / ".git" / "info" / "exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_entry = ".druppie_state.json"
        existing = exclude_path.read_text() if exclude_path.exists() else ""
        if exclude_entry not in existing:
            with exclude_path.open("a") as f:
                f.write(f"\n{exclude_entry}\n")

        # Configure git user
        subprocess.run(
            ["git", "config", "user.email", "agent@druppie.local"],
            cwd=workspace_path,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Druppie Agent"],
            cwd=workspace_path,
            check=False,
            capture_output=True,
        )

    # Determine branch: persisted state → actual git state → default "main"
    branch = "main"
    persisted = _load_workspace_state(workspace_path)
    if persisted and persisted.get("branch"):
        branch = persisted["branch"]
        logger.info("Restored branch from persisted state: %s", branch)

    # Belt-and-suspenders: check actual git branch
    try:
        git_branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        actual_branch = git_branch_result.stdout.strip()
        if actual_branch and actual_branch != branch:
            logger.info(
                "Git branch (%s) differs from persisted (%s), using git branch",
                actual_branch, branch,
            )
            branch = actual_branch
    except Exception as e:
        logger.warning("Failed to check actual git branch: %s", e)

    # Register workspace
    workspaces[derived_workspace_id] = {
        "path": str(workspace_path),
        "project_id": project_id,
        "branch": branch,
        "user_id": user_id,
        "session_id": session_id,
        "repo_name": repo_name,
        "repo_owner": repo_owner,
    }

    logger.info(
        "Auto-created workspace %s at %s (session_id=%s, repo=%s/%s)",
        derived_workspace_id,
        workspace_path,
        session_id,
        repo_owner,
        repo_name,
    )

    return derived_workspace_id, workspace_path


def get_gitea_clone_url(repo_name: str, repo_owner: str | None = None) -> str:
    """Get Gitea clone URL with embedded credentials if available.

    Args:
        repo_name: Repository name
        repo_owner: Repository owner/username. Defaults to GITEA_ORG if not specified.

    If GITEA_USER and GITEA_PASSWORD are set, returns authenticated URL.
    Otherwise returns unauthenticated URL.
    """
    owner = repo_owner or GITEA_ORG
    # Parse URL to inject credentials
    # GITEA_URL is like "http://gitea:3000"
    if GITEA_USER and GITEA_PASSWORD:
        # Embed credentials in URL for git operations
        # Result: http://user:pass@gitea:3000/owner/repo.git
        if "://" in GITEA_URL:
            protocol, rest = GITEA_URL.split("://", 1)
            from urllib.parse import quote
            return f"{protocol}://{quote(GITEA_USER)}:{quote(GITEA_PASSWORD)}@{rest}/{owner}/{repo_name}.git"
    # Fallback: unauthenticated URL (push will fail)
    return f"{GITEA_URL}/{owner}/{repo_name}.git"


def is_gitea_configured() -> bool:
    """Check if Gitea is configured with credentials for push."""
    return bool(GITEA_TOKEN or (GITEA_USER and GITEA_PASSWORD))


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
async def read_file(
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Read file from workspace.

    Can be called with either:
    - session_id (preferred): Auto-creates workspace if needed
    - workspace_id (legacy): Uses pre-registered workspace

    Args:
        path: File path relative to workspace
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with success, content, path, size
    """
    try:
        # Resolve workspace - session_id preferred, workspace_id for backward compat
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        file_path = resolve_path(path, workspace_path)

        logger.info("Reading file in workspace %s: %s", workspace_id, path)

        if not file_path.exists():
            logger.debug("File not found in workspace %s: %s", workspace_id, path)
            return {"success": False, "error": f"File not found: {path}"}

        if not file_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check size limit (10MB)
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            logger.warning(
                "File too large in workspace %s: %s (%d bytes)",
                workspace_id,
                path,
                size,
            )
            return {"success": False, "error": f"File too large: {size} bytes"}

        try:
            content = file_path.read_text(encoding="utf-8")
            logger.debug(
                "Successfully read file in workspace %s: %s (%d bytes)",
                workspace_id,
                path,
                size,
            )
            return {
                "success": True,
                "content": content,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
            }
        except UnicodeDecodeError:
            logger.debug(
                "Binary file detected in workspace %s: %s",
                workspace_id,
                path,
            )
            return {
                "success": True,
                "binary": True,
                "path": str(file_path.relative_to(workspace_path)),
                "size": size,
                "message": "File is binary",
            }

    except ValueError as e:
        logger.warning(
            "Path resolution error in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error reading file in workspace %s: %s - %s",
            workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool()
async def write_file(
    path: str,
    content: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Write file to workspace.

    Files are written to disk only. Use commit_and_push to commit and push.

    Args:
        path: File path relative to workspace
        content: File content
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for git remote setup)
        repo_owner: Gitea repository owner/username (for git remote setup)

    Returns:
        Dict with success, path, size
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        file_path = resolve_path(path, workspace_path)

        logger.info(
            "Writing file in workspace %s: %s (%d bytes)",
            resolved_workspace_id,
            path,
            len(content),
        )

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_text(content, encoding="utf-8")

        logger.debug(
            "Successfully wrote file in workspace %s: %s",
            resolved_workspace_id,
            path,
        )

        return {
            "success": True,
            "path": str(file_path.relative_to(workspace_path)),
            "size": len(content),
            "workspace_path": str(workspace_path),
        }

    except ValueError as e:
        logger.warning(
            "Path resolution error writing file in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error writing file in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_dir(
    path: str = ".",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    recursive: bool = False,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """List directory contents.

    Can be called with either:
    - session_id (preferred): Auto-creates workspace if needed
    - workspace_id (legacy): Uses pre-registered workspace

    Args:
        path: Directory path (default: ".")
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        recursive: Whether to list recursively
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with files and directories
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
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
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    auto_commit: bool = True,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Delete file from workspace.

    Args:
        path: File path to delete
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        auto_commit: Whether to auto-commit (default: True)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with success, deleted path
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}
        file_path = resolve_path(path, workspace_path)

        logger.info("Deleting file in workspace %s: %s", resolved_workspace_id, path)

        if not file_path.exists():
            logger.debug("File not found for deletion in workspace %s: %s", resolved_workspace_id, path)
            return {"success": False, "error": f"File not found: {path}"}

        if file_path.is_dir():
            return {"success": False, "error": f"Path is a directory: {path}"}

        file_path.unlink()

        logger.info("Successfully deleted file in workspace %s: %s", resolved_workspace_id, path)

        result = {
            "success": True,
            "deleted": str(file_path.relative_to(workspace_path)),
        }

        if auto_commit:
            commit_result = await _do_commit_and_push(resolved_workspace_id, f"Delete {path}")
            result["committed"] = commit_result.get("success", False)

        return result

    except ValueError as e:
        logger.warning(
            "Path resolution error deleting file in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error deleting file in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
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

        has_changes = bool(result.stdout.strip())

        if has_changes:
            # Commit staged changes
            subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

        # Always attempt to push (there may be unpushed commits from auto-commits)
        if is_gitea_configured():
            try:
                # Ensure remote has credentials for push
                ws = get_workspace(workspace_id)
                repo_name = ws.get("repo_name")
                repo_owner = ws.get("repo_owner")
                if repo_name:
                    # Update remote URL with credentials if needed
                    auth_url = get_gitea_clone_url(repo_name, repo_owner)
                    subprocess.run(
                        ["git", "remote", "set-url", "origin", auth_url],
                        cwd=cwd,
                        check=True,
                        capture_output=True,
                    )

                push_result = subprocess.run(
                    ["git", "push", "-u", "origin", branch],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if push_result.returncode == 0:
                    msg = f"Committed and pushed: {message}" if has_changes else f"Pushed (no new changes to commit): {message}"
                    return {"success": True, "message": msg, "pushed": True, "committed": has_changes}
                else:
                    logger.warning("Push failed: %s", push_result.stderr)
                    msg = f"Committed: {message}" if has_changes else "No changes to commit"
                    return {"success": True, "message": msg, "pushed": False, "committed": has_changes, "push_error": push_result.stderr}
            except subprocess.CalledProcessError as e:
                msg = f"Committed: {message}" if has_changes else "No changes to commit"
                return {"success": True, "message": msg, "pushed": False, "committed": has_changes, "push_error": str(e)}

        if not has_changes:
            return {"success": True, "message": "No changes to commit", "pushed": False, "committed": False}
        return {"success": True, "message": f"Committed: {message}", "pushed": False, "committed": True}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def batch_write_files(
    files: list[dict[str, str]],
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Write multiple files to workspace in a single operation.

    Files are written to disk only. Use commit_and_push to commit and push.

    Args:
        files: List of file objects, each with 'path' and 'content' keys
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for git remote setup)
        repo_owner: Gitea repository owner/username (for git remote setup)

    Returns:
        Dict with success, files_created list

    Example:
        batch_write_files(
            session_id="...",
            files=[
                {"path": "src/index.js", "content": "console.log('hello');"},
                {"path": "src/utils.js", "content": "export const add = (a, b) => a + b;"},
                {"path": "package.json", "content": '{"name": "myapp"}'}
            ]
        )
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        files_created = []
        errors = []

        # Write all files
        for file_entry in files:
            path = file_entry.get("path")
            content = file_entry.get("content")
            if not path or content is None:
                errors.append({"path": path, "error": "Missing path or content"})
                continue
            try:
                file_path = resolve_path(path, workspace_path)

                # Ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Write file
                file_path.write_text(content, encoding="utf-8")
                files_created.append(str(file_path.relative_to(workspace_path)))

            except Exception as e:
                errors.append({"path": path, "error": str(e)})

        # If no files were created, return error
        if not files_created:
            return {
                "success": False,
                "error": "No files were created",
                "errors": errors,
            }

        result = {
            "success": True,
            "files_created": files_created,
            "file_count": len(files_created),
            "workspace_path": str(workspace_path),
        }

        # Add errors if any files failed
        if errors:
            result["errors"] = errors
            result["partial_success"] = True

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def commit_and_push(
    message: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Commit all changes and push to Gitea.

    Args:
        message: Commit message
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for git remote setup)
        repo_owner: Gitea repository owner (for git remote setup)

    Returns:
        Dict with success, message
    """
    # Resolve workspace
    if session_id:
        resolved_workspace_id, _ = get_or_create_workspace(
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            workspace_id=workspace_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
        )
    elif workspace_id:
        resolved_workspace_id = workspace_id
    else:
        return {"success": False, "error": "Either session_id or workspace_id is required"}
    return await _do_commit_and_push(resolved_workspace_id, message)


@mcp.tool()
async def create_branch(
    branch_name: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Create and switch to a git branch. If the branch already exists, switches to it.

    Args:
        branch_name: Name of the branch to create or switch to
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with success, branch name, created (True if new, False if existing)
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
            cwd = str(workspace_path)
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            cwd = ws["path"]
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        # Try to create a new branch
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # New branch created successfully
            ws["branch"] = branch_name
            _save_workspace_state(ws)
            logger.info("Created new branch: %s", branch_name)
            return {"success": True, "branch": branch_name, "created": True}

        # Branch already exists — switch to it
        logger.info("Branch %s already exists, switching to it", branch_name)
        switch_result = subprocess.run(
            ["git", "checkout", branch_name],
            cwd=cwd,
            capture_output=True,
            text=True,
        )

        if switch_result.returncode == 0:
            ws["branch"] = branch_name
            _save_workspace_state(ws)
            return {"success": True, "branch": branch_name, "created": False, "message": "Switched to existing branch"}

        return {"success": False, "error": f"Failed to create or switch to branch: {result.stderr} / {switch_result.stderr}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def merge_to_main(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Merge current branch to main (requires approval).

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for workspace resolution)
        repo_owner: Gitea repository owner (for workspace resolution)

    Returns:
        Dict with success, merged branch
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
            cwd = str(workspace_path)
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            cwd = ws["path"]
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

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
        _save_workspace_state(ws)

        return {"success": True, "merged": current_branch}

    except subprocess.CalledProcessError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_git_status(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Get git status for workspace.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with branch, status, files
    """
    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
            cwd = str(workspace_path)
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            cwd = ws["path"]
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

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
# TESTING TOOLS (delegated to TestingModule)
# =============================================================================


@mcp.tool()
async def get_test_framework(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Auto-detect test framework in workspace (pytest, vitest, jest, playwright)."""
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        testing_module.workspace_root = workspace_path
        framework_info = testing_module.get_test_framework_info()

        if framework_info["framework"] == "unknown":
            return {
                "success": True,
                "framework": "unknown",
                "message": "No test framework detected yet. This is normal for new projects. Read technical_design.md to determine the tech stack and set up the appropriate test framework.",
            }

        return {"success": True, **framework_info}

    except Exception as e:
        logger.error("Error detecting test framework: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def run_tests(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    test_command: str | None = None,
    timeout: int = 300,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Run tests in workspace and return results with coverage.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        test_command: Optional custom test command (default: auto-detected)
        timeout: Timeout in seconds (default: 300)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with test results, pass/fail counts, and output
    """
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        testing_module.workspace_root = workspace_path

        # Detect framework if command not provided
        if not test_command or test_command.strip().lower() in ("null", "none", ""):
            test_command = None
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {
                    "success": False,
                    "error": "Could not auto-detect test framework. Please specify test_command.",
                }
            test_command = framework_info["test_command"]
            framework = framework_info["framework"]
        else:
            framework = "unknown"
            if "pytest" in test_command:
                framework = "pytest"
            elif "jest" in test_command or "npm test" in test_command:
                framework = "jest"
            elif "vitest" in test_command:
                framework = "vitest"
            elif "go test" in test_command:
                framework = "go"
            elif "cargo test" in test_command:
                framework = "cargo"

        logger.info("Running tests in workspace %s: %s", workspace_path, test_command)

        start_time = time.time()
        try:
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.time() - start_time

            parsed_results = testing_module.parse_test_results(
                result.stdout + "\n" + result.stderr,
                framework,
            )

            coverage = None
            if framework in ["vitest", "jest", "pytest"]:
                coverage = testing_module.parse_coverage_json(framework)
                if coverage:
                    parsed_results["coverage"] = coverage

            return {
                "success": True,
                "framework": framework,
                "command": test_command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "elapsed_seconds": elapsed,
                "results": parsed_results,
                "coverage": coverage,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Test execution timed out after {timeout} seconds",
                "framework": framework,
                "command": test_command,
            }

    except Exception as e:
        logger.error("Error running tests: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_coverage_report(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    framework: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Get detailed test coverage report.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        framework: Optional framework name (default: auto-detected)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with coverage information
    """
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        testing_module.workspace_root = workspace_path

        if not framework:
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {"success": False, "error": "Could not auto-detect test framework."}
            framework = framework_info["framework"]

        coverage = testing_module.parse_coverage_json(framework)

        if not coverage:
            return {
                "success": False,
                "error": f"No coverage data found for {framework}. Run tests with coverage first.",
                "framework": framework,
            }

        return {"success": True, "framework": framework, "coverage": coverage}

    except Exception as e:
        logger.error("Error getting coverage: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def install_test_dependencies(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    framework: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Install missing test dependencies for project.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        framework: Optional framework name (default: auto-detected)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with installation results
    """
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        testing_module.workspace_root = workspace_path

        if not framework:
            framework_info = testing_module.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {"success": False, "error": "Could not auto-detect test framework."}
            framework = framework_info["framework"]

        deps_check = testing_module._check_framework_dependencies(framework)
        missing = deps_check.get("missing", [])

        if not missing:
            return {
                "success": True,
                "framework": framework,
                "message": "All test dependencies are already installed.",
                "installed": deps_check.get("installed", []),
            }

        logger.info("Installing missing dependencies for %s: %s", framework, missing)
        results = []

        if framework == "pytest":
            for dep in missing:
                try:
                    result = subprocess.run(
                        ["pip", "install", dep],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                    )
                    results.append({
                        "dependency": dep,
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({"dependency": dep, "success": False, "error": str(e)})

        elif framework in ["vitest", "jest"]:
            for dep in missing:
                try:
                    result = subprocess.run(
                        ["npm", "install", "--save-dev", dep],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                    )
                    results.append({
                        "dependency": dep,
                        "success": result.returncode == 0,
                        "output": result.stdout,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({"dependency": dep, "success": False, "error": str(e)})

        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        return {
            "success": len(failed) == 0,
            "framework": framework,
            "installed": [r["dependency"] for r in successful],
            "failed": [r["dependency"] for r in failed],
            "results": results,
            "message": f"Installed {len(successful)}/{len(missing)} dependencies" if results else "No dependencies to install",
        }

    except Exception as e:
        logger.error("Error installing test dependencies: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def validate_tdd(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    coverage_threshold: float = 80.0,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Run full TDD validation (tests + coverage + threshold check).

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        coverage_threshold: Minimum coverage percentage (default: 80.0)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with validation results
    """
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        testing_module.workspace_root = workspace_path

        # Run tests first
        test_result = await run_tests(
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
        )

        if not test_result.get("success"):
            return {
                "success": False,
                "error": "Failed to run tests for TDD validation",
                "test_error": test_result.get("error"),
            }

        framework_info = testing_module.get_test_framework_info()
        framework = framework_info["framework"]

        coverage = testing_module.parse_coverage_json(framework)
        coverage_percent = coverage.get("overall_percent", 0) if coverage else 0

        test_results = test_result.get("results", {})
        config = {"coverage_threshold": coverage_threshold}

        validation = testing_module.validate_tdd_workflow(test_results, config)

        return {
            "success": True,
            "framework": framework,
            "test_results": test_results,
            "coverage_percent": coverage_percent,
            "coverage_threshold": coverage_threshold,
            "validation": validation,
            "tdd_passed": validation["passed"],
        }

    except Exception as e:
        logger.error("Error validating TDD: %s", str(e))
        return {"success": False, "error": str(e)}


# =============================================================================
# SANDBOX CODING TOOL (background-agents integration)
# =============================================================================

# Configuration for the external coding sandbox (background-agents control-plane)
SANDBOX_CONTROL_PLANE_URL = os.getenv("SANDBOX_CONTROL_PLANE_URL", "http://sandbox-control-plane:8787")
SANDBOX_API_SECRET = os.getenv("SANDBOX_API_SECRET", "sandbox-dev-secret")
BACKEND_URL = os.getenv("BACKEND_URL", "http://druppie-backend:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "druppie-internal-key")


def _generate_sandbox_auth_token() -> str:
    """Generate HMAC-SHA256 auth token for the background-agents control-plane.

    Token format: "timestamp.signature" where signature is HMAC-SHA256(secret, timestamp).
    Matches the verifyInternalToken logic in @open-inspect/shared.
    """
    import hashlib
    import hmac

    timestamp = str(int(time.time() * 1000))  # Unix milliseconds
    signature = hmac.new(
        SANDBOX_API_SECRET.encode(),
        timestamp.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{timestamp}.{signature}"


@mcp.tool()
async def execute_coding_task(
    task: str,
    agent: str = "druppie-builder",
    repo_url: str = "",
    model: str = "zai-coding-plan/glm-4.7",
    timeout_seconds: int = 86400,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Execute a coding task in an isolated sandbox using an external coding agent.

    Creates a sandbox session on the background-agents control-plane, sends the
    task as a prompt, polls until completion, and returns the results (changed
    files, agent output). The calling agent can then apply changes to the local
    workspace using batch_write_files + commit_and_push.

    Args:
        task: The coding task description / prompt for the sandbox agent
        repo_url: Git repo URL for the sandbox to clone (optional, uses Gitea if not set)
        model: LLM model for the sandbox agent (default: zai-coding-plan/glm-4.7)
        timeout_seconds: Max wait time in seconds (default: 86400 / 24 hours)
        session_id: Druppie session ID (auto-injected)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID (auto-injected)
        user_id: User ID (optional)
        repo_name: Gitea repository name (auto-injected)
        repo_owner: Gitea repository owner (auto-injected)

    Returns:
        Dict with success, sandbox_session_id, status, events, changed_files,
        agent_output, and elapsed_seconds
    """
    import httpx

    if not SANDBOX_CONTROL_PLANE_URL:
        return {
            "success": False,
            "error": "SANDBOX_CONTROL_PLANE_URL not configured. Set it to the background-agents control-plane URL.",
        }

    if not SANDBOX_API_SECRET:
        return {
            "success": False,
            "error": "SANDBOX_API_SECRET not configured. Set it to match MODAL_API_SECRET on the control-plane.",
        }

    if not task:
        return {"success": False, "error": "task parameter is required"}

    # Determine repo info for the sandbox to clone
    sandbox_repo_owner = repo_owner or GITEA_ORG
    sandbox_repo_name = repo_name or ""

    # Construct Gitea clone URL for the sandbox (uses internal Docker network)
    from urllib.parse import quote
    gitea_clone_url = ""
    if sandbox_repo_name:
        if GITEA_TOKEN:
            gitea_clone_url = f"http://{quote(GITEA_TOKEN, safe='')}@gitea:3000/{sandbox_repo_owner}/{sandbox_repo_name}.git"
        elif GITEA_USER and GITEA_PASSWORD:
            gitea_clone_url = f"http://{quote(GITEA_USER, safe='')}:{quote(GITEA_PASSWORD, safe='')}@gitea:3000/{sandbox_repo_owner}/{sandbox_repo_name}.git"

    logger.info(
        "execute_coding_task: starting sandbox task (repo=%s/%s, agent=%s, model=%s, timeout=%ds)",
        sandbox_repo_owner,
        sandbox_repo_name,
        agent,
        model,
        timeout_seconds,
    )

    # Resolve workspace for git pull after completion
    workspace_path = None
    try:
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
    except Exception as e:
        logger.warning("execute_coding_task: could not resolve workspace for git pull: %s", e)

    base_url = SANDBOX_CONTROL_PLANE_URL.rstrip("/")
    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Create sandbox session
            auth_headers = {
                "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
                "Content-Type": "application/json",
            }

            create_body = {
                "repoOwner": sandbox_repo_owner,
                "repoName": sandbox_repo_name,
                "model": model,
                "title": f"Druppie sandbox: {task[:80]}",
            }
            if gitea_clone_url:
                create_body["gitUrl"] = gitea_clone_url

            resp = await client.post(
                f"{base_url}/sessions",
                json=create_body,
                headers=auth_headers,
            )

            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Failed to create sandbox session: {resp.status_code} {resp.text}",
                }

            sandbox_session_id = resp.json().get("sessionId")
            if not sandbox_session_id:
                return {"success": False, "error": "No sessionId in create response"}

            logger.info("execute_coding_task: created sandbox session %s", sandbox_session_id)

            # Register sandbox session ownership with the backend
            if user_id:
                try:
                    reg_body = {
                        "sandbox_session_id": sandbox_session_id,
                        "user_id": user_id,
                    }
                    if session_id:
                        reg_body["session_id"] = session_id
                    await client.post(
                        f"{BACKEND_URL}/api/sandbox-sessions/internal/register",
                        json=reg_body,
                        headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                        timeout=5.0,
                    )
                    logger.info("execute_coding_task: registered sandbox session ownership for user %s", user_id)
                except Exception as e:
                    logger.warning("execute_coding_task: failed to register sandbox session ownership: %s", e)

            # Step 2: Send the task prompt
            prompt_headers = {
                "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
                "Content-Type": "application/json",
            }

            prompt_body = {
                "content": task,
                "authorId": "druppie-agent",
                "source": "api",
                "agent": agent,
            }

            resp = await client.post(
                f"{base_url}/sessions/{sandbox_session_id}/prompt",
                json=prompt_body,
                headers=prompt_headers,
            )

            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"Failed to send prompt: {resp.status_code} {resp.text}",
                    "sandbox_session_id": sandbox_session_id,
                }

            # Track our prompt's messageId so we only match OUR execution_complete
            prompt_message_id = resp.json().get("messageId", "")
            logger.info(
                "execute_coding_task: prompt sent (messageId=%s), polling for completion...",
                prompt_message_id,
            )

            # Step 3: Poll for completion
            # The events API returns events newest-first (backward pagination).
            # For forward polling, we fetch all events each time and deduplicate
            # by tracking seen event IDs.
            poll_interval = 5  # seconds
            all_events = []
            seen_event_ids = set()
            sandbox_status = "unknown"
            agent_output_parts = []  # (created_at, content) for chronological ordering
            execution_complete_seen = False

            while time.time() - start_time < timeout_seconds:
                await _async_sleep(poll_interval)

                # Refresh auth token each poll (tokens expire after 5 min)
                poll_headers = {
                    "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
                }

                # Get session state to check sandbox status
                state_resp = await client.get(
                    f"{base_url}/sessions/{sandbox_session_id}",
                    headers=poll_headers,
                )

                if state_resp.status_code == 200:
                    state = state_resp.json()
                    sandbox_info = state.get("sandbox") or {}
                    sandbox_status = sandbox_info.get("status", "unknown")

                    # Error states — break immediately
                    if sandbox_status in ("stopped", "failed", "stale"):
                        logger.info(
                            "execute_coding_task: sandbox error state: %s",
                            sandbox_status,
                        )
                        break

                # Fetch all events (no cursor — API paginates backward, not forward)
                events_url = f"{base_url}/sessions/{sandbox_session_id}/events?limit=200"
                events_resp = await client.get(events_url, headers=poll_headers)
                if events_resp.status_code == 200:
                    events_data = events_resp.json()
                    events = events_data.get("events", [])
                    new_count = 0

                    for event in events:
                        event_id = event.get("id", "")
                        if event_id in seen_event_ids:
                            continue
                        seen_event_ids.add(event_id)
                        all_events.append(event)
                        new_count += 1

                        # Detect execution_complete event — primary completion signal
                        # Only match OUR prompt's messageId to ignore stale events
                        if event.get("type") == "execution_complete":
                            event_msg_id = event.get("messageId", "") or (event.get("data") or {}).get("messageId", "")
                            if not prompt_message_id or event_msg_id == prompt_message_id:
                                execution_complete_seen = True
                                exec_data = event.get("data", {})
                                if not exec_data.get("success", True):
                                    sandbox_status = "failed"
                            else:
                                logger.debug(
                                    "execute_coding_task: ignoring stale execution_complete (event=%s, ours=%s)",
                                    event_msg_id,
                                    prompt_message_id,
                                )
                        # Extract agent text output from token events
                        elif event.get("type") == "token":
                            content = (event.get("data") or {}).get("content", "")
                            if content:
                                ts = event.get("createdAt") or event.get("created_at") or 0
                                agent_output_parts.append((ts, content))
                        elif event.get("type") == "agent_message":
                            content = event.get("content", "")
                            if content:
                                ts = event.get("createdAt") or event.get("created_at") or 0
                                agent_output_parts.append((ts, content))

                    if new_count > 0:
                        logger.info(
                            "execute_coding_task: %d new events (total: %d, types: %s)",
                            new_count,
                            len(all_events),
                            ", ".join(set(e.get("type", "?") for e in events[:new_count])),
                        )

                # Primary exit: execution_complete event
                if execution_complete_seen:
                    logger.info("execute_coding_task: execution_complete event seen")
                    break

            elapsed = time.time() - start_time
            timed_out = elapsed >= timeout_seconds and not execution_complete_seen and sandbox_status not in ("stopped", "failed", "stale")

            if timed_out:
                logger.warning(
                    "execute_coding_task: timed out after %.1fs (status=%s)",
                    elapsed,
                    sandbox_status,
                )

            success = not timed_out and sandbox_status not in ("failed", "stale")

            # Final fresh fetch of events to get the latest token content.
            # The control plane updates token events in-place (same event ID,
            # new content), but the polling loop deduplicates by event_id and
            # misses content updates.  One final fetch fixes this.
            try:
                final_headers = {
                    "Authorization": f"Bearer {_generate_sandbox_auth_token()}",
                }
                final_resp = await client.get(
                    f"{base_url}/sessions/{sandbox_session_id}/events?limit=200",
                    headers=final_headers,
                )
                if final_resp.status_code == 200:
                    final_events = (final_resp.json().get("events") or [])
                    # Replace agent_output_parts with fresh token content
                    agent_output_parts = []
                    for fe in final_events:
                        if fe.get("type") == "token":
                            content = (fe.get("data") or {}).get("content", "")
                            if content:
                                ts = fe.get("createdAt") or fe.get("created_at") or 0
                                agent_output_parts.append((ts, content))
                        elif fe.get("type") == "agent_message":
                            content = fe.get("content", "")
                            if content:
                                ts = fe.get("createdAt") or fe.get("created_at") or 0
                                agent_output_parts.append((ts, content))
                    # Also update all_events for changed_files extraction
                    for fe in final_events:
                        fid = fe.get("id", "")
                        if fid and fid not in seen_event_ids:
                            all_events.append(fe)
                            seen_event_ids.add(fid)
            except Exception as final_err:
                logger.warning("execute_coding_task: final events fetch failed: %s", final_err)

            # Step 4: Extract changed files from events (after final fetch for completeness)
            changed_files = _extract_changed_files_from_events(all_events)

            # Step 5: Git pull to sync sandbox changes into local workspace
            git_pull_result = None
            if success and workspace_path and changed_files:
                try:
                    cwd = str(workspace_path)
                    pull = subprocess.run(
                        ["git", "pull", "--rebase=false", "origin"],
                        cwd=cwd,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if pull.returncode == 0:
                        git_pull_result = "synced"
                        logger.info("execute_coding_task: git pull succeeded in %s", cwd)
                    else:
                        git_pull_result = f"failed: {pull.stderr.strip()}"
                        logger.warning("execute_coding_task: git pull failed: %s", pull.stderr.strip())
                except Exception as pull_err:
                    git_pull_result = f"error: {pull_err}"
                    logger.warning("execute_coding_task: git pull error: %s", pull_err)

            # Sort token parts chronologically and join
            agent_output_parts.sort(key=lambda x: x[0])
            agent_output = "\n".join(content for _, content in agent_output_parts).strip()

            result = {
                "success": success,
                "sandbox_session_id": sandbox_session_id,
                "status": "timeout" if timed_out else sandbox_status,
                "elapsed_seconds": round(elapsed, 1),
                "event_count": len(all_events),
                "changed_files": changed_files,
                "agent_output": agent_output[-5000:],  # Keep last 5000 chars (summary is at the end)
                "timed_out": timed_out,
            }
            if git_pull_result:
                result["git_pull"] = git_pull_result
            # conversation_history is persisted in the control plane events table
            # for governance — not included in the tool result to avoid bloating LLM context
            return result

    except httpx.TimeoutException:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "error": f"HTTP timeout connecting to sandbox control-plane at {base_url}",
            "elapsed_seconds": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("execute_coding_task: unexpected error: %s", e)
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": round(elapsed, 1),
        }


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)


def _extract_changed_files_from_events(events: list[dict]) -> list[dict]:
    """Extract file changes from sandbox events.

    Looks for tool_call events where the tool wrote files. The sandbox uses
    OpenCode which emits events like:
        {"type": "tool_call", "data": {"tool": "write", "args": {"filePath": "/workspace/foo.txt", ...}}}
        {"type": "tool_call", "data": {"tool": "bash", "args": {"command": "..."}}}

    Also handles Druppie's own MCP tool names (write_file, batch_write_files, etc.).

    Args:
        events: List of event dicts from the sandbox session

    Returns:
        List of dicts with 'path' and 'action' keys
    """
    changed_files = []
    seen_paths = set()

    for event in events:
        event_type = event.get("type", "")

        if event_type != "tool_call":
            continue

        # Events have data nested under "data" key
        data = event.get("data", event)
        tool_name = data.get("tool", data.get("name", ""))
        args = data.get("args", data.get("arguments", {}))
        result = data.get("result", {})

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = {}

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}

        # OpenCode "write" tool: args.filePath
        if tool_name == "write":
            path = args.get("filePath", args.get("path", ""))
            if path and path not in seen_paths:
                seen_paths.add(path)
                changed_files.append({"path": path, "action": "write"})

        # Druppie MCP write_file/WriteFile
        elif tool_name in ("write_file", "WriteFile"):
            path = args.get("path") or result.get("path", "")
            if path and path not in seen_paths:
                seen_paths.add(path)
                changed_files.append({"path": path, "action": "write"})

        elif tool_name in ("batch_write_files", "BatchWriteFiles"):
            files_created = result.get("files_created", [])
            for fp in files_created:
                if isinstance(fp, str) and fp not in seen_paths:
                    seen_paths.add(fp)
                    changed_files.append({"path": fp, "action": "write"})

        elif tool_name in ("delete_file", "DeleteFile"):
            path = args.get("path") or result.get("deleted", "")
            if path and path not in seen_paths:
                seen_paths.add(path)
                changed_files.append({"path": path, "action": "delete"})

    return changed_files


# =============================================================================
# PULL REQUEST TOOLS (Gitea API)
# =============================================================================


def _gitea_api_headers() -> dict:
    """Get headers for Gitea API requests.

    Uses GITEA_TOKEN if available, otherwise falls back to
    basic auth with GITEA_USER/GITEA_PASSWORD.
    """
    headers = {"Content-Type": "application/json"}
    if GITEA_TOKEN:
        headers["Authorization"] = f"token {GITEA_TOKEN}"
    elif GITEA_USER and GITEA_PASSWORD:
        import base64
        credentials = base64.b64encode(f"{GITEA_USER}:{GITEA_PASSWORD}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    return headers


def _get_repo_info(workspace_id: str) -> tuple[str, str] | None:
    """Extract repo_owner and repo_name from a workspace's git remote.

    Returns:
        Tuple of (owner, repo_name) or None if not found.
    """
    ws = workspaces.get(workspace_id)
    if not ws:
        return None

    cwd = ws["path"]
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        # Parse URL like http://user:pass@gitea:3000/owner/repo.git
        remote_url = result.stdout.strip()
        # Remove .git suffix
        if remote_url.endswith(".git"):
            remote_url = remote_url[:-4]
        # Get last two path segments: owner/repo
        parts = remote_url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
    except Exception:
        pass
    return None


@mcp.tool()
async def create_pull_request(
    title: str,
    body: str = "",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Create a pull request from the current branch to main on Gitea.

    Args:
        title: PR title
        body: PR description (optional)
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for workspace resolution)
        repo_owner: Gitea repository owner (for workspace resolution)

    Returns:
        Dict with success, pr_number, pr_url, html_url
    """
    import httpx

    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        current_branch = ws["branch"]

        # Reconcile with actual git state in case persistence was stale
        try:
            git_branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=ws["path"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            actual_branch = git_branch_result.stdout.strip()
            if actual_branch and actual_branch != current_branch:
                logger.info(
                    "create_pull_request: reconciling branch %s → %s (from git)",
                    current_branch, actual_branch,
                )
                current_branch = actual_branch
                ws["branch"] = actual_branch
                _save_workspace_state(ws)
        except Exception as e:
            logger.warning("Failed to check actual git branch in create_pull_request: %s", e)

        if current_branch == "main":
            return {"success": False, "error": "Already on main branch, nothing to PR"}

        # Get repo info from remote
        repo_info = _get_repo_info(resolved_workspace_id)
        if not repo_info:
            return {"success": False, "error": "Could not determine repo owner/name from git remote"}

        owner, repo = repo_info

        # Create PR via Gitea API
        api_url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": current_branch,
            "base": "main",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                api_url,
                json=payload,
                headers=_gitea_api_headers(),
                timeout=30.0,
            )

        if resp.status_code in (200, 201):
            pr_data = resp.json()
            return {
                "success": True,
                "pr_number": pr_data.get("number"),
                "pr_url": pr_data.get("url"),
                "html_url": pr_data.get("html_url"),
                "head_branch": current_branch,
                "base_branch": "main",
            }
        else:
            return {
                "success": False,
                "error": f"Gitea API error {resp.status_code}: {resp.text}",
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def merge_pull_request(
    pr_number: int,
    delete_branch: bool = True,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Merge a pull request on Gitea and optionally delete the source branch.

    Args:
        pr_number: The pull request number to merge
        delete_branch: Whether to delete the source branch after merge (default: True)
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for workspace resolution)
        repo_owner: Gitea repository owner (for workspace resolution)

    Returns:
        Dict with success, merged, branch_deleted
    """
    import httpx

    try:
        # Resolve workspace
        if session_id:
            resolved_workspace_id, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
                repo_name=repo_name,
                repo_owner=repo_owner,
            )
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        # Get repo info from remote
        repo_info = _get_repo_info(resolved_workspace_id)
        if not repo_info:
            return {"success": False, "error": "Could not determine repo owner/name from git remote"}

        owner, repo = repo_info
        cwd = ws["path"]

        # Merge PR via Gitea API
        merge_url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/pulls/{pr_number}/merge"
        merge_payload = {
            "Do": "merge",
            "delete_branch_after_merge": delete_branch,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                merge_url,
                json=merge_payload,
                headers=_gitea_api_headers(),
                timeout=30.0,
            )

        if resp.status_code in (200, 204):
            # Update local workspace to main branch
            subprocess.run(["git", "checkout", "main"], cwd=cwd, check=True)
            subprocess.run(["git", "pull", "origin", "main"], cwd=cwd, check=True)
            ws["branch"] = "main"
            _save_workspace_state(ws)

            return {
                "success": True,
                "merged": True,
                "pr_number": pr_number,
                "branch_deleted": delete_branch,
            }
        else:
            return {
                "success": False,
                "error": f"Gitea API error {resp.status_code}: {resp.text}",
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
