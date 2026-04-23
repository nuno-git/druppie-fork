# Startup & Recovery

The `@asynccontextmanager` lifespan handler in `druppie/api/main.py` (`lifespan(app)`) runs on FastAPI startup and shutdown; the helpers `_recover_zombie_sessions` and `_recover_orphaned_batch_runs` are defined earlier in the same module.

## Startup steps

1. **Connect to DB** — `engine` is a module-level SQLAlchemy engine in `druppie/db/database.py`.
   - PostgreSQL: `pool_size=20, max_overflow=30, pool_pre_ping=True`.
   - SQLite (test mode): `check_same_thread=False`.

2. **Create tables** — `Base.metadata.create_all(bind=engine)` is idempotent. Missing tables get created; existing tables are left alone (no ALTERs).

3. **Recover zombie sessions** (`_recover_zombie_sessions` called from the lifespan handler). At startup no background tasks exist, so any `ACTIVE` session is a zombie. The recovery (`ExecutionRepository.recover_zombie_sessions`, `druppie/repositories/execution_repository.py:889`):
   - Runs over every `ACTIVE` session.
   - Any `RUNNING` agent run on that session is unconditionally flipped to `PAUSED_USER` (no retry threshold).
   - Parent session → `PAUSED_CRASHED` if it had RUNNING runs, otherwise `PAUSED`.
   - Also rescues `FAILED` sessions that still have orphaned `RUNNING` runs: those runs go to `PAUSED_USER` and the session to `PAUSED_CRASHED`.
   - User can click "Resume" on the session to try again.

4. **Recover orphaned batch runs** (`_recover_orphaned_batch_runs`). `TestBatchRun.status == 'running'` with no matching live thread → `error` with `message = "Server restarted while test was running"` and `completed_at = now`.

5. **Clean up orphaned Gitea sandbox users** (`cleanup_orphaned_sandbox_users` from `druppie/opencode/gitea_cleanup.py`). Sandbox Gitea users that survived a prior crash are deleted.

6. **Initialize Tool Registry** (`initialize_tool_registry`). `ToolRegistry.initialize()`:
   - Iterates every MCP entry in `druppie/core/mcp_config.yaml`.
   - For each, calls `tools/list` on the MCP server.
   - Populates the in-memory registry with `ToolDefinition` objects.
   - On server failure: logs and continues (degraded mode) and schedules a background retry task for the failed servers.

7. **Start sandbox watchdog** (`create_tracked_task(sandbox_watchdog_loop(), name="sandbox-watchdog")`). Background task:
   - Sleeps for `SANDBOX_WATCHDOG_INTERVAL_SECONDS` (default 300).
   - Queries `ExecutionRepository.get_stuck_sandbox_tool_calls(cutoff=now - SANDBOX_TIMEOUT_MINUTES)`.
   - For each: mark tool call FAILED, parent agent run FAILED, parent session FAILED, attempt `DELETE` on the control plane to clean up the sandbox container.

8. **Yield** — app is now serving requests.

## Shutdown steps

9. **Cancel watchdog** — 30 s graceful timeout, then force-cancel.
10. **Close DB pool**.

## Post-startup invariants

After a successful startup:
- Every session is in exactly one status (`ACTIVE`, `PAUSED_*`, `COMPLETED`, `FAILED`).
- No session has an agent run in `RUNNING` status (either the task is alive, or the row was moved to `PAUSED_USER`/`FAILED` during recovery).
- Tool registry is populated for every available MCP.
- The watchdog is running.

## Health endpoints

- `GET /health` — liveness. Always 200 after startup. Used by Docker healthcheck.
- `GET /health/ready` — readiness. Checks:
  - DB connection (`SELECT 1`).
  - Agents loaded (the YAMLs parsed successfully at first `get_agents_list()` call).
  - Returns 200 or 503.

Frontend `getStatus()` hits `/api/status` which runs a richer probe (Keycloak, Gitea, LLM config, agent count).

## Crash recovery in practice

If Druppie is force-killed mid-agent:

- Tool call that was executing: stays `EXECUTING`. After recovery, never resumes. User must Resume session — orchestrator detects the orphan and either re-executes the tool (if idempotent) or fails.
- Tool call waiting on approval: stays `WAITING_APPROVAL`. Approval still visible to approvers; resolving it resumes as normal.
- LLM call that was mid-request: the request is lost. The LLM provider may have charged for it, but we have no record in `llm_calls`. No retry happens automatically.
- Session: moves to `PAUSED_CRASHED` with `error_message` explaining.

This recovery is conservative — it never automatically retries, because the system can't know whether the prior run had side effects (git commits, docker containers) that must be reconciled first.

## Running locally without Docker

`druppie/api/main.py` can be run directly:
```
uvicorn druppie.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Requires: PostgreSQL reachable at `DATABASE_URL`, Keycloak at `KEYCLOAK_URL`, and the MCP servers already running (or `USE_MCP_MICROSERVICES=false` to degrade gracefully). This is used for IDE debugging with breakpoints — `docker compose --profile dev` is the standard path.
