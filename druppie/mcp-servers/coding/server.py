"""Coding MCP Server.

Combined file operations and git functionality for workspace sandbox.
Uses FastMCP framework for HTTP transport.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("coding-mcp")

# Initialize FastMCP server
mcp = FastMCP("Coding MCP Server")

# =============================================================================
# SECURITY: COMMAND BLOCKLIST
# =============================================================================

# Dangerous command patterns that should never be executed
BLOCKED_COMMAND_PATTERNS = [
    # Destructive file operations
    r"rm\s+(-[rf]+\s+)*\s*/\s*$",  # rm -rf / or rm /
    r"rm\s+(-[rf]+\s+)*\s*/\*",  # rm -rf /*
    r"rm\s+(-[rf]+\s+)+\s*/",  # rm -rf /anything at root
    # Disk/filesystem operations
    r"\bmkfs\b",  # mkfs (format filesystem)
    r"\bdd\s+if=",  # dd if= (disk operations)
    r"\bfdisk\b",  # fdisk (partition management)
    r"\bparted\b",  # parted (partition management)
    # Privilege escalation
    r"\bsudo\b",  # sudo commands
    r"\bsu\s+-",  # su - (switch user)
    r"\bsu\s+root",  # su root
    # Dangerous permission changes
    r"\bchmod\s+777\b",  # chmod 777 (world-writable)
    r"\bchmod\s+-R\s+777\b",  # chmod -R 777
    r"\bchown\s+.*\s+/",  # chown on system directories
    # System modification
    r"\bshutdown\b",  # shutdown
    r"\breboot\b",  # reboot
    r"\binit\s+[0-6]",  # init runlevel changes
    r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|network)",  # Critical service disruption
    # Network attacks
    r":\(\)\s*{\s*:\|\s*:&\s*}\s*;",  # Fork bomb
    r">\s*/dev/sd[a-z]",  # Write to disk devices
    r">\s*/dev/null\s*2>&1\s*&",  # Background with hidden output (often malicious)
    # Sensitive file access
    r">\s*/etc/passwd",  # Overwrite passwd
    r">\s*/etc/shadow",  # Overwrite shadow
    r">\s*/etc/sudoers",  # Overwrite sudoers
    # Reverse shells and remote execution
    r"\bnc\s+-[elp]",  # netcat listener
    r"\bbash\s+-i\s+>&\s+/dev/tcp",  # Bash reverse shell
    r"\bcurl\s+.*\|\s*bash",  # Piping curl to bash
    r"\bwget\s+.*\|\s*bash",  # Piping wget to bash
    r"\bcurl\s+.*\|\s*sh",  # Piping curl to sh
    r"\bwget\s+.*\|\s*sh",  # Piping wget to sh
]

# Compile patterns for performance
BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMAND_PATTERNS]


def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches any blocked patterns.

    Args:
        command: The command string to check

    Returns:
        Tuple of (is_blocked, matched_pattern_description)
    """
    for i, pattern in enumerate(BLOCKED_PATTERNS_COMPILED):
        if pattern.search(command):
            return True, BLOCKED_COMMAND_PATTERNS[i]
    return False, None

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")

# In-memory workspace registry (in production, use Redis/DB)
workspaces: dict[str, dict] = {}


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
        # Update repo info if provided and not already set
        if repo_name and not ws.get("repo_name"):
            ws["repo_name"] = repo_name
            ws["repo_owner"] = repo_owner
        return derived_workspace_id, Path(ws["path"])

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

    # Register workspace
    workspaces[derived_workspace_id] = {
        "path": str(workspace_path),
        "project_id": project_id,
        "branch": "main",
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


@mcp.tool()
async def run_command(
    command: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    timeout: int = 60,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Execute shell command in workspace (requires approval).

    Args:
        command: Shell command to execute
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        timeout: Timeout in seconds (default: 60)
        repo_name: Gitea repository name (for cloning)
        repo_owner: Gitea repository owner (for cloning)

    Returns:
        Dict with success, stdout, stderr, return_code
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
            workspace_path = str(workspace_path)
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = ws["path"]
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        # Security: Check command against blocklist
        is_blocked, matched_pattern = is_command_blocked(command)
        if is_blocked:
            logger.warning(
                "Blocked dangerous command in workspace %s: %s (matched pattern: %s)",
                resolved_workspace_id,
                command,
                matched_pattern,
            )
            return {
                "success": False,
                "error": "Command blocked for security reasons",
                "blocked": True,
                "reason": "This command matches a dangerous pattern and cannot be executed",
            }

        logger.info(
            "Executing command in workspace %s: %s",
            resolved_workspace_id,
            command[:200] + "..." if len(command) > 200 else command,
        )

        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        logger.info(
            "Command completed in workspace %s with return code %d",
            resolved_workspace_id,
            result.returncode,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "cwd": workspace_path,
        }

    except subprocess.TimeoutExpired:
        logger.warning(
            "Command timed out after %ds in workspace %s: %s",
            timeout,
            session_id or workspace_id,
            command[:100],
        )
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        logger.error(
            "Command execution failed in workspace %s: %s",
            session_id or workspace_id,
            str(e),
        )
        return {"success": False, "error": str(e)}


def _detect_test_framework(workspace_path: Path) -> tuple[str | None, str | None]:
    """Detect test framework from project files.

    Returns:
        Tuple of (framework_name, test_command)
    """
    # Check for Node.js/npm project
    package_json = workspace_path / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                # Check for common test frameworks
                test_script = scripts["test"]
                if "jest" in test_script:
                    return ("jest", "npm test")
                elif "mocha" in test_script:
                    return ("mocha", "npm test")
                elif "vitest" in test_script:
                    return ("vitest", "npm test")
                elif "ava" in test_script:
                    return ("ava", "npm test")
                else:
                    return ("npm", "npm test")
        except (json.JSONDecodeError, KeyError):
            pass

    # Check for Python pytest
    pytest_ini = workspace_path / "pytest.ini"
    pyproject_toml = workspace_path / "pyproject.toml"
    setup_py = workspace_path / "setup.py"

    # Check for test files
    has_pytest_files = list(workspace_path.glob("test_*.py")) or list(workspace_path.glob("**/test_*.py"))
    has_tests_dir = (workspace_path / "tests").exists()

    if pytest_ini.exists() or has_pytest_files or has_tests_dir:
        return ("pytest", "pytest -v")

    # Check pyproject.toml for pytest config
    if pyproject_toml.exists():
        try:
            content = pyproject_toml.read_text()
            if "[tool.pytest" in content:
                return ("pytest", "pytest -v")
        except Exception:
            pass

    # Check for Go tests
    go_test_files = list(workspace_path.glob("*_test.go")) or list(workspace_path.glob("**/*_test.go"))
    go_mod = workspace_path / "go.mod"
    if go_test_files or go_mod.exists():
        return ("go", "go test -v ./...")

    # Check for Rust tests
    cargo_toml = workspace_path / "Cargo.toml"
    if cargo_toml.exists():
        return ("cargo", "cargo test")

    # Check for Ruby/RSpec
    gemfile = workspace_path / "Gemfile"
    spec_dir = workspace_path / "spec"
    if spec_dir.exists():
        return ("rspec", "bundle exec rspec")
    elif gemfile.exists():
        try:
            content = gemfile.read_text()
            if "rspec" in content.lower():
                return ("rspec", "bundle exec rspec")
            elif "minitest" in content.lower():
                return ("minitest", "bundle exec rake test")
        except Exception:
            pass

    # Check for Java/Maven
    pom_xml = workspace_path / "pom.xml"
    if pom_xml.exists():
        return ("maven", "mvn test")

    # Check for Java/Gradle
    build_gradle = workspace_path / "build.gradle"
    build_gradle_kts = workspace_path / "build.gradle.kts"
    if build_gradle.exists() or build_gradle_kts.exists():
        return ("gradle", "./gradlew test")

    return (None, None)


def _parse_test_output(stdout: str, stderr: str, framework: str) -> dict:
    """Parse test output to extract pass/fail counts.

    Returns:
        Dict with total, passed, failed, skipped, failed_tests
    """
    result = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failed_tests": [],
    }

    combined = stdout + "\n" + stderr

    if framework == "pytest":
        # pytest output: "5 passed, 2 failed, 1 skipped in 1.23s"
        match = re.search(
            r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?",
            combined,
        )
        if match:
            result["passed"] = int(match.group(1))
            result["failed"] = int(match.group(2)) if match.group(2) else 0
            result["skipped"] = int(match.group(3)) if match.group(3) else 0
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Extract failed test names
        failed_matches = re.findall(r"FAILED\s+([\w:]+)", combined)
        result["failed_tests"] = failed_matches

    elif framework in ("jest", "vitest"):
        # Jest/Vitest: "Tests: 2 failed, 5 passed, 7 total"
        match = re.search(
            r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total",
            combined,
        )
        if match:
            result["failed"] = int(match.group(1)) if match.group(1) else 0
            result["skipped"] = int(match.group(2)) if match.group(2) else 0
            result["passed"] = int(match.group(3)) if match.group(3) else 0
            result["total"] = int(match.group(4))

        # Extract failed test names
        failed_matches = re.findall(r"FAIL\s+(.+)", combined)
        result["failed_tests"] = failed_matches

    elif framework == "mocha":
        # Mocha: "5 passing (1s)\n2 failing"
        passing = re.search(r"(\d+)\s+passing", combined)
        failing = re.search(r"(\d+)\s+failing", combined)
        pending = re.search(r"(\d+)\s+pending", combined)

        if passing:
            result["passed"] = int(passing.group(1))
        if failing:
            result["failed"] = int(failing.group(1))
        if pending:
            result["skipped"] = int(pending.group(1))
        result["total"] = result["passed"] + result["failed"] + result["skipped"]

    elif framework == "go":
        # Go test: "ok  \tpackage\t0.123s" or "FAIL\tpackage\t0.123s"
        # Also: "--- FAIL: TestName"
        ok_count = len(re.findall(r"^ok\s+", combined, re.MULTILINE))
        fail_count = len(re.findall(r"^FAIL\s+", combined, re.MULTILINE))
        skip_count = len(re.findall(r"^SKIP\s+", combined, re.MULTILINE))

        # Try to get individual test counts
        pass_match = re.search(r"PASS", combined)
        individual_fails = re.findall(r"--- FAIL:\s+(\w+)", combined)

        result["passed"] = ok_count if ok_count else (1 if pass_match else 0)
        result["failed"] = len(individual_fails) if individual_fails else fail_count
        result["skipped"] = skip_count
        result["total"] = result["passed"] + result["failed"] + result["skipped"]
        result["failed_tests"] = individual_fails

    elif framework == "cargo":
        # Rust/Cargo: "test result: ok. 5 passed; 0 failed; 0 ignored"
        match = re.search(
            r"(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+ignored",
            combined,
        )
        if match:
            result["passed"] = int(match.group(1))
            result["failed"] = int(match.group(2))
            result["skipped"] = int(match.group(3))
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Extract failed test names
        failed_matches = re.findall(r"---- (\S+) stdout ----", combined)
        result["failed_tests"] = failed_matches

    elif framework == "rspec":
        # RSpec: "10 examples, 2 failures, 1 pending"
        match = re.search(
            r"(\d+)\s+examples?,\s*(\d+)\s+failures?(?:,\s*(\d+)\s+pending)?",
            combined,
        )
        if match:
            result["total"] = int(match.group(1))
            result["failed"] = int(match.group(2))
            result["skipped"] = int(match.group(3)) if match.group(3) else 0
            result["passed"] = result["total"] - result["failed"] - result["skipped"]

    elif framework in ("maven", "gradle"):
        # Maven/Gradle: "Tests run: 10, Failures: 2, Errors: 1, Skipped: 1"
        match = re.search(
            r"Tests\s+run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
            combined,
        )
        if match:
            result["total"] = int(match.group(1))
            result["failed"] = int(match.group(2)) + int(match.group(3))  # failures + errors
            result["skipped"] = int(match.group(4))
            result["passed"] = result["total"] - result["failed"] - result["skipped"]

    else:
        # Generic npm test or unknown - try common patterns
        # Try "X passing, Y failing" pattern
        match = re.search(r"(\d+)\s+(?:passing|passed)", combined)
        if match:
            result["passed"] = int(match.group(1))
        match = re.search(r"(\d+)\s+(?:failing|failed)", combined)
        if match:
            result["failed"] = int(match.group(1))
        match = re.search(r"(\d+)\s+(?:pending|skipped)", combined)
        if match:
            result["skipped"] = int(match.group(1))
        result["total"] = result["passed"] + result["failed"] + result["skipped"]

    return result


@mcp.tool()
async def run_tests(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    test_command: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run tests in the workspace and return structured results.

    If test_command is not provided, auto-detects the test framework
    and runs the appropriate command (npm test, pytest, etc.).

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        test_command: Optional test command to run
        timeout: Timeout in seconds (default 120)

    Returns:
        {
            "success": true/false,
            "framework": "pytest",
            "command_used": "pytest -v",
            "total": 10,
            "passed": 8,
            "failed": 2,
            "skipped": 0,
            "failed_tests": ["test_foo", "test_bar"],
            "stdout": "...",
            "stderr": "...",
            "duration_seconds": 5.2
        }
    """
    try:
        # Resolve workspace
        if session_id:
            _, workspace_path = get_or_create_workspace(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
        elif workspace_id:
            ws = get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        # Auto-detect test framework if command not provided
        framework = None
        command = test_command

        if command is None:
            framework, command = _detect_test_framework(workspace_path)
            if command is None:
                return {
                    "success": False,
                    "error": "Could not detect test framework. Please provide test_command.",
                    "hint": "Supported frameworks: pytest, jest, mocha, vitest, go test, cargo test, rspec, maven, gradle",
                }
        else:
            # Try to determine framework from command
            if "pytest" in command:
                framework = "pytest"
            elif "jest" in command:
                framework = "jest"
            elif "vitest" in command:
                framework = "vitest"
            elif "mocha" in command:
                framework = "mocha"
            elif "go test" in command:
                framework = "go"
            elif "cargo test" in command:
                framework = "cargo"
            elif "rspec" in command:
                framework = "rspec"
            elif "mvn test" in command or "maven" in command:
                framework = "maven"
            elif "gradle" in command:
                framework = "gradle"
            elif "npm test" in command:
                # Try to detect from package.json
                framework, _ = _detect_test_framework(workspace_path)
                if framework is None:
                    framework = "npm"
            else:
                framework = "unknown"

        # Run the test command
        start_time = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_time

            # Parse test output
            parsed = _parse_test_output(result.stdout, result.stderr, framework)

            return {
                "success": result.returncode == 0,
                "framework": framework,
                "command_used": command,
                "total": parsed["total"],
                "passed": parsed["passed"],
                "failed": parsed["failed"],
                "skipped": parsed["skipped"],
                "failed_tests": parsed["failed_tests"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "duration_seconds": round(duration, 2),
            }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return {
                "success": False,
                "framework": framework,
                "command_used": command,
                "error": f"Test command timed out after {timeout} seconds",
                "duration_seconds": round(duration, 2),
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
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
    files: dict[str, str],
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
        files: Dict mapping file paths (relative to workspace) to their contents
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
            files={
                "src/index.js": "console.log('hello');",
                "src/utils.js": "export const add = (a, b) => a + b;",
                "package.json": '{"name": "myapp"}'
            }
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
        for path, content in files.items():
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
) -> dict:
    """Commit all changes and push to Gitea.

    Args:
        message: Commit message
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
) -> dict:
    """Create and switch to a git branch. If the branch already exists, switches to it.

    Args:
        branch_name: Name of the branch to create or switch to
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
) -> dict:
    """Merge current branch to main (requires approval).

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
) -> dict:
    """Get git status for workspace.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
) -> dict:
    """Create a pull request from the current branch to main on Gitea.

    Args:
        title: PR title
        body: PR description (optional)
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
            )
            ws = workspaces[resolved_workspace_id]
        elif workspace_id:
            ws = get_workspace(workspace_id)
            resolved_workspace_id = workspace_id
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        current_branch = ws["branch"]
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
) -> dict:
    """Merge a pull request on Gitea and optionally delete the source branch.

    Args:
        pr_number: The pull request number to merge
        delete_branch: Whether to delete the source branch after merge (default: True)
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)

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
