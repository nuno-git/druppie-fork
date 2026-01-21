"""Coding MCP Server.

Provides file operations and code generation capabilities.
"""

import os
import glob as glob_module
import shutil
import subprocess
from typing import Any

import structlog

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool

logger = structlog.get_logger()


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
        description="Write content to a file (creates parent directories if needed)",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
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
        description="Delete a file",
        category="coding",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
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
        if not os.path.exists(path):
            return {"success": False, "error": f"File does not exist: {path}"}

        if not os.path.isfile(path):
            return {"success": False, "error": f"Path is not a file: {path}"}

        # Check size limit (10MB)
        size = os.path.getsize(path)
        if size > 10 * 1024 * 1024:
            return {
                "success": False,
                "error": f"File too large ({size} bytes). Max is 10MB.",
            }

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "success": True,
                "content": content,
                "size": size,
                "encoding": "utf-8",
            }
        except UnicodeDecodeError:
            return {
                "success": True,
                "binary": True,
                "size": size,
                "message": "File is binary. Cannot return content.",
            }

    except Exception as e:
        logger.error("read_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def write_file(path: str, content: str) -> dict[str, Any]:
    """Write content to a file."""
    try:
        # Ensure parent directory exists
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("file_written", path=path, size=len(content))
        return {"success": True, "path": path, "size": len(content)}

    except Exception as e:
        logger.error("write_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def list_dir(
    path: str,
    patterns: list[str] | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    """List files in a directory."""
    try:
        if not os.path.exists(path):
            return {"success": False, "error": f"Path does not exist: {path}"}

        if not os.path.isdir(path):
            return {"success": False, "error": f"Path is not a directory: {path}"}

        files = []
        patterns = patterns or ["*"]

        for pattern in patterns:
            if recursive:
                search_pattern = os.path.join(path, "**", pattern)
                matches = glob_module.glob(search_pattern, recursive=True)
            else:
                search_pattern = os.path.join(path, pattern)
                matches = glob_module.glob(search_pattern)

            for match in matches:
                if os.path.isfile(match):
                    files.append({
                        "path": match,
                        "name": os.path.basename(match),
                        "size": os.path.getsize(match),
                    })

        return {"success": True, "files": files, "count": len(files)}

    except Exception as e:
        logger.error("list_dir_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def delete_file(path: str) -> dict[str, Any]:
    """Delete a file."""
    try:
        if not os.path.exists(path):
            return {"success": False, "error": f"File does not exist: {path}"}

        if os.path.isdir(path):
            return {"success": False, "error": f"Path is a directory: {path}"}

        os.remove(path)
        logger.info("file_deleted", path=path)
        return {"success": True, "deleted": path}

    except Exception as e:
        logger.error("delete_file_error", path=path, error=str(e))
        return {"success": False, "error": str(e)}


async def run_command(
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute a shell command."""
    try:
        result = subprocess.run(
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
            returncode=result.returncode,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        logger.warning("command_timeout", command=command[:100], timeout=timeout)
        return {"success": False, "error": f"Command timed out after {timeout}s"}

    except Exception as e:
        logger.error("command_error", command=command[:100], error=str(e))
        return {"success": False, "error": str(e)}


async def move_file(source: str, destination: str) -> dict[str, Any]:
    """Move or rename a file."""
    try:
        if not os.path.exists(source):
            return {"success": False, "error": f"Source does not exist: {source}"}

        # Ensure destination parent exists
        dest_parent = os.path.dirname(destination)
        if dest_parent:
            os.makedirs(dest_parent, exist_ok=True)

        shutil.move(source, destination)
        logger.info("file_moved", source=source, destination=destination)
        return {"success": True, "source": source, "destination": destination}

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
