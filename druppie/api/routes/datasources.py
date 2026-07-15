"""Connected services API — exposes data sources, Azure DevOps, and Entra ID status."""

from uuid import UUID

from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import get_current_user
from druppie.core.entra_token import is_entra_configured, check_entra_linked
from druppie.core.mcp_config import get_mcp_config
from druppie.execution.mcp_http import MCPHttp

logger = structlog.get_logger()

router = APIRouter()

_mcp_http: MCPHttp | None = None


def _get_mcp_http() -> MCPHttp:
    global _mcp_http
    if _mcp_http is None:
        _mcp_http = MCPHttp(get_mcp_config())
    return _mcp_http


@router.get("/datasources")
async def list_datasources(user: dict = Depends(get_current_user)):
    """List connected services and the current user's Entra ID link status."""
    user_id = str(UUID(user["sub"]))

    entra_configured = is_entra_configured()
    entra_linked = await check_entra_linked(user_id) if entra_configured else False

    # Data sources from the dataaccess MCP server
    sources = []
    try:
        result = await _get_mcp_http().call("dataaccess", "list_sources", {})
        sources = result.get("sources", [])
    except Exception as e:
        logger.warning("datasources_list_failed", error=str(e))

    # Azure DevOps: check if the MCP server is configured
    mcp_config = get_mcp_config()
    devops_configured = "azuredevops" in mcp_config.get_servers()
    devops_accessible = devops_configured and entra_linked

    return {
        "entra_configured": entra_configured,
        "entra_linked": entra_linked,
        "sources": sources,
        "services": {
            "devops": {
                "configured": devops_configured,
                "accessible": devops_accessible,
                "name": "Azure DevOps",
                "auth_type": "obo",
            },
        },
    }
