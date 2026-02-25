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

        # Capture commit SHA after commit
        commit_sha = None
        if has_changes:
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True
            )
            commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

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
                    result = {"success": True, "message": msg, "pushed": True, "committed": has_changes}
                    if commit_sha:
                        result["commit_sha"] = commit_sha
                    return result
                else:
                    logger.warning("Push failed: %s", push_result.stderr)
                    msg = f"Committed: {message}" if has_changes else "No changes to commit"
                    result = {"success": True, "message": msg, "pushed": False, "committed": has_changes, "push_error": push_result.stderr}
                    if commit_sha:
                        result["commit_sha"] = commit_sha
                    return result
            except subprocess.CalledProcessError as e:
                msg = f"Committed: {message}" if has_changes else "No changes to commit"
                result = {"success": True, "message": msg, "pushed": False, "committed": has_changes, "push_error": str(e)}
                if commit_sha:
                    result["commit_sha"] = commit_sha
                return result

        if not has_changes:
            return {"success": True, "message": "No changes to commit", "pushed": False, "committed": False}
        result = {"success": True, "message": f"Committed: {message}", "pushed": False, "committed": True}
        if commit_sha:
            result["commit_sha"] = commit_sha
        return result

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

        import time
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
# INTERNAL TOOLS (used by backend, not exposed to agents)
# =============================================================================


@mcp.tool()
async def _internal_revert_to_commit(
    target_commit: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Revert workspace to a specific commit (hard reset + force push).

    Internal tool used by the backend for retry/revert operations.
    Not intended for direct agent use.

    Args:
        target_commit: The commit SHA to reset to
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner

    Returns:
        Dict with success, previous_head, new_head, force_pushed
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
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        cwd = str(workspace_path)
        branch = ws["branch"]

        # Capture current HEAD
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True
        )
        previous_head = head_result.stdout.strip() if head_result.returncode == 0 else None

        logger.info(
            "revert_to_commit: %s -> %s (branch=%s)",
            previous_head, target_commit, branch,
        )

        # Hard reset to target commit
        reset_result = subprocess.run(
            ["git", "reset", "--hard", target_commit],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if reset_result.returncode != 0:
            return {
                "success": False,
                "error": f"git reset --hard failed: {reset_result.stderr}",
            }

        # Capture new HEAD
        new_head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True
        )
        new_head = new_head_result.stdout.strip() if new_head_result.returncode == 0 else None

        # Force push if Gitea is configured
        force_pushed = False
        if is_gitea_configured():
            repo_name_ws = ws.get("repo_name") or repo_name
            repo_owner_ws = ws.get("repo_owner") or repo_owner
            if repo_name_ws:
                auth_url = get_gitea_clone_url(repo_name_ws, repo_owner_ws)
                subprocess.run(
                    ["git", "remote", "set-url", "origin", auth_url],
                    cwd=cwd,
                    check=True,
                    capture_output=True,
                )

            push_result = subprocess.run(
                ["git", "push", "--force", "origin", branch],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if push_result.returncode == 0:
                force_pushed = True
                logger.info("Force pushed to %s after revert", branch)
            else:
                logger.warning("Force push failed: %s", push_result.stderr)
                return {
                    "success": True,
                    "message": "Reset succeeded but force push failed",
                    "previous_head": previous_head,
                    "new_head": new_head,
                    "force_pushed": False,
                    "push_error": push_result.stderr,
                }

        return {
            "success": True,
            "previous_head": previous_head,
            "new_head": new_head,
            "force_pushed": force_pushed,
        }

    except Exception as e:
        logger.error("revert_to_commit error: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
async def _internal_close_pull_request(
    pr_number: int,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Close an open pull request on Gitea without merging.

    Internal tool used by the backend for retry/revert operations.

    Args:
        pr_number: The pull request number to close
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner

    Returns:
        Dict with success, pr_number, closed
    """
    import httpx

    try:
        # Resolve workspace to get repo info
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

        # Get repo info from remote
        repo_info = _get_repo_info(resolved_workspace_id)
        if not repo_info:
            return {"success": False, "error": "Could not determine repo owner/name from git remote"}

        owner, repo = repo_info

        # Close PR via Gitea API
        api_url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/pulls/{pr_number}"
        payload = {"state": "closed"}

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                api_url,
                json=payload,
                headers=_gitea_api_headers(),
                timeout=30.0,
            )

        if resp.status_code in (200, 204):
            logger.info("Closed PR #%d on %s/%s", pr_number, owner, repo)
            return {"success": True, "pr_number": pr_number, "closed": True}
        else:
            return {
                "success": False,
                "error": f"Gitea API error {resp.status_code}: {resp.text}",
            }

    except Exception as e:
        logger.error("close_pull_request error: %s", e)
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
