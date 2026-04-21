"""Module discovery and proxy endpoints for the Druppie SDK.

Apps use these endpoints to discover and call modules at runtime.
Data comes from mcp_config.yaml — no database needed.

The /modules/{id}/call endpoint proxies tool calls through the backend
so apps don't need to handle the MCP Streamable HTTP protocol directly.

Auth for /modules/{id}/call: when DRUPPIE_MODULE_API_TOKEN is set in the
backend environment, callers must pass the matching token in the
X-Druppie-Token header. In dev mode (token unset) the check is skipped
with a one-time warning. The token is auto-injected into deployed apps
via compose_up, so the SDK just forwards it transparently.
"""

import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from druppie.core.mcp_config import get_mcp_config

logger = logging.getLogger(__name__)

router = APIRouter()

_MODULE_API_TOKEN_ENV = "DRUPPIE_MODULE_API_TOKEN"
_dev_mode_warning_logged = False


def require_module_api_token(
    x_druppie_token: str | None = Header(default=None, alias="X-Druppie-Token"),
) -> None:
    """Validate the X-Druppie-Token header against DRUPPIE_MODULE_API_TOKEN.

    If the env var is unset, the check is skipped with a one-time warning
    (dev/local mode). If set, requests without a matching header are
    rejected with 401.
    """
    expected = os.environ.get(_MODULE_API_TOKEN_ENV)
    if not expected:
        global _dev_mode_warning_logged
        if not _dev_mode_warning_logged:
            logger.warning(
                "%s is not set — /modules/{id}/call is UNAUTHENTICATED. "
                "Set this env var in production.",
                _MODULE_API_TOKEN_ENV,
            )
            _dev_mode_warning_logged = True
        return

    if not x_druppie_token or not hmac.compare_digest(x_druppie_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Druppie-Token",
        )


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


@router.post(
    "/modules/{module_id}/call",
    dependencies=[Depends(require_module_api_token)],
)
async def call_module_tool(module_id: str, req: ModuleCallRequest):
    """Proxy a tool call to a module via MCP.

    Apps call this instead of calling MCP servers directly. The backend
    handles the Streamable HTTP protocol and returns the result.

    Requires the X-Druppie-Token header matching DRUPPIE_MODULE_API_TOKEN
    when that env var is set (see require_module_api_token).
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
        raise HTTPException(status_code=502, detail="Module call failed")
