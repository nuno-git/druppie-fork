"""Azure AI Foundry status routes."""

import structlog
from fastapi import APIRouter, Depends

from druppie.api.deps import get_current_user
from druppie.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter()


@router.get("/foundry/status")
async def get_foundry_status(
    user: dict = Depends(get_current_user),
):
    """Check if Azure AI Foundry is configured and reachable.

    Uses DefaultAzureCredential (az login, managed identity, env vars)
    or an explicit API key set via FOUNDRY_API_KEY.
    """
    from druppie.services.foundry_service import FoundryService

    settings = get_settings()
    foundry = FoundryService(
        endpoint=settings.llm.foundry_project_endpoint,
        api_key=settings.llm.foundry_api_key or None,
    )
    return foundry.check_connection()
