import structlog
from datetime import datetime, timezone

from ..core.background_tasks import create_tracked_task
from ..core.gitea import get_gitea_client
from ..domain import DocumentationEntry, ProjectSummary
from ..repositories import ProjectRepository, DocumentationCacheRepository

logger = structlog.get_logger()

DOC_PATH = 'docs/documentation.md'
DEFAULT_BRANCH = 'main'
CACHE_TTL_SECONDS = 60
STALE_CLEANUP_INTERVAL_SECONDS = 60  # Rate-limit stale cleanup to align with cache TTL

SOURCE_TYPE_GITEA = 'gitea'


class DocumentationService:
    _last_stale_cleanup: datetime | None = None

    def __init__(self, project_repo: ProjectRepository, cache_repo: DocumentationCacheRepository):
        self.project_repo = project_repo
        self.cache_repo = cache_repo

    async def get_all_documentation(self) -> list[DocumentationEntry]:
        entries: list[DocumentationEntry] = []

        projects, _ = self.project_repo.list_all(limit=1000)

        gitea_entries = await self._fetch_gitea_docs(projects)
        entries.extend(gitea_entries)

        # Run cleanup in the background — do not block the HTTP response
        create_tracked_task(
            self._cleanup_stale_gitea_cache(projects),
            name="doc-stale-cache-cleanup",
        )

        return entries

    async def _cleanup_stale_gitea_cache(self, projects: list[ProjectSummary]) -> None:
        now = datetime.now(timezone.utc)
        last = self.__class__._last_stale_cleanup
        if last is not None and (now - last).total_seconds() < STALE_CLEANUP_INTERVAL_SECONDS:
            logger.debug("stale_cleanup_skipped", reason="rate_limited")
            return

        self.__class__._last_stale_cleanup = now

        active_ids = {str(p.id) for p in projects if p.repo_url}

        cached = self.cache_repo.list_by_source_type(SOURCE_TYPE_GITEA)
        for entry in cached:
            if entry.source_id not in active_ids:
                self.cache_repo.delete_by_source(SOURCE_TYPE_GITEA, entry.source_id)
                logger.info('cleaned_stale_doc_cache', source_id=entry.source_id, title=entry.title)

    async def _fetch_gitea_docs(self, projects: list[ProjectSummary]) -> list[DocumentationEntry]:
        gitea = get_gitea_client()
        entries: list[DocumentationEntry] = []

        for project in projects:
            if not project.repo_url:
                continue
            if not project.repo_name:
                continue

            source_id = str(project.id)

            cached = self.cache_repo.get_fresh(
                SOURCE_TYPE_GITEA, source_id, DOC_PATH, max_age_seconds=CACHE_TTL_SECONDS
            )
            if cached is not None and cached.content:
                entries.append(DocumentationEntry(
                    source_type=SOURCE_TYPE_GITEA,
                    source_id=source_id,
                    title=project.name,
                    content=cached.content,
                ))
                continue

            try:
                result = await gitea.get_file(
                    repo=project.repo_name,
                    path=DOC_PATH,
                    branch=DEFAULT_BRANCH,
                    owner=project.repo_owner,
                )

                if not result.get('success') or not result.get('content'):
                    logger.warning('doc_not_found', project_id=source_id, repo=project.repo_name)
                    continue

                content = result['content']
                gitea_sha = result.get('sha', '')
                cache_sha = self.cache_repo.compute_sha(content)
                actual_sha = gitea_sha or cache_sha

                self.cache_repo.upsert(
                    source_type=SOURCE_TYPE_GITEA,
                    source_id=source_id,
                    path=DOC_PATH,
                    content=content,
                    sha=actual_sha,
                    title=project.name,
                )
                self.cache_repo.commit()

                entries.append(DocumentationEntry(
                    source_type=SOURCE_TYPE_GITEA,
                    source_id=source_id,
                    title=project.name,
                    content=content,
                ))

            except Exception as e:
                logger.warning('doc_fetch_failed', project_id=source_id, repo=project.repo_name, error=str(e))

        return entries
