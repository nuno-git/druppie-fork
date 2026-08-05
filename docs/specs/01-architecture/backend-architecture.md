# Backend Architecture

The `druppie/` Python package implements **Clean Architecture** with five concentric layers. Each layer imports only from layers below it.

```
                ┌──────────────────────────────┐
                │  api/routes/   (HTTP/FastAPI)│   thin: request → response
                ├──────────────────────────────┤
                │  services/     (orchestration)│   business logic + authz
                ├──────────────────────────────┤
                │  repositories/ (data access) │   queries, to_summary/detail
                ├──────────────────────────────┤
                │  domain/       (Pydantic)    │   in-memory models
                ├──────────────────────────────┤
                │  db/models/    (SQLAlchemy)  │   persistence
                └──────────────────────────────┘
```

### Orthogonal layers

- `execution/` — agent orchestrator + tool executor + HTTP client for MCP calls. Imported by routes that spawn background tasks (`chat.py`, `approvals.py`, `sessions.py`, `questions.py`).
- `core/` — cross-cutting infra: `auth.py`, `mcp_config.py`, `tool_registry.py`, `gitea.py`, `background_tasks.py`.
- `llm/` — provider-agnostic LLM calling (LiteLLM wrapper, fallback provider chain, resolver).
- `agents/` — YAML loader + in-process agent runtime (LLM loop, prompt builder, message history).
- `testing/` — evaluation harness (imports everything, exposes CLI + `EvaluationService`).

## Layer contracts

### Routes layer (`druppie/api/routes/*.py`)

Responsibility: HTTP only. Validate request with Pydantic, invoke a single service method, wrap result in a response model, map `NotFoundError`/`AuthorizationError`/`ConflictError`/`ValidationError` → `HTTPException` with the right status code.

Must NOT: touch `db/models/`, build SQLAlchemy queries, call MCP servers directly.

Pattern:
```python
@router.post("/{session_id}/resume")
async def resume_session(
    session_id: UUID,
    session_service: SessionService = Depends(get_session_service),
    current_user: User = Depends(get_current_user),
):
    try:
        session = session_service.lock_for_resume(session_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e))
    background_tasks.add_task(_resume_background, session.id)
    return {"session_id": session.id, "status": session.status}
```

### Services layer (`druppie/services/*.py`)

Responsibility: transactional business logic, authorization decisions, orchestration across repositories. Receives domain models, returns domain models.

Every service takes a SQLAlchemy session in its constructor (provided via `Depends(get_db)` in routes) and a set of repositories. Services never hold state across requests.

Key pattern — **row-level locking** for state transitions:
```python
def lock_for_retry(self, session_id: UUID) -> SessionDetail:
    session = self.session_repo.get_by_id_for_update(session_id)  # SELECT ... FOR UPDATE
    if session.status == SessionStatus.ACTIVE:
        raise ConflictError("Session already active")
    session.status = SessionStatus.ACTIVE
    self.session_repo.commit()
    return self.session_repo.get_detail(session_id)
```

### Repositories layer (`druppie/repositories/*.py`)

Responsibility: data access. Build queries, eager-load relationships, convert ORM models → domain models via private `_to_summary()` / `_to_detail()` methods.

Every repository has a base `BaseRepository` exposing `db`, `commit()`, `rollback()`.

Queries to note:
- `SessionRepository._build_timeline()` merges `messages` + `agent_runs` chronologically into `TimelineEntry` objects the frontend consumes as a single feed.
- `ApprovalRepository.get_pending_for_roles()` filters on `required_role IN user_roles OR (required_role = SESSION_OWNER AND session.user_id = current_user)`.
- `ProjectRepository.get_detail()` aggregates token usage via `SUM(total_tokens)` across child sessions.

### Domain layer (`druppie/domain/*.py`)

Responsibility: Pydantic models used across layers. No DB, no network, pure data shapes.

Pattern: **Summary / Detail split**.
- `XxxSummary` — fields shown in list views (id, name, status, created_at). Cheap.
- `XxxDetail` — extends Summary with heavy fields (timeline, LLM call traces, children). Used in detail endpoints.

Each domain file exports both shapes and any enums used (`SessionStatus`, `AgentRunStatus`, etc. in `common.py`). All exports flow through `druppie/domain/__init__.py`.

### DB models layer (`druppie/db/models/*.py`)

Responsibility: SQLAlchemy 2.0 ORM. One file per entity, one `Base` in `base.py`.

Rules (CLAUDE.md):
- **No migrations.** Change the class, reset the DB.
- **No JSON/JSONB for queryable fields.** JSON is permitted only for `arguments`, `result`, `request_messages`, `response_tool_calls`, `choices`, `selected_indices` — these are opaque payloads never indexed.
- **UUID primary keys** everywhere (using `uuid.uuid4` default).
- **CASCADE on child tables** so deleting a session takes everything with it.

## Dependency injection

Dependencies are wired in `druppie/api/deps.py`. Every route uses `Depends(…)`:

| Dependency | Returns | Purpose |
|------------|---------|---------|
| `get_db` | `Session` | SQLAlchemy session per request |
| `get_current_user` | `User` | Decode JWT, upsert user in DB, return domain model |
| `get_optional_user` | `User \| None` | For endpoints that work unauthenticated |
| `verify_internal_api_key` | `None` | HMAC check for MCP → backend callbacks |
| `require_admin` | `User` | Shortcut; raises 403 if not admin |
| `require_role(role)` | `callable` | Factory; returns a Depends that checks role |
| `get_session_service` etc. | Service | Constructs a service with its repos |

## Error handling

`druppie/api/errors.py` defines four exception classes routes catch:

- `NotFoundError(entity, id)` → 404
- `AuthorizationError(message)` → 403
- `ConflictError(message)` → 409 (state transition invalid)
- `ValidationError(message, field)` → 422

Services raise these; routes translate. Unhandled exceptions → 500 via FastAPI default handler with full traceback logged.

## Startup lifecycle

`druppie/api/main.py:88` — async lifespan handler runs on app startup and shutdown:

1. Connect to DB (`engine` in `druppie/db/database.py`).
2. `Base.metadata.create_all()` — create missing tables (idempotent).
3. **Recover zombie sessions** — any `Session.status == ACTIVE` with no live task → `PAUSED_CRASHED`.
4. **Recover orphaned batch runs** — `TestBatchRun.status == running` older than N minutes → `failed`.
5. **Clean up orphaned Gitea sandbox users** — `gitea.delete_sandbox_users()`.
6. Initialize `ToolRegistry` — fetch `tools/list` from every MCP in `mcp_config.yaml`.
7. Start `sandbox_watchdog_loop()` — polls every 5 min for stuck `WAITING_SANDBOX` tool calls older than `SANDBOX_TIMEOUT_MINUTES`.
8. Yield (app runs).
9. Shutdown: cancel watchdog, close DB pool, 30s graceful timeout.

## Concurrency model

- **Per-request SQLAlchemy session** — scoped via `Depends(get_db)`, closed by FastAPI.
- **Background tasks** — `create_session_task()` / `run_session_task()` in `druppie/core/background_tasks.py` wrap agent runs in a fresh DB session so they outlive the HTTP request.
- **Per-session lock** — an in-process concurrency guard prevents two background tasks from driving the same session simultaneously (used by approval, question, resume, retry flows).
- **No multiprocessing** — Uvicorn runs single-process with the asyncio loop; horizontal scaling would require externalizing the lock and zombie recovery via a shared store (not implemented).

## Package boundaries (import rules)

- `domain/` imports nothing from `druppie/` except `common.py`.
- `db/` imports nothing except `sqlalchemy`.
- `repositories/` imports `db/`, `domain/`.
- `services/` imports `repositories/`, `domain/`, `core/`.
- `api/` imports `services/`, `domain/`, `execution/` (for background tasks).
- `execution/` imports `core/`, `llm/`, `agents/`, `db/` (directly, because background tasks open their own session).
- `testing/` imports everything.

Violations surface as circular import errors; there is no linter enforcing the rule but PRs are reviewed against it.
