"""Module discovery endpoints for the Druppie SDK.

Apps use these endpoints to discover module URLs at runtime.
Data comes from mcp_config.yaml — no database needed.
"""

from fastapi import APIRouter, HTTPException

from druppie.core.mcp_config import get_mcp_config

router = APIRouter()


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
    server_type = config.get_server_type(module_id)

    # Check if module exists in config
    if module_id not in config.get_servers():
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found")

    # Only expose modules with type 'module' or 'both'
    if server_type not in ("module", "both"):
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' is not available to apps")

    url = config.get_server_url(module_id).removesuffix("/mcp")
    return {"url": url, "type": server_type}
