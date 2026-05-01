"""Coding v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)

Contains ALL tools from the original coding MCP server plus:
- validate_design (internal) — Mermaid pre-validation
- get_git_status — was referenced in agent YAMLs but never implemented
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastmcp import FastMCP
from .mermaid_validator import validate_mermaid_in_markdown
from .retry_module import revert_to_commit, close_pull_request
from .testing_module import TestingModule

# Configure logging
logger = logging.getLogger("coding-mcp")

MODULE_ID = "coding"
MODULE_VERSION = "1.0.0"

# Initialize FastMCP server
mcp = FastMCP(
    "Coding v1",
    version=MODULE_VERSION,
    instructions="File operations, git, testing, and pull requests in workspace sandbox.",
)

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")


def _testing_module(workspace_path: str | Path) -> TestingModule:
    """Create a TestingModule for the given workspace.

    This creates a new instance per call to avoid concurrency issues —
    a module-level singleton with mutated workspace_root would race
    under concurrent requests.
    """
    return TestingModule(str(workspace_path))


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


def _sanitize_param(value: str | None) -> str | None:
    """Sanitize LLM-provided parameter values.

    LLMs often send the literal strings "null", "none", or "undefined"
    when they don't have a value. Treat these as None to prevent
    cross-session data leaks via shared workspace registry keys.
    """
    if value and value.lower() in ("null", "none", "undefined", ""):
        return None
    return value


def _seed_platform_standards(workspace_path: Path) -> None:
    """Seed docs/platform-functional-standards.md into a workspace if missing.

    The BA agent expects this file to exist so it can reference platform
    defaults. Older projects (created before the template) won't have it.
    Seeding here ensures it's always available regardless of repo state.
    """
    standards_rel = Path("docs") / "platform-functional-standards.md"
    target = workspace_path / standards_rel
    if target.exists():
        return

    # Locate the template — bundled with the coding MCP server
    template = Path("/app/templates/platform-functional-standards.md")
    if not template.is_file():
        # Fallback: look relative to this file (dev mode / local runs)
        template = Path(__file__).resolve().parent.parent / "templates" / "platform-functional-standards.md"
    if not template.is_file():
        # Second fallback: full repo path (dev mode with full repo)
        template = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "project" / standards_rel
    if not template.is_file():
        return

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Seeded %s into workspace %s", standards_rel, workspace_path)
    except Exception as e:
        logger.warning("Failed to seed platform standards: %s", e)


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
    # Sanitize LLM sentinel strings ("null", "none", "undefined") → None
    workspace_id = _sanitize_param(workspace_id)
    user_id = _sanitize_param(user_id)
    project_id = _sanitize_param(project_id)

    # session_id is the canonical key — always derive workspace from it.
    # workspace_id is only a fallback when session_id is absent.
    derived_workspace_id = f"session-{session_id}"

    # Check if already registered for this session
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

    # Legacy fallback: workspace_id only used when not already matched by session
    if workspace_id and workspace_id in workspaces:
        ws = workspaces[workspace_id]
        # Verify session ownership — never return another session's workspace
        if ws.get("session_id") == session_id:
            if repo_name and not ws.get("repo_name"):
                ws["repo_name"] = repo_name
                ws["repo_owner"] = repo_owner
            return workspace_id, Path(ws["path"])
        else:
            logger.warning(
                "workspace_session_mismatch: workspace_id=%s belongs to session %s, "
                "but called from session %s — ignoring stale workspace_id",
                workspace_id, ws.get("session_id"), session_id,
            )

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

        # Seed platform standards file if missing from workspace
        _seed_platform_standards(workspace_path)

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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

    Files are written to disk only. Use run_git to commit and push.

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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "pre_validate": "validate_design"},
)
async def make_design(
    path: str,
    content: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Write a design document with Mermaid syntax validation.

    Validates all Mermaid code blocks before writing. If any Mermaid diagram
    contains syntax errors, the file is NOT written and errors are returned.

    Args:
        path: File path relative to workspace (e.g. docs/technical-design.md)
        content: Full markdown content for the design document
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for git remote setup)
        repo_owner: Gitea repository owner/username (for git remote setup)

    Returns:
        Dict with success, path, size — or error with Mermaid validation details
    """
    try:
        # Step 1: Validate Mermaid syntax before writing
        errors = validate_mermaid_in_markdown(content)
        if errors:
            error_lines = [
                f"Line {e.line_number} [{e.rule}]: {e.message}"
                for e in errors
            ]
            error_msg = (
                "MERMAID SYNTAX ERRORS — file was NOT written. "
                "Fix these errors and try again:\n\n"
                + "\n".join(error_lines)
                + "\n\nAfter fixing, call make_design again with the corrected content."
            )
            return {"success": False, "error": error_msg}

        # Step 2: No errors — write the file (same logic as write_file)
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
            "Writing design file in workspace %s: %s (%d bytes, Mermaid validated)",
            resolved_workspace_id,
            path,
            len(content),
        )

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(file_path.relative_to(workspace_path)),
            "size": len(content),
            "workspace_path": str(workspace_path),
        }

    except ValueError as e:
        logger.warning(
            "Path resolution error writing design in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(
            "Error writing design in workspace %s: %s - %s",
            session_id or workspace_id,
            path,
            str(e),
        )
        return {"success": False, "error": str(e)}


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "internal": True},
)
async def validate_design(
    content: str,
) -> dict:
    """Validate Mermaid syntax in markdown content without writing a file.

    Internal tool used for pre-validation of design documents.

    Args:
        content: Full markdown content to validate

    Returns:
        Dict with valid (bool) and optionally errors list
    """
    try:
        errors = validate_mermaid_in_markdown(content)
        if errors:
            return {
                "valid": False,
                "errors": [
                    {
                        "line_number": e.line_number,
                        "rule": e.rule,
                        "message": e.message,
                    }
                    for e in errors
                ],
            }
        return {"valid": True}
    except Exception as e:
        logger.error("Error validating design: %s", str(e))
        return {"valid": False, "errors": [{"message": str(e)}]}


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def delete_file(
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
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

        return {
            "success": True,
            "deleted": str(file_path.relative_to(workspace_path)),
        }

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


async def _run_git(
    workspace_id: str, command: str, repo_name: str = None, repo_owner: str = None
) -> dict:
    """Execute a whitelisted git command and return raw output."""
    ALLOWED_SUBCOMMANDS = {"add", "commit", "push", "pull", "fetch", "status", "checkout", "log", "diff", "branch"}
    CREDENTIAL_SUBCOMMANDS = {"push", "pull", "fetch"}

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return {"success": False, "error": f"Invalid command syntax: {e}"}

    if not parts:
        return {"success": False, "error": "Empty command"}

    # Strip leading "git" if provided
    if parts[0] == "git":
        parts = parts[1:]

    if not parts:
        return {"success": False, "error": "No git subcommand provided"}

    subcommand = parts[0]

    if subcommand not in ALLOWED_SUBCOMMANDS:
        return {
            "success": False,
            "error": f"Git subcommand '{subcommand}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_SUBCOMMANDS))}",
        }

    # Block destructive flags (not -f as it means different things per subcommand)
    BLOCKED_FLAGS = {"--force", "--hard"}
    found = BLOCKED_FLAGS & set(parts)
    if found:
        return {
            "success": False,
            "error": f"Destructive flags are not allowed: {found}",
        }

    ws = get_workspace(workspace_id)
    work_dir = ws["path"]

    # Inject credentials for network commands
    if subcommand in CREDENTIAL_SUBCOMMANDS and repo_name and repo_owner:
        gitea_url = get_gitea_clone_url(repo_name, repo_owner)
        if gitea_url:
            try:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", gitea_url],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                pass

    # Build and run the git command
    full_cmd = ["git"] + parts
    logger.info("run_git: command=%s work_dir=%s", full_cmd, work_dir)

    try:
        result = subprocess.run(
            full_cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 120 seconds"}
    except Exception as e:
        return {"success": False, "error": f"Failed to execute command: {e}"}

    output = result.stdout.strip()
    error_output = result.stderr.strip()
    combined = f"{output}\n{error_output}".strip() if error_output else output

    response = {
        "success": result.returncode == 0,
        "output": combined,
        "exit_code": result.returncode,
    }

    # Auto-capture commit SHA from git commit output
    if subcommand == "commit" and result.returncode == 0:
        sha_match = re.search(r'\[[\w/.-]+ ([a-f0-9]+)\]', output + " " + error_output)
        if sha_match:
            response["commit_sha"] = sha_match.group(1)

    # Update workspace branch tracking on checkout
    if subcommand == "checkout" and result.returncode == 0:
        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if branch_result.returncode == 0:
                ws["branch"] = branch_result.stdout.strip()
                _save_workspace_state(ws)
        except Exception:
            pass

    if not response["success"]:
        response["error"] = error_output or "Command failed"

    return response


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

    Files are written to disk only. Use run_git to commit and push.

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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def run_git(
    command: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Execute a git command in the workspace.

    Allowed subcommands: add, commit, push, pull, fetch, status, checkout, log, diff, branch.
    Destructive flags (--force, --hard) are blocked.

    Args:
        command: Git command to execute (e.g. "status", "git log --oneline -5")
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for credential injection on push)
        repo_owner: Gitea repository owner (for credential injection on push)

    Returns:
        Dict with success, output, exit_code, and optionally commit_sha or error
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

    return await _run_git(resolved_workspace_id, command, repo_name, repo_owner)


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_git_status(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
) -> dict:
    """Get git status of the workspace.

    Convenience tool that wraps run_git("status"). Referenced in agent YAML
    definitions for quick workspace state checks.

    Args:
        session_id: Session ID (auto-creates workspace if needed)
        workspace_id: Legacy workspace ID (optional)
        project_id: Project ID for workspace path (optional)
        user_id: User ID for workspace path (optional)
        repo_name: Gitea repository name (for workspace resolution)
        repo_owner: Gitea repository owner (for workspace resolution)

    Returns:
        Dict with success, output, exit_code
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

    return await _run_git(resolved_workspace_id, "status", repo_name, repo_owner)


# =============================================================================
# TESTING TOOLS (delegated to TestingModule)
# =============================================================================


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

        tm = _testing_module(workspace_path)
        framework_info = tm.get_test_framework_info()

        if framework_info["framework"] == "unknown":
            return {
                "success": True,
                "framework": "unknown",
                "message": "No test framework detected yet. This is normal for new projects. Read docs/technical-design.md to determine the tech stack and set up the appropriate test framework.",
            }

        return {"success": True, **framework_info}

    except Exception as e:
        logger.error("Error detecting test framework: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

        tm = _testing_module(workspace_path)

        # Detect framework if command not provided
        if not test_command or test_command.strip().lower() in ("null", "none", ""):
            test_command = None
            framework_info = tm.get_test_framework_info()
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
            elif "vitest" in test_command:
                framework = "vitest"
            elif "jest" in test_command:
                framework = "jest"
            elif test_command.strip() in ("npm test", "npm run test"):
                # Generic npm test — try to detect the actual framework
                framework_info = tm.get_test_framework_info()
                if framework_info["framework"] != "unknown":
                    framework = framework_info["framework"]
            elif "go test" in test_command:
                framework = "go"
            elif "cargo test" in test_command:
                framework = "cargo"

        logger.info("Running tests in workspace %s: %s", workspace_path, test_command)

        start_time = time.time()
        try:
            # Use shlex.split + shell=False to prevent shell injection.
            # test_command can come from the LLM agent via prompt injection.
            result = subprocess.run(
                shlex.split(test_command),
                shell=False,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.time() - start_time

            parsed_results = tm.parse_test_results(
                result.stdout + "\n" + result.stderr,
                framework,
            )

            coverage = None
            if framework in ["vitest", "jest", "pytest"]:
                coverage = tm.parse_coverage_json(framework)
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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

        tm = _testing_module(workspace_path)

        if not framework:
            framework_info = tm.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {"success": False, "error": "Could not auto-detect test framework."}
            framework = framework_info["framework"]

        coverage = tm.parse_coverage_json(framework)

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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

        tm = _testing_module(workspace_path)

        if not framework:
            framework_info = tm.get_test_framework_info()
            if framework_info["framework"] == "unknown":
                return {"success": False, "error": "Could not auto-detect test framework."}
            framework = framework_info["framework"]

        results = []

        if framework == "pytest":
            # Install project dependencies first (mirrors npm install for Node.js).
            # This must happen before checking what's missing because
            # _check_framework_dependencies only checks if packages are listed
            # in requirements.txt, not whether they're actually installed.
            requirements_txt = workspace_path / "requirements.txt"
            pyproject_toml = workspace_path / "pyproject.toml"

            if requirements_txt.exists():
                logger.info("Installing project dependencies from requirements.txt in %s", workspace_path)
                try:
                    req_result = subprocess.run(
                        ["pip", "install", "-r", "requirements.txt"],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    results.append({
                        "dependency": "requirements.txt (all)",
                        "success": req_result.returncode == 0,
                        "output": req_result.stdout,
                        "error": req_result.stderr if req_result.returncode != 0 else None,
                    })
                    if req_result.returncode != 0:
                        return {
                            "success": False,
                            "framework": framework,
                            "error": f"Failed to install project dependencies: {req_result.stderr}",
                            "results": results,
                        }
                except subprocess.TimeoutExpired:
                    return {
                        "success": False,
                        "framework": framework,
                        "error": "pip install -r requirements.txt timed out after 300 seconds",
                        "results": results,
                    }
                except Exception as e:
                    results.append({"dependency": "requirements.txt (all)", "success": False, "error": str(e)})
            elif pyproject_toml.exists():
                logger.info("Installing project from pyproject.toml in %s", workspace_path)
                try:
                    pyp_result = subprocess.run(
                        ["pip", "install", "."],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    results.append({
                        "dependency": "pyproject.toml (all)",
                        "success": pyp_result.returncode == 0,
                        "output": pyp_result.stdout,
                        "error": pyp_result.stderr if pyp_result.returncode != 0 else None,
                    })
                    if pyp_result.returncode != 0:
                        return {
                            "success": False,
                            "framework": framework,
                            "error": f"Failed to install project: {pyp_result.stderr}",
                            "results": results,
                        }
                except subprocess.TimeoutExpired:
                    return {
                        "success": False,
                        "framework": framework,
                        "error": "pip install . timed out after 300 seconds",
                        "results": results,
                    }
                except Exception as e:
                    results.append({"dependency": "pyproject.toml (all)", "success": False, "error": str(e)})

            # After installing project deps, check which test frameworks are still missing.
            # requirements.txt may include pytest, so re-check actual installation.
            deps_check = tm._check_framework_dependencies(framework)
            missing = deps_check.get("missing", [])

            if missing:
                logger.info("Installing missing test framework packages: %s", missing)
                for dep in missing:
                    try:
                        result = subprocess.run(
                            ["pip", "install", dep],
                            cwd=str(workspace_path),
                            capture_output=True,
                            text=True,
                            timeout=120,
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
            # Run npm install first if node_modules doesn't exist
            node_modules = workspace_path / "node_modules"
            if not node_modules.exists():
                logger.info("node_modules missing, running npm install first in %s", workspace_path)
                try:
                    npm_result = subprocess.run(
                        ["npm", "install"],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    results.append({
                        "dependency": "npm install (all)",
                        "success": npm_result.returncode == 0,
                        "output": npm_result.stdout,
                        "error": npm_result.stderr if npm_result.returncode != 0 else None,
                    })
                    if npm_result.returncode != 0:
                        return {
                            "success": False,
                            "framework": framework,
                            "error": f"npm install failed: {npm_result.stderr}",
                            "results": results,
                        }
                except subprocess.TimeoutExpired:
                    return {
                        "success": False,
                        "framework": framework,
                        "error": "npm install timed out after 180 seconds",
                        "results": results,
                    }
                except Exception as e:
                    results.append({"dependency": "npm install (all)", "success": False, "error": str(e)})

            # Install any still-missing individual packages
            # Re-check after npm install
            deps_recheck = _testing_module(workspace_path)._check_framework_dependencies(framework)
            still_missing = deps_recheck.get("missing", [])

            for dep in still_missing:
                try:
                    result = subprocess.run(
                        ["npm", "install", "--save-dev", dep],
                        cwd=str(workspace_path),
                        capture_output=True,
                        text=True,
                        timeout=120,
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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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

        tm = _testing_module(workspace_path)

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

        framework_info = tm.get_test_framework_info()
        framework = framework_info["framework"]

        coverage = tm.parse_coverage_json(framework)
        coverage_percent = coverage.get("overall_percent", 0) if coverage else 0

        test_results = test_result.get("results", {})
        config = {"coverage_threshold": coverage_threshold}

        validation = tm.validate_tdd_workflow(test_results, config)

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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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
# PROJECT DISCOVERY TOOLS (cross-project read-only access via Gitea API)
# =============================================================================


@mcp.tool(
    name="list_projects",
    description=(
        "List all project repositories in the Gitea organization. "
        "Returns name, description, last update time, and default branch "
        "for each project. Use this to discover what has been built before."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_projects() -> dict:
    """List all project repos in the Gitea organization."""
    import httpx

    if not GITEA_URL or not GITEA_ORG:
        return {"success": False, "error": "Gitea not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{GITEA_URL}/api/v1/orgs/{GITEA_ORG}/repos",
                headers=_gitea_api_headers(),
                params={"limit": 50},
            )
            if response.status_code != 200:
                return {"success": False, "error": f"Gitea API returned {response.status_code}"}

            repos = response.json()
            projects = [
                {
                    "name": r["name"],
                    "description": r.get("description", ""),
                    "updated_at": r.get("updated_at", ""),
                    "default_branch": r.get("default_branch", "main"),
                }
                for r in repos
            ]
            return {"success": True, "count": len(projects), "projects": projects}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="read_project_file",
    description=(
        "Read a file from any project repository in Gitea. "
        "Use this to inspect docs/technical-design.md, Dockerfiles, or source "
        "code from existing projects to understand patterns and reuse opportunities."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def read_project_file(repo_name: str, path: str, ref: str = "main") -> dict:
    """Read a file from any project repository."""
    import re
    import httpx

    if not GITEA_URL or not GITEA_ORG:
        return {"success": False, "error": "Gitea not configured"}

    # Validate inputs to prevent path traversal
    if not re.match(r"^[a-zA-Z0-9._-]+$", repo_name):
        return {"success": False, "error": "Invalid repo_name"}
    if ".." in path or path.startswith("/"):
        return {"success": False, "error": "Invalid path"}
    if not re.match(r"^[a-zA-Z0-9._/\-]+$", ref):
        return {"success": False, "error": "Invalid ref"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{GITEA_URL}/api/v1/repos/{GITEA_ORG}/{repo_name}/raw/{path}",
                headers=_gitea_api_headers(),
                params={"ref": ref},
            )
            if response.status_code == 404:
                return {"success": False, "error": f"File '{path}' not found in {repo_name} (ref: {ref})"}
            if response.status_code != 200:
                return {"success": False, "error": f"Gitea API returned {response.status_code}"}

            content = response.text
            # Cap large files
            if len(content) > 50000:
                content = content[:50000] + "\n\n... (truncated, file too large)"

            return {"success": True, "repo": repo_name, "path": path, "ref": ref, "content": content}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="list_project_files",
    description=(
        "List all files in a project repository. "
        "Use this to understand a project's structure before reading specific files."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_project_files(repo_name: str, path: str = "", ref: str = "main") -> dict:
    """List files in a project repository."""
    import httpx

    if not GITEA_URL or not GITEA_ORG:
        return {"success": False, "error": "Gitea not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{GITEA_URL}/api/v1/repos/{GITEA_ORG}/{repo_name}/git/trees/{ref}",
                headers=_gitea_api_headers(),
                params={"recursive": "true"},
            )
            if response.status_code == 404:
                return {"success": False, "error": f"Repository '{repo_name}' not found or ref '{ref}' does not exist"}
            if response.status_code != 200:
                return {"success": False, "error": f"Gitea API returned {response.status_code}"}

            tree = response.json().get("tree", [])
            # Filter by path prefix if specified
            if path:
                prefix = path.rstrip("/") + "/"
                tree = [e for e in tree if e.get("path", "").startswith(prefix)]

            files = [
                {
                    "path": e["path"],
                    "type": e.get("type", ""),  # "blob" or "tree"
                    "size": e.get("size", 0),
                }
                for e in tree
            ]
            return {"success": True, "repo": repo_name, "ref": ref, "count": len(files), "files": files}

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# INTERNAL TOOLS (used by backend, not exposed to agents)
# =============================================================================


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "internal": True},
)
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
        else:
            return {"success": False, "error": "Either session_id or workspace_id is required"}

        # Build Gitea clone URL if configured
        gitea_clone_url = None
        if is_gitea_configured():
            repo_name_ws = ws.get("repo_name") or repo_name
            repo_owner_ws = ws.get("repo_owner") or repo_owner
            if repo_name_ws:
                gitea_clone_url = get_gitea_clone_url(repo_name_ws, repo_owner_ws)

        return revert_to_commit(
            workspace_path=workspace_path,
            branch=ws["branch"],
            target_commit=target_commit,
            gitea_clone_url=gitea_clone_url,
            is_gitea_configured=is_gitea_configured(),
        )

    except Exception as e:
        logger.error("revert_to_commit error: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "internal": True},
)
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
    """
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

        return await close_pull_request(
            pr_number=pr_number,
            repo_owner=owner,
            repo_name=repo,
            gitea_url=GITEA_URL,
            api_headers=_gitea_api_headers(),
        )

    except Exception as e:
        logger.error("close_pull_request error: %s", e)
        return {"success": False, "error": str(e)}
