"""Vector Store Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imported by v1/tools.py for MCP exposure.
"""

import json
import logging
import os
import re
import uuid
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from db import get_pool

logger = logging.getLogger("vectorstore-mcp.v1")

MODULE_LLM_URL = os.getenv("MODULE_LLM_URL", "http://module-llm:9008")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

_SAFE_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class VectorStoreModule:
    """v1 business logic for vector storage and retrieval."""

    def __init__(self, llm_url: str = MODULE_LLM_URL):
        self._llm_url = llm_url

    async def index_documents(
        self,
        index_name: str,
        documents: list[dict[str, Any]],
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: str = "default",
        description: str = "",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Index documents by chunking, embedding, and storing in pgvector."""
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})"
            )

        pool = await get_pool()

        async with pool.acquire() as conn:
            index_row = await conn.fetchrow(
                """
                INSERT INTO indices (project_id, name, description, embedding_model,
                                     chunk_size, chunk_overlap)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (project_id, name) DO UPDATE
                    SET description = EXCLUDED.description,
                        embedding_model = EXCLUDED.embedding_model,
                        chunk_size = EXCLUDED.chunk_size,
                        chunk_overlap = EXCLUDED.chunk_overlap,
                        updated_at = now()
                RETURNING id, dimensions
                """,
                project_id, index_name, description,
                embedding_model, chunk_size, chunk_overlap,
            )
            index_id = index_row["id"]
            current_dimensions = index_row["dimensions"]

        total_chunks = 0
        all_chunk_ids: list[uuid.UUID] = []
        all_texts: list[str] = []

        effective_chunk_size = chunk_size - chunk_overlap

        for doc in documents:
            content = doc["content"]
            source_name = doc.get("source_name", "unknown")
            source_type = doc.get("source_type", "text")
            doc_metadata = doc.get("metadata", {})

            chunks = self._chunk_text(content, effective_chunk_size, chunk_overlap)

            async with pool.acquire() as conn:
                doc_row = await conn.fetchrow(
                    """
                    INSERT INTO documents (index_id, source_name, source_type,
                                           chunk_count, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    RETURNING id
                    """,
                    index_id, source_name, source_type,
                    len(chunks), _to_json(doc_metadata),
                )
                document_id = doc_row["id"]

                for i, chunk_text in enumerate(chunks):
                    chunk_row = await conn.fetchrow(
                        """
                        INSERT INTO chunks (index_id, document_id, chunk_index,
                                            content, source_name, source_page,
                                            source_section, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                        RETURNING id
                        """,
                        index_id, document_id, i, chunk_text,
                        source_name, doc.get("source_page"),
                        doc.get("source_section"), _to_json(doc_metadata),
                    )
                    all_chunk_ids.append(chunk_row["id"])
                    all_texts.append(chunk_text)

            total_chunks += len(chunks)

        if all_texts:
            embeddings = await self._get_embeddings(all_texts, embedding_model)
            dimensions = len(embeddings[0]) if embeddings else 0

            async with pool.acquire() as conn:
                if current_dimensions == 0 and dimensions > 0:
                    await conn.execute(
                        "UPDATE indices SET dimensions = $1 WHERE id = $2",
                        dimensions, index_id,
                    )

                for chunk_id, embedding in zip(all_chunk_ids, embeddings):
                    await conn.execute(
                        "UPDATE chunks SET embedding = $1 WHERE id = $2",
                        str(embedding), chunk_id,
                    )

                await self._ensure_vector_index(conn, index_id, dimensions)

        return {
            "index_id": str(index_id),
            "index_name": index_name,
            "documents_indexed": len(documents),
            "chunks_created": total_chunks,
        }

    async def search(
        self,
        index_name: str,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        filter_metadata: dict[str, Any] | None = None,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Search for relevant chunks using vector similarity."""
        if filter_metadata:
            for key in filter_metadata:
                if not _SAFE_KEY_RE.match(key):
                    raise ValueError(
                        f"Invalid metadata filter key: '{key}'. "
                        "Keys must be alphanumeric/underscore identifiers."
                    )

        pool = await get_pool()

        async with pool.acquire() as conn:
            index_row = await conn.fetchrow(
                "SELECT id, embedding_model FROM indices WHERE project_id = $1 AND name = $2",
                project_id, index_name,
            )
            if not index_row:
                raise ValueError(f"Index '{index_name}' not found for this project")

            index_id = index_row["id"]
            embedding_model = index_row["embedding_model"]

        query_embeddings = await self._get_embeddings([query], embedding_model)
        if not query_embeddings:
            raise RuntimeError("Failed to generate query embedding")
        query_embedding = query_embeddings[0]

        async with pool.acquire() as conn:
            query_sql = """
                SELECT c.id, c.content, c.source_name, c.source_page,
                       c.source_section, c.metadata, c.chunk_index,
                       1 - (c.embedding <=> $1::vector) AS score
                FROM chunks c
                WHERE c.index_id = $2
                  AND c.embedding IS NOT NULL
            """
            params: list[Any] = [str(query_embedding), index_id]
            param_idx = 3

            if similarity_threshold > 0:
                query_sql += f" AND 1 - (c.embedding <=> $1::vector) >= ${param_idx}"
                params.append(similarity_threshold)
                param_idx += 1

            if filter_metadata:
                for key, value in filter_metadata.items():
                    query_sql += f" AND c.metadata->>'{key}' = ${param_idx}"
                    params.append(str(value))
                    param_idx += 1

            query_sql += " ORDER BY c.embedding <=> $1::vector LIMIT $" + str(param_idx)
            params.append(top_k)

            rows = await conn.fetch(query_sql, *params)

        results = [
            {
                "chunk_id": str(row["id"]),
                "content": row["content"],
                "score": float(row["score"]),
                "source_name": row["source_name"],
                "source_page": row["source_page"],
                "source_section": row["source_section"],
                "metadata": _from_json(row["metadata"]),
                "chunk_index": row["chunk_index"],
            }
            for row in rows
        ]

        return {
            "results": results,
            "index_name": index_name,
            "query": query,
            "result_count": len(results),
        }

    async def get_chunk(
        self,
        chunk_id: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve a specific chunk by ID."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.id, c.content, c.chunk_index, c.source_name,
                       c.source_page, c.source_section, c.metadata, c.created_at,
                       d.source_type, i.name AS index_name
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                JOIN indices i ON c.index_id = i.id
                WHERE c.id = $1 AND i.project_id = $2
                """,
                uuid.UUID(chunk_id), project_id,
            )

        if not row:
            raise ValueError(f"Chunk '{chunk_id}' not found")

        return {
            "chunk_id": str(row["id"]),
            "content": row["content"],
            "chunk_index": row["chunk_index"],
            "source_name": row["source_name"],
            "source_page": row["source_page"],
            "source_section": row["source_section"],
            "source_type": row["source_type"],
            "metadata": _from_json(row["metadata"]),
            "index_name": row["index_name"],
            "created_at": row["created_at"].isoformat(),
        }

    async def delete_index(
        self,
        index_name: str,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Delete an entire index and all its documents and chunks."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id FROM indices WHERE project_id = $1 AND name = $2",
                    project_id, index_name,
                )
                if not row:
                    raise ValueError(f"Index '{index_name}' not found for this project")

                index_id = row["id"]

                chunk_count = await conn.fetchval(
                    "SELECT count(*) FROM chunks WHERE index_id = $1",
                    index_id,
                )

                await conn.execute(
                    "DELETE FROM indices WHERE id = $1",
                    index_id,
                )

        return {
            "deleted": True,
            "index_name": index_name,
            "chunks_removed": chunk_count,
        }

    async def list_indices(
        self,
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """List all indices for a project."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT i.id, i.name, i.description, i.embedding_model,
                       i.dimensions, i.chunk_size, i.chunk_overlap,
                       i.created_at, i.updated_at,
                       (SELECT count(*) FROM documents d WHERE d.index_id = i.id) AS document_count,
                       (SELECT count(*) FROM chunks c WHERE c.index_id = i.id) AS chunk_count
                FROM indices i
                WHERE i.project_id = $1
                ORDER BY i.created_at DESC
                """,
                project_id,
            )

        return {
            "indices": [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"],
                    "embedding_model": row["embedding_model"],
                    "dimensions": row["dimensions"],
                    "chunk_size": row["chunk_size"],
                    "chunk_overlap": row["chunk_overlap"],
                    "document_count": row["document_count"],
                    "chunk_count": row["chunk_count"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in rows
            ],
            "count": len(rows),
        }

    def _chunk_text(
        self, text: str, chunk_size: int, chunk_overlap: int,
    ) -> list[str]:
        """Split text into overlapping chunks at sentence boundaries."""
        if len(text) <= chunk_size:
            return [text]

        separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]
        return self._recursive_split(text, chunk_size, chunk_overlap, separators)

    def _recursive_split(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str],
    ) -> list[str]:
        """Recursively split text using progressively finer separators."""
        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        separator = separators[0] if separators else ""
        remaining_separators = separators[1:] if len(separators) > 1 else []

        if separator:
            parts = text.split(separator)
        else:
            step = max(1, chunk_size - chunk_overlap)
            parts = [text[i:i + chunk_size] for i in range(0, len(text), step)]
            return [p.strip() for p in parts if p.strip()]

        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = current + separator + part if current else part
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current.strip():
                    chunks.append(current.strip())
                if len(part) > chunk_size and remaining_separators:
                    sub_chunks = self._recursive_split(
                        part, chunk_size, chunk_overlap, remaining_separators,
                    )
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = part

        if current.strip():
            chunks.append(current.strip())

        if chunk_overlap > 0 and len(chunks) > 1:
            chunks = self._add_overlap(chunks, chunk_overlap)

        return chunks

    def _add_overlap(self, chunks: list[str], overlap: int) -> list[str]:
        """Add overlap between consecutive chunks by prepending context from the previous chunk."""
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
            overlapped = prev_tail + " " + chunks[i]
            result.append(overlapped)
        return result

    async def _get_embeddings(
        self, texts: list[str], model: str,
    ) -> list[list[float]]:
        """Get embeddings from module-llm via MCP tool call."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + EMBEDDING_BATCH_SIZE]
            embeddings = await self._call_llm_embed(batch, model)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def _call_llm_embed(
        self, texts: list[str], model: str,
    ) -> list[list[float]]:
        """Call module-llm embed tool via FastMCP client."""
        arguments: dict[str, Any] = {"texts": texts}
        if model and model != "default":
            arguments["model"] = model

        transport = StreamableHttpTransport(url=f"{self._llm_url}/mcp")
        async with Client(transport) as client:
            result = await client.call_tool("embed", arguments)

        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if hasattr(first_item, "text"):
                data = json.loads(first_item.text)
                return data.get("embeddings", [])

        raise RuntimeError("Unexpected response format from module-llm embed")

    async def _ensure_vector_index(
        self, conn, index_id: uuid.UUID, dimensions: int,
    ):
        """Create HNSW index for vector similarity search if not exists."""
        if dimensions <= 0:
            return

        safe_id = str(index_id).replace("-", "_")
        if not re.match(r"^[a-f0-9_]+$", safe_id):
            raise ValueError(f"Invalid index_id format: {index_id}")
        if not isinstance(dimensions, int) or dimensions <= 0 or dimensions > 10000:
            raise ValueError(f"Invalid dimensions: {dimensions}")

        index_name = f"idx_chunks_embedding_{safe_id}"

        exists = await conn.fetchval(
            "SELECT 1 FROM pg_indexes WHERE indexname = $1",
            index_name,
        )
        if not exists:
            await conn.execute(f"""
                CREATE INDEX {index_name}
                ON chunks USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
                WHERE index_id = '{index_id}'
            """)
            logger.info("Created HNSW index %s (dim=%d)", index_name, dimensions)


def _to_json(data: dict | None) -> str:
    return json.dumps(data or {})


def _from_json(data) -> dict:
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        return json.loads(data)
    return {}
