"""MCPs API routes.

Endpoints for listing and managing MCP servers and tools.
Now reads from mcp_config.yaml via MCPClient.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user, get_db
from druppie.core.mcp_client import get_mcp_client
from sqlalchemy.orm import Session

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# HEALTH CHECK HELPER
# =============================================================================


async def check_server_health(url: str, timeout: float = 2.0) -> str:
    """Check if an MCP server is healthy.

    Args:
        url: The MCP server URL (will check /health endpoint)
        timeout: Timeout in seconds for the health check

    Returns:
        Status string: "healthy", "unhealthy", or "unknown"
    """
    # Remove /mcp suffix if present to get base URL
    base_url = url.rstrip("/mcp").rstrip("/")
    health_url = f"{base_url}/health"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(health_url)
            if response.status_code == 200:
                return "healthy"
            else:
                return "unhealthy"
    except httpx.TimeoutException:
        logger.warning("health_check_timeout", url=health_url)
        return "unknown"
    except Exception as e:
        logger.warning("health_check_failed", url=health_url, error=str(e))
        return "unhealthy"


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class ToolResponse(BaseModel):
    """Tool response model."""

    id: str
    name: str
    description: str
    category: str
    requires_approval: bool
    danger_level: str
    required_roles: list[str] = []


class ServerResponse(BaseModel):
    """MCP server response model."""

    id: str
    name: str
    description: str
    url: str
    tools: list[ToolResponse]


class MCPListResponse(BaseModel):
    """List of MCP servers response."""

    servers: list[ServerResponse]
    total_tools: int


class ServerStatusResponse(BaseModel):
    """MCP server with status response model."""

    id: str
    name: str
    description: str
    url: str
    status: str  # healthy, unhealthy, unknown


class ServersListResponse(BaseModel):
    """List of MCP servers with status response."""

    servers: list[ServerStatusResponse]


class FlatToolResponse(BaseModel):
    """Flat tool response model (includes server info)."""

    server: str
    name: str
    description: str
    requires_approval: bool


class ToolsListResponse(BaseModel):
    """List of tools response."""

    tools: list[FlatToolResponse]


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/mcps", response_model=MCPListResponse)
async def list_mcps(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List available MCP servers and tools.

    Returns tools accessible to the current user based on their roles.
    """
    mcp_client = get_mcp_client(db)
    config = mcp_client.config
    user_roles = user.get("realm_access", {}).get("roles", [])

    servers = []
    total_tools = 0

    for server_id, server_config in config.get("mcps", {}).items():
        tools = []
        for tool in server_config.get("tools", []):
            # Check if user can access this tool based on required_roles
            required_roles = tool.get("required_roles", [])
            if required_roles and "admin" not in user_roles:
                if not any(r in required_roles for r in user_roles):
                    continue

            tools.append(
                ToolResponse(
                    id=f"{server_id}:{tool['name']}",
                    name=tool["name"],
                    description=tool.get("description", ""),
                    category=server_id,
                    requires_approval=tool.get("requires_approval", False),
                    danger_level=tool.get("danger_level", "low"),
                    required_roles=required_roles,
                )
            )

        if tools:
            servers.append(
                ServerResponse(
                    id=server_id,
                    name=server_id.title(),
                    description=server_config.get("description", ""),
                    url=mcp_client.get_mcp_url(server_id),
                    tools=tools,
                )
            )
            total_tools += len(tools)

    return MCPListResponse(servers=servers, total_tools=total_tools)


@router.get("/mcps/servers", response_model=ServersListResponse)
async def list_mcp_servers(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List MCP servers with their status.

    Returns all configured MCP servers with health status checks.
    """
    mcp_client = get_mcp_client(db)
    config = mcp_client.config

    servers = []
    for server_id, server_config in config.get("mcps", {}).items():
        url = mcp_client.get_mcp_url(server_id)
        status = await check_server_health(url)

        servers.append(
            ServerStatusResponse(
                id=server_id,
                name=f"{server_id.title()} MCP",
                description=server_config.get("description", ""),
                url=url,
                status=status,
            )
        )

    return ServersListResponse(servers=servers)


@router.get("/mcps/tools", response_model=ToolsListResponse)
async def list_mcp_tools(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all tools across all MCP servers.

    Returns a flat list of all tools with their server info.
    """
    mcp_client = get_mcp_client(db)
    config = mcp_client.config

    tools = []
    for server_id, server_config in config.get("mcps", {}).items():
        for tool in server_config.get("tools", []):
            tools.append(
                FlatToolResponse(
                    server=server_id,
                    name=tool["name"],
                    description=tool.get("description", ""),
                    requires_approval=tool.get("requires_approval", False),
                )
            )

    return ToolsListResponse(tools=tools)


@router.get("/mcps/tools/{tool_id}")
async def get_tool(
    tool_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get details of a specific tool."""
    mcp_client = get_mcp_client(db)

    # Parse tool_id (format: server:tool_name)
    if ":" not in tool_id:
        raise HTTPException(status_code=400, detail="Invalid tool ID format. Use server:tool_name")

    server_id, tool_name = tool_id.split(":", 1)
    tool_config = mcp_client.get_tool_config(server_id, tool_name)

    if not tool_config:
        raise HTTPException(status_code=404, detail="Tool not found")

    user_roles = user.get("realm_access", {}).get("roles", [])
    required_roles = tool_config.get("required_roles", [])

    # Check if user can approve
    can_approve = (
        "admin" in user_roles or
        any(r in required_roles for r in user_roles) if required_roles else True
    )

    return {
        "id": tool_id,
        "name": tool_name,
        "description": tool_config.get("description", ""),
        "category": server_id,
        "requires_approval": tool_config.get("requires_approval", False),
        "required_roles": required_roles,
        "danger_level": tool_config.get("danger_level", "low"),
        "permission": {
            "allowed": True,  # All tools are visible, but may require approval
            "can_approve": can_approve,
            "requires_approval": tool_config.get("requires_approval", False),
        },
    }


@router.get("/mcps/{server_id}")
async def get_mcp_server(
    server_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get details of a specific MCP server."""
    mcp_client = get_mcp_client(db)
    config = mcp_client.config

    server_config = config.get("mcps", {}).get(server_id)
    if not server_config:
        raise HTTPException(status_code=404, detail="Server not found")

    user_roles = user.get("realm_access", {}).get("roles", [])

    tools = []
    for tool in server_config.get("tools", []):
        required_roles = tool.get("required_roles", [])
        if required_roles and "admin" not in user_roles:
            if not any(r in required_roles for r in user_roles):
                continue

        tools.append({
            "id": f"{server_id}:{tool['name']}",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "requires_approval": tool.get("requires_approval", False),
            "danger_level": tool.get("danger_level", "low"),
            "required_roles": required_roles,
        })

    return {
        "id": server_id,
        "name": server_id.title(),
        "description": server_config.get("description", ""),
        "url": mcp_client.get_mcp_url(server_id),
        "tools": tools,
    }
