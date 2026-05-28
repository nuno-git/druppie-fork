import hashlib
from datetime import datetime, timedelta, timezone

from .base import BaseRepository
from ..db.models import DocumentationCache
from ..db.models.base import utcnow


class DocumentationCacheRepository(BaseRepository):

    def get(self, source_type: str, source_id: str, path: str) -> DocumentationCache | None:
        return (
            self.db.query(DocumentationCache)
            .filter_by(source_type=source_type, source_id=source_id, path=path)
            .first()
        )

    def get_fresh(self, source_type: str, source_id: str, path: str, max_age_seconds: int = 60) -> DocumentationCache | None:
        entry = self.get(source_type, source_id, path)
        if entry is None:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        if entry.fetched_at and entry.fetched_at >= cutoff:
            return entry
        return None

    def upsert(
        self,
        source_type: str,
        source_id: str,
        path: str,
        content: str | None,
        sha: str,
        title: str | None = None,
    ) -> DocumentationCache:
        existing = self.get(source_type, source_id, path)
        if existing:
            existing.content = content
            existing.sha = sha
            existing.title = title
            existing.fetched_at = utcnow()
        else:
            existing = DocumentationCache(
                source_type=source_type,
                source_id=source_id,
                path=path,
                content=content,
                sha=sha,
                title=title,
            )
            self.db.add(existing)
        self.db.flush()
        return existing

    def list_by_source_type(self, source_type: str) -> list[DocumentationCache]:
        return (
            self.db.query(DocumentationCache)
            .filter_by(source_type=source_type)
            .order_by(DocumentationCache.title, DocumentationCache.path)
            .all()
        )

    def delete_by_source(self, source_type: str, source_id: str) -> None:
        self.db.query(DocumentationCache).filter_by(
            source_type=source_type, source_id=source_id
        ).delete()

    @staticmethod
    def compute_sha(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
