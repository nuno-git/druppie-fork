"""Vector Store v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
import time
from typing import Any

from fastmcp import FastMCP
from .module import VectorStoreModule

MODULE_ID = "vectorstore"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Vector Store v1",
    version=MODULE_VERSION,
    instructions="""Vector storage and retrieval for RAG (Retrieval-Augmented Generation).

Use when:
- Indexing documents for semantic search
- Searching a knowledge base to find relevant context
- Building document Q&A or citation-driven workflows
- Finding similar content across a document collection

Don't use when:
- You need exact keyword/grep matching (use module-filesearch)
- You only need to read a single known file (use coding read_file)
- You need web search (use module-web)
""",
)

module = VectorStoreModule(
    llm_url=os.getenv("MODULE_LLM_URL", "http://module-llm:9008"),
)


@mcp.tool(
    name="index_documents",
    description="Index documents for semantic search. Chunks text, generates embeddings, and stores in vector database. Each document needs 'content' and 'source_name' fields.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def index_documents(
    index_name: str,
    documents: list[dict[str, Any]],
    chunk_size: int = 2048,
    chunk_overlap: int = 256,
    embedding_model: str = "default",
    description: str = "",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.index_documents(
        index_name=index_name,
        documents=documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embedding_model=embedding_model,
        description=description,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }


@mcp.tool(
    name="search",
    description="Search indexed documents using semantic similarity. Returns ranked chunks with source citations (source_name, source_page, source_section) for traceability.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def search(
    index_name: str,
    query: str,
    top_k: int = 5,
    similarity_threshold: float = 0.0,
    filter_metadata: dict[str, Any] | None = None,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.search(
        index_name=index_name,
        query=query,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        filter_metadata=filter_metadata,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }


@mcp.tool(
    name="get_chunk",
    description="Retrieve a specific chunk by ID. Use after search to get the full context of a result including all source metadata for citation.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
    },
)
async def get_chunk(
    chunk_id: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    result = await module.get_chunk(
        chunk_id=chunk_id,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
        },
    }


@mcp.tool(
    name="delete_index",
    description="Delete an entire index and all its documents and chunks. This is irreversible.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
    },
)
async def delete_index(
    index_name: str,
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    result = await module.delete_index(
        index_name=index_name,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
        },
    }


@mcp.tool(
    name="list_indices",
    description="List all vector indices for the current project with document and chunk counts.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
    },
)
async def list_indices(
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    result = await module.list_indices(
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
        },
    }
