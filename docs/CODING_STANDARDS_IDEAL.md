# Druppie Coding Standards (Ideal / Target State)

This document defines the **aspirational target state** for the Druppie codebase. It describes the standard we are working toward.

> **Note:** The current codebase deviates from these standards in several areas. See `CODING_STANDARDS.md` (Current State) for how things work today, and `docs/BACKLOG.md` for tracked refactoring items. When introducing new code, prefer these standards. When touching existing code, match the local pattern unless the file is already being refactored.

## Table of Contents

1. [Branch & Workflow Standards](#branch--workflow-standards)
2. [Backend Standards (Python / FastAPI)](#backend-standards-python--fastapi)
3. [Frontend Standards (React / Vite)](#frontend-standards-react--vite)
4. [Database Standards (PostgreSQL / SQLAlchemy)](#database-standards-postgresql--sqlalchemy)
5. [Data Handling & Type Safety](#data-handling--type-safety)
6. [Security Standards](#security-standards)
7. [Agent Execution & Async Patterns](#agent-execution--async-patterns)
8. [Testing Standards](#testing-standards)
9. [Docker & Infrastructure Standards](#docker--infrastructure-standards)
10. [CI/CD & Git Standards](#cicd--git-standards)
11. [Documentation Standards](#documentation-standards)
12. [AI Review Agent — Quick Checklist](#ai-review-agent--quick-checklist)
13. [Anti-Patterns & Common Mistakes](#anti-patterns--common-mistakes)

---

## Branch & Workflow Standards

| Rule | Standard |
|------|----------|
| Default branch | `colab-dev` |
| Branch from | Always `colab-dev`. Run `git pull origin colab-dev` first. |
| Feature branch naming | `feature/<descriptive-name>` |
| PR target | `colab-dev` (from `feature/<name>`) |
| Commits | Always commit and push. Keep changes in git. |
| Integration to `main` | Occasionally: merge `colab-dev` → `main`. |

---

## Backend Standards (Python / FastAPI)

### Project Structure

```
druppie/
├── api/              # FastAPI routes — THIN layer, minimal logic
│   ├── main.py       # App factory, lifespan, router registration
│   ├── deps.py       # Dependency injection (repos, services, auth)
│   ├── errors.py     # Standardized error handling
│   └── routes/       # Route modules
├── services/         # Business logic layer
├── repositories/     # Data access layer — returns typed domain models
├── domain/           # Pydantic models
├── db/
│   ├── models/       # SQLAlchemy ORM models
│   └── database.py   # Session factory, engine
├── execution/        # Agent orchestrator, ToolExecutor, MCPHttp, HumanInput
├── agents/           # Agent runtime, YAML definitions, system prompts
│   └── definitions/  # YAML files only
├── agent_runtime/    # Agent runtime library (loop, compat, subagents)
├── core/             # Config, auth, MCP client, tool registry, Gitea client
├── llm/              # LLM providers, resolver, fallback, service
├── skills/           # Skill definitions (markdown)
├── jobs/             # Job definitions
├── testing/          # Evaluation framework
├── tests/            # pytest unit tests
└── mcp-servers/      # MCP microservice implementations
```

### Layer Responsibilities

| Layer | Responsibility | Out of scope |
|-------|----------------|------------|
| `api/routes/` | HTTP routing, request/response serialization, dependency injection, auth checks | Business logic, event processing, complex formatting |
| `services/` | Business logic, orchestration, validation | Direct DB queries (use repositories unless none exists yet) |
| `repositories/` | Data access, SQLAlchemy queries, returns typed domain models | Business logic, HTTP concerns |
| `domain/` | Pydantic models for API contracts | DB-specific types |
| `db/models/` | SQLAlchemy ORM definitions | API serialization logic |
| `execution/` | Agent loop orchestration, tool execution, HITL | Route definitions |
| `agents/` | YAML definitions, prompt building | Runtime logic (belongs in `execution/` or `agent_runtime/`) |

### Data Flow

One direction only:

```
Repository → Domain Model → Service → API Route
```

Routes call services. Services call repositories. Repositories return domain models.

**Exceptions:**
- External API wrappers (Gitea, Keycloak) may return `dict` or `TypedDict` because the upstream schema is versioned externally. Prefer `TypedDict` over plain `dict`.
- Pure aggregation/group-by queries (analytics dashboards) may return dynamic shapes that are hard to model as flat Pydantic classes. In these cases, define a `TypedDict` or Pydantic model with clearly named fields; avoid raw `dict`.

### Domain Model Naming

Use the **Summary / Detail** pattern:

- `SessionSummary` — for list responses (minimal fields)
- `SessionDetail` — for single-item responses (full fields)

All domain models are exported through `druppie/domain/__init__.py`. Route modules import from `druppie.domain`, never from internal module files directly.

### Code Style

- **Python version**: 3.11
- **Line length**: 100 (both `black` and `ruff`)
- **Formatter**: `black .` (run inside `druppie/`)
- **Linter**: `ruff check .` — rules `E`, `F`, `W`, `I`; ignores `E501`
- **Type hints**: Required on all public functions, method parameters, and return values. Note: no type checker (mypy/pyright) is configured yet — adoption is tracked in BACKLOG. Once added, type hints become enforceable in CI.

### Error Handling

All API errors are standardized in `druppie/api/errors.py`:

- Use `ErrorCode` enum for error codes.
- Raise `APIError` with structured messages.
- Register exception handlers in `main.py` lifespan.

### Hard Constraints (Blocking Rules)

These are enforced. A PR introducing any of these must be blocked.

1. **NO database migrations** — Update SQLAlchemy models directly. Reset the DB with:
   ```bash
   docker compose --profile reset-db run --rm reset-db
   ```
2. **Config in YAML files** — Agent definitions live in `agents/definitions/*.yaml` and `agents/system_prompts/`. Never store agent config in the database.
3. **No hardcoded secrets** — Use environment variables. No tokens, passwords, or API keys in committed `.py`, `.js`, `.yaml`, `.json`, or `.md` files.
4. **`.env` is gitignored** — The template `.env.example` contains placeholders. Never commit a real `.env`.

---

## Frontend Standards (React / Vite)

### Project Structure

```
frontend/
├── src/
│   ├── main.jsx              # Entry point (React.StrictMode)
│   ├── App.jsx               # Root: routing, auth context, layout
│   ├── index.css             # Tailwind + global styles + Prism theme
│   ├── pages/                # Route-level page components
│   │   ├── evaluations/      # Sub-components for Evaluations page
│   │   ├── Chat.jsx
│   │   ├── Dashboard.jsx
│   │   └── ...
│   ├── components/
│   │   ├── chat/             # Chat-specific components
│   │   ├── shared/           # Reusable UI (PageHeader, EmptyState, Skeleton, ...)
│   │   ├── archimate/        # ArchiMate diagram renderers
│   │   ├── NavRail.jsx
│   │   ├── ErrorBoundary.jsx
│   │   └── ...
│   ├── services/
│   │   ├── api.js            # API calls (monolithic — target: split by domain)
│   │   ├── keycloak.js       # Auth service
│   │   ├── pendingChat.js    # Module-level pending message store
│   │   └── uploadManager.js  # Module-level upload manager
│   └── utils/                # Utility helpers
└── tests/e2e/                # Playwright specs
```

### Language & Framework

- **JSX only** — No TypeScript (`.tsx`). The project uses plain JSX (`.jsx`) files.
- **React 18** with functional components and hooks.
- **Build tool**: Vite 5.
- **Routing**: React Router (configured in `App.jsx`).

### Styling

- **Tailwind CSS 3** is the only styling system.
- Custom styles go in `src/index.css` (Tailwind directives + global rules + Prism theme overrides).
- Do NOT create component-level `.css` files, CSS Modules, or styled-components.

### State Management

- **Server state**: React Query (TanStack Query).
- **Client state**: Zustand.
- Do not over-use Context for state that could live in Zustand or React Query.

### API Client Patterns

- **Target**: split `api.js` by domain into smaller service modules under `src/services/` (e.g. `sessionApi.js`, `approvalApi.js`). This refactor has not started yet — new features should create a new domain module rather than growing `api.js`.
- All API calls must handle errors and propagate meaningful messages to the UI (via Toast or ErrorBoundary).

### Linting

- **ESLint**: `npm run lint` (`.js` and `.jsx` files, `--max-warnings 0`).
- No Prettier config exists — rely on ESLint for formatting consistency.

---

## Database Standards (PostgreSQL / SQLAlchemy)

- **Engine**: PostgreSQL 15 (Alpine in Docker).
- **ORM**: SQLAlchemy models in `druppie/db/models/`.
- **Primary keys**: UUID. Use the PostgreSQL native `UUID` type. For test compatibility, the project uses a SQLite UUID shim when running on SQLite.
- **Normalization**: Prefer relational tables. **Use `Column(JSON)` only for data with genuinely variable or open-ended schema** (e.g. raw LLM payloads, tool call arguments with provider-specific extensions). When you use JSON, document the expected shape in a code comment. Do not use JSON for data with a stable, queryable schema.
- **Migrations**: Forbidden. Update models directly and reset the DB.
- **Naming**: Table names are snake_case. Model classes are PascalCase.

---

## Data Handling & Type Safety

### Raw Dicts Between Layers

Data should travel between repository, service, and route layers as typed Pydantic domain models. Define Pydantic models or `TypedDict` structures.

**Core domain** (sessions, projects, approvals, agent runs): repositories must return Pydantic models. Services must consume and return them. Routes must declare `response_model`.

**Evaluation/analytics**: prefer Pydantic models where schemas are stable. For pure aggregations that return cross-tabulated data with many nullable fields, a `TypedDict` return type is acceptable as long as the fields are documented.

**External integrations** (Gitea, Keycloak): wrap external API responses in `TypedDict` with expected fields rather than plain `dict`.

### Specific Types for MCP / Agent Memory

When working with agent memory, tool arguments, or MCP payloads, use **concrete typed structures** (`TypedDict`, Pydantic models, or `@dataclass`), not generic `dict[str, Any]`.

- **Agent memory** — Define a `Memory` Pydantic model or `TypedDict` with explicit fields.
- **Tool arguments** — Validate tool inputs with Pydantic models before execution.
- **MCP messages** — Use the project's MCP message types rather than raw dicts.

### Validation at Boundaries

- **Repository boundary** — Convert SQLAlchemy models to Pydantic models using `model_validate()` or explicit factory methods.
- **API boundary** — Use FastAPI `response_model` on routes returning domain data. Exception: pure aggregation routes where the shape varies by query parameters (these should still use `TypedDict`).
- **External data boundary** — Validate all incoming JSON/YAML from external systems (LLM responses, MCP tools, WebSocket payloads) with Pydantic before processing.

### Type Safety Rules

1. **No plain `dict` as a public interface** — Public methods must return Pydantic models or `TypedDict`. Internal helpers may use plain `dict` temporarily.
2. **No `**kwargs` abuse** — Prefer explicit named parameters. `**kwargs` is only acceptable for passthrough to external libraries.
3. **No `typing.cast` to silence the type checker** — Fix the underlying type issue or redesign the interface.
4. **`# type: ignore` / `# noqa`** — Acceptable for known SQLAlchemy idiom false positives and template unused imports. Do not add them for new code without justification.

---

## Security Standards

### Authentication

- **All routes that read or mutate project-scoped data** must validate JWT tokens via FastAPI dependency injection (`deps.py`).
- **Truly public endpoints** (health checks, Swagger docs, public status pages) may skip auth.
- **Internal read-only aggregations** (cross-project analytics that do not expose individual data) may skip auth if the data is not sensitive. Revisit this if the endpoint begins returning project-scoped details.
- **Token extraction** happens in `deps.py`, never duplicated in individual route modules.
- **Roles** are enforced in routes using `RequireRole(...)` dependencies. Service methods should receive roles from the route via parameters, not fetch them from `deps.py` directly.

### Authorization & MCP Permissions

- MCP tool permissions are role-based and configured in Keycloak (`iac/users.yaml` / `iac/realm.yaml`).
- The backend reads MCP permissions from the JWT token claims, not from a separate request.
- **Approval workflows** (deployment, codeChange, complianceChange) must be respected in service logic. Do not short-circuit or bypass approvals.

### Input Validation

- **Route level** — Use FastAPI path/query/body parameter models (Pydantic) for all user input. Do not manually parse `request.json()`.
- **Service level** — Re-validate business-critical inputs that skip the API (e.g., internal calls, agent-generated payloads).
- **SQL Injection** — Never use string formatting or f-strings for SQL. Use SQLAlchemy ORM queries exclusively. Raw SQL is forbidden unless in a controlled migration or analytics script outside the main app.

### Secrets & Credentials

- **No hardcoded secrets** in `.py`, `.js`, `.yaml`, `.json`, or `.md` files. Use environment variables.
- **No secrets in logs** — Sanitize logs before writing tokens, passwords, or API keys.
- **`.env` is gitignored** — The template `.env.example` contains placeholder/weak defaults. Never commit a real `.env`.

### Agent Tool Security

- **Sandbox** — Agent code runs inside isolated sysbox containers. Never allow agents to access the host filesystem or Docker socket directly.
- **Tool scoping** — The `ToolExecutor` filters available tools per agent run. Never grant broader tool access than the agent definition specifies.
- **Human-in-the-Loop (HITL)** — Sensitive tools (code changes, deployments) require explicit human approval. Do not auto-approve in production.

---

## Agent Execution & Async Patterns

### Async / Await Conventions

- **The entire backend is async** — FastAPI with async SQLAlchemy (or sync DB in threadpool depending on config). Services and repositories should be `async def` where I/O occurs.
- **No blocking calls in async paths** — Use `await` for DB, HTTP, and file operations. Offload CPU-heavy work to a threadpool if needed.
- **Context propagation** — Preserve request context (user, session, trace ID) across async boundaries using `contextvars` or FastAPI `Request` state.

### Agent Runtime Patterns

The agent loop lives in `druppie/execution/` and `druppie/agent_runtime/` with the following conventions:

- **Event-driven** — The loop emits events (`EventEmitter`) for every state change. UI consumes events via SSE/WebSocket.
- **Tool filtering** — `ToolExecutor` restricts tools per agent run. New tools must be registered in `core/tool_registry.py` or via MCP config.
- **Resume / Retry** — Agent runs support resuming from a checkpoint. Never mutate historical run state in-place; create new runs for retries.
- **State machine** — Agent runs follow a status lifecycle (`pending` → `running` → `done` / `error` / `cancelled`). Status transitions must be explicit, not implicit side effects.

### MCP Server Integration

- **MCP servers** are microservices in `druppie/mcp-servers/`. Each exposes tools via HTTP.
- **Connection lifecycle** — MCP connections are established per-session and closed cleanly. Do not leak connections.
- **Tool schemas** — Every MCP tool exposes a JSON schema. The agent runtime validates tool calls against schemas before execution.
- **Registration** — New MCP modules must include a `MODULE.yaml` manifest and be wired into `docker-compose.yml` with a profile.

---

## Testing Standards

### Backend Unit Tests (pytest)

| Item | Standard |
|------|----------|
| Location | `druppie/tests/` and subdirectories |
| Naming | `test_*.py` exclusively |
| Async tests | Use `@pytest.mark.asyncio` |
| Fixtures | Shared fixtures in `druppie/tests/` subdirectories |
| Mocking | `unittest.mock.MagicMock` / `AsyncMock`. `MockLLM` and `MockToolProvider` from conftest. |
| DB tests | In-memory SQLite with UUID shim |
| Command | `cd druppie && pytest` |

### Frontend E2E Tests (Playwright)

| Item | Standard |
|------|----------|
| Location | `frontend/tests/e2e/` |
| Naming | `*.spec.js` |
| Config | `frontend/playwright.config.js` |
| Run | `npm run test:e2e` |
| Fixed-delay waits | **NEVER use `page.waitForTimeout(N)`** — it pauses execution for a fixed duration regardless of page state, making tests slow and flaky. Use `waitForSelector`, `waitForResponse`, or `waitForURL` (waits until condition is met, then proceeds immediately). **Test-level timeouts** (e.g. Playwright config `timeout`, `test.setTimeout()`) are safety rails and are required — they are not the same thing. |
| Workers | `workers: 1`, `fullyParallel: false` |

### Evaluation Tests

- Custom framework in `druppie/testing/` (NOT pytest):
  - `testing/tools/` — YAML tool test definitions.
  - `testing/agents/` — Agent tests with real LLM execution.
  - `testing/checks/` — Reusable assertion bundles.
  - `testing/profiles/` — HITL simulator and judge LLM profiles.
- Run via API: `POST /api/evaluations/run-tests`.

### Coverage Expectation

There is no formal coverage target. PR reviewers should flag:

- New backend logic without corresponding `test_*.py` additions.
- New frontend user flows without e2e coverage.
- PRs that delete failing tests instead of fixing them.

---

## Docker & Infrastructure Standards

### docker-compose.yml

- Single file. Uses **profiles** to group services.
- Common profiles: `dev`, `prod`, `infra`, `init`, `reset-db`, `reset-hard`, `nuke`, `reset-cache`.

### Base Images

| Service | Base Image |
|---------|------------|
| Backend | `python:3.11-slim` |
| Frontend | `node:20-alpine` |
| Database | `postgres:15-alpine` |
| Keycloak | `quay.io/keycloak/keycloak:24.0` |
| Gitea | `gitea/gitea:1.21` |

**Rule**: Pin external image tags explicitly. Do NOT use `latest`.

**Exception**: Custom build images (e.g. sandbox) may use `:latest` via environment variable fallback in `docker-compose.yml` because the image is rebuilt locally during development.

### Dockerfile Patterns

- **Backend**: Use pip cache mount for faster rebuilds:
  ```dockerfile
  RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
  ```
- **Frontend**: Multi-stage build (builder stage → runtime stage with `serve`).
- **Dev frontend**: `Dockerfile.dev` runs `npm install && npm run dev`.

### Environment Variables

- Naming: `UPPER_SNAKE_CASE` with domain prefixes:
  - `DRUPPIE_*` — application
  - `KEYCLOAK_*` — Keycloak
  - `GITEA_*` — Gitea
  - `MCP_*` — MCP servers
  - `ZAI_*`, `DEEPINFRA_*`, etc. — LLM providers
- Public URLs use `_PUBLIC_URL` suffix.
- Ports use `_PORT` suffix.
- `.env` is gitignored. `.env.example` is the template.

---

## CI/CD & Git Standards

### GitHub Actions

- `.github/workflows/build-and-deploy.yml` — Self-hosted ARC runner inside K3s:
  - Builds Docker images with BuildKit.
  - Pushes to internal registry then syncs to pull registry.
  - Deploys via Helm to K3s cluster.
  - PR builds tag `pr-<number>` (no deploy).
- `.github/workflows/sync-main-to-colab-dev.yml` — Auto-syncs `main` merges back to `colab-dev`.

### Git Configuration

- `.gitattributes`: Forces LF line endings for `.sh`, `Dockerfile*`, `.py`, `.yaml`, `.yml`, `.json`.
- `.gitignore`: Comprehensive (Python, Node, IDE, secrets, Helm, testing artifacts, Docker volumes).
- No pre-commit hooks configured.

---

## Documentation Standards

When making **significant changes**, update the corresponding doc:

| Change Type | Document |
|-------------|----------|
| New feature or feature change | `docs/FEATURES.md` |
| Bug, technical debt, improvement | `docs/BACKLOG.md` |
| Architecture or technical change | `docs/TECHNICAL.md` |

Additional reference docs exist under `docs/` — update them when relevant.

### Agent Definitions

- Stored as YAML in `druppie/agents/definitions/*.yaml`.
- System prompts in `druppie/agents/system_prompts/`.
- **Never store agent configuration in the database.**

---

## AI Review Agent — Quick Checklist

Use this checklist when reviewing a Pull Request. Flag any item that fails.

### Architecture & Structure
- [ ] Backend changes follow layer separation: routes thin, logic in services, data access in repositories.
- [ ] Domain models use Summary/Detail naming where applicable.
- [ ] New domain models exported via `druppie/domain/__init__.py`.
- [ ] Agent definitions added as YAML in `agents/definitions/`, not DB migrations or code-in-DB.
- [ ] No new JSON columns in DB models **unless** the data has a genuinely variable schema. If JSON is used, the expected shape is documented.
- [ ] No Alembic/database migration files introduced.
- [ ] No new backward-compat aliases introduced. Existing aliases may be kept during deprecation.
- [ ] **New code in core domain** (sessions/projects/approvals): repositories return Pydantic models, not plain dicts.
- [ ] **New code in evaluation/analytics**: aggregates should use Pydantic models or TypedDict, not raw `dict`.
- [ ] Agent memory / MCP payloads use typed structures (Pydantic, TypedDict).

### Code Quality
- [ ] Python type hints present on new functions and methods.
- [ ] No `typing.cast` to bypass type safety.
- [ ] Black formatting passes (`black .` inside `druppie/`).
- [ ] Ruff linting passes (`ruff check .` inside `druppie/`).
- [ ] Line length does not exceed 100.
- [ ] No empty `except:` or `catch(e) {}` blocks.
- [ ] ESLint passes (`npm run lint` in `frontend/`).
- [ ] Dead code removed: no unused imports, variables, functions, or commented-out blocks left behind by the feature branch.

### Frontend
- [ ] New components use `.jsx` (not `.tsx` — no TypeScript in this project).
- [ ] Styling uses Tailwind CSS classes only (no new `.css` files for components).
- [ ] API calls are in `src/services/` (prefer splitting by domain rather than adding to monolithic `api.js`).
- [ ] No `page.waitForTimeout()` in new Playwright tests.

### Security
- [ ] New routes that handle sensitive/project-scoped data enforce auth via FastAPI dependencies.
- [ ] Role checks use dependency injection where possible; service-level role filtering is acceptable for existing subsystems.
- [ ] No hardcoded secrets in committed code.
- [ ] User input is validated with Pydantic models at route boundaries.
- [ ] No f-string SQL or raw SQL concatenation in application code.
- [ ] MCP tool permissions are respected; no short-circuiting of approval workflows.

### Agent Execution & Async
- [ ] Async services/repositories use `await` for I/O, no blocking calls in async paths.
- [ ] New tools registered in `core/tool_registry.py` or MCP config.
- [ ] MCP connections are established and closed cleanly per session.
- [ ] Agent run state transitions are explicit, not implicit side effects.

### Testing
- [ ] New backend logic has corresponding `test_*.py` file or additions.
- [ ] New frontend user flows have Playwright e2e coverage or justification.
- [ ] No failing tests deleted to make CI green.
- [ ] Mocking uses `MagicMock` / `AsyncMock`, not real external calls in unit tests.

### Infrastructure
- [ ] Docker image tags are pinned (not `latest`). Custom build images are exempt.
- [ ] New env vars follow `UPPER_SNAKE_CASE` with domain prefix.
- [ ] `.env.example` updated if new env vars are introduced.
- [ ] No hardcoded secrets in committed files.
- [ ] `.gitignore` covers new generated artifacts if applicable.

### Documentation
- [ ] `docs/FEATURES.md` updated if a new feature is added.
- [ ] `docs/TECHNICAL.md` updated if architecture changes.
- [ ] `docs/BACKLOG.md` updated if technical debt or bugs are introduced.

---

## Anti-Patterns & Common Mistakes

| Anti-Pattern | Why It's Wrong | What To Do Instead |
|--------------|----------------|--------------------|
| `page.waitForTimeout(2000)` in Playwright | Fixed-duration sleep that pauses test for N ms regardless of DOM state. Slow, flaky across environments. | Use `waitForSelector`, `waitForResponse`, or `waitForURL` (wait until condition, proceed immediately). Test-level timeouts (config `timeout`) are still required as a safety rail. |
| Monolithic `api.js` | Hard to maintain, prone to merge conflicts. | Split by domain into `sessionApi.js`, `approvalApi.js`, etc. |
| Adding business logic to `api/routes/` | Violates separation of concerns. | Move logic to `services/`. |
| Direct SQLAlchemy queries outside `repositories/` | Leaks data access into business/API layers. | Create or use a repository method. |
| JSON column for data with stable schema | Relational tables are more queryable, type-safe, and support foreign keys. | Normalize into separate tables with foreign keys. |
| Database migration file | Project policy is model-then-reset. | Update SQLAlchemy model, then reset the DB. |
| Agent config stored in DB | Violates YAML-only config policy. | Add/modify `agents/definitions/*.yaml`. |
| Hardcoded secrets in committed YAML/JS/Python | Security risk, easy to leak. | Use environment variables injected at runtime. |
| Deleting a failing test to pass CI | Hides bugs, destroys coverage. | Fix the underlying code or mock the dependency. |
| No tests for new backend service | Untrusted code. | Add `test_*.py` covering success and error paths. |
| Large `if/elif` chains in Python | Hard to extend and test. | Use strategy pattern, registry dict, or polymorphism. |
| Suppressing type errors to avoid fixing them | Erodes type safety over time. | Fix the types or redesign the interface. |
| **Returning raw `dict` from a repository (core domain)** | Destroys autocomplete, bypasses static analysis, allows silent key errors. | Return Pydantic domain models via `model_validate()`. |
| **Returning raw `dict` in evaluation/analytics** | Untyped data allows field drift and runtime crashes. | Define `TypedDict` or Pydantic model with explicit fields. |
| **Passing `**kwargs` through service boundaries** | Hides required parameters from the type checker. | Use explicit named parameters. |
| **Inline `if user.role == "admin":` in service methods** | Auth logic belongs in the route layer via dependencies. | Use `RequireRole(...)` FastAPI dependencies in `api/`. |
| **f-string SQL or raw string concatenation** | SQL injection vulnerability. | Use SQLAlchemy ORM expressions exclusively. |
| **Blocking calls (`requests.get`, `open(...)`) inside `async def`** | Blocks the event loop, degrades throughput. | Use async equivalents (`httpx.AsyncClient`, `aiofiles`). |
| **Leaking MCP connections** | Resource exhaustion and stale state. | Open per session, close in `finally` / context manager. |
| **Dead code in a PR** — unused imports, functions, variables, commented-out blocks | Creates noise, hides intent, increases review cost. | Remove before PR. Use `ruff check .` (rules F401, F811, F841) and review diff. |
| **Auto-approving deployment/codeChange tools** | Bypasses governance and HITL policy. | Require explicit human approval via approval workflow. |
