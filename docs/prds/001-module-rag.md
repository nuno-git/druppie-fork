---
id: "001"
title: "module-rag (orchestrator)"
status: draft
author: mk2023-land
date: 2026-06-01
linked_adrs: []
linked_research: ["docs/research/001-rag-patterns.md"]
linked_specs: []
linked_workitem: null
supersedes: null
superseded_by: null
---

# MODULE_SPEC — `module-rag` (orchestrator, Story B)

> Status: design document for the future `module-rag` orchestration
> module. **Not yet implemented.** Today the storage/retrieval lives in
> each app's own database via `app/rag.py` (pgvector) and `module-llm.embed`.
> **Note:** this spec references `module-vectorstore` which has been
> replaced by distributed app-local pgvector. Story B should build on
> `rag.py` rather than a central vectorstore module.
> are available; the application layer composes them. `module-rag` is
> the Story B work that wraps those primitives plus chunking, rerank,
> query rewriting, and citation formatting into high-level tools so
> the application no longer wires the pipeline itself.
>
> Predecessor: [rag-patterns.md](../research/001-rag-patterns.md) — research
> foundation with the per-layer choices that `module-rag` will
> implement as defaults.
> Convention: follows
> [`module-convention`](../../druppie/skills/module-convention/SKILL.md).
> Today's primitive lives at
> [`druppie/mcp-servers/module-vectorstore/`](../../druppie/mcp-servers/module-vectorstore/).

## 1. Why this module

In v1 (today), an application that wants to do RAG must compose:
- `module-vectorstore.index_documents` — chunk + embed + store
- `module-vectorstore.search` — semantic retrieval
- BM25 / lexical search — application-layer
- Re-ranking — application-layer (e.g. BGE-reranker-v2-m3)
- Query expansion / decomposition / HyDE — application-layer
- Citation formatting (footnotes, anchor tags) — application-layer
- `module-llm.embed` for query embeddings, `module-llm.chat` for the
  generation step

That works but pushes a lot of policy into every application. Every
project has to remember the platform-default chunk size, hybrid-search
parameters, reranker model, citation style, NFR-archetype-driven
budget for retrieval latency, and so on.

`module-rag` lifts those defaults into a single MCP module. The
application gets one tool call per RAG pattern; the module enforces
the defaults from the `rag-patterns` skill and the platform standards
§5 RAG defaults.

## 2. Identity

| Field | Value |
|---|---|
| Module ID | `rag` |
| Directory | `druppie/mcp-servers/module-rag/` |
| Container | `druppie-module-rag` |
| Compose service | `module-rag` |
| Type | Mostly stateless (does not own storage — delegates to `module-vectorstore` for index + chunks, and to `module-llm` for embeddings + generation). May hold a small Postgres for query-log / audit / freshness-tracking. |
| Latest version | `1.0.0` (planned) |
| Endpoint | `/v1/mcp`, `/mcp` (latest), `/health` |
| Port | `9013` (next free after `module-vectorstore` at 9012) |

## 3. Tool surface — the four RAG patterns

The four tools below correspond to the four patterns covered in the
`rag-patterns` skill. Each tool is a fully-composed pipeline; the
application picks the tool that fits its query type.

| Tool | What it does | Internally |
|---|---|---|
| `rag_query` | Simple RAG — one question, one answer with citations. | Hybrid retrieve (vectorstore + BM25) → rerank → generate with citations |
| `rag_conversational_query` | Multi-turn Q&A; resolves pronouns and context against chat history. | Query rewrite using history → `rag_query` |
| `rag_agentic_query` | Adaptive routing; lets a small LLM classify the question (factual / synthesis / multi-hop) and pick the right retrieval strategy. | Router → one of: `rag_query`, plan-and-execute, self-RAG loop, multi-hop. Hard cap on iterations + latency circuit-breaker. |
| `rag_graph_query` | Multi-entity / synthesis questions over a corpus where entity relations matter. | LightRAG-style parallel retriever fused with `rag_query`, gated on a query classifier. |

Plus the corpus-management tools:

| Tool | What it does |
|---|---|
| `rag_ingest` | High-level wrapper around `module-vectorstore.index_documents` that applies the platform-default chunking strategy per content type (recursive 512-token by default, parent-document for long structured docs, late chunking when anaphora-heavy). |
| `rag_delete_documents` | Forget documents (and their chunks). Needed for freshness updates. Maps to `module-vectorstore.delete_index` plus a future granular delete on the primitive. |
| `rag_list_corpora` | Discoverability — which corpora exist for the current project. Wraps `module-vectorstore.list_indices` with corpus-level metadata (last indexed, doc count, freshness SLA). |

### 3.1 `rag_query`

```
Input:
  corpus:               str                          # The named corpus (index) to search
  question:             str
  question_language:    str | None                   # Default: auto-detect; selects BM25 analyzer
  top_k:                int = 8                      # Chunks passed to the LLM
  filters:              dict | None                  # Metadata filters (doc_type, date, status, …)
  rerank:               bool = True
  citation_style:       "footnotes" | "anchors" | "inline" = "footnotes"
  archetype:            "LS" | "HS" | "B" = "HS"     # Drives NFR targets (latency/faithfulness budget)

Output:
  answer:   str                                       # Markdown with citations
  citations: list[{ chunk_id, source_name, page, section, span: { start, end } | None }]
  meta:     { retrieval_ms, rerank_ms, generation_ms, ttft_ms, ttc_ms,
              chunks_retrieved, chunks_used, faithfulness_score | None }
```

### 3.2 `rag_conversational_query`

Same shape as `rag_query`, plus `history: list[{role, text}]`. Internally:
1. Rewrite the user's question using history (calls `module-llm.chat`).
2. Pass the rewritten query to `rag_query` machinery.

### 3.3 `rag_agentic_query`

Same input shape as `rag_query`, plus a `max_iterations` cap and
`router_model: str | None`. Internally:
1. Adaptive Router classifies the question into one of four buckets.
2. Dispatches to the matching retrieval strategy.
3. Optionally invokes Self-RAG / CRAG grading on synthesis paths.
4. Plan-and-execute on research-style questions, capped at four
   sub-goals.

### 3.4 `rag_graph_query`

Same shape as `rag_query`. Activates a LightRAG parallel retriever
that runs alongside vector + BM25, with results fused via RRF.
Reserved for corpora where the architect's gold-set shows
multi-entity / synthesis improvement.

## 4. Defaults the module enforces

The module enforces the platform defaults from
[`rag-patterns.md`](../research/001-rag-patterns.md) and platform standards §5:

- Chunking: recursive, `chunk_size=2048` / `chunk_overlap=256` characters
  (≈ 512 tokens) as default; `parent_document` strategy for long
  structured docs; `late_chunking` for anaphora-heavy text.
- Retrieval: hybrid (BM25 + dense) with RRF k=60.
- BM25 analyzer: language-specific (`to_tsvector('<lang>', ...)`) per
  field, derived from `question_language` and corpus metadata.
- Embedding: whatever `module-llm.embed` returns (platform default).
- Re-ranking: BGE-reranker-v2-m3 self-hosted, default on, candidate
  count N=50 → top-5..8.
- Citations: content-hash chunk IDs (`source_id + version + hash(span)`),
  with `page` / `section` / `parent_section_title` metadata. Footnote
  style in the answer Markdown; anchor tags for interactive UIs.
- NFR archetype targets (LS / HS / B) from the TR-RAG-XX table in the
  `rag-patterns` skill drive the internal latency / cost budgets.

## 5. Dependencies

| Dependency | Reason |
|---|---|
| `module-vectorstore` | Index + chunk storage + semantic search. The module-rag orchestrator never owns chunks; it always calls vectorstore. |
| `module-llm` | Embeddings (`embed` tool) for queries, generation (`chat` tool) for answers, classification / rewriting for the conversational and agentic patterns. |
| `module-convention` skill | Directory layout, MODULE.yaml, server-routing, tools.py pattern. |

**Not** a dependency:
- Document extraction libraries — caller-side, same as for
  `module-vectorstore`.

## 6. Open questions for the Story B implementation

1. **State**: does the orchestrator own a tiny Postgres for query
   audit / freshness tracking / gold-set runs, or is it fully
   stateless (delegating audit to a sidecar logger)?
2. **Reranker location**: bake the BGE-reranker model into the
   container (≈ +600 MB image) or run a sibling `module-reranker`?
   Sibling keeps the orchestrator slim and allows reranker
   swap-out per use-case.
3. **Hybrid BM25**: implement BM25 inside `module-rag` and merge with
   vectorstore results, or push BM25 into `module-vectorstore` as a
   capability extension?
4. **Streaming**: does `rag_query` stream its answer (TTFT-focused)
   or return the full answer (TTC-focused)? Likely both via two
   tool variants.
5. **Gold-set evaluation**: is the gold-set a `module-rag` concern
   (built-in evaluation tool) or a Druppie-platform concern
   (separate eval pipeline)? Strong case for the latter to keep the
   module focused on serving queries.
6. **Multilingual analyzers**: how are analyzer mappings configured —
   per corpus, per project, or globally?
7. **Module-vectorstore evolution**: which capabilities should move
   from `module-rag` orchestration back into the primitive? Hybrid
   BM25, in-graph metadata filtering, parent-section metadata are
   candidates that fit naturally in the primitive once stable.

## 7. Validation scenarios

When `module-rag` lands, at minimum cover:

- A Dutch-language doc-heavy use-case (e.g. HDSR-notas validation
  scenario from `docs/guides/rag-testing.md`) end-to-end via `rag_query`.
- Multilingual corpus: same corpus with NL and EN documents, each
  findable in its own language with `question_language` auto-detect.
- Conversational follow-up resolution via `rag_conversational_query`.
- Adaptive routing on a mixed query stream that includes factual,
  synthesis, and multi-hop questions.
- Hard-cap enforcement on `rag_agentic_query` — no infinite loops.
- Citation stability across re-indexing: identical content-hash IDs
  for chunks whose text didn't change.
