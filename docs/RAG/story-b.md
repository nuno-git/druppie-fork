# Story B — `module-rag` orchestrator (handoff)

> Audience: the engineer who picks this up. Self-contained — read this
> first, then dive into the linked artifacts. The Story A work
> (research, skill, spec, primitive integration) is **done and merged
> on the `RAG` branch**. This document tells you what's left to build
> for Story B and where every relevant file lives.

## 1. Goal in one sentence

Build a new MCP module `module-rag` that wraps the existing
`app-local pgvector (`rag.py`)` primitive + `module-llm` (chat + embed) +
chunking strategy selection + re-ranking + query rewriting + citation
formatting into a small set of high-level RAG tools, so an
application no longer has to compose the pipeline itself.

## 2. Why this work exists

Right now, an application that wants RAG must compose six things by
hand: chunk text correctly, call `module-llm.embed`, store via
`app-local pgvector (`rag.py`).index_documents`, search via
`app-local pgvector (`rag.py`).search`, rerank, format citations, then call
`module-llm.chat` for the answer. That's a lot of policy to repeat
across projects. Every project re-decides the chunk size, the rerank
threshold, the citation style — drift is guaranteed.

Story B consolidates the policy into one module. The application
calls `rag_query(corpus, question)` and gets a cited answer back. The
defaults the module enforces are the ones the `rag-patterns` skill
already documents and the `rag-patterns.md` research already justifies.

## 3. What v1 already gives you (no need to rebuild)

These all live in this repo today (on the `RAG` branch) and are
ready to consume from inside `module-rag`:

| Building block | Where | What it gives you |
|---|---|---|
| `app-local pgvector (`rag.py`)` | `druppie/mcp-servers/app-local pgvector (`rag.py`)/` (port 9012, pgvector) | `index_documents`, `search`, `get_chunk`, `list_indices`, `delete_index`. Char-based recursive chunker with `chunk_size=2048` / `chunk_overlap=256` defaults (≈ 512 tokens). |
| `module-llm.embed` | `druppie/mcp-servers/module-llm/v1/tools.py` (`embed` tool) | Wraps the OpenAI-compatible embeddings endpoint (Z.AI / DeepInfra / etc., configured centrally). Returns vectors for one or more texts. |
| `module-llm.chat` | same file (`chat` tool) | The generation step. |
| `rag-patterns` skill | `druppie/skills/rag-patterns/SKILL.md` | The architect's decision guide. Read it — `module-rag` defaults must match what the skill promises. |
| Platform standards §5 RAG defaults | `druppie/templates/project/docs/platform-technical-standards.md` | What every project inherits. `module-rag` defaults must match this. |

## 4. What you build

A new MCP module at `druppie/mcp-servers/module-rag/` following the
`module-convention` skill. Port `9013`. Mostly stateless (delegates
storage to `app-local pgvector (`rag.py`)`); may carry a tiny Postgres for query
audit / freshness tracking — see open question §1 in the spec.

The seven tools to expose are spelled out in
[`module-rag-spec.md`](./module-rag-spec.md) §3:

- `rag_query` — simple RAG: one question, one cited answer.
- `rag_conversational_query` — adds chat-history-aware query rewrite.
- `rag_agentic_query` — adaptive router → factual / synthesis /
  multi-hop / conversational paths with hard caps.
- `rag_graph_query` — GraphRAG-style retrieval (LightRAG-flavoured)
  fused with hybrid retrieval, gated on the router.
- `rag_ingest` — wraps `app-local pgvector (`rag.py`).index_documents` with the
  right chunking strategy per content type.
- `rag_delete_documents` — granular delete for freshness updates.
- `rag_list_corpora` — corpus discoverability with freshness metadata.

Each tool's exact input/output shape is in the spec.

## 5. Defaults the module enforces

All defaults below are research-justified. Don't pick alternatives
without re-reading the research first.

- **Chunking**: recursive, `chunk_size=2048` / `chunk_overlap=256`
  characters (≈ 512 tokens). For long structured docs (rapporten,
  contracten, beleidsstukken): switch to `parent_document` strategy.
  For anaphora-heavy text: `late_chunking` (requires long-context
  embedding model).
- **Retrieval**: hybrid (BM25 + dense) with RRF k=60.
- **BM25 analyzer**: language-specific
  (`to_tsvector('<corpus-language>', ...)`).
- **Re-ranking**: BGE-reranker-v2-m3 self-hosted, on by default, N=50
  candidates → top-5..8.
- **Citations**: content-hash chunk IDs
  (`source_id + version + hash(span)`) for stable references across
  re-indexing; page + section + parent-section metadata; footnote
  style in formal Markdown output, anchor tags
  (`<cite chunk_id="..." span="...">`) for interactive UIs.
- **NFRs**: targets from the TR-RAG-XX table in the `rag-patterns`
  skill, driven by the `archetype` parameter (LS / HS / B) the caller
  passes.

## 6. Where everything is written down

All the supporting artifacts are already in the repo. Use them as
your reference; do not re-derive.

### Research foundation (read this first)
- **`docs/RAG/rag-patterns.md`** *(Dutch, ~760 lines)* — the research
  document that backs every default in this Story. Per-axis
  comparisons (chunking, retrieval, embedding, vector store, advanced
  patterns, NFRs) with 2026 benchmarks and decision-guides. Read at
  least the Eindaanbeveling section and the Open vraagstukken at the
  bottom.

### Architect-side artifacts (must stay in sync with what you build)
- **`druppie/skills/rag-patterns/SKILL.md`** *(English)* — the
  decision guide the architect invokes. Section "Two modules
  involved" at the top describes the v1 vs Story B split. Update this
  skill in lockstep with what the orchestrator actually offers.
- **`druppie/templates/project/docs/platform-technical-standards.md`**
  §5 "RAG defaults" — what every project inherits at creation time.
  Update when defaults change.
- **`druppie/skills/technical-design-format/SKILL.md`** — has a
  conditional `#### 3. RAG choices` subsection. After Story B, TDs
  start citing `module-rag` as the single building block.
- **`druppie/agents/definitions/architect.yaml`** — Step 1 has a
  two-line detection trigger for doc-heavy FDs that invokes the
  `rag-patterns` skill. Likely no change needed.

### Module spec (the actual instructions)
- **`docs/RAG/module-rag-spec.md`** — full design: identity, the 7
  tools, defaults the module enforces, dependencies, open questions
  for the implementation, validation scenarios.

### Testing
- **`testing/tools/architect-fd-rag-pending.yaml`** — Story A's seed
  test that lands a doc-heavy FD paused on FD-approval. After the
  user approves, the architect should detect doc-heavy and invoke
  `rag-patterns`. Story B should add an end-to-end test that goes
  one step further: real `module-rag` tools called by a built
  application against a real corpus.
- **`docs/RAG/testing.md`** — manual e2e instructions for Story A.
  Add a Story B equivalent that covers `rag_query` against a real
  indexed corpus.

### Documentation
- **`docs/FEATURES.md`** — Architect-Side Skills table mentions
  `rag-patterns`; update with `module-rag` once built.
- **`docs/TECHNICAL.md`** §6.8 — RAG server section. Currently
  documents `app-local pgvector (`rag.py`)`; add a §6.9 for `module-rag` when
  built.

### Robbe's predecessor PR
- **PR #214 (`feature/rag-for-agents`)** — Robbe's original RAG PR.
  Closed in favour of the `RAG` branch but contains useful
  predecessor work: `vectorstore-usage` skill, `platform-knowledge`
  auto-indexing scripts, his architect Level 2b "Indexed documents"
  prompt section. Read it for context, especially if you want
  inspiration for how `module-rag` should be wired into the architect
  for context gathering.

## 7. Open questions to resolve early

From spec §6:

1. **Statefulness**: does `module-rag` own a Postgres for query
   audit / freshness / gold-set runs, or is it fully stateless?
2. **Reranker placement**: bake the BGE-reranker model into the
   container (+600 MB image), or run a sibling `module-reranker`?
3. **Hybrid BM25**: implement inside `module-rag` (orchestrator
   merges) or push down into `app-local pgvector (`rag.py`)` as a primitive
   capability?
4. **Streaming**: TTFT-focused `rag_query` (stream) vs TTC-focused
   (return whole answer) — likely both, as two tools.
5. **Gold-set evaluation**: a `module-rag` concern or a separate
   platform eval pipeline?
6. **Multilingual analyzers**: per-corpus, per-project, or global
   configuration?
7. **Primitive evolution**: should hybrid BM25 / in-graph metadata
   filter / parent-section metadata move down into
   `app-local pgvector (`rag.py`)` once stable?

## 8. Suggested step-by-step plan

1. **Scaffold** `druppie/mcp-servers/module-rag/` per
   `module-convention`. MODULE.yaml, Dockerfile, server.py with
   /v1/mcp routing, `v1/__init__.py`, `v1/module.py`, `v1/tools.py`.
   Decide on statefulness — likely stateless to start.
2. **`rag_ingest`** — simplest tool. Wraps
   `app-local pgvector (`rag.py`).index_documents` with chunking-strategy
   selection per content type. Get this working first; it's the
   foundation.
3. **`rag_query`** — the bread and butter. Implement the full
   pipeline: parse question → embed (via `module-llm.embed`) →
   vector search (`app-local pgvector (`rag.py`).search`) → BM25 search → RRF
   fusion → rerank (BGE-reranker-v2-m3) → assemble prompt with
   citation instructions → call `module-llm.chat` → return answer
   with parsed citations.
4. **NFR tracking** — every tool returns the latency-budget
   numbers in its `meta` block. The `archetype` parameter picks the
   targets from the TR-RAG-XX table.
5. **`rag_conversational_query`** — adds a single LLM call for query
   rewrite using history.
6. **`rag_agentic_query`** — adaptive router (small classifier
   prompt) + the three downstream strategies. Hard cap on
   iterations + latency circuit-breaker is non-negotiable.
7. **`rag_graph_query`** — LightRAG-style parallel retriever. Only
   wire this if a project explicitly opts in; keep it cleanly
   separable.
8. **Citation stability** — implement content-hash chunk IDs in the
   orchestrator (since the v1 primitive uses UUID). Optionally push
   this down into `app-local pgvector (`rag.py`)` as part of this story.
9. **Tests** — unit per tool, plus an end-to-end test similar to
   `testing/tools/architect-fd-rag-pending.yaml` but going one step
   further: simulate the built application calling `rag_query`
   against a small indexed corpus.
10. **Update the architect-side artifacts** — once `module-rag`
    exists, update the `rag-patterns` skill and the platform
    standards §5 so TDs reference `module-rag` as the single
    building block, and update the TD-format skill's RAG choices
    subsection accordingly.

## 9. Estimated scope

Reference points:
- Story A (research + skill + spec + standards + architect trigger +
  seed test) — landed in 9 commits, mostly markdown + minimal YAML.
- Robbe's `app-local pgvector (`rag.py`)` v1 — ~500 lines of Python in
  `v1/module.py` plus the surrounding scaffolding, took one focused
  PR (PR #214).

Story B is bigger than either:
- 4 query tools + 3 corpus tools, each non-trivial.
- The agentic and graph variants are the heaviest.
- NFR tracking + content-hash IDs add another layer.

Rough estimate: **5–8 story points**, depending on how much of the
reranker / BM25 work is pushed down into `app-local pgvector (`rag.py`)` (which
would split this into two PRs).

## 10. Definition of done

- All seven tools implemented and accessible via MCP.
- Defaults match what `rag-patterns` skill and platform standards §5
  promise.
- Architect-side artifacts updated so TDs reference `module-rag`
  instead of "vectorstore + llm + app-layer pipeline".
- End-to-end test covers `rag_query` against an indexed corpus from
  a built application, with passing citation checks.
- TECHNICAL.md gets a new §6.9 "module-rag orchestrator".
- FEATURES.md "Architect-Side Skills" row for `rag-patterns` updated
  to say `module-rag` is now built.
- `docs/RAG/testing.md` has a Story B manual e2e section.
- This handoff document gets a closing note: "Story B done — see
  [linked PR]".
