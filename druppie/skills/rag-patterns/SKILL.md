---
name: rag-patterns
description: >
  This skill should be used when designing an application that contains
  large-document retrieval, knowledge-base search, citation-backed Q&A,
  or any other doc-heavy use-case. It covers when an in-app LLM + RAG
  pipeline is a valid building block, how to choose chunking, retrieval,
  embedding, vector store, re-ranking and advanced patterns, which NFRs
  to put in the TD, and how to use app-local pgvector with module-llm.
---

# RAG Patterns for Doc-Heavy Applications

RAG (Retrieval-Augmented Generation) is a **first-class building block**
in Druppie. When a use-case deals with many or large documents, RAG is
often the right answer — not stuffing the documents into the prompt,
and not forcing the user to search manually.

## Architecture: distributed vector storage

- **`app/rag.py`** *(in every app template)* — stores chunks +
  embeddings in the app's own Postgres (pgvector), performs semantic
  search, returns chunks with source metadata for citations. Functions:
  `create_index`, `index_documents`, `search`, `delete_index`,
  `list_indices`.
- **`module-llm`** `embed` tool *(stateless, shared)* — generates
  embeddings via the Druppie SDK. The app never calls an embedding
  API directly.

Each app owns its own vectors in its own database. There is no shared
vectorstore — this gives physical data isolation per app.  The
application layer composes `rag.py` + `module-llm` using the per-layer
decisions below.

## When to use RAG

Use RAG when at least one of these holds:
- The corpus is **too large for the prompt context window** (multiple
  documents, or a single document over 20 pages).
- The user asks **questions whose answers are spread across documents**.
- The application must produce **answers with source citations**
  (legal, compliance, policy, regulated customer-contact).
- The corpus **mutates faster than the release cycle** — fine-tuning
  would always be stale.

**Do not use RAG when:**
- The corpus fits in one LLM context window and rarely changes — just
  put it in the prompt; cheaper and more precise.
- The use-case is **classification or structured extraction** without
  an open-ended question — RAG adds complexity without quality gain.
- The question is a **single-fact lookup in a structured source**
  (database, API) — `module-data-access` is the right choice, not RAG.

### Plain RAG vs agentic search

Both retrieve before generating; the difference is **who decides how
often to search**.

- **Plain (single-shot) RAG** — one retrieval, then generate. The
  **default**. Use it when a question maps to one retrieval pass:
  factual Q&A, policy/citation lookups, "what does document X say
  about Y". Predictable latency and cost.
- **Agentic search** — the agent retrieves **in a loop**: reformulate,
  judge sufficiency, fetch more, possibly decompose, then answer. Use
  it only when a single pass demonstrably cannot answer: **multi-hop**
  questions, iterative refinement, or research-style synthesis.

**Start with plain RAG;** escalate to agentic only when an eval set
shows single-shot retrieval missing multi-step answers — never
pre-emptively (agentic loops multiply latency/cost; see *Advanced
patterns → Agentic loops*).

## Stop — do not reinvent the RAG pipeline

Reference `app-local pgvector (`rag.py`)` (primitive) and `module-llm` (embeddings
via the `embed` tool) instead of designing chunking, embedding, or
vector-search components from scratch. The defaults below are
platform-level; the architect motivates in the TD which layer deviates
and why. Once `module-rag` lands (Story B), TDs target it as the
single building block instead of composing primitives.

## Platform default stack

Start every RAG design from these defaults. Deviate only with an
explicit trigger from the per-layer decision guides below.

| Layer | Default | When to deviate |
|---|---|---|
| Chunking | Recursive 512-token, 10–20% overlap | Long structured docs → parent-document; anaphora-heavy text → late chunking |
| Retrieval | Hybrid (BM25 + dense) with RRF k=60 | Pure-vector only as a stopgap; ColBERT on measured out-of-domain gap |
| BM25 analyzer | Postgres `to_tsvector('<corpus-language>')` per field | Mixed-language corpus → analyzer per field or multilingual analyzer |
| Metadata filter | SQL filter on `doc_type`, `date`, `status`, `tenant_id` | n/a — mandatory once the corpus has more than one doc-type |
| Embedding | `multilingual-e5-large-instruct` (MIT, CPU-feasible) | ≥8 GB GPU budget + quality requirement → Qwen3-Embedding-4B |
| Vector store | pgvector (inside `app-local pgvector (`rag.py`)`'s own Postgres) | >10M chunks or hard p95 filtered-ANN requirement → escape to Qdrant via Story B |
| Re-ranking | BGE-reranker-v2-m3 self-hosted (application layer today; baked into `module-rag` orchestrator in Story B) | Use-case gold-set ≥5 nDCG points better with Cohere → switch (Bedrock EU) |
| Query transformation | Query expansion + classifier-gated decomposition | HyDE for short/vague queries with style gap to the corpus |
| GraphRAG | **Not default** | ≥30% of queries multi-entity/synthesis → LightRAG as parallel retriever |
| Agentic loop | **Not default** | Adaptive Router as first agentic step; Self-RAG only in the synthesis path |
| Citations | Content-hash chunk IDs + page/paragraph + parent-section title; footnote style in formal output | Legal precision → sentence-level span tracking (Claude Citations API) |

## Per-layer decision guides

### Chunking
- **Recursive 512** is the safe default — 2026 benchmarks consistently
  rank it #1 among token-based strategies. Use a tiktoken encoder, not
  character count.
- **Parent-document / hierarchical** once answers are correct but
  citations are either too narrow ("half a sentence out of context") or
  too broad ("entire section as source").
- **Late chunking** for documents with many anaphora ("this decision",
  "the aforementioned party") — requires a long-context embedding model
  (8K+ tokens).
- **Avoid fixed-size** in production unless the corpus is truly
  homogeneous (logs, transcripts).

### Retrieval
- **Hybrid is the defensive default.** Pure dense systematically leaves
  jargon and proper nouns on the table in formal/technical text.
- **Configure a language-specific BM25 analyzer per corpus language.**
  Without one, lexical retrieval delivers half its value.
- **Always add metadata filtering** once the corpus has more than one
  doc-type, year, or category.
- **ColBERT / multi-vector** only when you measure a gap on
  out-of-domain queries and have the storage budget; for most
  use-cases, hybrid + rerank is cheaper and more effective.

### Embedding model
Selection criteria, in order:
1. Broad multilingual coverage (at minimum NL and EN).
2. Self-host feasibility (data residency); API-only is a blocker
   unless EU-hosted and legally cleared.
3. Permissive license (MIT or Apache 2.0). Non-commercial (jina-v3)
   is a blocker.
4. Proven quality on multilingual and language-specific benchmarks.

- **Default**: `multilingual-e5-large-instruct` — MIT, ~2 GB,
  CPU-feasible, broad coverage.
- **Upgrade**: Qwen3-Embedding-4B if ≥8 GB GPU budget; BGE-M3 if you
  want hybrid-with-one-model.
- **Avoid**: OpenAI text-embedding-3-* (weak on non-English European
  languages + API-only), mxbai / nomic-v2 (English-only in practice),
  jina-v3 (non-commercial license).

### Vector store
- **Default = pgvector inside `app-local pgvector (`rag.py`)`.** Postgres already
  runs in the Druppie stack; up to ~10M chunks this delivers sub-100ms
  search latency with SQL filtering and transactional consistency.
- **Move to Qdrant** once: corpus exceeds 10M chunks, hard p95 on
  filtered ANN is required, or native ColBERT/sparse vectors are
  needed. This is a Story B path on top of `app-local pgvector (`rag.py`)`; the
  MCP interface is designed so the migration does not force an
  embedding rebuild.
- **Weaviate / Milvus / Chroma / LanceDB**: only consider with an
  explicit use-case driver (multimodal, billions of vectors,
  embedded-only). Not a default.

### Re-ranking
- **Today**: application-layer reranking with BGE-reranker-v2-m3 — free,
  sovereign, broad language coverage. **Story B**: baked into the
  `module-rag` orchestrator as a default-on step inside `rag_query`.
- **Switch to Cohere Rerank** (Bedrock EU) once a use-case gold-set
  shows ≥5 nDCG points improvement and data egress is acceptable.
- **Turn it off** if latency budget < 500ms p95 without GPU, or
  recall@10 is already >85% without rerank.
- **Candidate count**: standard N=50 → top-5..8; long docs N=80–100;
  latency-critical N=30 → top-3.

### Query transformation
- **Query expansion** is the cheap default — a project glossary of
  domain jargon and synonyms.
- **Decomposition** only when a light classifier detects conjunctions
  ("and", "difference between", "how does X relate to Y"). Cap at
  N=3 sub-questions.
- **HyDE** only for short/vague queries with a style gap to the
  corpus.
- **Step-back** as an optional step inside an agentic loop for very
  specific questions.
- **Anti-pattern**: multi-query + decomposition at the same time →
  latency explosion without added value.

### Advanced patterns
- **GraphRAG is not default.** Add it (LightRAG as a parallel
  retriever inside an Adaptive Router) once ≥30% of queries are
  multi-entity / synthesis. Full Microsoft GraphRAG only for explicit
  corpus-wide synthesis projects.
- **Agentic loops are not default.** Progression: (1) get baseline +
  rerank working → (2) Adaptive Router (3–4 class classifier) →
  (3) Self-RAG / CRAG in the synthesis path → (4) plan-and-execute
  only for research-style questions. Always with hard iteration caps
  and a latency circuit-breaker.

## Citations

For doc-heavy applications where users must verify the source,
citation tracking is **not a feature but a requirement**. Mandatory
in the pipeline:

1. **Content-hash chunk IDs** (`source_id + version + hash(span_text)`)
   — stable across re-indexing.
2. **Page / paragraph metadata** — users must be able to jump to the
   source passage.
3. **Parent-section title** as metadata when using hierarchical
   chunking — context-rich citations.
4. **Footnote style in formal Markdown output** plus parallel
   **anchor tags** (`<cite chunk_id="..." span="...">text</cite>`) for
   interactive UI with a clickable source preview.
5. **Sentence-level span tracking** if legal/compliance precision is
   required — Claude Citations API or post-hoc matching.

Citations verify that the **source exists**, not that the **claim is
correct**. Keep that distinction visible in UX and in evaluation.

## NFRs for RAG in the TD

RAG quality and latency targets belong **inside the RAG subsection**
of the TD, not in the global Requirements table. Keep it compact —
typically one short paragraph or table covering the targets that
actually drive design decisions for this use-case. Common picks
(non-exhaustive): faithfulness, citation precision, hallucination
rate, end-to-end latency. Pick the ones that matter for the chosen
archetype and skip the rest.

**Archetypes** (used to set numeric targets):
- **LS (Low-stakes interactive)**: chatbot, FAQ, quick Q&A.
- **HS (High-stakes interactive)**: governance advice, legal,
  compliance, regulated customer contact. Stricter
  faithfulness/citation/hallucination thresholds.
- **B (Batch)**: nightly digests, research summaries. Latency is
  loose, quality strict.

The full menu of TR-RAG-XX requirements with per-archetype defaults
lives in
[rag-patterns research → Default-NFR-tabel](../../../docs/RAG/rag-patterns.md#default-nfr-tabel).
Cite from it as needed — do not paste the entire table into every TD.

## How to land this in a TD

In the Technical Design of a RAG project:

1. **Section "Solution direction"** — reference `app-local pgvector (`rag.py`)`
   explicitly as the storage/retrieval building block and `module-llm`
   for embeddings + generation, and motivate why RAG (rather than
   classification, in-prompt context, or a structured DB query). If
   `module-rag` is available (Story B), reference it as the single
   orchestrator building block instead.
2. **Section "Architecture"** — show the pipeline steps: ingest →
   chunk → embed → store → search → rerank → generate. Mark which
   steps `app-local pgvector (`rag.py`)` performs, which `module-llm`, and which
   the application itself. After Story B, `module-rag` collapses
   chunk → embed → store on one side and search → rerank on the other
   into single tool calls.
3. **Section "Choices per layer"** — for chunking, retrieval,
   embedding, vector store, rerank, query transformation, and
   advanced patterns, state whether you follow the platform default
   or deviate (and with which trigger).
4. **Section "Citation strategy"** — describe which citation style
   appears in the output, which metadata lives in the index, and what
   the user sees in the UI.
5. **Section "Non-functional requirements"** — include the
   TR-RAG-XX requirements with use-case-specific targets (pick an
   archetype and adjust as needed).
6. **Section "Open questions / out-of-scope"** — what v1 does not do
   (advanced patterns, multi-tenant physical isolation, fancy
   reranking) and what would trigger v2.

## Anti-patterns to catch in a design

- **"We use RAG"** without naming pipeline steps, embedding model, or
  vector store. Under-specified; requires TD revision.
- **Pure-vector search** as the only retrieval strategy in production
  — systematically loses jargon and proper nouns.
- **GraphRAG or agentic RAG** without a proven problem they solve —
  adds latency and cost without quality gain.
- **Custom vector store** (Qdrant, Weaviate, etc.) without a concrete
  trigger from the decision guide. Default = pgvector via
  `app-local pgvector (`rag.py`)`.
- **Citations as "source list at the bottom"** instead of per-claim
  binding — a blocker for regulated use-cases.
- **Embedding model picked from the MTEB-EN leaderboard** without
  checking multilingual / NL benchmarks and license.
- **Document extraction hidden inside the module** — the caller is
  responsible for PDF/Word → text; `app-local pgvector (`rag.py`)` accepts
  pre-extracted text + metadata. Same expectation for `module-rag`
  when it lands (Story B).

## References

- Research foundation with full comparison + trade-off tables:
  [`docs/RAG/rag-patterns.md`](../../../docs/RAG/rag-patterns.md)
- Module-rag orchestrator spec (Story B):
  [`docs/RAG/module-rag-spec.md`](../../../docs/RAG/module-rag-spec.md)
- Module-vectorstore primitive (v1, code):
  [`druppie/mcp-servers/app-local pgvector (`rag.py`)/`](../../mcp-servers/app-local pgvector (`rag.py`)/)
- Platform standards RAG section (defaults seeded into every project):
  [`druppie/templates/project/docs/platform-technical-standards.md`](../../templates/project/docs/platform-technical-standards.md) §5 RAG defaults
