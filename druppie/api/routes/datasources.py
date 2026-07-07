"""Data sources API — exposes connected data sources and Entra ID status."""

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
    """List data sources and the current user's Entra ID link status."""
    user_id = str(UUID(user["sub"]))

    entra_configured = is_entra_configured()
    entra_linked = await check_entra_linked(user_id) if entra_configured else False

    sources = []
    try:
        result = await _get_mcp_http().call("dataaccess", "list_sources", {})
        sources = result.get("sources", [])
    except Exception as e:
        logger.warning("datasources_list_failed", error=str(e))

    return {
        "entra_configured": entra_configured,
        "entra_linked": entra_linked,
        "sources": sources,
    }
