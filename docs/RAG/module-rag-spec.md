# MODULE_SPEC — `module-rag`

> Status: design-document. Geen implementatie — dit is de outline waar Story B (de werkende module) op gaat bouwen.
> Voorganger: [rag-patterns.md](./rag-patterns.md) (research-fundament met de keuzes per laag).
> Conventie: volgt [`module-convention`](../../druppie/skills/module-convention/SKILL.md).

## 1. Identiteit

| Veld | Waarde |
|---|---|
| Module-ID | `rag` |
| Directory | `druppie/mcp-servers/module-rag/` |
| Container | `druppie-module-rag` |
| Compose-service | `module-rag` |
| Type | Stateful (eigen Postgres-DB met pgvector-extensie) |
| Latest version | `1.0.0` |
| Endpoint | `/v1/mcp`, `/mcp` (latest), `/health` |
| Poort | `9012` (eerstvolgende vrije in 9010-9099 range; in gebruik: 9001 coding, 9002 docker, 9008 llm, 9010 data-access, 9011 vision) |
| DB-container | `druppie-module-rag-db` |
| DB-naam | `module_rag` |

## 2. Doel & scope

`module-rag` levert **document-retrieval-as-a-service** aan elke Druppie-applicatie die doc-heavy use-cases bouwt (kennisbanken, juridische zoek, compliance-search, klantcontact-Q&A, beleidsdocumenten, productdocumentatie). De module dekt de **R** in RAG — indexering, opslag, retrieval — niet de **G** (generation, dat blijft `module-llm`).

**In scope (v1):**
- Indexeren van pre-extraheerde tekst-chunks met metadata.
- Hybrid search (BM25 + dense vector) met RRF-fusie.
- Metadata-filter (doc_type, datum, status, tenant, vrije keys).
- Optionele in-pipeline re-ranking (BGE-reranker-v2-m3 self-hosted).
- Citatie-metadata: content-hash chunk-ID, page/paragraph, parent-section-titel.
- Logische tenant-isolatie via `tenant_id`.
- Index-management (list, delete).
- Multi-talige retrieval (NL, EN, en bredere set die het embedding-model dekt).

**Out of scope (v1, eventueel v2):**
- **Document-extractie** (PDF/Word/HTML → tekst). Caller is verantwoordelijk; aparte extractor-skill of -module kan dit later invullen.
- **Embedding-generation** zelf — `module-rag` consumeert embeddings via `module-llm` (zie §6 Dependencies).
- **GraphRAG, agentic RAG, query-rewriting**. Patronen liggen vast in de `rag-patterns` skill; de architect orkestreert ze in de applicatielaag bovenop deze module.
- **Generation/Augmentation**: het composen van prompts met retrieved chunks gebeurt in de applicatielaag.
- **Fysieke per-tenant index-separatie** als gelaagde feature — wordt in v1 gerealiseerd door meerdere `module-rag`-instances met aparte DB's te draaien indien nodig.

## 3. Tool-surface

| Tool | Doel |
|---|---|
| `index_documents` | Documenten chunken, embedden, opslaan in een index. |
| `search` | Hybrid retrieval over een index, optioneel met re-rank. |
| `get_chunk` | Eén chunk + metadata ophalen (voor citatie-resolutie in UI). |
| `delete_documents` | Verwijder documenten (en bijbehorende chunks) uit een index — nodig voor freshness-updates. |
| `list_indices` | Discoverability — welke indices bestaan voor een tenant. |
| `delete_index` | Volledige index droppen. |

### 3.1 `index_documents`

Indexeert één of meerdere pre-extraheerde documenten in een index.

```
Input:
  tenant_id:   str                                 # Verplicht, isolatie-key
  index_name:  str                                 # Verplicht, namespace binnen tenant (bv. "policies-2024")
  documents:   list[
    {
      source_id:    str,                            # App-bepaald stabiel ID van het brondocument
      source_uri:   str,                            # Verwijzing terug naar de bron (URL, Gitea-path, etc.)
      version:      str,                            # Versie-tag, bv. SHA of timestamp
      text:         str,                            # Volledige pre-extraheerde tekst
      language:     str | None,                     # BCP-47 (bv. "nl", "en"); None = auto-detect
      metadata:     dict[str, str | int | bool],    # Vrije metadata: doc_type, datum, status, sectie-info, ...
      pages:        list[ { page_no: int, text_offset: int } ] | None  # Optioneel: pagina-mapping voor citaties
    }, ...
  ]
  chunking:    {
    strategy:     "recursive" | "parent_document",  # Default: "recursive"
    chunk_size:   int = 512,                        # Tokens
    chunk_overlap: int = 64,                        # Tokens
    parent_size:  int = 2048                        # Alleen voor parent_document
  } | None
  embedding_model: str | None                       # Override; default uit module-config

Output:
  index_name: str
  documents_indexed: int
  chunks_created: int
  cost_cents: float                                 # Embedding-kosten
  processing_ms: int
```

**Gedrag:**
- Chunkt elk document volgens `chunking.strategy` (default: recursive 512-token met tiktoken-encoder).
- Genereert content-hash chunk-IDs (`source_id + version + hash(span_text)`) — stabiel over re-indexering.
- Vraagt embeddings op via `module-llm` (zie §6).
- Schrijft per chunk: dense vector, BM25 tsvector (met taal-analyzer per `language`), metadata.
- Idempotent op `(source_id, version)`: hetzelfde document twee keer indexeren overschrijft de bestaande chunks.

### 3.2 `search`

Voert hybrid retrieval uit, optioneel met re-rank.

```
Input:
  tenant_id:    str
  index_name:   str
  query:        str
  query_language: str | None                       # Default: auto-detect; bepaalt BM25-analyzer
  top_k:        int = 8                            # Aantal chunks dat teruggegeven wordt
  search_mode:  "hybrid" | "vector_only" | "lexical_only" = "hybrid"
  rrf_k:        int = 60                           # RRF-fusion-parameter
  filters:      dict[str, str | int | bool] | None # Match op metadata-velden
  rerank:       bool = True                        # Re-rank na retrieval
  rerank_candidates: int = 50                      # N kandidaten vóór rerank (alleen als rerank=True)
  include_parent_text: bool = False                # Bij parent_document-chunking: ook ouder-text teruggeven

Output:
  results: list[
    {
      chunk_id:      str,
      source_id:     str,
      source_uri:    str,
      version:       str,
      score:         float,                         # Eindscore (na rerank indien actief)
      retrieval_scores: { vector: float, lexical: float, rrf: float, rerank: float | None },
      text:          str,                           # Chunk-tekst (kind-chunk bij hierarchical)
      parent_text:   str | None,                    # Alleen als include_parent_text=True
      metadata:      dict,                          # Volledig — incl. page_no, section_title, etc.
    }, ...
  ]
  processing_ms: int
  rerank_used: bool
```

### 3.3 `get_chunk`

```
Input:
  tenant_id: str
  chunk_id:  str

Output:
  chunk: { chunk_id, source_id, source_uri, version, text, parent_text, metadata }
```

Bedoeld voor citatie-resolutie in een UI ("klik op voetnoot → toon chunk + parent").

### 3.4 `delete_documents`

```
Input:
  tenant_id:   str
  index_name:  str
  source_ids:  list[str]                           # Verwijder alle versies van deze source-IDs
  versions:    list[str] | None                    # Optioneel: alleen specifieke versies

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
      index_name:        str,
      documents_count:   int,
      chunks_count:      int,
      created_at:        ISO8601,
      last_indexed_at:   ISO8601,
      languages:         list[str]                  # Talen voorkomend in de index
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

## 4. Datamodel

Twee primaire tabellen plus pgvector-extensie. Stable, content-addressable IDs; geen positionele indexen die breken bij re-ingest.

```sql
-- 001_initial.sql (outline, niet definitief)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    chunk_id        TEXT PRIMARY KEY,              -- content-hash, stabiel over reindex
    tenant_id       TEXT NOT NULL,
    index_name      TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_uri      TEXT NOT NULL,
    version         TEXT NOT NULL,
    parent_chunk_id TEXT,                          -- bij hierarchical chunking
    chunk_text      TEXT NOT NULL,
    chunk_tokens    INT  NOT NULL,
    page_no         INT,
    section_title   TEXT,
    language        TEXT NOT NULL,                 -- BCP-47
    metadata        JSONB NOT NULL DEFAULT '{}',   -- Vrije velden (uitzondering op no-JSONB-regel: dit is search-payload, niet domain-model)
    embedding       vector(1024) NOT NULL,         -- Default: multilingual-e5-large-instruct (1024 dims)
    text_search     tsvector,                      -- BM25 / lexical search-kolom
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

> **JSONB-uitzondering**: de Druppie-conventie zegt "no JSONB" voor domain-modellen. Hier wordt JSONB bewust gebruikt voor `metadata` omdat het search-payload is met onbekend schema (per use-case verschillend). Dit is een retrieval-index, geen genormaliseerd domain-model. Te bevestigen in review.

## 5. Configuratie

Environment variables (zie [§7 Docker Compose Service Template](../../druppie/skills/module-convention/SKILL.md) van de module-convention voor patroon):

```
MCP_PORT=9012
MODULE_DB_URL=postgresql://module_rag:<pw>@module-rag-db:5432/module_rag

# Embedding (default — opt-out per call via index_documents.embedding_model)
RAG_EMBEDDING_MODEL=multilingual-e5-large-instruct
RAG_EMBEDDING_DIMS=1024
RAG_EMBEDDING_MCP_URL=http://module-llm:9008/mcp   # Module-llm endpoint dat embedding-tool aanbiedt

# Re-ranking (default — opt-out per search-call)
RAG_RERANKER_ENABLED=true
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANKER_DEVICE=cpu                              # cpu | cuda
```

## 6. Dependencies

| Dependency | Type | Reden |
|---|---|---|
| Postgres 16+ met `pgvector` extensie | Eigen DB-container | Storage + ANN + lexical search in één engine |
| `module-llm` (port 9008) | Sibling MCP-module | Embedding-generation. Vereist een nieuwe `embed` of `embeddings` tool in `module-llm` (zie open vraagstuk in research-doc). |
| Re-ranker-runtime | In-container (FastEmbed/sentence-transformers) | BGE-reranker-v2-m3 lokaal draaien; geen extra service. Eventueel uitknopbaar via `RAG_RERANKER_ENABLED=false`. |
| `module-convention` skill | Conventie | Directory-layout, MODULE.yaml, server-routing, tools.py-pattern. |

**Niet** een dependency:
- Document-extractie-libs (PyPDF, Tika, Unstructured): caller-responsibility.
- LangChain / LlamaIndex als framework: zware dependency, niet nodig — chunking + RRF + pgvector-queries zijn ~enkele honderden regels eigen code.

## 7. Niet-functionele requirements

Volg de NFR-tabel uit [rag-patterns.md → RAG-specifieke NFRs](./rag-patterns.md#default-nfr-tabel). Specifiek voor `module-rag` als deelsysteem:

| Eis | Target |
|---|---|
| `search` p95 (zonder rerank) | < 200 ms @ 10⁵ chunks |
| `search` p95 (met rerank, 50 candidates) | < 500 ms @ 10⁵ chunks |
| `index_documents` throughput | ≥ 100 chunks/sec @ batched embeddings |
| `delete_documents` consistency | binnen één Postgres-transactie |
| Pipeline-uptime | 99.5% (interactief), 99.9% (high-stakes) |
| Degraded-mode bij reranker-failure | `search` blijft werken zonder rerank; flag in response |

## 8. Versioning & migratie

- v1 ondersteunt één embedding-model per index (vast bij `index_documents`-eerste-call, opgeslagen in `index_registry`).
- Switchen van embedding-model = nieuwe index aanmaken (re-embed alle documenten). Geen in-place migratie in v1.
- v2 (potentieel): hot-swap van embedding-model met dual-write tijdens migratie. Niet in v1-scope.

## 9. Open vraagstukken voor implementatie (Story B)

1. **Embedding-tool in `module-llm`**: vereist eigen story/PR. Welke embedding-tool-interface (`embed_texts(list[str]) → list[vector]`?). Caching-strategie binnen `module-llm` of bij caller?
2. **Reranker-loader**: bake BGE-reranker-v2-m3 in de container (verhoogt image-size ~600 MB) of pull-on-startup? Bake-in lijkt simpeler voor reproducibility.
3. **Index-level vs chunk-level taal**: één index met meerdere talen (per-chunk taal-veld → analyzer per zoekkant) of één index per taal? Voorstel: meerdere talen per index toestaan, taal-analyzer per chunk bij BM25.
4. **JSONB-metadata-policy**: bevestiging in review dat dit binnen Druppie-conventie acceptabel is (zie noot bij §4).
5. **Auth & RLS**: gaan we Postgres row-level security gebruiken voor tenant-isolatie (extra defense-in-depth), of vertrouwen we op application-level `tenant_id`-filtering?

## 10. Validatie-scenario's

Story A's e2e-test en Story B's HDSR-notas-validatie raken minimaal:
- Indexeren van een Nederlandstalig document met hierarchical chunking.
- Hybrid search met metadata-filter en rerank.
- Citatie-resolutie via `get_chunk` met parent-section-titel.
- Multilingual: zelfde index, één NL- en één EN-document, beide vindbaar in eigen taal.
- Re-index-stabiliteit: `chunk_id`'s blijven gelijk over een tweede `index_documents`-call van hetzelfde document.
