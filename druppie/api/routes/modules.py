"""Module discovery and proxy endpoints for the Druppie SDK.

Apps use these endpoints to discover and call modules at runtime.
Data comes from mcp_config.yaml — no database needed.

The /modules/{id}/call endpoint proxies tool calls through the backend
so apps don't need to handle the MCP Streamable HTTP protocol directly.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from druppie.core.mcp_config import get_mcp_config

logger = logging.getLogger(__name__)

router = APIRouter()


class ModuleCallRequest(BaseModel):
    tool: str
    arguments: dict = {}


@router.get("/modules")
async def list_modules():
    """List modules available to apps (type 'module' or 'both', not 'core')."""
    config = get_mcp_config()
    modules = []
    for server_id in config.get_servers():
        server_type = config.get_server_type(server_id)
        if server_type in ("module", "both"):
            # get_server_url appends /mcp — strip it for the base URL
            url = config.get_server_url(server_id).removesuffix("/mcp")
            modules.append({"id": server_id, "url": url, "type": server_type})
    return modules


@router.get("/modules/{module_id}/endpoint")
async def get_module_endpoint(module_id: str):
    """Get the URL for a specific module. 404 if unknown or core-only."""
    config = get_mcp_config()

    # Check if module exists in config
    if module_id not in config.get_servers():
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    # Only expose modules with type 'module' or 'both'
    server_type = config.get_server_type(module_id)
    if server_type not in ("module", "both"):
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' is not available to apps")

    url = config.get_server_url(module_id).removesuffix("/mcp")
    return {"url": url, "type": server_type}


@router.post("/modules/{module_id}/call")
async def call_module_tool(module_id: str, req: ModuleCallRequest):
    """Proxy a tool call to a module via MCP.

    Apps call this instead of calling MCP servers directly. The backend
    handles the Streamable HTTP protocol and returns the result.
    """
    config = get_mcp_config()

    if module_id not in config.get_servers():
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    server_type = config.get_server_type(module_id)
    if server_type not in ("module", "both"):
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' is not available to apps")

    mcp_url = config.get_server_url(module_id)

    try:
        from druppie.execution.mcp_http import MCPHttp
        mcp = MCPHttp(config)
        result = await mcp.call(
            module_id, req.tool, req.arguments,
            timeout_seconds=120,
            max_retries=1,
        )
        return result
    except Exception as e:
        logger.error("module_call_failed: %s/%s — %s", module_id, req.tool, e)
        raise HTTPException(status_code=502, detail=f"Module call failed: {e}")
