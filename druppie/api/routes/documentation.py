from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import get_current_user, get_project_repository
from druppie.repositories import ProjectRepository
from druppie.services.documentation_service import DocumentationService

logger = structlog.get_logger()
router = APIRouter()

@router.get('/documentation')
async def get_documentation(
    project_repo: ProjectRepository = Depends(get_project_repository),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    service = DocumentationService(project_repo)
    return await service.get_all_documentation()
