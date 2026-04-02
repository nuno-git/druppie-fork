"""Cache API routes.

Proxies to the sandbox manager to list cached dependency packages.

Endpoints:
- GET /cache/packages - List all cached packages grouped by package manager
"""

import os

from fastapi import APIRouter, Depends
import httpx
import structlog

from druppie.api.deps import get_current_user
from druppie.core.sandbox_auth import generate_control_plane_token

logger = structlog.get_logger()

router = APIRouter()

SANDBOX_MANAGER_URL = os.getenv("SANDBOX_MANAGER_URL", "http://sandbox-manager:8000")


@router.get("/cache/packages")
async def get_cached_packages(user: dict = Depends(get_current_user)):
    """List all cached dependency packages from the shared sandbox cache."""
    token = generate_control_plane_token()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{SANDBOX_MANAGER_URL}/api/cache/packages",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
    except httpx.ConnectError:
        logger.warning("sandbox_manager_unreachable", url=SANDBOX_MANAGER_URL)
        return {"managers": {}, "total_count": 0, "error": "Sandbox manager unreachable"}
    except Exception as e:
        logger.error("cache_packages_fetch_failed", error=str(e))
        return {"managers": {}, "total_count": 0, "error": str(e)}
