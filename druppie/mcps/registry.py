"""Unified MCP Registry with permission model.

Defines available MCP tools and their permission requirements.
"""

from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class ApprovalType(str, Enum):
    """Type of approval required for a tool."""

    NONE = "none"  # No approval needed
    SELF = "self"  # User can self-approve (just confirmation)
    ROLE = "role"  # Specific role must approve
    MULTI = "multi"  # Multiple approvals from different roles


class MCPTool(BaseModel):
    """Definition of an MCP tool with permissions."""

    id: str
    name: str
    description: str
    category: str  # coding, git, docker, hitl

    # Input schema for the tool
    input_schema: dict[str, Any] = Field(default_factory=dict)

    # Permission model
    allowed_roles: list[str] = Field(default_factory=list)  # Empty = all roles
    approval_type: ApprovalType = ApprovalType.NONE
    approval_roles: list[str] = Field(default_factory=list)  # Who can approve

    # Danger level (for UI warnings)
    danger_level: str = "low"  # low, medium, high, critical

    class Config:
        extra = "allow"


class MCPServer(BaseModel):
    """Definition of an MCP server providing tools."""

    id: str
    name: str
    description: str

    # Tools provided
    tools: list[MCPTool] = Field(default_factory=list)

    # Handler functions (not serialized)
    _handlers: dict[str, Callable] = {}

    class Config:
        extra = "allow"
        underscore_attrs_are_private = True

    def register_handler(self, tool_id: str, handler: Callable) -> None:
        """Register a handler function for a tool."""
        self._handlers[tool_id] = handler

    def get_handler(self, tool_id: str) -> Callable | None:
        """Get handler function for a tool."""
        return self._handlers.get(tool_id)


class MCPRegistry:
    """Registry for MCP servers and tools with permission checking."""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, MCPTool] = {}

    def register_server(self, server: MCPServer) -> None:
        """Register an MCP server and its tools."""
        self._servers[server.id] = server
        for tool in server.tools:
            self._tools[tool.id] = tool
        logger.info(
            "mcp_server_registered",
            server_id=server.id,
            tools_count=len(server.tools),
        )

    def get_server(self, server_id: str) -> MCPServer | None:
        """Get an MCP server by ID."""
        return self._servers.get(server_id)

    def get_tool(self, tool_id: str) -> MCPTool | None:
        """Get a tool by ID."""
        return self._tools.get(tool_id)

    def list_servers(self, user_roles: list[str] | None = None) -> list[MCPServer]:
        """List servers accessible to user."""
        servers = list(self._servers.values())
        return servers

    def list_tools(self, user_roles: list[str] | None = None) -> list[MCPTool]:
        """List tools accessible to user."""
        tools = list(self._tools.values())

        if user_roles is None:
            return tools

        # Admin sees everything
        if "admin" in user_roles:
            return tools

        # Filter by allowed_roles
        filtered = []
        for tool in tools:
            if not tool.allowed_roles or any(r in tool.allowed_roles for r in user_roles):
                filtered.append(tool)

        return filtered

    def check_permission(
        self,
        tool_id: str,
        user_roles: list[str],
        user_id: str,
    ) -> dict[str, Any]:
        """Check if user can execute a tool.

        Returns:
            {
                "allowed": bool,
                "requires_approval": bool,
                "approval_type": str,
                "approval_roles": list[str],
                "message": str,
            }
        """
        tool = self.get_tool(tool_id)
        if not tool:
            return {
                "allowed": False,
                "requires_approval": False,
                "message": f"Tool '{tool_id}' not found",
            }

        # Check role access
        if tool.allowed_roles and "admin" not in user_roles:
            if not any(r in tool.allowed_roles for r in user_roles):
                return {
                    "allowed": False,
                    "requires_approval": False,
                    "message": f"Requires one of roles: {', '.join(tool.allowed_roles)}",
                }

        # Check approval requirements
        if tool.approval_type == ApprovalType.NONE:
            return {
                "allowed": True,
                "requires_approval": False,
                "message": "No approval required",
            }

        if tool.approval_type == ApprovalType.SELF:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "self",
                "approval_roles": [],
                "message": "Requires your confirmation",
            }

        if tool.approval_type == ApprovalType.ROLE:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "role",
                "approval_roles": tool.approval_roles,
                "message": f"Requires approval from: {', '.join(tool.approval_roles)}",
            }

        if tool.approval_type == ApprovalType.MULTI:
            return {
                "allowed": True,
                "requires_approval": True,
                "approval_type": "multi",
                "approval_roles": tool.approval_roles,
                "message": f"Requires multiple approvals from: {', '.join(tool.approval_roles)}",
            }

        return {"allowed": True, "requires_approval": False}

    def get_tools_for_mcp(self, mcp_id: str) -> list[MCPTool]:
        """Get all tools for a specific MCP server."""
        server = self.get_server(mcp_id)
        if not server:
            return []
        return server.tools

    def get_tools_for_mcps(self, mcp_ids: list[str]) -> list[MCPTool]:
        """Get all tools for multiple MCP servers."""
        tools = []
        for mcp_id in mcp_ids:
            tools.extend(self.get_tools_for_mcp(mcp_id))
        return tools

    async def call_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Call a tool and return the result.

        Args:
            tool_id: Full tool ID (e.g., "coding:read_file")
            arguments: Tool arguments
            session_id: Optional session ID for HITL operations

        Returns:
            Tool result dict
        """
        # Parse server:tool format
        if ":" in tool_id:
            server_id, tool_name = tool_id.split(":", 1)
        else:
            # Try to find tool by ID
            tool = self.get_tool(tool_id)
            if not tool:
                return {"success": False, "error": f"Tool not found: {tool_id}"}
            server_id = tool.category
            tool_name = tool_id.split(".")[-1] if "." in tool_id else tool_id

        server = self.get_server(server_id)
        if not server:
            return {"success": False, "error": f"MCP server not found: {server_id}"}

        handler = server.get_handler(tool_name)
        if not handler:
            return {"success": False, "error": f"Handler not found: {tool_name}"}

        # Validate required arguments before calling
        full_tool_id = f"{server_id}:{tool_name}"
        tool_def = self.get_tool(full_tool_id)
        if tool_def and tool_def.input_schema:
            required = tool_def.input_schema.get("required", [])
            missing = [arg for arg in required if arg not in arguments]
            if missing:
                logger.warning(
                    "tool_call_missing_args",
                    tool=full_tool_id,
                    missing=missing,
                    provided=list(arguments.keys()),
                )
                return {
                    "success": False,
                    "error": f"Missing required arguments: {', '.join(missing)}",
                }

        try:
            # Add session_id for HITL operations
            if server_id == "hitl" and session_id:
                arguments["session_id"] = session_id

            result = await handler(**arguments)
            return result
        except TypeError as e:
            # Handle missing positional arguments more gracefully
            if "missing" in str(e) and "argument" in str(e):
                logger.warning("tool_call_arg_error", tool=tool_id, error=str(e), args=arguments)
                return {"success": False, "error": f"Invalid arguments for {tool_id}: {str(e)}"}
            raise
        except Exception as e:
            logger.error("tool_call_error", tool=tool_id, error=str(e))
            return {"success": False, "error": str(e)}

    def to_openai_tools(self, mcp_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Convert tools to OpenAI function calling format.

        Args:
            mcp_ids: Optional list of MCP IDs to include. If None, include all.

        Returns:
            List of tool definitions in OpenAI format
        """
        if mcp_ids:
            tools = self.get_tools_for_mcps(mcp_ids)
        else:
            tools = list(self._tools.values())

        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.id.replace(":", "_").replace(".", "_"),
                    "description": tool.description,
                    "parameters": tool.input_schema
                    or {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            })

        return openai_tools

    def to_dict(self) -> dict[str, Any]:
        """Export registry as dictionary."""
        return {
            "servers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tools": [
                        {
                            "id": t.id,
                            "name": t.name,
                            "description": t.description,
                            "category": t.category,
                            "approval_type": t.approval_type.value,
                            "danger_level": t.danger_level,
                        }
                        for t in s.tools
                    ],
                }
                for s in self._servers.values()
            ]
        }


# Global singleton
_mcp_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    """Get the global MCP registry instance."""
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = MCPRegistry()
        _register_default_servers(_mcp_registry)
    return _mcp_registry


def _register_default_servers(registry: MCPRegistry) -> None:
    """Register default MCP servers."""
    from . import coding, git, docker, hitl

    coding.register(registry)
    git.register(registry)
    docker.register(registry)
    hitl.register(registry)
