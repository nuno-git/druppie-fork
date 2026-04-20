# Platform Standards

**Revision:** 2026-04-20

This file defines the defaults every Druppie-created application follows. The
Architect treats these as givens when writing `technical_design.md` and only
documents deviations.

If a project needs to break a standard, the Architect documents the deviation
in the TD under *"Platform standard deviations"* with a short rationale.

## 1. Scope

Everything in this file is a platform-level default. The Architect does NOT
restate these in a project's TD — the TD references this file instead and only
describes the project-specific decisions on top.

## 2. Stack

| Layer | Default | Notes |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript | From `druppie/templates/project/frontend/` |
| Backend | Python 3.11 + FastAPI | From `druppie/templates/project/app/` |
| Database | Postgres 15 | One DB per project, no sharing |
| Runtime | Docker Compose (dev) + the Druppie deploy pipeline (prod) | |
| LLM access | Druppie SDK (`druppie_sdk.client`) — never direct provider SDKs | Provider swaps handled centrally |
| Module access | Druppie SDK — module discovery + calls | Do NOT reimplement capabilities that exist as modules |

TDs do not restate any of this. They only call it out when they deviate.

## 3. Template is the starting point

Every app starts from `druppie/templates/project/`. The chat UI, session
management, agent loop, and SDK wiring are already there. The Architect's TD
assumes this scaffold exists and only describes:

- New routes/components/endpoints added on top
- Data model (the project's own tables)
- Domain logic and business rules
- External integrations specific to this project

The Architect does not document: the chat panel, session list, keycloak
wiring, agent framework, SDK setup — these are the template and do not change
per project.

## 4. Modules before code

Before designing a capability from scratch, the Architect checks the module
registry:

- Text generation / reasoning → `module-llm`
- Image / OCR / document vision → `module-vision`
- Web search → `module-web`
- File search inside a codebase → `module-filesearch`
- ArchiMate / architecture reasoning → `module-archimate`
- Shell / coding execution → `module-coding`

If an existing module covers the capability, the TD references the module and
the SDK call pattern — it does not design an alternative. Building a new
capability is only valid if no matching module exists; the Architect notes
this in the TD with a short justification.

## 5. Database & persistence

- **Postgres is the default.** Reach for it whenever data needs to be queried,
  filtered, joined, or aggregated.
- **Use relational tables when you need to query inside the data.** If a field
  is filtered, joined on, or aggregated — make it a proper column.
- **JSON / JSONB is fine when the data is only read back whole.** If you store
  a blob, look it up by id, and hand it back to the caller as-is, there's no
  reason to normalise it. Common examples: opaque third-party payloads,
  rendered content, configuration snapshots.
- **Migrations are allowed.** Use them when schema changes need to land in an
  existing environment without a reset.

Programming style — follow the Druppie core:

- **Summary / Detail domain models** — `FooSummary` for lists, `FooDetail` for
  single-item endpoints (see `SessionSummary` / `SessionDetail`). All domain
  types live in `app/domain/` and are exported from `app/domain/__init__.py`.
- **One repository per aggregate.** `FooRepository` owns all data access for
  `Foo`; repositories return domain models, not ORM rows.
- **Services compose repositories.** Services hold business logic; they never
  touch the DB directly. Route handlers call services.

## 6. API conventions

- FastAPI routers under `app/api/routes/`.
- Routes are thin: validate input, call a service, return a domain model. No
  business logic in route handlers.
- Services under `app/services/` contain the business logic.
- Repositories under `app/repositories/` own data access and return domain
  models, not ORM rows.
- All domain types are Pydantic models in `app/domain/`, exported from
  `app/domain/__init__.py`.

## 7. Frontend conventions

- TypeScript, strict mode on.
- Pages under `src/pages/`, reusable components under `src/components/`.
- API client under `src/services/api.ts` — all HTTP calls go through it.
- Styling: Tailwind via the classes already set up in the template.
- Chat UI: use the template's `ChatPanel` (from
  `druppie/templates/project/frontend/src/components/chat/`). Do not roll a
  new chat UI.

## 8. Testing

- Backend: pytest. Integration tests target a real Postgres (via the
  template's `docker-compose.yaml`). Mocks only for external third-party APIs.
- Frontend: Playwright for end-to-end. Unit tests only where logic is
  non-trivial — UI snapshots are usually not worth it.
- The TD names the scenarios that need tests; test implementation details
  live in the repo, not the TD.

## 9. Security

- **Auth is handled by Druppie.** Every app is deployed behind the Druppie
  platform, which already does Keycloak-based auth. Apps read the
  authenticated user from request headers; they do NOT implement their own
  login, token issuance, password storage, or role management.
- **Secrets** come from env vars. No secrets in code, no secrets in the repo.
- **PII** — if an app handles personal data, the Architect calls that out in
  the TD with retention + access-restriction notes. Everything else defaults
  to "authenticated Druppie user may access their own data."

## 10. Explicitly out of scope (for now)

The following are platform concerns, will be addressed later, and should NOT
appear in individual project TDs:

- **Authentication & authorisation implementation.** Handled by Druppie; apps
  trust headers.
- **Cost tracking / LLM-spend accounting.** Will be a platform feature; apps
  do not need to track or expose costs.
- **Audit logging of data access.** Platform concern.
- **Rate limiting.** Platform concern (handled at the ingress).
- **Multi-tenancy isolation beyond per-user data scoping.** Single-tenant per
  app for now.
- **Backups / disaster recovery.** Platform concern.

If a project has a genuine reason to do any of these itself (e.g. a
compliance-driven exception), the Architect documents it as a platform-
standard deviation with rationale.

## 11. Deployment

- Each app ships a `Dockerfile` and a `docker-compose.yaml` in the same shape
  as the template.
- Every service has a `/health` endpoint returning 200 when ready.
- Startup uses the existing `init` pattern — see
  `druppie/templates/project/docker-compose.yaml`.
- Prod deployment is via the Druppie deploy pipeline; the TD does not
  describe Kubernetes manifests or cloud infra.

## 12. Git

- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
  `chore:`).
- Feature branches off `main`; PRs back to `main`.
- One logical change per commit.
- Every PR description states the why, not just the what.
