"""MCP connection type for communicating with MCP servers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class MCPConnection:
    """Connection to an MCP server (in-process or out-of-process).

    Represents either:
    - A remote MCP server (endpoint is a URL, e.g., "http://localhost:9001")
    - An in-process MCP server (endpoint is None)

    The call_tool callable handles the actual tool execution, which varies
    by connection type (HTTP call vs in-process dispatch).
    """

    server_name: str
    endpoint: str | None  # URL for out-of-process servers, None for in-process
    tools: list[dict[str, Any]] = field(default_factory=list)  # OpenAI function-calling format
    _call_tool_fn: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] = field(default=None, repr=False)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool on this MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Result dict with at least a "success" key:
            - Success: {"success": True, "data": ...}
            - Error: {"success": False, "error": "description"}
            - Pending: {"success": True, "_pending": True, "resume_id": "..."}
        """
        if self._call_tool_fn is None:
            return {"success": False, "error": f"No call_tool function configured for {self.server_name}"}

        try:
            return await self._call_tool_fn(tool_name, arguments)
        except Exception as e:
            return {"success": False, "error": str(e)}
