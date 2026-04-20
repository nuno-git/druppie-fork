# Orchestrator

`druppie/execution/orchestrator.py` — the entry point for all agent work. Intentionally "dumb": it owns session lifecycle and agent-run sequencing, but delegates real intelligence to agent prompts (`set_intent`, `make_plan`).

## Class shape

```python
class Orchestrator:
    def __init__(self, db: Session, user_service, session_service, ...):
        self.db = db
        ...

    async def process_message(
        self,
        message: str,
        user_id: UUID,
        session_id: UUID | None,
        project_id: UUID | None,
    ) -> UUID:
        """Entry for new message / new session; returns session_id."""

    async def resume_after_approval(self, approval_id: UUID) -> None: ...
    async def resume_after_answer(self, question_id: UUID) -> None: ...
    async def resume_after_sandbox(self, sandbox_session_id: UUID) -> None: ...
    async def resume_session(self, session_id: UUID) -> None: ...
```

## process_message flow

1. If `session_id` is given, load existing session; else create new with `user_id`, `title = message[:80]`, `status = ACTIVE`.
2. Insert `Message(role=user, content=message)`.
3. If session is new, seed router + planner PENDING runs.
4. Call `execute_pending_runs(session_id)`.

## execute_pending_runs

```python
async def execute_pending_runs(self, session_id: UUID) -> None:
    while True:
        run = self.repo.next_pending_run(session_id)
        if run is None or session_not_active(session_id):
            break
        run.status = RUNNING
        self.db.commit()
        try:
            await self.agent_loop.run(run)
        except Exception as e:
            run.status = FAILED
            run.error_message = str(e)
            self.db.commit()
            break
```

The loop stops when there are no more pending runs. The planner creating new pending runs (via `make_plan`) keeps the loop alive.

## Delegated intelligence

The orchestrator deliberately avoids "if intent is create_project, do X" logic. Instead:

- **`set_intent` tool** (router's responsibility) — updates `session.intent` and creates the project + Gitea repo if needed. Side effect inside the tool handler.
- **`make_plan` tool** (planner's responsibility) — inserts new PENDING agent runs with their planned prompts. Side effect inside the tool handler.

This keeps the orchestrator small and makes the pipeline shape encoded in YAML (agent prompts) rather than code.

## Resumption entry points

All four `resume_*` methods:
1. Look up the relevant entity (approval, question, sandbox_session).
2. Update the associated tool_call with the external result (approved tool runs; answer becomes the tool result; sandbox events become the extracted result text).
3. Update the agent run status back to RUNNING.
4. Call `execute_pending_runs` which finds this run and continues its loop.

Because the loop is idempotent — it picks up the next PENDING or RUNNING run — no explicit "continue this specific run" bookkeeping is needed.

## Concurrency guard

Per-session lock implemented in `druppie/core/background_tasks.py`:

```python
_session_locks: dict[UUID, asyncio.Lock] = {}
async def run_session_task(session_id: UUID, coro):
    lock = _session_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        await coro
```

This prevents two background tasks from both driving the same session's orchestrator (e.g. approval + sandbox webhook arriving near-simultaneously).

## Bounded mode (testing)

`druppie/testing/bounded_orchestrator.py:BoundedOrchestrator` wraps the real Orchestrator and halts execution after a specified set of agents complete. Used by agent tests to run only `[router, planner, business_analyst]` without the rest of the pipeline firing.

Mechanism: overrides `execute_pending_runs` to check `_all_real_agents_done()` after each iteration. If all listed agents are COMPLETED, it cancels remaining PENDING runs and exits cleanly. 10-minute wall-clock timeout as safety.
