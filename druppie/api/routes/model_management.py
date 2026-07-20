"""Model Management API routes (admin only).

Endpoints for viewing and managing runtime LLM model overrides
per agent and for the translation service.
"""

from collections.abc import Generator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from druppie.api.deps import require_admin
from druppie.db.database import SessionLocal
from druppie.domain.model_override import LocalModelLogs, LocalModelStatus, ModelManagementView, ModelOverrideSummary, ProviderStatus
from druppie.repositories.model_override_repository import ModelOverrideRepository
from druppie.services.model_management_service import ModelManagementService

logger = structlog.get_logger()

router = APIRouter()


class SetModelOverrideRequest(BaseModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


def get_model_management_service() -> Generator[ModelManagementService, None, None]:
    db = SessionLocal()
    try:
        repo = ModelOverrideRepository(db)
        yield ModelManagementService(repo)
    finally:
        db.close()


@router.get("/admin/models", response_model=ModelManagementView)
async def get_model_management(
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    return service.get_management_view()


@router.put("/admin/models/agents/{agent_id}", response_model=ModelOverrideSummary)
async def set_agent_model_override(
    agent_id: str,
    body: SetModelOverrideRequest,
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    admin_id = UUID(user["sub"]) if user.get("sub") else None

    validation = await service.validate_api_key(body.provider, body.model)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=validation["error"],
        )

    if body.fallback_provider:
        fb_validation = await service.validate_api_key(body.fallback_provider, body.fallback_model)
        if not fb_validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"Fallback: {fb_validation['error']}",
            )

    try:
        return service.set_agent_override(
            agent_id, body.provider, body.model, admin_id,
            fallback_provider=body.fallback_provider,
            fallback_model=body.fallback_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/admin/models/agents/{agent_id}", status_code=204)
async def remove_agent_model_override(
    agent_id: str,
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    if not service.remove_agent_override(agent_id):
        raise HTTPException(status_code=404, detail="No override found")


@router.put("/admin/models/translation", response_model=ModelOverrideSummary)
async def set_translation_model_override(
    body: SetModelOverrideRequest,
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    admin_id = UUID(user["sub"]) if user.get("sub") else None

    validation = await service.validate_api_key(body.provider, body.model)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=validation["error"],
        )

    if body.fallback_provider:
        fb_validation = await service.validate_api_key(body.fallback_provider, body.fallback_model)
        if not fb_validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"Fallback: {fb_validation['error']}",
            )

    try:
        return service.set_translation_override(
            body.provider, body.model, admin_id,
            fallback_provider=body.fallback_provider,
            fallback_model=body.fallback_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/admin/models/translation", status_code=204)
async def remove_translation_model_override(
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    if not service.remove_translation_override():
        raise HTTPException(status_code=404, detail="No override found")


@router.get("/admin/models/providers", response_model=list[ProviderStatus])
async def get_provider_statuses(
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    return service.get_provider_statuses()


@router.post("/admin/models/providers/{provider}/validate")
async def validate_provider(
    provider: str,
    model: str | None = Query(None),
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    return await service.validate_api_key(provider, model)


@router.get("/admin/models/local-status", response_model=LocalModelStatus)
async def get_local_model_status(
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    return await service.get_local_status()


@router.get("/admin/models/local-logs", response_model=LocalModelLogs)
async def get_local_model_logs(
    tail: int = Query(50, ge=1, le=500),
    service: ModelManagementService = Depends(get_model_management_service),
    user: dict = Depends(require_admin),
):
    return await service.get_local_logs(tail=tail)
