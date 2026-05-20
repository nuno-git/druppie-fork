import structlog
from ..core.gitea import get_gitea_client
from ..repositories import ProjectRepository

logger = structlog.get_logger()

DOC_PATH = 'docs/documentation.md'
DEFAULT_BRANCH = 'main'

class DocumentationService:

    def __init__(self, project_repo: ProjectRepository):
        self.project_repo = project_repo

    async def get_all_documentation(self) -> list[dict]:
        gitea = get_gitea_client()
        projects = self.project_repo.list_all(limit=1000)[0]
        entries = []

        for project in projects:
            if not project.repo_url:
                continue
            project_model = self.project_repo.get_by_id(project.id)
            if not project_model or not project_model.repo_name:
                continue

            try:
                result = await gitea.get_file(
                    repo=project_model.repo_name,
                    path=DOC_PATH,
                    branch=DEFAULT_BRANCH,
                    owner=project_model.repo_owner,
                )
                if result.get('success') and result.get('content'):
                    entries.append({
                        'project_id': str(project.id),
                        'project_name': project.name,
                        'repo_name': project_model.repo_name,
                        'content': result['content'],
                    })
                else:
                    logger.warning('doc_not_found', project_id=str(project.id), repo=project_model.repo_name)
            except Exception as e:
                logger.warning('doc_fetch_failed', project_id=str(project.id), repo=project_model.repo_name, error=str(e))

        return entries
