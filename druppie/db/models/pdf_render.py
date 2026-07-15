"""PDF render cache model.

Tracks rendered PDFs keyed by (project_id, typ_path, file_sha) so that
repeated requests for the same source at the same Git revision serve
instantly from cache. On environment reset the table is rebuilt; the
source of truth is always Gitea, and the PDF is a reproducible build
artifact (typ_path + file_sha → identical PDF).
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class PdfRender(Base):
    """A cached PDF render for a Typst source file."""

    __tablename__ = "pdf_renders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    typ_path = Column(String(500), nullable=False)
    file_sha = Column(String(64), nullable=False)
    pdf_storage_path = Column(String(1000), nullable=False)
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "typ_path",
            "file_sha",
            name="uq_pdf_render_cache_key",
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "typ_path": self.typ_path,
            "file_sha": self.file_sha,
            "pdf_storage_path": self.pdf_storage_path,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
