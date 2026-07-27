"""PDF render repository — cached-render CRUD."""

from uuid import UUID

from druppie.db.models import PdfRender
from druppie.repositories.base import BaseRepository


class PdfRenderRepository(BaseRepository):
    """Repository for PdfRender cache table."""

    def get_by_cache_key(
        self,
        project_id: UUID,
        typ_path: str,
        file_sha: str,
    ) -> PdfRender | None:
        return (
            self.db.query(PdfRender)
            .filter(PdfRender.project_id == project_id)
            .filter(PdfRender.typ_path == typ_path)
            .filter(PdfRender.file_sha == file_sha)
            .first()
        )

    def create(
        self,
        project_id: UUID,
        typ_path: str,
        file_sha: str,
        pdf_storage_path: str,
        file_size: int,
    ) -> PdfRender:
        render = PdfRender(
            project_id=project_id,
            typ_path=typ_path,
            file_sha=file_sha,
            pdf_storage_path=pdf_storage_path,
            file_size=file_size,
        )
        self.db.add(render)
        self.db.flush()
        return render
