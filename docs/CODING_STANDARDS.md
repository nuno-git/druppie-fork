# Druppie Coding Standards (Current State)

This document describes how the Druppie codebase **actually works today**. It is the single source of truth for current conventions, patterns, and layer responsibilities.

For the aspirational target state, see [`CODING_STANDARDS_IDEAL.md`](CODING_STANDARDS_IDEAL.md).

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
├── api/              # FastAPI routes — some contain event extraction/formatting
│   ├── main.py       # App factory, lifespan, router registration
│   ├── deps.py       # Dependency injection (repos, services, auth)
│   ├── errors.py     # Standardized error handling
│   └── routes/       # Route modules
├── services/         # Business logic layer — also does direct DB queries where needed
├── repositories/     # Data access layer — core domain returns Pydantic models; evaluation/analytics returns raw dicts
├── domain/           # Pydantic models
├── db/
│   ├── models/       # SQLAlchemy ORM models — some use Column(JSON) for dynamic data
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
├── tests/            # pytest unit tests (agent_runtime is well covered; services not)
└── mcp-servers/      # MCP microservice implementations
```

### Layer Responsibilities

These reflect actual patterns in the codebase. New code should follow the "Preferred" column but it is okay to match existing patterns when working in a subsystem that already deviates.

| Layer | What It Actually Does | Preferred Direction |
|-------|----------------------|---------------------|
| `api/routes/` | HTTP routing, request/response serialization, auth checks. Some routes contain significant event extraction, formatting, and direct `db.query()` calls for simple lookups. | Keep routes thin: orchestration only, move event processing and complex formatting to `services/`. |
| `services/` | Business logic, orchestration, validation. Also performs direct DB queries via `repo.db.query(...)` where repository methods do not exist or where coordinated cross-table access is needed. | Prefer using repository methods for data access; add new repository methods instead of `repo.db.query()` in services. |
| `repositories/` | Data access, SQLAlchemy queries. Core domain (sessions, projects, approvals) returns typed Pydantic models. Evaluation/analytics returns raw `dict` / `list[dict]`. | New repositories should return Pydantic domain models. Evaluation/analytics is an acknowledged exception. |
| `domain/` | Pydantic models for API contracts. `LLMMessage.tool_calls` uses `list[dict[str, Any]]` because tool call schemas are open-ended. | Use Pydantic models wherever the schema is fixed. `dict[str, Any]` is acceptable when the schema is dynamic. |
| `db/models/` | SQLAlchemy ORM definitions. Several models use `Column(JSON)` for data with variable schema (LLM messages, tool arguments, question choices). | Normalize into relational tables when the schema is stable and queryable. |
| `execution/` | Agent loop orchestration, tool execution, HITL. Also manages DB sessions per tool call. | Keep execution logic out of `routes/` and `agents/`. |
| `agents/` | YAML definitions, prompt building, runtime wrappers. Some files contain agent loop logic; this is historical. | New runtime logic belongs in `execution/` or `agent_runtime/`. |

### Data Flow

One direction only (the intended architecture):

```
Repository → Domain Model → Service → API Route
```

In practice:
- **Core domain** follows this (sessions, projects, approvals, agent runs).
- **Evaluation/analytics** does not — repositories return raw `dict`, services pass them through, and routes return them without `response_model`.
- **Auth/Gitea** return `dict[str, Any]` because they wrap dynamic external API responses.

### Domain Model Naming

Use the **Summary / Detail** pattern:

- `SessionSummary` — for list responses (minimal fields)
- `SessionDetail` — for single-item responses (full fields)

All domain models are exported through `druppie/domain/__init__.py`. Route modules import from `druppie.domain`, never from internal module files directly.

**Backward compatibility aliases** exist in the domain module. These are preserved to avoid breaking downstream consumers. New code should use the current names.

### Code Style

- **Python version**: 3.11
- **Line length**: 100 (both `black` and `ruff`)
- **Formatter**: `black .` (run inside `druppie/`)
- **Linter**: `ruff check .` — rules `E`, `F`, `W`, `I`; ignores `E501`
- **Type hints**: Mandatory. Functions, method parameters, and return values must be annotated.

### Error Handling

All API errors are standardized in `druppie/api/errors.py`:

- Use `ErrorCode` enum for error codes.
- Raise `APIError` with structured messages.
- Register exception handlers in `main.py` lifespan.

### Hard Constraints (Blocking Rules for New Code)

These are rules that are actually enforced. A PR introducing any of these must be blocked.

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
│   │   ├── api.js            # API calls (monolithic)
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

- `api.js` currently holds all API calls. **New features should split by domain** into smaller service modules under `src/services/`, e.g. `sessionApi.js`, `approvalApi.js`.
- All API calls must handle errors and propagate meaningful messages to the UI (via Toast or ErrorBoundary).

### Linting

- **ESLint**: `npm run lint` (`.js` and `.jsx` files, `--max-warnings 0`).
- No Prettier config exists — rely on ESLint for formatting consistency.

---

## Database Standards (PostgreSQL / SQLAlchemy)

- **Engine**: PostgreSQL 15 (Alpine in Docker).
- **ORM**: SQLAlchemy models in `druppie/db/models/`.
- **Primary keys**: UUID. Use the PostgreSQL native `UUID` type. For test compatibility, the project uses a SQLite UUID shim when running on SQLite.
- **Normalization**: Relational tables are preferred. However, `Column(JSON)` is used for data with variable or open-ended schema:
  - `llm_call.request_messages` / `response_tool_calls` / `raw_request` / `raw_response`
  - `tool_call.arguments`
  - `approval.arguments`
  - `question.choices`
  When adding a JSON column, document the expected shape in a code comment.
- **Migrations**: Forbidden. Update models directly and reset the DB.
- **Naming**: Table names are snake_case. Model classes are PascalCase.

---

## Data Handling & Type Safety

### Raw Dicts Between Layers

**Core domain** (sessions, projects, approvals, agent runs): repositories return Pydantic models, services consume and return them, routes use `response_model`. This is the pattern to follow for new code.

**Evaluation/analytics** (test runs, benchmarks): repositories return raw `dict` / `list[dict]`. Services pass them through. Routes return them directly. This is acknowledged existing practice; new evaluation code should prefer Pydantic models where the schema is stable.

**External integrations** (Gitea, Keycloak JWKS): returning `dict[str, Any]` is acceptable because the upstream API schema is dynamic and versioned externally.

### Specific Types for MCP / Agent Memory

When working with agent memory, tool arguments, or MCP payloads:

- Use **concrete typed structures** (`TypedDict`, Pydantic models, or `@dataclass`) where the schema is fixed.
- `dict[str, Any]` is acceptable for open-ended structures (e.g. dynamic tool call arguments, raw LLM payloads).

### Validation at Boundaries

- **Repository boundary** — Convert SQLAlchemy models to Pydantic models using `model_validate()` or explicit factory methods.
- **API boundary** — Use FastAPI `response_model` on routes returning core domain data. Evaluation/analytics routes currently do not use `response_model`.
- **External data boundary** — Validate all incoming JSON/YAML from external systems (LLM responses, MCP tools, WebSocket payloads) with Pydantic before processing.

### Type Safety Rules

1. **No `typing.cast` to silence the type checker** — Fix the underlying type issue.
2. **`**kwargs`** — Prefer explicit named parameters. One existing exception: `evaluation_repository.update_batch_run(self, batch_id: str, **kwargs)`.
3. **`# type: ignore` / `# noqa`** — Acceptable for known idioms (e.g. SQLAlchemy boolean comparison matching) and template unused imports. Do not add them for new code without justification.

---

## Security Standards

### Authentication

- **Sensitive routes** (sessions, chat, approvals, deployments) validate JWT tokens via FastAPI dependency injection (`deps.py`, `get_current_user`).
- **Read-only / internal analytics routes** (evaluations, analytics, workspace files) do not require auth. This is current practice but should be revisited if those endpoints expose project-scoped data.
- **Token extraction** happens in `deps.py`, never duplicated in individual route modules.
- **Roles** are enforced in routes using `RequireRole(...)` dependencies. Some services also perform role filtering internally (e.g. checking for the `"admin"` role or session-owner role). New code should prefer route-level `RequireRole` where possible.

### Authorization & MCP Permissions

- MCP tool permissions are role-based and configured in Keycloak (`iac/users.yaml` / `iac/realm.yaml`).
- The backend reads MCP permissions from the JWT token claims, not from a separate request.
- **Approval workflows** (deployment, codeChange, complianceChange) must be respected in service logic. Do not short-circuit or bypass approvals.

### Input Validation

- **Route level** — Use FastAPI path/query/body parameter models (Pydantic) for all user input. Do not manually parse `request.json()`.
- **Service level** — Re-validate business-critical inputs that skip the API (e.g., internal calls, agent-generated payloads).
- **SQL Injection** — Never use string formatting or f-strings for SQL. Use SQLAlchemy ORM queries exclusively. Raw SQL is acceptable only in controlled postgres-native operations and MCP server microservices.

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

- **FastAPI routes are async** — use `await` for DB, HTTP, and file operations.
- **No blocking calls in async paths** — `requests.get`, `time.sleep`, `open(...)` inside `async def` without offloading blocks the event loop. Use `httpx.AsyncClient`, `aiofiles`, or `asyncio.to_thread`.
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

**Coverage reality**: `agent_runtime/` has good test coverage. Most `services/` modules (approval, session, job, revert, etc.) lack dedicated `test_*.py` files. New services should include tests.

### Frontend E2E Tests (Playwright)

| Item | Standard |
|------|----------|
| Location | `frontend/tests/e2e/` |
| Naming | `*.spec.js` |
| Config | `frontend/playwright.config.js` |
| Run | `npm run test:e2e` |
| Fixed-delay waits | **NEVER use `page.waitForTimeout(N)`** — it pauses execution for a fixed duration regardless of page state, making tests slow and flaky. Use `waitForSelector`, `waitForResponse`, or `waitForURL` (waits until condition is met, then proceeds immediately). `waitForTimeout` exists in some existing tests but should not be added to new ones. **Test-level timeouts** (e.g. Playwright config `timeout`, `test.setTimeout()`) are safety rails and are required — they are not the same thing. |
| Workers | `workers: 1`, `fullyParallel: false` |

### Evaluation Tests

- Custom framework in `druppie/testing/` (NOT pytest):
  - `testing/tools/` — ~80 YAML tool test definitions.
  - `testing/agents/` — Agent tests with real LLM execution.
  - `testing/checks/` — Reusable assertion bundles.
  - `testing/profiles/` — HITL simulator and judge LLM profiles.
- Run via API: `POST /api/evaluations/run-tests`.

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

**Exception**: Custom build images (e.g. sandbox) use `:latest` via environment variable fallback in `docker-compose.yml` because the image is rebuilt locally during development.

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
  - Builds 12 Docker images with BuildKit.
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
- [ ] New backend changes follow layer separation: routes thin, logic in services, data access in repositories.
- [ ] Domain models use Summary/Detail naming where applicable.
- [ ] New domain models exported via `druppie/domain/__init__.py`.
- [ ] Agent definitions added as YAML in `agents/definitions/`, not DB migrations or code-in-DB.
- [ ] No Alembic/database migration files introduced.
- [ ] New code in core domain (sessions/projects/approvals): repositories return Pydantic models, not raw dicts.
- [ ] Agent memory / MCP payloads use typed structures (Pydantic, TypedDict) where schema is fixed.

### Code Quality
- [ ] Python type hints present on new functions and methods.
- [ ] No `typing.cast` to bypass type safety.
- [ ] Black formatting passes (`black .` inside `druppie/`).
- [ ] Ruff linting passes (`ruff check .` inside `druppie/`).
- [ ] Line length does not exceed 100.
- [ ] No empty `except:` or `catch(e) {}` blocks.
- [ ] ESLint passes (`npm run lint` in `frontend/`).
- [ ] Dead code removed: no unused imports, variables, functions, or commented-out blocks.

### Frontend
- [ ] New components use `.jsx` (not `.tsx` — no TypeScript in this project).
- [ ] Styling uses Tailwind CSS classes only (no new `.css` files for components).
- [ ] API calls are in `src/services/` (prefer splitting by domain rather than adding to monolithic `api.js`).
- [ ] No `page.waitForTimeout()` in new Playwright tests.

### Security
- [ ] New routes that handle sensitive data enforce auth via FastAPI dependencies.
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
| Database migration file | Project policy is model-then-reset. | Update SQLAlchemy model, then reset the DB. |
| Agent config stored in DB | Violates YAML-only config policy. | Add/modify `agents/definitions/*.yaml`. |
| Hardcoded secrets in committed YAML/JS/Python | Security risk, easy to leak. | Use environment variables injected at runtime. |
| Deleting a failing test to pass CI | Hides bugs, destroys coverage. | Fix the underlying code or mock the dependency. |
| No tests for new backend service | Untrusted code. | Add `test_*.py` covering success and error paths. |
| Large `if/elif` chains in Python | Hard to extend and test. | Use strategy pattern, registry dict, or polymorphism. |
| Suppressing type errors to avoid fixing them | Erodes type safety over time. | Fix the types or redesign the interface. |
| **Returning raw `dict` from a repository (core domain)** | Destroys autocomplete, bypasses static analysis, allows silent key errors. | Return Pydantic domain models via `model_validate()`. |
| **Using `dict[str, Any]` for agent memory / MCP data** | Untyped data allows field drift and runtime crashes. | Define `TypedDict` or Pydantic model with explicit fields. |
| **Passing `**kwargs` through service boundaries** | Hides required parameters from the type checker. | Use explicit named parameters. |
| **f-string SQL or raw string concatenation** | SQL injection vulnerability. | Use SQLAlchemy ORM expressions exclusively. |
| **Blocking calls (`requests.get`, `open(...)`) inside `async def`** | Blocks the event loop, degrades throughput. | Use async equivalents (`httpx.AsyncClient`, `aiofiles`). |
| **Leaking MCP connections** | Resource exhaustion and stale state. | Open per session, close in `finally` / context manager. |
| **Dead code in a PR** — unused imports, functions, variables, commented-out blocks | Creates noise, hides intent, increases review cost. | Remove before PR. Use `ruff check .` (rules F401, F811, F841) and review diff. |
| **Auto-approving deployment/codeChange tools** | Bypasses governance and HITL policy. | Require explicit human approval via approval workflow. |
