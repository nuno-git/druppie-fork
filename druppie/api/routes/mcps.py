"""MCPs API routes.

Endpoints for listing and managing MCP servers and tools.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_current_user
from druppie.mcps import get_mcp_registry

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class ToolResponse(BaseModel):
    """Tool response model."""

    id: str
    name: str
    description: str
    category: str
    approval_type: str
    danger_level: str


class ServerResponse(BaseModel):
    """MCP server response model."""

    id: str
    name: str
    description: str
    tools: list[ToolResponse]


class MCPListResponse(BaseModel):
    """List of MCP servers response."""

    servers: list[ServerResponse]
    total_tools: int


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/mcps", response_model=MCPListResponse)
async def list_mcps(
    user: dict = Depends(get_current_user),
):
    """List available MCP servers and tools.

    Returns tools accessible to the current user based on their roles.
    """
    registry = get_mcp_registry()
    user_roles = user.get("realm_access", {}).get("roles", [])

    servers = []
    total_tools = 0

    for server in registry.list_servers(user_roles):
        tools = []
        for tool in server.tools:
            # Check if user can access this tool
            if tool.allowed_roles and "admin" not in user_roles:
                if not any(r in tool.allowed_roles for r in user_roles):
                    continue

            tools.append(
                ToolResponse(
                    id=tool.id,
                    name=tool.name,
                    description=tool.description,
                    category=tool.category,
                    approval_type=tool.approval_type.value,
                    danger_level=tool.danger_level,
                )
            )

        if tools:
            servers.append(
                ServerResponse(
                    id=server.id,
                    name=server.name,
                    description=server.description,
                    tools=tools,
                )
            )
            total_tools += len(tools)

    return MCPListResponse(servers=servers, total_tools=total_tools)


@router.get("/mcps/{server_id}")
async def get_mcp_server(
    server_id: str,
    user: dict = Depends(get_current_user),
):
    """Get details of a specific MCP server."""
    registry = get_mcp_registry()
    server = registry.get_server(server_id)

    if not server:
        return {"error": "Server not found"}

    user_roles = user.get("realm_access", {}).get("roles", [])

    tools = []
    for tool in server.tools:
        if tool.allowed_roles and "admin" not in user_roles:
            if not any(r in tool.allowed_roles for r in user_roles):
                continue

        tools.append({
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "approval_type": tool.approval_type.value,
            "danger_level": tool.danger_level,
        })

    return {
        "id": server.id,
        "name": server.name,
        "description": server.description,
        "tools": tools,
    }


@router.get("/mcps/tools/{tool_id}")
async def get_tool(
    tool_id: str,
    user: dict = Depends(get_current_user),
):
    """Get details of a specific tool."""
    registry = get_mcp_registry()
    tool = registry.get_tool(tool_id)

    if not tool:
        return {"error": "Tool not found"}

    user_roles = user.get("realm_access", {}).get("roles", [])

    # Check permission
    permission = registry.check_permission(tool_id, user_roles, user.get("sub", ""))

    return {
        "id": tool.id,
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "input_schema": tool.input_schema,
        "approval_type": tool.approval_type.value,
        "approval_roles": tool.approval_roles,
        "danger_level": tool.danger_level,
        "permission": permission,
    }
