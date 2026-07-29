from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import (
    get_current_user,
    get_documentation_service,
)
from druppie.domain import DocumentationEntry, PlatformDocEntry
from druppie.services import DocumentationService
from druppie.services.platform_docs_service import PlatformDocsService

logger = structlog.get_logger()
router = APIRouter()


@router.get('/documentation')
async def get_documentation(
    service: DocumentationService = Depends(get_documentation_service),
    user: dict = Depends(get_current_user),
) -> list[DocumentationEntry]:
    return await service.get_all_documentation()


@router.get('/documentation/platform')
async def get_platform_documentation(
    user: dict = Depends(get_current_user),
) -> list[PlatformDocEntry]:
    """Return every formal doc in the platform's own ``docs/`` directory.

    Reads ADRs, PRDs, Specs (.feature Gherkin), Research notes and Guides,
    parses their frontmatter (or ``# @tag`` headers for specs), and returns
    a flat list sorted by type then id. The frontend renders a single
    filterable documentation portal from this list.
    """
    service = PlatformDocsService()
    return service.list()
