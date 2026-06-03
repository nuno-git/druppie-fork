"""Documentation cache database model.

Caches fetched documentation content keyed by (source_type, source_id, path).
Supports multiple source types: gitea, agent, module, mcp, tool.
Uses SHA for future staleness checks, TTL-based freshness for now.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class DocumentationCache(Base):
    """Cached documentation content from any source type."""
    __tablename__ = "documentation_cache"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "path", name="uq_doc_cache"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_type = Column(String(50), nullable=False)  # gitea, core_file, agent_def, module, mcp, tool
    source_id = Column(String(255), nullable=False)   # project UUID, agent name, module name, etc.
    path = Column(String(512), nullable=False)         # file path within the source
    sha = Column(String(64), nullable=False)           # content hash for staleness check
    content = Column(Text, nullable=True)              # the document content (markdown)
    title = Column(String(255), nullable=True)         # display title (e.g. project name)
    fetched_at = Column(DateTime(timezone=True), default=utcnow)
