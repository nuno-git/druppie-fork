from fastapi import APIRouter, Depends
import structlog

from druppie.api.deps import get_current_user, get_project_repository
from druppie.db.database import get_db
from druppie.repositories import DocumentationCacheRepository
from druppie.services.documentation_service import DocumentationService
from sqlalchemy.orm import Session

logger = structlog.get_logger()
router = APIRouter()

def get_doc_cache_repo(db: Session = Depends(get_db)) -> DocumentationCacheRepository:
    return DocumentationCacheRepository(db)


@router.get('/documentation')
async def get_documentation(
    project_repo=Depends(get_project_repository),
    cache_repo: DocumentationCacheRepository = Depends(get_doc_cache_repo),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    service = DocumentationService(project_repo, cache_repo)
    return await service.get_all_documentation()
