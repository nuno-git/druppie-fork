"""ToolProvider — router that aggregates tools from MCP servers.

The ToolProvider is the abstraction layer between the runtime and MCP servers.
It routes tool calls to the correct MCP server, handles approval gates,
and supports pre-validation hooks.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from druppie.agent_runtime.tools.mcp import MCPConnection


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol defining the tool routing interface."""

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return ALL tools from connected MCP servers (no filtering)."""
        ...

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool with pre-validation and approval gates.

        Returns:
            Success: {"success": True, "data": ...}
            Error: {"success": False, "error": "description"}
            Pending: {"success": True, "_pending": True, "resume_id": "..."}
        """
        ...

    async def close(self) -> None:
        """Clean up MCP connections."""
        ...


class MCPToolProvider:
    """Concrete ToolProvider implementation.

    Holds a dict of {server_name: MCPConnection} and routes tool calls
    to the correct MCP server based on tool name.

    Supports:
    - Tool routing: maps tool_name -> server_name -> MCPConnection
    - Approval gates: checks approval_overrides, returns _pending if needed
    - Pre-validation hooks: calls validation tool before execution
    """

    def __init__(
        self,
        connections: dict[str, MCPConnection] | None = None,
        approval_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._connections: dict[str, MCPConnection] = connections or {}
        self._tool_to_server: dict[str, str] = {}
        self._approval_overrides = approval_overrides or {}
        self._build_tool_mapping()

    def add_connection(self, server_name: str, connection: MCPConnection) -> None:
        """Add or replace an MCP connection."""
        self._connections[server_name] = connection
        self._build_tool_mapping()

    def remove_connection(self, server_name: str) -> None:
        """Remove an MCP connection."""
        self._connections.pop(server_name, None)
        self._build_tool_mapping()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Aggregate all tools from all MCP connections."""
        all_tools: list[dict[str, Any]] = []
        for connection in self._connections.values():
            all_tools.extend(connection.tools)
        return all_tools

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool, routing to the correct MCP server.

        Pipeline:
        1. Check pre-validation hook (if configured)
        2. Check approval gate (if configured)
        3. Route to the correct MCP server
        """
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        connection = self._connections.get(server_name)
        if not connection:
            return {"success": False, "error": f"No connection for server: {server_name}"}

        override_key = f"{server_name}:{tool_name}"
        override = self._approval_overrides.get(override_key, {})

        pre_validate = override.get("pre_validate")
        if pre_validate:
            val_result = await connection.call_tool(pre_validate, arguments)
            if not val_result.get("success", False):
                return val_result

        requires_approval = override.get("requires_approval", False)
        if requires_approval:
            required_role = override.get("required_role")
            return {
                "success": True,
                "_pending": True,
                "resume_id": f"approval_{tool_name}",
                "message": f"Requires approval from {required_role or 'owner'}",
                "required_role": required_role,
                "tool_name": tool_name,
                "arguments": arguments,
            }

        return await connection.call_tool(tool_name, arguments)

    async def close(self) -> None:
        """Clean up all MCP connections."""
        self._connections.clear()
        self._tool_to_server.clear()

    def _build_tool_mapping(self) -> None:
        """Build {tool_name: server_name} mapping from all connections."""
        self._tool_to_server.clear()
        for server_name, connection in self._connections.items():
            for tool in connection.tools:
                tool_name = tool.get("name")
                if tool_name:
                    self._tool_to_server[tool_name] = server_name

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Get the server name that handles a tool."""
        return self._tool_to_server.get(tool_name)
