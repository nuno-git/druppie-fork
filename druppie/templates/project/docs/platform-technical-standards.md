# Platform Technical Standards

**Revision:** 2026-06-01

Every Druppie-created application follows these technical defaults. The
Architect treats them as givens when writing `docs/technical-design.md` and only
documents deviations.

The TD references this file by name and revision — it does not restate the
defaults. See the user-facing functional defaults in
[`platform-functional-standards.md`](./platform-functional-standards.md).

## 1. Stack

| Layer | Default | Notes |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript | From `druppie/templates/project/frontend/` |
| Backend | Python 3.11 + FastAPI | From `druppie/templates/project/app/` |
| Database | Postgres 15 | One DB per project, no sharing |
| Runtime | Helm chart on Kubernetes, via the Druppie deploy pipeline | App ships its own `chart/`; local dev runs the app directly |
| LLM access | Druppie SDK (`druppie_sdk.client`) — never direct provider SDKs | Provider swaps handled centrally |
| Module access | Druppie SDK — module discovery + calls | Do NOT reimplement capabilities that exist as modules |

TDs do not restate this. They only call it out when they deviate.

## 2. Template is the starting point

Every app starts from `druppie/templates/project/`. The chat UI, session
management, agent loop, and SDK wiring are already there. The TD assumes
this scaffold exists and only describes:

- New routes/components/endpoints added on top
- Data model (the project's own tables)
- Domain logic and business rules
- External integrations specific to this project

The TD does not document: the chat panel, session list, keycloak wiring,
agent framework, SDK setup — these are the template and do not change
per project.

## 3. Modules before code

Before designing a capability from scratch, the Architect checks the module
registry:

- Text generation / reasoning → `module-llm`
- Image / OCR / document vision → `module-vision`
- Web search → `module-web`
- File search inside a codebase → `module-filesearch`
- ArchiMate / architecture reasoning → `module-archimate`
- Shell / coding execution → `module-coding`
- Document-heavy retrieval, knowledge-base search, citation-backed Q&A
  → app-local pgvector via `app/rag.py` helper (storage + semantic search)
  and `module-llm` `embed` tool (embeddings via SDK). Each app stores
  vectors in its own database for full data isolation.

If an existing module covers the capability, the TD references the module
and the SDK call pattern — it does not design an alternative. Building a
new capability is only valid if no matching module exists; the Architect
notes this in the TD with a short justification.

## 4. Database & persistence

- **Postgres is the default.** Reach for it whenever data needs to be
  queried, filtered, joined, or aggregated.
- **Use relational tables when you need to query inside the data.** If a
  field is filtered, joined on, or aggregated — make it a proper column.
- **JSON / JSONB is fine when the data is only read back whole.** If you
  store a blob, look it up by id, and hand it back to the caller as-is,
  there's no reason to normalise it. Common examples: opaque third-party
  payloads, rendered content, configuration snapshots.
- **Migrations are allowed.** Use them when schema changes need to land
  in an existing environment without a reset.

Programming style — follow the Druppie core:

- **Summary / Detail domain models** — `FooSummary` for lists, `FooDetail`
  for single-item endpoints (see `SessionSummary` / `SessionDetail`). All
  domain types live in `app/domain/` and are exported from
  `app/domain/__init__.py`.
- **One repository per aggregate.** `FooRepository` owns all data access
  for `Foo`; repositories return domain models, not ORM rows.
- **Services compose repositories.** Services hold business logic; they
  never touch the DB directly. Route handlers call services.

## 5. RAG defaults

For doc-heavy applications (knowledge bases, document search,
citation-backed Q&A, large-document retrieval) the platform defaults are:

| Topic | Default |
|---|---|
| Vector storage | App's own Postgres with pgvector (`pgvector/pgvector:pg16` image). Use `app/rag.py` helper — never reimplement chunking or vector search from scratch. |
| Embeddings | `module-llm` `embed` tool via the Druppie SDK (stateless, shared). Research recommends `multilingual-e5-large-instruct` (MIT, multilingual, CPU-feasible); `module-llm` config pins the active default. |
| Retrieval | Semantic (cosine similarity) via `rag.py` `search()`. Hybrid (BM25 + dense) with RRF k=60 is a future upgrade — application-layer BM25 fusion until then. |
| BM25 analyzer | Language-specific (`to_tsvector('<corpus-language>', ...)`) per field — application-layer |
| Chunking | Recursive splitter, default `chunk_size=2048` / `chunk_overlap=256` characters (≈ 512 tokens, per the 2026 benchmarks in `docs/RAG/rag-patterns.md`) |
| Re-ranking | BGE-reranker-v2-m3 self-hosted — application layer |
| Citation metadata | `source_name` + `source_page` + `source_section` + `chunk_id` returned by every search result |
| Citation format | Footnote style in formal Markdown output + anchor tags for interactive UI |
| Document extraction | Caller-side; `rag.py` `index_documents()` accepts pre-extracted text + metadata |
| Data isolation | Physical — each app owns its vectors in its own database. No shared vectorstore, no cross-app access. |

Mandatory NFRs in the TD for any RAG component: retrieval latency,
recall on a gold-set, faithfulness, citation precision, hallucination
rate, freshness SLA, named content owner per domain, PII tagging
before indexing, lineage per chunk. Use the `LS / HS / Batch`
archetype defaults from the `rag-patterns` skill.

The TD does not restate these defaults. It only documents deviations
and the trigger that justifies them.

For deeper guidance — chunking variants, advanced patterns
(re-ranking, query rewriting, GraphRAG, agentic), NFR archetypes,
anti-patterns — see the `rag-patterns` skill in the Druppie core.

## 6. API conventions

- FastAPI routers under `app/api/routes/`.
- Routes are thin: validate input, call a service, return a domain model.
  No business logic in route handlers.
- Services under `app/services/` contain the business logic.
- Repositories under `app/repositories/` own data access and return
  domain models, not ORM rows.
- All domain types are Pydantic models in `app/domain/`, exported from
  `app/domain/__init__.py`.

## 7. Frontend conventions

- TypeScript, strict mode on.
- Pages under `src/pages/`, reusable components under `src/components/`.
- API client under `src/services/api.ts` — all HTTP calls go through it.
- Styling: Tailwind via the classes already set up in the template.
- Chat UI: use the template's `ChatPanel` (from
  `druppie/templates/project/frontend/src/components/chat/`). Do not
  roll a new chat UI.

## 8. Testing

- Backend: pytest. Integration tests target a real Postgres (the chart
  ships a Postgres StatefulSet; locally, point tests at any Postgres).
  Mocks only for external third-party APIs.
- Frontend: Playwright for end-to-end. Unit tests only where logic is
  non-trivial — UI snapshots are usually not worth it.
- The TD names the scenarios that need tests; test implementation
  details live in the repo, not the TD.

## 9. Security (technical)

- **Auth is handled by Druppie.** Every app is deployed behind the
  Druppie platform, which already does Keycloak-based auth. Apps read
  the authenticated user from request headers; they do NOT implement
  their own login, token issuance, password storage, or role management.
- **Secrets** come from env vars. No secrets in code, no secrets in the
  repo.
- **PII** — if an app handles personal data, the Architect calls that
  out in the TD with retention + access-restriction notes. Everything
  else defaults to "authenticated Druppie user may access their own
  data."

The user-facing side of auth (no login screen, no role-admin UI) lives
in the functional standards file.

## 10. Explicitly out of scope (for now)

The following are platform concerns and should NOT appear in individual
project TDs:

- **Authentication & authorisation implementation.** Handled by Druppie;
  apps trust headers.
- **Cost tracking / LLM-spend accounting.** Will be a platform feature.
- **Audit logging of data access.** Platform concern.
- **Rate limiting.** Platform concern (handled at the ingress).
- **Multi-tenancy isolation beyond per-user data scoping.** Single-tenant
  per app for now.
- **Backups / disaster recovery.** Platform concern.

If a project has a genuine reason to do any of these itself (e.g. a
compliance-driven exception), the Architect documents it as a platform-
standard deviation with rationale.

## 11. Deployment

- Each app ships a `Dockerfile` and a Helm `chart/` in the same
  shape as the template.
- Every service has a `/health` endpoint returning 200 when ready.
- Startup uses the chart's init pattern — see
  `druppie/templates/project/chart/`.
- Prod deployment is via the Druppie deploy pipeline; the TD does not
  describe Kubernetes manifests or cloud infra.

## 12. Git

- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
  `chore:`).
- Feature branches off `main`; PRs back to `main`.
- One logical change per commit.
- Every PR description states the why, not just the what.

## 13. Referencing this file in the TD

Every `technical-design.md` starts with a **Platform standards** line
linking back here with the revision the TD was written against:

> Platform standards: conforms to [docs/platform-technical-standards.md](./platform-technical-standards.md) rev 2026-06-01.
> Only deviations are documented below.
