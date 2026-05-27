from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import (
    get_current_user,
    get_documentation_service,
)
from druppie.domain import DocumentationEntry
from druppie.services import DocumentationService

logger = structlog.get_logger()
router = APIRouter()


@router.get('/documentation')
async def get_documentation(
    service: DocumentationService = Depends(get_documentation_service),
    user: dict = Depends(get_current_user),
) -> list[DocumentationEntry]:
    return await service.get_all_documentation()
