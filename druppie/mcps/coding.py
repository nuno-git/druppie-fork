"""Coding MCP Server.

Provides file operations and code generation capabilities.
All file operations are sandboxed to the workspace directory.

In the git-first architecture:
- Files are relative to the workspace.local_path (cloned repo)
- write_file can auto-commit and push changes
- The workspace is set via ExecutionContext
"""

import asyncio
import os
import glob as glob_module
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool
from druppie.core.execution_context import get_current_context

logger = structlog.get_logger()

# Fallback workspace root (used when no workspace context is set)
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))


def get_workspace_root() -> Path:
    """Get the workspace root for the current context.

    Returns workspace_path from ExecutionContext if available,
    otherwise falls back to WORKSPACE_ROOT.
    """
    ctx = get_current_context()
    if ctx and ctx.workspace_path:
        return Path(ctx.workspace_path)
    return WORKSPACE_ROOT


def resolve_path(path: str, workspace_root: Path | None = None) -> Path:
    """Resolve a path relative to the workspace root.

    - Absolute paths are rejected (security)
    - Relative paths are resolved within workspace root
    - Path traversal attempts (../) are blocked

    Args:
        path: Path to resolve
        workspace_root: Override workspace root (uses context if not provided)

    Returns:
        Resolved absolute path
    """
    root = workspace_root or get_workspace_root()

    # Convert to Path object
    p = Path(path)

    # Block absolute paths
    if p.is_absolute():
        # Allow if it's already under workspace root
        try:
            p.relative_to(root)
            return p
        except ValueError:
            # Re-root to workspace
            return root / p.name

    # Resolve relative path within workspace
    resolved = (root / p).resolve()

    # Security: ensure it's still under workspace root
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"Path traversal not allowed: {path}")

    return resolved


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

CODING_TOOLS = [
    MCPTool(
        id="coding:read_file",
        name="Read File",
        description="Read the contents of a file",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="coding:write_file",
        name="Write File",
        description="Write content to a file (creates parent directories if needed). Auto-commits to git if workspace is initialized.",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "auto_commit": {
                    "type": "boolean",
                    "description": "Automatically commit and push changes (default: true)",
                    "default": True,
                },
                "commit_message": {
                    "type": "string",
                    "description": "Custom commit message (optional)",
                },
            },
            "required": ["path", "content"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="coding:list_dir",
        name="List Directory",
        description="List files in a directory with optional pattern matching",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns to match (e.g., ['*.py', '*.js'])",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search recursively",
                    "default": True,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="coding:delete_file",
        name="Delete File",
        description="Delete a file. Auto-commits to git if workspace is initialized.",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
                "auto_commit": {
                    "type": "boolean",
                    "description": "Automatically commit and push changes (default: true)",
                    "default": True,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="coding:run_command",
        name="Run Command",
        description="Execute a shell command and return output",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
        allowed_roles=["developer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="high",
    ),
    MCPTool(
        id="coding:move_file",
        name="Move File",
        description="Move or rename a file",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source path"},
                "destination": {"type": "string", "description": "Destination path"},
            },
            "required": ["source", "destination"],
        },
        approval_type=ApprovalType.NONE,
    ),
]


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================


async def read_file(path: str) -> dict[str, Any]:
    """Read the contents of a file."""
    try:
        workspace_root = get_workspace_root()
        resolved = resolve_path(path, workspace_root)

        if not resolved.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        if not resolved.is_file():
            return {"success": False, "error": f"Path is not a file: {path}"}

        # Check size limit (10MB)
        size = resolved.stat().st_size
        if size > 10 * 1024 * 1024:
            return {
                "success": False,
                "error": f"File too large ({size} bytes). Max is 10MB.",
            }

        try:
            content = resolved.read_text(encoding="utf-8")
            return {
                "success": True,
                "content": content,
                "path": str(resolved),
                "size": size,
                "encoding": "utf-8",
            }
        except UnicodeDecodeError:
            return {
                "success": True,
                "binary": True,
                "path": str(resolved),
                "size": size,
                "message": "File is binary. Cannot return content.",
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("read_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def write_file(
    path: str,
    content: str,
    auto_commit: bool = True,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """Write content to a file, optionally auto-committing to git."""
    try:
        # Get workspace root and resolve path
        workspace_root = get_workspace_root()
        resolved = resolve_path(path, workspace_root)

        # Ensure parent directory exists
        parent_dir = resolved.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # Write the file
        resolved.write_text(content, encoding="utf-8")

        logger.info("file_written", path=str(resolved), size=len(content))

        result = {
            "success": True,
            "path": str(resolved),
            "relative_path": str(resolved.relative_to(workspace_root)) if resolved.is_relative_to(workspace_root) else path,
            "size": len(content),
        }

        # Auto-commit if workspace is initialized
        ctx = get_current_context()
        if auto_commit and ctx and ctx.workspace_id:
            commit_result = await _auto_commit(
                workspace_root,
                commit_message or f"Update {path}",
            )
            result["committed"] = commit_result.get("success", False)
            if commit_result.get("success"):
                result["commit_message"] = commit_message or f"Update {path}"

        return result

    except Exception as e:
        logger.error("write_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def _auto_commit(workspace_path: Path, message: str) -> dict[str, Any]:
    """Auto-commit and push changes.

    This is a lightweight version that doesn't require WorkspaceService.
    """
    try:
        # Configure git user (for container environment)
        await asyncio.to_thread(
            subprocess.run,
            ["git", "config", "user.email", "druppie@localhost"],
            cwd=str(workspace_path),
            capture_output=True,
            timeout=10,
        )
        await asyncio.to_thread(
            subprocess.run,
            ["git", "config", "user.name", "Druppie Agent"],
            cwd=str(workspace_path),
            capture_output=True,
            timeout=10,
        )

        # Stage all changes
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "-A"],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning("git_add_failed", stderr=result.stderr)
            return {"success": False, "error": result.stderr}

        # Check if there are changes
        status_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "status", "--porcelain"],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if not status_result.stdout.strip():
            return {"success": True, "message": "No changes to commit"}

        # Commit
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", message],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning("git_commit_failed", stderr=result.stderr)
            return {"success": False, "error": result.stderr}

        # Push
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "push"],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.warning("git_push_failed", stderr=result.stderr)
            # Push failure is not critical - changes are committed locally
            return {"success": True, "pushed": False, "error": result.stderr}

        logger.info("auto_committed", workspace=str(workspace_path), message=message[:50])
        return {"success": True, "pushed": True}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git operation timed out"}
    except Exception as e:
        logger.error("auto_commit_error", error=str(e))
        return {"success": False, "error": str(e)}


async def list_dir(
    path: str = ".",
    patterns: list[str] | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    """List files in a directory."""
    try:
        workspace_root = get_workspace_root()
        resolved = resolve_path(path, workspace_root)

        if not resolved.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}

        if not resolved.is_dir():
            return {"success": False, "error": f"Path is not a directory: {path}"}

        files = []
        directories = []
        patterns = patterns or ["*"]

        for pattern in patterns:
            if recursive:
                search_pattern = str(resolved / "**" / pattern)
                matches = glob_module.glob(search_pattern, recursive=True)
            else:
                search_pattern = str(resolved / pattern)
                matches = glob_module.glob(search_pattern)

            for match in matches:
                match_path = Path(match)
                # Get path relative to workspace
                try:
                    rel_path = match_path.relative_to(workspace_root)
                except ValueError:
                    rel_path = match_path.name

                if match_path.is_file():
                    files.append({
                        "path": str(rel_path),
                        "name": match_path.name,
                        "size": match_path.stat().st_size,
                        "type": "file",
                    })
                elif match_path.is_dir() and match_path.name not in ["__pycache__", ".git", "node_modules"]:
                    directories.append({
                        "path": str(rel_path),
                        "name": match_path.name,
                        "type": "directory",
                    })

        return {
            "success": True,
            "path": str(resolved),
            "files": files,
            "directories": directories,
            "count": len(files) + len(directories),
        }

    except Exception as e:
        logger.error("list_dir_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def delete_file(path: str, auto_commit: bool = True) -> dict[str, Any]:
    """Delete a file, optionally auto-committing to git."""
    try:
        workspace_root = get_workspace_root()
        resolved = resolve_path(path, workspace_root)

        if not resolved.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        if resolved.is_dir():
            return {"success": False, "error": f"Path is a directory: {path}"}

        resolved.unlink()
        logger.info("file_deleted", path=str(resolved))

        result = {"success": True, "deleted": str(resolved)}

        # Auto-commit if workspace is initialized
        ctx = get_current_context()
        if auto_commit and ctx and ctx.workspace_id:
            commit_result = await _auto_commit(
                workspace_root,
                f"Delete {path}",
            )
            result["committed"] = commit_result.get("success", False)

        return result

    except Exception as e:
        logger.error("delete_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def run_command(
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute a shell command in the workspace directory."""
    try:
        # Use workspace path as default cwd
        if cwd is None:
            workspace_root = get_workspace_root()
            cwd = str(workspace_root)
        else:
            # Resolve cwd relative to workspace
            workspace_root = get_workspace_root()
            cwd = str(resolve_path(cwd, workspace_root))

        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        logger.info(
            "command_executed",
            command=command[:100],
            cwd=cwd,
            returncode=result.returncode,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "cwd": cwd,
        }

    except subprocess.TimeoutExpired:
        logger.warning("command_timeout", command=command[:100], timeout=timeout)
        return {"success": False, "error": f"Command timed out after {timeout}s"}

    except Exception as e:
        logger.error("command_error", command=command[:100], error=str(e))
        return {"success": False, "error": str(e)}


async def move_file(source: str, destination: str, auto_commit: bool = True) -> dict[str, Any]:
    """Move or rename a file, optionally auto-committing to git."""
    try:
        workspace_root = get_workspace_root()
        resolved_source = resolve_path(source, workspace_root)
        resolved_dest = resolve_path(destination, workspace_root)

        if not resolved_source.exists():
            return {"success": False, "error": f"Source does not exist: {source}"}

        # Ensure destination parent exists
        resolved_dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(resolved_source), str(resolved_dest))
        logger.info("file_moved", source=str(resolved_source), destination=str(resolved_dest))

        result = {
            "success": True,
            "source": str(resolved_source),
            "destination": str(resolved_dest),
        }

        # Auto-commit if workspace is initialized
        ctx = get_current_context()
        if auto_commit and ctx and ctx.workspace_id:
            commit_result = await _auto_commit(
                workspace_root,
                f"Move {source} to {destination}",
            )
            result["committed"] = commit_result.get("success", False)

        return result

    except Exception as e:
        logger.error("move_file_error", source=source, error=str(e))
        return {"success": False, "error": str(e)}


# =============================================================================
# REGISTRATION
# =============================================================================


def register(registry: MCPRegistry) -> None:
    """Register the coding MCP server."""
    server = MCPServer(
        id="coding",
        name="Coding",
        description="File operations and code execution",
        tools=CODING_TOOLS,
    )

    # Register handlers
    server.register_handler("read_file", read_file)
    server.register_handler("write_file", write_file)
    server.register_handler("list_dir", list_dir)
    server.register_handler("delete_file", delete_file)
    server.register_handler("run_command", run_command)
    server.register_handler("move_file", move_file)

    registry.register_server(server)
