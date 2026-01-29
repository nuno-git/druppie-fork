"""MCP Bridge API routes.

Exposes MCP server tools via REST API for direct testing.
This allows the frontend to call MCP tools directly without going
through the agent workflow.

Endpoints:
- GET /api/mcp/servers - List available MCP servers
- GET /api/mcp/servers/{server}/tools - List tools for a server
- POST /api/mcp/call - Call an MCP tool directly
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_current_user
from druppie.core.mcp_config import MCPConfig
from druppie.execution.mcp_http import MCPHttp, MCPHttpError

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# MODELS
# =============================================================================


class MCPServer(BaseModel):
    """MCP server info."""
    name: str
    url: str
    description: str
    builtin: bool = False


class MCPTool(BaseModel):
    """MCP tool info."""
    name: str
    description: str
    requires_approval: bool = False
    required_role: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class MCPCallRequest(BaseModel):
    """Request to call an MCP tool."""
    server: str = Field(..., description="MCP server name (coding, docker)")
    tool: str = Field(..., description="Tool name")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    session_id: str | None = Field(None, description="Session ID (auto-injected if not provided)")


class MCPCallResponse(BaseModel):
    """Response from MCP tool call."""
    success: bool
    server: str
    tool: str
    result: dict[str, Any] | None = None
    error: str | None = None


class MCPServersResponse(BaseModel):
    """Response listing MCP servers."""
    servers: list[MCPServer]


class MCPToolsResponse(BaseModel):
    """Response listing MCP tools."""
    server: str
    tools: list[MCPTool]


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

_mcp_config: MCPConfig | None = None
_mcp_http: MCPHttp | None = None


def get_mcp_config() -> MCPConfig:
    """Get or create MCP config singleton."""
    global _mcp_config
    if _mcp_config is None:
        _mcp_config = MCPConfig()
    return _mcp_config


def get_mcp_http() -> MCPHttp:
    """Get or create MCP HTTP client singleton."""
    global _mcp_http
    if _mcp_http is None:
        _mcp_http = MCPHttp(get_mcp_config())
    return _mcp_http


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/servers", response_model=MCPServersResponse)
async def list_servers(
    user: dict = Depends(get_current_user),
) -> MCPServersResponse:
    """List all available MCP servers.

    Returns server names, URLs, and descriptions.
    """
    config = get_mcp_config()
    servers = []

    for name, server_config in config.config.get("mcps", {}).items():
        servers.append(MCPServer(
            name=name,
            url=server_config.get("url", ""),
            description=server_config.get("description", ""),
            builtin=server_config.get("builtin", False),
        ))

    logger.info("mcp_bridge_list_servers", count=len(servers))
    return MCPServersResponse(servers=servers)


@router.get("/servers/{server}/tools", response_model=MCPToolsResponse)
async def list_server_tools(
    server: str,
    user: dict = Depends(get_current_user),
) -> MCPToolsResponse:
    """List tools available from an MCP server.

    Returns tool names, descriptions, and approval requirements.
    """
    config = get_mcp_config()
    mcp_http = get_mcp_http()

    server_config = config.config.get("mcps", {}).get(server)
    if not server_config:
        raise HTTPException(status_code=404, detail=f"MCP server '{server}' not found")

    # Get tool config from mcp_config.yaml
    config_tools = {t["name"]: t for t in server_config.get("tools", [])}

    # Try to get live tools from server (if not builtin)
    live_tools = []
    if not server_config.get("builtin", False):
        try:
            live_tools = await mcp_http.list_tools(server)
        except Exception as e:
            logger.warning("mcp_bridge_list_tools_failed", server=server, error=str(e))

    # Merge config and live tools
    tools = []
    seen = set()

    # First add live tools (with config overlay)
    for live_tool in live_tools:
        name = live_tool["name"]
        seen.add(name)
        config_tool = config_tools.get(name, {})
        tools.append(MCPTool(
            name=name,
            description=live_tool.get("description") or config_tool.get("description", ""),
            requires_approval=config_tool.get("requires_approval", False),
            required_role=config_tool.get("required_role"),
            parameters=live_tool.get("parameters", config_tool.get("parameters", {})),
        ))

    # Then add config-only tools not seen in live list
    for name, config_tool in config_tools.items():
        if name not in seen:
            tools.append(MCPTool(
                name=name,
                description=config_tool.get("description", ""),
                requires_approval=config_tool.get("requires_approval", False),
                required_role=config_tool.get("required_role"),
                parameters=config_tool.get("parameters", {}),
            ))

    logger.info("mcp_bridge_list_tools", server=server, count=len(tools))
    return MCPToolsResponse(server=server, tools=tools)


@router.post("/call", response_model=MCPCallResponse)
async def call_tool(
    request: MCPCallRequest,
    user: dict = Depends(get_current_user),
) -> MCPCallResponse:
    """Call an MCP tool directly.

    This bypasses the agent workflow and approval system.
    Use for testing MCP connectivity.

    NOTE: For production use, tools should be called through the
    agent workflow which handles approvals properly.
    """
    config = get_mcp_config()
    mcp_http = get_mcp_http()

    # Validate server exists
    server_config = config.config.get("mcps", {}).get(request.server)
    if not server_config:
        raise HTTPException(status_code=404, detail=f"MCP server '{request.server}' not found")

    # Check if builtin (can't call via HTTP)
    if server_config.get("builtin", False):
        raise HTTPException(
            status_code=400,
            detail=f"Server '{request.server}' is builtin - cannot call via HTTP"
        )

    # Inject session_id if provided (for workspace auto-creation)
    args = dict(request.args)
    if request.session_id and "session_id" not in args:
        args["session_id"] = request.session_id

    logger.info(
        "mcp_bridge_call",
        server=request.server,
        tool=request.tool,
        args_keys=list(args.keys()),
        user_id=user.get("sub"),
    )

    try:
        result = await mcp_http.call(
            server=request.server,
            tool=request.tool,
            args=args,
            timeout_seconds=60.0,
        )

        logger.info(
            "mcp_bridge_call_success",
            server=request.server,
            tool=request.tool,
            result_keys=list(result.keys()) if isinstance(result, dict) else None,
        )

        return MCPCallResponse(
            success=True,
            server=request.server,
            tool=request.tool,
            result=result,
        )

    except MCPHttpError as e:
        logger.error(
            "mcp_bridge_call_error",
            server=request.server,
            tool=request.tool,
            error=str(e),
        )
        return MCPCallResponse(
            success=False,
            server=request.server,
            tool=request.tool,
            error=str(e),
        )

    except Exception as e:
        logger.error(
            "mcp_bridge_call_unexpected_error",
            server=request.server,
            tool=request.tool,
            error=str(e),
            exc_info=True,
        )
        return MCPCallResponse(
            success=False,
            server=request.server,
            tool=request.tool,
            error=f"Unexpected error: {e}",
        )
