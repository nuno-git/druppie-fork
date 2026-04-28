"""Azure AI Foundry status routes."""

import structlog
from fastapi import APIRouter, Depends

from druppie.api.deps import get_current_user, require_any_role
from druppie.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter()


@router.get("/foundry/status")
async def get_foundry_status(
    user: dict = Depends(get_current_user),
    _role=Depends(require_any_role(["developer", "admin", "architect"])),
):
    """Check if Azure AI Foundry is configured and reachable.

    Uses DefaultAzureCredential (az login, managed identity, env vars).
    """
    from druppie.services.foundry_service import FoundryService

    settings = get_settings()
    foundry = FoundryService(endpoint=settings.llm.foundry_project_endpoint)
    return foundry.check_connection()


@router.get("/foundry/models")
async def list_foundry_models(
    user: dict = Depends(get_current_user),
    _role=Depends(require_any_role(["developer", "admin", "architect"])),
):
    """List available model deployments from Azure AI Foundry."""
    from druppie.services.foundry_service import FoundryService

    settings = get_settings()
    foundry = FoundryService(endpoint=settings.llm.foundry_project_endpoint)
    return {"models": foundry.list_models()}
