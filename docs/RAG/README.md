# RAG op het Druppie-platform — eindstaat & keuzes

Beknopt overzicht van de uiteindelijke RAG-architectuur en de gemaakte
keuzes. De diepere onderbouwing staat in de onderzoeksdocumenten in deze
map (zie [Verder lezen](#verder-lezen)); dit document is de samenvatting.

## Gekozen architectuur: distributed vector storage

Vectoropslag leeft in **de eigen database van elke app**, niet in een
centrale module. Geen gedeelde vectorstore-container, geen
cross-project toegang — fysieke data-isolatie per app.

| Laag | Wat | Waar |
|---|---|---|
| Opslag + search | `app/rag.py` (chunking, opslag, similarity search) | In de eigen Postgres van elke app (`pgvector/pgvector:pg16`) |
| Embeddings | `module-llm` `embed`-tool (stateless, gedeeld) | Via de Druppie SDK; de app roept nooit zelf een embedding-API aan |
| Ontwerp-begeleiding | `rag-patterns` skill | Architect (keuze van bouwblokken) + developer (implementatie) |

Een eerder ontwerp met een gedeelde `module-vectorstore` + eigen
database-container is **vervangen** door dit distributed model, na
review-feedback (PR #221). Reden: alle bestaande modules zijn stateless,
elke app krijgt al een eigen Postgres, en de SDK-proxy injecteert geen
`project_id` voor app-calls — een gedeelde store zou een isolatie-gat en
single point of failure zijn.

## Platform-defaults

Start elk RAG-ontwerp vanaf deze defaults; afwijken alleen met een
expliciete trigger (zie de `rag-patterns` skill / `rag-patterns.md`).

- **Chunking:** recursive ~512 tokens, 10–20% overlap.
- **Retrieval:** hybride (BM25 + dense) met RRF.
- **Embedding:** `multilingual-e5-large-instruct` (MIT, CPU-haalbaar).
- **Vector store:** pgvector in de eigen app-database.
- **Rerank:** BGE-reranker-v2-m3 (applicatielaag).
- **Citations:** content-hash chunk-IDs + pagina/paragraaf.
- **GraphRAG:** géén default — alleen op bewezen behoefte (≥30%
  multi-entity queries).
- **Agentic search:** **default voor niet-triviale retrieval.** Benchmarks
  laten consistent zien dat agentic search beter presteert dan
  single-shot op alles voorbij simpele one-fact lookups. Single-shot
  alleen als debug-referentie of bij harde latency-eis (< 2s p95).

Agentic search is de default; single-shot alleen voor triviale lookups
of bij harde latency-eisen. Zie "When to use RAG → Plain RAG vs
agentic search" in de skill.

## Wat in deze PR zit (Story A)

- Design-laag: onderzoek + `rag-patterns` skill, platform-standards §5
  (RAG defaults), `technical-design-format` RAG-subsectie, architect-trigger.
- Primitive: `app/rag.py` in de app-template + `module-llm` `embed`-tool.
- Werkend voorbeeld: `POST /api/rag/index` en `POST /api/rag/search` in
  de app-template (`app/routes.py`) — embed → opslaan → similarity search.

## Story B (toekomst)

Een `module-rag`-orchestrator die `app/rag.py`-patroon + `module-llm` +
chunking + rerank + query-rewriting + citations achter high-level tools
verpakt. Handoff: [`story-b.md`](story-b.md), spec:
[`module-rag-spec.md`](module-rag-spec.md).

Daarnaast: een data-scientist / AI-engineer subagent voor de diepe
RAG-implementatiekeuzes zodra subagents in de core zitten — zie issue #231.

## Verder lezen

- [`rag-patterns.md`](rag-patterns.md) — volledig onderzoek (per-as
  vergelijkingen, 2026-benchmarks, NFR-menu).
- [`module-rag-spec.md`](module-rag-spec.md) — Story B orchestrator-spec.
- [`story-b.md`](story-b.md) — handoff voor Story B.
- [`testing.md`](testing.md) — e2e-testinstructies (geautomatiseerd + handmatig).
- `docs/TECHNICAL.md` §6.8 — architectuur in de platformdocumentatie.
