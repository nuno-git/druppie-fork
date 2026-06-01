# MODULE_SPEC — `module-rag`

> Status: design document. No implementation — this is the outline that
> Story B (the working module) will build on.
> Predecessor: [rag-patterns.md](./rag-patterns.md) (research foundation
> with per-layer choices, in Dutch).
> Convention: follows
> [`module-convention`](../../druppie/skills/module-convention/SKILL.md).

## 1. Identity

| Field | Value |
|---|---|
| Module ID | `rag` |
| Directory | `druppie/mcp-servers/module-rag/` |
| Container | `druppie-module-rag` |
| Compose service | `module-rag` |
| Type | Stateful (own Postgres DB with pgvector extension) |
| Latest version | `1.0.0` |
| Endpoint | `/v1/mcp`, `/mcp` (latest), `/health` |
| Port | `9012` (next free in the 9010-9099 range; in use: 9001 coding, 9002 docker, 9008 llm, 9010 data-access, 9011 vision) |
| DB container | `druppie-module-rag-db` |
| DB name | `module_rag` |

## 2. Purpose & scope

`module-rag` provides **document-retrieval-as-a-service** to any
Druppie application that builds doc-heavy use-cases (knowledge bases,
legal search, compliance search, customer-contact Q&A, policy
documents, product documentation). The module covers the **R** in RAG
— indexing, storage, retrieval — not the **G** (generation, which
remains `module-llm`).

**In scope (v1):**
- Indexing pre-extracted text chunks with metadata.
- Hybrid search (BM25 + dense vector) with RRF fusion.
- Metadata filtering (`doc_type`, `date`, `status`, `tenant`, free
  keys).
- Optional in-pipeline re-ranking (BGE-reranker-v2-m3 self-hosted).
- Citation metadata: content-hash chunk ID, page/paragraph,
  parent-section title.
- Logical tenant isolation via `tenant_id`.
- Index management (list, delete).
- Multilingual retrieval (NL, EN, and the broader set covered by the
  embedding model).

**Out of scope (v1, possibly v2):**
- **Document extraction** (PDF/Word/HTML → text). The caller is
  responsible; a separate extractor skill or module can fill this in
  later.
- **Embedding generation** itself — `module-rag` consumes embeddings
  via `module-llm` (see §6 Dependencies).
- **GraphRAG, agentic RAG, query rewriting**. These patterns live in
  the `rag-patterns` skill; the architect orchestrates them in the
  application layer above this module.
- **Generation / augmentation**: composing prompts with retrieved
  chunks happens in the application layer.
- **Physical per-tenant index isolation** as a layered feature — in
  v1 this is achieved by running multiple `module-rag` instances with
  separate databases when required.

## 3. Tool surface

| Tool | Purpose |
|---|---|
| `index_documents` | Chunk, embed, and store documents in an index. |
| `search` | Hybrid retrieval over an index, optionally with rerank. |
| `get_chunk` | Fetch one chunk + metadata (for citation resolution in UI). |
| `delete_documents` | Remove documents (and their chunks) from an index — needed for freshness updates. |
| `list_indices` | Discoverability — which indices exist for a tenant. |
| `delete_index` | Drop a full index. |

### 3.1 `index_documents`

Indexes one or more pre-extracted documents into an index.

```
Input:
  tenant_id:   str                                 # Required, isolation key
  index_name:  str                                 # Required, namespace within tenant (e.g. "policies-2024")
  documents:   list[
    {
      source_id:    str,                            # App-defined stable ID of the source document
      source_uri:   str,                            # Reference back to the source (URL, Gitea path, etc.)
      version:      str,                            # Version tag, e.g. SHA or timestamp
      text:         str,                            # Full pre-extracted text
      language:     str | None,                     # BCP-47 (e.g. "nl", "en"); None = auto-detect
      metadata:     dict[str, str | int | bool],    # Free metadata: doc_type, date, status, section info, ...
      pages:        list[ { page_no: int, text_offset: int } ] | None  # Optional: page mapping for citations
    }, ...
  ]
  chunking:    {
    strategy:      "recursive" | "parent_document",  # Default: "recursive"
    chunk_size:    int = 512,                        # Tokens
    chunk_overlap: int = 64,                         # Tokens
    parent_size:   int = 2048                        # Only for parent_document
  } | None
  embedding_model: str | None                       # Override; default from module config

Output:
  index_name:        str
  documents_indexed: int
  chunks_created:    int
  cost_cents:        float                          # Embedding cost
  processing_ms:     int
```

**Behavior:**
- Chunks each document according to `chunking.strategy` (default:
  recursive 512-token with tiktoken encoder).
- Generates content-hash chunk IDs
  (`source_id + version + hash(span_text)`) — stable across
  re-indexing.
- Requests embeddings via `module-llm` (see §6).
- Writes per chunk: dense vector, BM25 tsvector (with language
  analyzer based on `language`), metadata.
- Idempotent on `(source_id, version)`: indexing the same document
  twice overwrites the existing chunks.

### 3.2 `search`

Performs hybrid retrieval, optionally with rerank.

```
Input:
  tenant_id:           str
  index_name:          str
  query:               str
  query_language:      str | None                  # Default: auto-detect; selects BM25 analyzer
  top_k:               int = 8                     # Number of chunks returned
  search_mode:         "hybrid" | "vector_only" | "lexical_only" = "hybrid"
  rrf_k:               int = 60                    # RRF fusion parameter
  filters:             dict[str, str | int | bool] | None  # Match on metadata fields
  rerank:              bool = True                 # Rerank after retrieval
  rerank_candidates:   int = 50                    # N candidates before rerank (only when rerank=True)
  include_parent_text: bool = False                # For parent_document chunking: also return parent text

Output:
  results: list[
    {
      chunk_id:         str,
      source_id:        str,
      source_uri:       str,
      version:          str,
      score:            float,                      # Final score (after rerank if active)
      retrieval_scores: { vector: float, lexical: float, rrf: float, rerank: float | None },
      text:             str,                        # Chunk text (child chunk for hierarchical)
      parent_text:      str | None,                 # Only if include_parent_text=True
      metadata:         dict                        # Full — incl. page_no, section_title, etc.
    }, ...
  ]
  processing_ms: int
  rerank_used:   bool
```

### 3.3 `get_chunk`

```
Input:
  tenant_id: str
  chunk_id:  str

Output:
  chunk: { chunk_id, source_id, source_uri, version, text, parent_text, metadata }
```

Intended for citation resolution in a UI ("click the footnote → show
chunk + parent").

### 3.4 `delete_documents`

```
Input:
  tenant_id:  str
  index_name: str
  source_ids: list[str]                            # Remove all versions of these source IDs
  versions:   list[str] | None                     # Optional: only specific versions

Output:
  documents_deleted: int
  chunks_deleted:    int
```

### 3.5 `list_indices`

```
Input:
  tenant_id: str

Output:
  indices: list[
    {
      index_name:      str,
      documents_count: int,
      chunks_count:    int,
      created_at:      ISO8601,
      last_indexed_at: ISO8601,
      languages:       list[str]                   # Languages present in the index
    }, ...
  ]
```

### 3.6 `delete_index`

```
Input:
  tenant_id:  str
  index_name: str

Output:
  index_name:        str
  chunks_deleted:    int
  documents_deleted: int
```

## 4. Data model

Two primary tables plus the pgvector extension. Stable,
content-addressable IDs; no positional indices that break on
re-ingest.

```sql
-- 001_initial.sql (outline, not final)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    chunk_id        TEXT PRIMARY KEY,              -- content-hash, stable across reindex
    tenant_id       TEXT NOT NULL,
    index_name      TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_uri      TEXT NOT NULL,
    version         TEXT NOT NULL,
    parent_chunk_id TEXT,                          -- for hierarchical chunking
    chunk_text      TEXT NOT NULL,
    chunk_tokens    INT  NOT NULL,
    page_no         INT,
    section_title   TEXT,
    language        TEXT NOT NULL,                 -- BCP-47
    metadata        JSONB NOT NULL DEFAULT '{}',   -- Free fields (exception to no-JSONB rule: this is search payload, not a domain model)
    embedding       vector(1024) NOT NULL,         -- Default: multilingual-e5-large-instruct (1024 dims)
    text_search     tsvector,                      -- BM25 / lexical search column
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, index_name, source_id, version, chunk_id)
);

CREATE INDEX idx_documents_tenant_index
    ON documents (tenant_id, index_name);
CREATE INDEX idx_documents_source
    ON documents (tenant_id, index_name, source_id, version);
CREATE INDEX idx_documents_metadata
    ON documents USING GIN (metadata jsonb_path_ops);
CREATE INDEX idx_documents_text_search
    ON documents USING GIN (text_search);
CREATE INDEX idx_documents_embedding
    ON documents USING hnsw (embedding vector_cosine_ops);

CREATE TABLE index_registry (
    tenant_id        TEXT NOT NULL,
    index_name       TEXT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    last_indexed_at  TIMESTAMPTZ,
    embedding_model  TEXT NOT NULL,
    embedding_dims   INT  NOT NULL,
    chunking_config  JSONB NOT NULL,
    PRIMARY KEY (tenant_id, index_name)
);
```

> **JSONB exception**: the Druppie convention says "no JSONB" for
> domain models. Here JSONB is used deliberately for `metadata`
> because it is search payload with an unknown schema (different per
> use-case). This is a retrieval index, not a normalized domain model.
> To be confirmed in review.

## 5. Configuration

Environment variables (see the
[module-convention skill](../../druppie/skills/module-convention/SKILL.md)
for the Docker Compose service template pattern):

```
MCP_PORT=9012
MODULE_DB_URL=postgresql://module_rag:<pw>@module-rag-db:5432/module_rag

# Embedding (default — overridable per call via index_documents.embedding_model)
RAG_EMBEDDING_MODEL=multilingual-e5-large-instruct
RAG_EMBEDDING_DIMS=1024
RAG_EMBEDDING_MCP_URL=http://module-llm:9008/mcp   # module-llm endpoint that exposes the embedding tool

# Re-ranking (default — overridable per search call)
RAG_RERANKER_ENABLED=true
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANKER_DEVICE=cpu                              # cpu | cuda
```

## 6. Dependencies

| Dependency | Type | Reason |
|---|---|---|
| Postgres 16+ with the `pgvector` extension | Own DB container | Storage + ANN + lexical search in one engine |
| `module-llm` (port 9008) | Sibling MCP module | Embedding generation. Requires a new `embed` or `embeddings` tool in `module-llm` (see open question in research doc). |
| Reranker runtime | In-container (FastEmbed / sentence-transformers) | Run BGE-reranker-v2-m3 locally; no extra service. Switchable via `RAG_RERANKER_ENABLED=false`. |
| `module-convention` skill | Convention | Directory layout, MODULE.yaml, server routing, tools.py pattern. |

**Not** a dependency:
- Document extraction libraries (PyPDF, Tika, Unstructured): caller
  responsibility.
- LangChain / LlamaIndex as a framework: heavy dependency, not needed
  — chunking + RRF + pgvector queries are a few hundred lines of own
  code.

## 7. Non-functional requirements

Follow the NFR table in
[rag-patterns.md → Default-NFR-tabel](./rag-patterns.md#default-nfr-tabel).
Specific to `module-rag` as a subsystem:

| Requirement | Target |
|---|---|
| `search` p95 (no rerank) | < 200 ms @ 10⁵ chunks |
| `search` p95 (with rerank, 50 candidates) | < 500 ms @ 10⁵ chunks |
| `index_documents` throughput | ≥ 100 chunks/sec @ batched embeddings |
| `delete_documents` consistency | within a single Postgres transaction |
| Pipeline uptime | 99.5% (interactive), 99.9% (high-stakes) |
| Degraded mode on reranker failure | `search` keeps working without rerank; flag in response |

## 8. Versioning & migration

- v1 supports one embedding model per index (fixed on first
  `index_documents` call, stored in `index_registry`).
- Switching the embedding model = create a new index (re-embed all
  documents). No in-place migration in v1.
- v2 (potential): hot-swap of the embedding model with dual-write
  during migration. Out of scope for v1.

## 9. Open questions for implementation (Story B)

1. **Embedding tool in `module-llm`**: needs its own story/PR. Which
   embedding-tool interface (`embed_texts(list[str]) → list[vector]`?).
   Caching strategy inside `module-llm` or at the caller?
2. **Reranker loading**: bake BGE-reranker-v2-m3 into the container
   image (increases image size by ~600 MB) or pull on startup?
   Bake-in seems simpler for reproducibility.
3. **Index-level vs chunk-level language**: one index with multiple
   languages (per-chunk language field → analyzer per search side) or
   one index per language? Proposal: allow multiple languages per
   index, per-chunk language analyzer for BM25.
4. **JSONB metadata policy**: confirm in review that this is
   acceptable within the Druppie convention (see note under §4).
5. **Auth & RLS**: do we use Postgres row-level security for tenant
   isolation (extra defense-in-depth), or do we rely on
   application-level `tenant_id` filtering?

## 10. Validation scenarios

Story A's e2e test and Story B's HDSR-notas validation must at
minimum cover:
- Indexing a Dutch-language document with hierarchical chunking.
- Hybrid search with metadata filter and rerank.
- Citation resolution via `get_chunk` with parent-section title.
- Multilingual: one NL and one EN document in the same index, both
  findable in their own language.
- Re-index stability: `chunk_id`s remain identical across a second
  `index_documents` call of the same document.
