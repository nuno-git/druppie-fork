"""Model Management API routes (admin only).

Endpoints for viewing and managing runtime LLM model overrides
per agent and for the translation service.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from druppie.api.deps import require_admin
from druppie.domain.model_override import ModelManagementView, ModelOverrideSummary, ProviderStatus
from druppie.services.model_management_service import ModelManagementService

logger = structlog.get_logger()

router = APIRouter()


class SetModelOverrideRequest(BaseModel):
    provider: str
    model: str


def get_model_management_service() -> ModelManagementService:
    from druppie.db.database import SessionLocal
    from druppie.repositories.model_override_repository import ModelOverrideRepository

    db = SessionLocal()
    repo = ModelOverrideRepository(db)
    return ModelManagementService(repo)


@router.get("/admin/models", response_model=ModelManagementView)
async def get_model_management(user: dict = Depends(require_admin)):
    service = get_model_management_service()
    return service.get_management_view()


@router.put("/admin/models/agents/{agent_id}", response_model=ModelOverrideSummary)
async def set_agent_model_override(
    agent_id: str,
    body: SetModelOverrideRequest,
    user: dict = Depends(require_admin),
):
    service = get_model_management_service()
    admin_id = UUID(user["sub"]) if user.get("sub") else None
    try:
        return service.set_agent_override(agent_id, body.provider, body.model, admin_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/admin/models/agents/{agent_id}", status_code=204)
async def remove_agent_model_override(
    agent_id: str,
    user: dict = Depends(require_admin),
):
    service = get_model_management_service()
    service.remove_agent_override(agent_id)


@router.put("/admin/models/translation", response_model=ModelOverrideSummary)
async def set_translation_model_override(
    body: SetModelOverrideRequest,
    user: dict = Depends(require_admin),
):
    service = get_model_management_service()
    admin_id = UUID(user["sub"]) if user.get("sub") else None
    try:
        return service.set_translation_override(body.provider, body.model, admin_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/admin/models/translation", status_code=204)
async def remove_translation_model_override(
    user: dict = Depends(require_admin),
):
    service = get_model_management_service()
    service.remove_translation_override()


@router.get("/admin/models/providers", response_model=list[ProviderStatus])
async def get_provider_statuses(user: dict = Depends(require_admin)):
    service = get_model_management_service()
    return service.get_provider_statuses()


@router.post("/admin/models/providers/{provider}/validate")
async def validate_provider(
    provider: str,
    model: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    service = get_model_management_service()
    return await service.validate_api_key(provider, model)
