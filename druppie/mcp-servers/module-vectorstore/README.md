# module-vectorstore

MCP module for vector storage and semantic search (RAG). Provides document indexing with automatic chunking, embedding generation, and similarity search with source citations.

## Standalone usage

This module is designed to run independently of the Druppie platform. Any project that needs RAG capabilities can use it — the only external dependency is a running `module-llm` instance for embedding generation.

### Requirements

| Dependency | Purpose |
|---|---|
| **PostgreSQL 16 + pgvector** | Vector storage and similarity search |
| **module-llm** | Embedding generation via the `embed` MCP tool |

### Quick start with Docker Compose

```yaml
services:
  vectorstore-db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: module_vectorstore
      POSTGRES_USER: module_vectorstore
      POSTGRES_PASSWORD: changeme
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U module_vectorstore"]
      interval: 10s
      timeout: 5s
      retries: 5

  vectorstore:
    build:
      context: ./druppie/mcp-servers
      dockerfile: module-vectorstore/Dockerfile
    environment:
      MCP_PORT: "9012"
      MODULE_DB_URL: postgresql://module_vectorstore:changeme@vectorstore-db:5432/module_vectorstore
      MODULE_LLM_URL: http://module-llm:9008
    ports:
      - "9012:9012"
    depends_on:
      vectorstore-db:
        condition: service_healthy
```

### Database auto-initialisation

The module is fully self-initialising. On first request it will:

1. Connect to PostgreSQL and create the `vector` extension (`CREATE EXTENSION IF NOT EXISTS vector`)
2. Run all schema migrations from `v1/schema/` (creates `indices`, `documents`, `chunks` tables)
3. Create a connection pool with pgvector type registration

No manual database setup, migration scripts, or init containers are needed. The only requirement is a running PostgreSQL instance with the pgvector extension available (provided by the `pgvector/pgvector:pg16` image).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `MODULE_DB_URL` | `postgresql://module_vectorstore:module_vectorstore_dev@module-vectorstore-db:5432/module_vectorstore` | PostgreSQL connection string |
| `MODULE_LLM_URL` | `http://module-llm:9008` | URL of the module-llm MCP server (for embeddings) |
| `MCP_PORT` | `9012` | Port the MCP server listens on |
| `EMBEDDING_BATCH_SIZE` | `100` | Number of texts to embed per batch |

## MCP Tools

### index_documents

Index documents for semantic search. Chunks text, generates embeddings via module-llm, and stores everything in pgvector.

```json
{
  "index_name": "my-knowledge-base",
  "documents": [
    {
      "content": "Full text of the document...",
      "source_name": "Policy Document 2024",
      "source_page": 42,
      "source_section": "§3.2 Budget",
      "metadata": {"doctype": "policy", "status": "approved"}
    }
  ],
  "chunk_size": 2048,
  "chunk_overlap": 256
}
```

Returns: `index_name`, `documents_indexed`, `chunks_created`.

### search

Semantic similarity search over indexed documents. Returns ranked chunks with source citations.

```json
{
  "index_name": "my-knowledge-base",
  "query": "What is the budget for 2024?",
  "top_k": 5,
  "filter_metadata": {"status": "approved"}
}
```

Returns: ranked `results[]` with `content`, `score`, `source_name`, `source_page`, `source_section`, `metadata`.

### get_chunk

Retrieve a specific chunk by ID (for citation drill-down).

### list_indices

List all indices for the current project with document and chunk counts.

### delete_index

Delete an index and all its documents and chunks (irreversible).

## Architecture

```
module-vectorstore
├── server.py              # MCP server entrypoint
├── db.py                  # Connection pool + auto-initialisation
├── MODULE.yaml            # Module registry metadata
├── v1/
│   ├── tools.py           # MCP tool definitions (contract)
│   ├── module.py          # Business logic (chunking, embedding, search)
│   └── schema/
│       ├── 001_initial.sql    # pgvector extension + tables
│       └── current.sql        # Current schema reference
├── Dockerfile
├── requirements.txt
└── README.md
```

### Data flow

```
Document → chunk_text() → _get_embeddings() → pgvector INSERT
                              ↓
                         module-llm:embed
                              ↓
Query → _get_embeddings() → cosine similarity → ranked chunks with citations
```

### Schema

- **indices**: project-scoped index metadata (name, embedding model, chunk config)
- **documents**: source documents with metadata
- **chunks**: text chunks with embeddings, linked to documents. Carries `source_name`, `source_page`, `source_section` for citation traceability.

HNSW indexes are created automatically per index after the first batch of embeddings is stored.
