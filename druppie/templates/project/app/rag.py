"""RAG helper — index and search documents using the app's own database.

Embeddings are generated via the Druppie platform (module-llm), vector
storage lives in this app's own Postgres with pgvector.  No shared
database, no cross-app data leakage.

Usage:
    from app.rag import RAG
    from app.database import SessionLocal
    from druppie_sdk import DruppieClient

    druppie = DruppieClient()
    db = SessionLocal()

    rag = RAG(db, druppie)
    rag.create_index("knowledge-base")
    rag.index_documents("knowledge-base", [
        {"content": "Full text...", "source_name": "Policy 2024", "source_page": 42},
    ])
    results = rag.search("knowledge-base", "wat is het beleid?")
"""

import json
import logging
import re
import uuid

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session

from app.database import Base

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# SQLAlchemy models (created in the app's own database)
# ---------------------------------------------------------------------------

class VectorIndex(Base):
    __tablename__ = "vector_indices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False, default="")
    embedding_model = Column(String, nullable=False, default="default")
    dimensions = Column(Integer, nullable=False, default=0)
    chunk_size = Column(Integer, nullable=False, default=2048)
    chunk_overlap = Column(Integer, nullable=False, default=256)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VectorDocument(Base):
    __tablename__ = "vector_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_id = Column(UUID(as_uuid=True), ForeignKey("vector_indices.id", ondelete="CASCADE"), nullable=False)
    source_name = Column(String, nullable=False)
    source_type = Column(String, nullable=False, default="text")
    chunk_count = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index("idx_vector_documents_index_id", VectorDocument.index_id)


class VectorChunk(Base):
    __tablename__ = "vector_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_id = Column(UUID(as_uuid=True), ForeignKey("vector_indices.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("vector_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector())
    source_name = Column(String, nullable=False, default="")
    source_page = Column(Integer)
    source_section = Column(String)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index("idx_vector_chunks_index_id", VectorChunk.index_id)
Index("idx_vector_chunks_document_id", VectorChunk.document_id)

_SAFE_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------------------
# RAG class
# ---------------------------------------------------------------------------

class RAG:
    """RAG helper that stores vectors in the app's own database."""

    def __init__(self, db: Session, druppie):
        self._db = db
        self._druppie = druppie

    def create_index(
        self,
        name: str,
        description: str = "",
        chunk_size: int = 2048,
        chunk_overlap: int = 256,
    ) -> dict:
        idx = self._db.query(VectorIndex).filter(VectorIndex.name == name).first()
        if idx:
            idx.description = description
            idx.chunk_size = chunk_size
            idx.chunk_overlap = chunk_overlap
        else:
            idx = VectorIndex(
                name=name,
                description=description,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            self._db.add(idx)
        self._db.commit()
        return {"index_id": str(idx.id), "name": name}

    def index_documents(
        self,
        index_name: str,
        documents: list[dict],
        embedding_model: str = "default",
    ) -> dict:
        idx = self._db.query(VectorIndex).filter(VectorIndex.name == index_name).first()
        if not idx:
            raise ValueError(f"Index '{index_name}' not found — call create_index first")

        chunk_size = idx.chunk_size - idx.chunk_overlap
        chunk_overlap = idx.chunk_overlap

        all_chunks = []
        all_texts = []

        for doc in documents:
            content = doc["content"]
            source_name = doc.get("source_name", "unknown")
            texts = _chunk_text(content, chunk_size, chunk_overlap)

            vdoc = VectorDocument(
                index_id=idx.id,
                source_name=source_name,
                source_type=doc.get("source_type", "text"),
                chunk_count=len(texts),
                metadata_=doc.get("metadata", {}),
            )
            self._db.add(vdoc)
            self._db.flush()

            for i, chunk_text in enumerate(texts):
                chunk = VectorChunk(
                    index_id=idx.id,
                    document_id=vdoc.id,
                    chunk_index=i,
                    content=chunk_text,
                    source_name=source_name,
                    source_page=doc.get("source_page"),
                    source_section=doc.get("source_section"),
                    metadata_=doc.get("metadata", {}),
                )
                self._db.add(chunk)
                all_chunks.append(chunk)
                all_texts.append(chunk_text)

        self._db.flush()

        if all_texts:
            embeddings = self._get_embeddings(all_texts, embedding_model)
            dimensions = len(embeddings[0]) if embeddings else 0

            if idx.dimensions == 0 and dimensions > 0:
                idx.dimensions = dimensions

            for chunk, emb in zip(all_chunks, embeddings):
                chunk.embedding = np.array(emb)

        self._db.commit()

        return {
            "index_name": index_name,
            "documents_indexed": len(documents),
            "chunks_created": len(all_chunks),
        }

    def search(
        self,
        index_name: str,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        filter_metadata: dict | None = None,
    ) -> list[dict]:
        idx = self._db.query(VectorIndex).filter(VectorIndex.name == index_name).first()
        if not idx:
            raise ValueError(f"Index '{index_name}' not found")

        if filter_metadata:
            for key in filter_metadata:
                if not _SAFE_KEY_RE.match(key):
                    raise ValueError(f"Invalid metadata filter key: '{key}'")

        query_embedding = self._get_embeddings([query], "default")[0]

        sql = """
            SELECT id, content, source_name, source_page, source_section,
                   metadata, chunk_index,
                   1 - (embedding <=> :qvec::vector) AS score
            FROM vector_chunks
            WHERE index_id = :idx AND embedding IS NOT NULL
        """
        params = {"idx": idx.id, "qvec": str(query_embedding)}

        if similarity_threshold > 0:
            sql += " AND 1 - (embedding <=> :qvec::vector) >= :threshold"
            params["threshold"] = similarity_threshold

        if filter_metadata:
            for i, (key, value) in enumerate(filter_metadata.items()):
                pname = f"fv{i}"
                sql += f" AND metadata->>'{key}' = :{pname}"
                params[pname] = str(value)

        sql += " ORDER BY embedding <=> :qvec::vector LIMIT :topk"
        params["topk"] = top_k

        rows = self._db.execute(text(sql), params).fetchall()

        return [
            {
                "chunk_id": str(row.id),
                "content": row.content,
                "score": float(row.score),
                "source_name": row.source_name,
                "source_page": row.source_page,
                "source_section": row.source_section,
                "metadata": row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
                "chunk_index": row.chunk_index,
            }
            for row in rows
        ]

    def delete_index(self, name: str) -> dict:
        idx = self._db.query(VectorIndex).filter(VectorIndex.name == name).first()
        if not idx:
            raise ValueError(f"Index '{name}' not found")
        self._db.delete(idx)
        self._db.commit()
        return {"deleted": True, "name": name}

    def list_indices(self) -> list[dict]:
        indices = self._db.query(VectorIndex).order_by(VectorIndex.created_at.desc()).all()
        return [
            {
                "name": idx.name,
                "description": idx.description,
                "dimensions": idx.dimensions,
                "chunk_size": idx.chunk_size,
                "chunk_overlap": idx.chunk_overlap,
            }
            for idx in indices
        ]

    def _get_embeddings(self, texts: list[str], model: str) -> list[list[float]]:
        all_embeddings = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + EMBEDDING_BATCH_SIZE]
            kwargs = {"texts": batch}
            if model and model != "default":
                kwargs["model"] = model
            result = self._druppie.call("llm", "embed", kwargs)
            all_embeddings.extend(result.get("embeddings", []))
        return all_embeddings


# ---------------------------------------------------------------------------
# Text chunking (recursive split at sentence boundaries with overlap)
# ---------------------------------------------------------------------------

def _chunk_text(text_content: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if len(text_content) <= chunk_size:
        return [text_content]

    separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]
    return _recursive_split(text_content, chunk_size, chunk_overlap, separators)


def _recursive_split(
    text_content: str,
    chunk_size: int,
    chunk_overlap: int,
    separators: list[str],
) -> list[str]:
    if len(text_content) <= chunk_size:
        return [text_content.strip()] if text_content.strip() else []

    separator = separators[0] if separators else ""
    remaining = separators[1:] if len(separators) > 1 else []

    if not separator:
        step = max(1, chunk_size - chunk_overlap)
        parts = [text_content[i:i + chunk_size] for i in range(0, len(text_content), step)]
        return [p.strip() for p in parts if p.strip()]

    parts = text_content.split(separator)
    chunks = []
    current = ""

    for part in parts:
        candidate = current + separator + part if current else part
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            if len(part) > chunk_size and remaining:
                chunks.extend(_recursive_split(part, chunk_size, chunk_overlap, remaining))
                current = ""
            else:
                current = part

    if current.strip():
        chunks.append(current.strip())

    if chunk_overlap > 0 and len(chunks) > 1:
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-chunk_overlap:] if len(chunks[i - 1]) > chunk_overlap else chunks[i - 1]
            result.append(prev_tail + " " + chunks[i])
        chunks = result

    return chunks
