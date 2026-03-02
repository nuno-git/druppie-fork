# Pause / Resume Agent Runs — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add user-initiated pause/resume for agent runs, with zombie detection on startup for reboot recovery.

**Architecture:** Piggyback on the existing cancellation DB-polling pattern. The pause endpoint sets `session.status = PAUSED` in the DB; the orchestrator loop detects this and exits cleanly after the current step. Resume spawns a background task that calls `agent.continue_run()` (which reconstructs state from DB) then continues executing pending runs.

**Tech Stack:** Python/FastAPI backend, SQLAlchemy ORM, React/TanStack Query frontend

**Design doc:** `docs/plans/2026-03-02-pause-resume-design.md`

---

## Task 1: Add New Status Enums

**Files:**
- Modify: `druppie/domain/common.py:13-31`

**Step 1: Add PAUSED to SessionStatus**

In `druppie/domain/common.py`, add `PAUSED = "paused"` to `SessionStatus` (after `PAUSED_HITL`):

```python
class SessionStatus(str, Enum):
    """Session execution status."""
    ACTIVE = "active"
    PAUSED_APPROVAL = "paused_approval"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"          # Waiting for user answer
    PAUSED = "paused"                    # User-initiated pause
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Step 2: Add PAUSED_USER to AgentRunStatus**

In the same file, add `PAUSED_USER = "paused_user"` to `AgentRunStatus` (after `PAUSED_HITL`):

```python
class AgentRunStatus(str, Enum):
    """Agent run execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED_TOOL = "paused_tool"    # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"    # Waiting for user answer
    PAUSED_USER = "paused_user"    # User-initiated pause
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Step 3: Verify no existing code breaks**

Run: `cd druppie && ruff check .`
Expected: No new errors

**Step 4: Commit**

```bash
git add druppie/domain/common.py
git commit -m "feat: add PAUSED and PAUSED_USER status enums for user-initiated pause"
```

---

## Task 2: Add Pause Detection in Orchestrator Loop

**Files:**
- Modify: `druppie/execution/orchestrator.py:287-359`

**Step 1: Add pause check after cancellation check in execute_pending_runs()**

In `druppie/execution/orchestrator.py`, in the `execute_pending_runs()` method, right after the cancellation check block (line 295), before the `get_next_pending` call (line 298), add:

```python
            # Check for user-initiated pause
            if session and session.status == SessionStatus.PAUSED.value:
                # Mark the currently running agent run as paused (if any)
                # Pending runs stay PENDING — they'll resume later
                logger.info("execution_paused_by_user", session_id=str(session_id))
                return
```

**Step 2: Add pause check after agent completes (alongside cancellation re-check)**

After the cancellation re-check block (line 343), before the "If paused" block (line 345), add:

```python
            # Re-check for user-initiated pause after agent completes
            if session_check and session_check.status == SessionStatus.PAUSED.value:
                logger.info("execution_paused_by_user_after_agent", session_id=str(session_id))
                return
```

**Step 3: Verify no existing code breaks**

Run: `cd druppie && ruff check .`
Expected: No new errors

**Step 4: Commit**

```bash
git add druppie/execution/orchestrator.py
git commit -m "feat: add pause detection in orchestrator execution loop"
```

---

## Task 3: Add resume_paused_session() to Orchestrator

**Files:**
- Modify: `druppie/execution/orchestrator.py` (after `resume_after_answer` method, ~line 729)

**Step 1: Add the resume_paused_session method**

Add this method to the `Orchestrator` class, after `resume_after_answer()`:

```python
    async def resume_paused_session(self, session_id: UUID) -> UUID:
        """Resume a user-paused session.

        Finds the PAUSED_USER agent run, continues it via continue_run(),
        then executes remaining pending runs.

        If no PAUSED_USER run exists (e.g., pause happened between runs),
        just executes pending runs directly.
        """
        from druppie.agents.runtime import Agent

        logger.info("resume_paused_session", session_id=str(session_id))

        # Set session back to active
        self.session_repo.update_status(session_id, SessionStatus.ACTIVE)
        self.session_repo.commit()

        # Find the paused agent run
        paused_run = self.execution_repo.get_user_paused_run(session_id)

        if not paused_run:
            # Pause happened between runs — just continue with pending
            logger.info(
                "resume_no_paused_run_found",
                session_id=str(session_id),
            )
            await self.execute_pending_runs(session_id)
            return session_id

        logger.info(
            "resuming_user_paused_agent",
            agent_run_id=str(paused_run.id),
            agent_id=paused_run.agent_id,
        )

        # Mark agent run as running
        self.execution_repo.update_status(paused_run.id, AgentRunStatus.RUNNING)
        self.execution_repo.commit()

        # Build fresh context and continue the agent
        db = self.execution_repo.db
        context = self._build_project_context(session_id)
        agent = Agent(paused_run.agent_id, db=db)
        result = await agent.continue_run(
            session_id=session_id,
            agent_run_id=paused_run.id,
            context=context,
        )

        # Handle result — same pattern as resume_after_approval
        if result.get("status") == "paused" or result.get("paused"):
            pause_reason = result.get("reason", "unknown")
            if pause_reason == "waiting_answer":
                self.execution_repo.update_status(paused_run.id, AgentRunStatus.PAUSED_HITL)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED_HITL)
            else:
                self.execution_repo.update_status(paused_run.id, AgentRunStatus.PAUSED_TOOL)
                self.session_repo.update_status(session_id, SessionStatus.PAUSED_APPROVAL)
            self.execution_repo.commit()
            return session_id

        # Completed — mark agent and continue with remaining pending runs
        self.execution_repo.update_status(paused_run.id, AgentRunStatus.COMPLETED)
        self.execution_repo.commit()

        logger.info(
            "agent_resumed_after_pause_completed",
            agent_run_id=str(paused_run.id),
            agent_id=paused_run.agent_id,
        )

        await self.execute_pending_runs(session_id)
        return session_id
```

**Step 2: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors (will warn about `get_user_paused_run` not existing yet — that's Task 4)

**Step 3: Commit**

```bash
git add druppie/execution/orchestrator.py
git commit -m "feat: add resume_paused_session() to orchestrator"
```

---

## Task 4: Add Repository Methods

**Files:**
- Modify: `druppie/repositories/execution_repository.py`

**Step 1: Add get_user_paused_run() method**

Add this method after the existing `get_paused_run()` method (~line 169):

```python
    def get_user_paused_run(self, session_id: UUID) -> AgentRunSummary | None:
        """Get the user-paused agent run for a session."""
        agent_run = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == AgentRunStatus.PAUSED_USER.value,
            )
            .first()
        )
        return self._to_summary(agent_run) if agent_run else None
```

**Step 2: Add recover_zombie_sessions() method**

Add this method to the `ExecutionRepository` class:

```python
    def recover_zombie_sessions(self) -> list[UUID]:
        """Find and recover zombie sessions after a server restart.

        A zombie session is one with status='active' that has at least one
        agent run with status='running'. On startup, no background tasks
        exist, so these sessions are stuck.

        Marks zombie sessions as PAUSED and their running runs as PAUSED_USER.

        Returns:
            List of recovered session IDs.
        """
        from druppie.db.models import Session as DBSession

        # Find sessions that are active with running agent runs
        zombie_sessions = (
            self.db.query(DBSession)
            .filter(DBSession.status == SessionStatus.ACTIVE.value)
            .join(AgentRun, AgentRun.session_id == DBSession.id)
            .filter(AgentRun.status == AgentRunStatus.RUNNING.value)
            .distinct()
            .all()
        )

        recovered_ids = []
        for session in zombie_sessions:
            # Mark running agent runs as PAUSED_USER
            running_runs = (
                self.db.query(AgentRun)
                .filter(
                    AgentRun.session_id == session.id,
                    AgentRun.status == AgentRunStatus.RUNNING.value,
                )
                .all()
            )
            for run in running_runs:
                run.status = AgentRunStatus.PAUSED_USER.value

            # Mark session as PAUSED
            session.status = SessionStatus.PAUSED.value
            recovered_ids.append(session.id)

        return recovered_ids
```

**Step 3: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors

**Step 4: Commit**

```bash
git add druppie/repositories/execution_repository.py
git commit -m "feat: add get_user_paused_run() and recover_zombie_sessions() to repository"
```

---

## Task 5: Add Pause Endpoint

**Files:**
- Modify: `druppie/api/routes/chat.py`

**Step 1: Update CANCELABLE_STATUSES and add PAUSABLE_STATUSES**

After the existing `CANCELABLE_STATUSES` (line 273), add:

```python
PAUSABLE_STATUSES = {"active"}
```

Also add `"paused"` to `CANCELABLE_STATUSES` so users can cancel a paused session too:

```python
CANCELABLE_STATUSES = {"active", "paused", "paused_approval", "paused_hitl"}
```

**Step 2: Add the pause endpoint**

Add the pause endpoint after the cancel endpoint (after line 323):

```python
@router.post("/chat/{session_id}/pause")
async def pause_session(
    session_id: UUID,
    user: dict = Depends(get_current_user),
    session_repo: SessionRepository = Depends(get_session_repository),
):
    """Pause a running session.

    Sets session status to PAUSED. The background orchestrator loop will
    detect this on its next DB poll and exit cleanly after the current
    agent step completes. Pending runs stay PENDING for later resumption.
    """
    user_id = UUID(user["sub"])
    user_roles = user.get("realm_access", {}).get("roles", [])

    # Lock the row to prevent race with concurrent operations
    session = session_repo.get_by_id_for_update(session_id)
    if not session:
        raise NotFoundError("session", str(session_id))

    # Only owner or admin can pause
    is_owner = session.user_id == user_id
    is_admin = "admin" in user_roles
    if not is_owner and not is_admin:
        raise AuthorizationError("Cannot pause this session")

    if session.status not in PAUSABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pause session with status '{session.status}'",
        )

    # Set session status to paused — the background task will detect this
    session_repo.update_status(session_id, SessionStatus.PAUSED)
    session_repo.commit()

    logger.info("session_paused", session_id=str(session_id))

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session paused",
    }
```

**Step 3: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors

**Step 4: Commit**

```bash
git add druppie/api/routes/chat.py
git commit -m "feat: add POST /chat/{session_id}/pause endpoint"
```

---

## Task 6: Add Resume Endpoint

**Files:**
- Modify: `druppie/api/routes/sessions.py`

**Step 1: Add the background task function**

Add this after the existing `_run_retry_background` function (before the `retry_from_run` route, ~line 272):

```python
async def _run_resume_background(session_id: UUID) -> None:
    """Resume a paused session in background.

    Creates fresh DB session and repositories (same pattern as chat.py).
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories import (
        SessionRepository,
        ExecutionRepository,
        ProjectRepository,
        QuestionRepository,
    )
    from druppie.execution import Orchestrator

    db = SessionLocal()
    try:
        session_repo = SessionRepository(db)
        execution_repo = ExecutionRepository(db)
        project_repo = ProjectRepository(db)
        question_repo = QuestionRepository(db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
        )

        await orchestrator.resume_paused_session(session_id)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            "resume_background_error",
            session_id=str(session_id),
            error=error_msg,
            exc_info=True,
        )
        try:
            db.rollback()
            from druppie.repositories import SessionRepository
            session_repo = SessionRepository(db)
            session_repo.update_status(
                session_id,
                SessionStatus.FAILED,
                error_message=error_msg[:2000],
            )
            db.commit()
        except Exception as update_error:
            logger.error(
                "failed_to_update_session_status_after_resume",
                session_id=str(session_id),
                error=str(update_error),
            )
    finally:
        db.close()
```

**Step 2: Add the resume endpoint**

Add the endpoint after the background function:

```python
@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Resume a paused session.

    Spawns a background task that continues the paused agent run
    and then executes remaining pending runs.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    # Validate session exists and user has access
    detail = service.get_detail(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
    )

    if detail.status != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resume session with status '{detail.status}'",
        )

    logger.info(
        "resume_session_requested",
        session_id=str(session_id),
        user_id=str(user_id),
    )

    # Spawn background task
    create_tracked_task(
        _run_resume_background(session_id=session_id),
        name=f"resume-{session_id}",
    )

    return {
        "success": True,
        "session_id": str(session_id),
        "message": "Session resuming",
    }
```

**Step 3: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors

**Step 4: Commit**

```bash
git add druppie/api/routes/sessions.py
git commit -m "feat: add POST /sessions/{session_id}/resume endpoint"
```

---

## Task 7: Add Zombie Detection on Startup

**Files:**
- Modify: `druppie/api/main.py:24-38`

**Step 1: Add zombie recovery to the lifespan handler**

Modify the `lifespan` function in `druppie/api/main.py` to add zombie detection after the agents list:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("druppie_starting")

    # List available agents
    agents_list = Agent.list_agents()
    logger.info("druppie_initialized", agents=len(agents_list))

    # Recover zombie sessions (active sessions with running agent runs
    # that were interrupted by server shutdown/crash)
    _recover_zombie_sessions()

    yield

    # Shutdown — wait for background tasks before exiting
    await shutdown_background_tasks(timeout=30.0)
    logger.info("druppie_stopping")
```

**Step 2: Add the helper function**

Add this function before the `lifespan` function in the same file:

```python
def _recover_zombie_sessions() -> None:
    """Recover sessions that were active when the server stopped.

    On startup, any session with status='active' and running agent runs
    is a zombie — mark it as PAUSED so users can resume via the UI.
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories import ExecutionRepository

    db = SessionLocal()
    try:
        execution_repo = ExecutionRepository(db)
        recovered = execution_repo.recover_zombie_sessions()

        if recovered:
            db.commit()
            logger.warning(
                "zombie_sessions_recovered",
                count=len(recovered),
                session_ids=[str(sid) for sid in recovered],
            )
        else:
            logger.info("no_zombie_sessions_found")
    except Exception as e:
        logger.error("zombie_recovery_failed", error=str(e), exc_info=True)
        db.rollback()
    finally:
        db.close()
```

**Step 3: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors

**Step 4: Commit**

```bash
git add druppie/api/main.py
git commit -m "feat: add zombie session detection and recovery on startup"
```

---

## Task 8: Add Pause/Resume API Calls to Frontend

**Files:**
- Modify: `frontend/src/services/api.js`

**Step 1: Add pauseSession() function**

After the existing `cancelChat` function (~line 80), add:

```javascript
export const pauseSession = (sessionId) =>
  request(`/api/chat/${sessionId}/pause`, { method: 'POST' })
```

**Step 2: Add resumeSession() function**

After `pauseSession`, add:

```javascript
export const resumeSession = (sessionId) =>
  request(`/api/sessions/${sessionId}/resume`, { method: 'POST' })
```

**Step 3: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "feat: add pauseSession and resumeSession API client functions"
```

---

## Task 9: Add Pause/Resume Buttons and Status to Frontend

**Files:**
- Modify: `frontend/src/components/chat/SessionDetail.jsx`

**Step 1: Import the new API functions**

Find the import line for `cancelChat` and add `pauseSession`, `resumeSession`:

```javascript
import { cancelChat, pauseSession, resumeSession, ... } from '../../services/api'
```

**Step 2: Add mutations for pause and resume**

Near the existing `cancelMutation` definition, add:

```javascript
const pauseMutation = useMutation({
  mutationFn: () => pauseSession(sessionId),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
})

const resumeMutation = useMutation({
  mutationFn: () => resumeSession(sessionId),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
})
```

**Step 3: Add paused status to the status dot color map**

In the `statusDotColor` object (~line 557), add an entry for `paused`:

```javascript
const statusDotColor = {
  completed: 'bg-green-500',
  active: 'bg-blue-500 animate-pulse',
  running: 'bg-blue-500 animate-pulse',
  failed: 'bg-red-500',
  cancelled: 'bg-gray-400',
  pending: 'bg-gray-400',
  paused: 'bg-amber-500 animate-pulse',           // <-- ADD THIS
  paused_hitl: 'bg-amber-500 animate-pulse',
  paused_tool: 'bg-amber-500 animate-pulse',
  paused_approval: 'bg-amber-500 animate-pulse',
  waiting_approval: 'bg-amber-500 animate-pulse',
  waiting_answer: 'bg-amber-500 animate-pulse',
}[data.status] || 'bg-gray-400'
```

**Step 4: Add paused status to polling condition**

Find the `refetchInterval` logic and ensure `paused` is NOT in the polling list (no need to poll when paused — nothing is running):

The existing polling should be for `active`, `running`, `paused_approval`, `paused_hitl`. Do NOT add `paused` — when user-paused, nothing is happening server-side.

**Step 5: Replace the stop button in the header with a pause/resume toggle**

Replace the existing stop button block (~lines 581-594) with:

```jsx
{data.status === 'active' && (
  <button
    onClick={() => pauseMutation.mutate()}
    disabled={pauseMutation.isPending}
    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-amber-600 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 disabled:opacity-50 transition-colors"
  >
    {pauseMutation.isPending ? (
      <Loader2 className="w-3.5 h-3.5 animate-spin" />
    ) : (
      <PauseCircle className="w-3.5 h-3.5" />
    )}
    Pause
  </button>
)}
{data.status === 'paused' && (
  <button
    onClick={() => resumeMutation.mutate()}
    disabled={resumeMutation.isPending}
    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-green-600 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50 transition-colors"
  >
    {resumeMutation.isPending ? (
      <Loader2 className="w-3.5 h-3.5 animate-spin" />
    ) : (
      <PlayCircle className="w-3.5 h-3.5" />
    )}
    Continue
  </button>
)}
{['active', 'paused', 'paused_approval', 'paused_hitl'].includes(data.status) && (
  <button
    onClick={() => cancelMutation.mutate()}
    disabled={cancelMutation.isPending}
    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors"
  >
    {cancelMutation.isPending ? (
      <Loader2 className="w-3.5 h-3.5 animate-spin" />
    ) : (
      <StopCircle className="w-3.5 h-3.5" />
    )}
    Stop
  </button>
)}
```

**Step 6: Import PauseCircle and PlayCircle icons**

At the top of the file, find the lucide-react import and add `PauseCircle` and `PlayCircle`:

```javascript
import { ..., PauseCircle, PlayCircle, ... } from 'lucide-react'
```

**Step 7: Update the input bar stop button to be a pause button**

In the input bar area (~lines 835-847), the existing inline stop button should also become a pause button when the session is active. Replace the inline stop button block with:

```jsx
{data.status === 'active' ? (
  <button
    onClick={() => pauseMutation.mutate()}
    disabled={pauseMutation.isPending}
    className="flex-shrink-0 p-2 rounded-xl bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
    aria-label="Pause agent"
  >
    {pauseMutation.isPending ? (
      <Loader2 className="w-4 h-4 animate-spin" />
    ) : (
      <PauseCircle className="w-4 h-4" />
    )}
  </button>
) : data.status === 'paused' ? (
  <button
    onClick={() => resumeMutation.mutate()}
    disabled={resumeMutation.isPending}
    className="flex-shrink-0 p-2 rounded-xl bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
    aria-label="Continue agent"
  >
    {resumeMutation.isPending ? (
      <Loader2 className="w-4 h-4 animate-spin" />
    ) : (
      <PlayCircle className="w-4 h-4" />
    )}
  </button>
) : ['paused_approval', 'paused_hitl'].includes(data.status) ? (
  <button
    onClick={() => cancelMutation.mutate()}
    disabled={cancelMutation.isPending}
    className="flex-shrink-0 p-2 rounded-xl bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
    aria-label="Stop agent"
  >
    {cancelMutation.isPending ? (
      <Loader2 className="w-4 h-4 animate-spin" />
    ) : (
      <StopCircle className="w-4 h-4" />
    )}
  </button>
) : (
  <button
    onClick={handleContinueSend}
    disabled={!continueInput.trim() || continueMutation.isPending}
    className="flex-shrink-0 p-2 rounded-xl bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 disabled:hover:bg-gray-900 transition-colors"
    aria-label="Send message"
  >
    {continueMutation.isPending ? (
      <Loader2 className="w-4 h-4 animate-spin" />
    ) : (
      <ArrowUp className="w-4 h-4" />
    )}
  </button>
)}
```

**Step 8: Make input bar visible for paused sessions**

Update the condition that controls input bar visibility. Change from:

```jsx
{data.status !== 'failed' && data.status !== 'cancelled' && viewMode !== 'inspect' && (
```

This already allows `paused` status through since it only excludes `failed` and `cancelled`. Good — no change needed here.

**Step 9: Verify frontend**

Run: `cd frontend && npm run lint`
Expected: No errors

**Step 10: Commit**

```bash
git add frontend/src/components/chat/SessionDetail.jsx
git commit -m "feat: add pause/resume buttons and paused status indicator in UI"
```

---

## Task 10: Update the Orchestrator Pause Check to Mark Running Agent Run

**Files:**
- Modify: `druppie/execution/orchestrator.py`

**Step 1: Enhance the pause detection to mark the current agent run**

The pause check in Task 2 was minimal — it just returned. But we need to also mark the agent run that just completed its step as `PAUSED_USER`. Update the second pause check (after agent completes) to:

```python
            # Re-check for user-initiated pause after agent completes
            if session_check and session_check.status == SessionStatus.PAUSED.value:
                # Mark the agent run that just finished its step as PAUSED_USER
                # (only if it's still RUNNING — it may have already been marked completed/paused)
                refreshed = self.execution_repo.get_by_id(next_run.id)
                if refreshed and refreshed.status == AgentRunStatus.RUNNING.value:
                    self.execution_repo.update_status(next_run.id, AgentRunStatus.PAUSED_USER)
                    self.execution_repo.commit()
                logger.info("execution_paused_by_user_after_agent", session_id=str(session_id))
                return
```

Note: The first pause check (at the top of the loop) runs BEFORE an agent starts. At that point, no agent is running yet — the run that just completed was already marked `COMPLETED` by `_run_agent()`. So the first check just needs to `return`.

But there's a subtlety: if the pause happens DURING `_run_agent()`, the `_run_agent` method returns `"completed"` (the agent finished its step), then we check for pause. In this case the agent run was already marked `COMPLETED` by `_run_agent()` at line 506. So we DON'T need to re-mark it as `PAUSED_USER` — it completed naturally. The pause just means "don't start the next pending run."

Actually, let me reconsider. The `_run_agent` marks the run as COMPLETED on line 506. So after a pause:
- If agent completed: run is COMPLETED. Next loop iteration checks pause → returns. No PAUSED_USER needed.
- If agent paused (HITL/approval): run is PAUSED_TOOL/PAUSED_HITL. The "if paused" block fires first. But what if the user sent a pause request while the agent was paused for HITL? In that case, the existing PAUSED_HITL handling fires, the session stays PAUSED_HITL. The user's pause request will fail (status not 'active'). That's correct.

So the simplest approach: the pause check at the TOP of the loop is all we need. If the user pauses while an agent is in the middle of its loop, the agent finishes its current LLM call+tool, `_run_agent` marks it COMPLETED, then the loop comes back to the top and sees PAUSED.

Wait — but `_run_agent` marks it completed. That means when we resume, `get_user_paused_run()` won't find any PAUSED_USER run. Instead, `execute_pending_runs()` will just pick up the next PENDING run. That's fine! The agent's work IS done at that point.

BUT — if the agent is mid-loop (iteration 3 of 10), `_run_agent` only returns when the agent's loop finishes (either by completing, pausing for HITL, or hitting max iterations). The pause signal doesn't interrupt the agent mid-loop.

Let me check how the agent loop works to understand if we can inject a pause check there too.

**Actually — this is the design decision we already made: "Wait for current LLM call + tool execution to complete, then pause before next iteration."** The agent's internal loop handles one LLM call per iteration. The question is: does the orchestrator's loop iterate per-agent-run, or does the agent's internal loop iterate per-LLM-call?

Looking at the code: `_run_agent()` calls `agent.run()` which runs the agent's full loop until completion/pause. The orchestrator's loop iterates per-agent-run. So:

- **Pause between agent runs:** Works perfectly with just the top-of-loop check. No PAUSED_USER status needed on agent runs — completed ones stay COMPLETED.
- **Pause mid-agent (during internal LLM loop):** NOT supported with current approach. The agent finishes its entire run before the orchestrator checks.

For this to work at the LLM-call granularity, we'd need to add a pause check inside the agent's loop. But that's more invasive. Let's keep the current design (pause between agent runs) and note this as a future enhancement.

**Revised Step 1:** Simplify — remove PAUSED_USER concept from agent runs. Pause only works between runs.

Actually, looking back at this more carefully — this significantly impacts the design. Let me reconsider.

The user said "wait for current step to finish, then pause." In the context of a multi-agent session (router → planner → coder → reviewer → deployer), a "step" = one agent run. The pause happens cleanly between runs. The completed agent is COMPLETED, the next pending one stays PENDING.

For **zombie detection**, a crashed agent run IS mid-execution. It's status='running' but no task owns it. We still need PAUSED_USER for that case.

So: PAUSED_USER is only used for zombie recovery (crashed mid-run), not for user-initiated pause (which happens between runs).

**Updated implementation:** The pause check stays simple (just `return` at top of loop). PAUSED_USER is only set by zombie recovery. The resume endpoint handles both cases:
1. PAUSED_USER exists → continue it with `continue_run()`
2. No PAUSED_USER → just `execute_pending_runs()` (picks up next PENDING)

This is actually what Task 3's `resume_paused_session()` already does! No change needed.

**Step 2: Remove the second pause check (after agent completes)**

On reflection, we don't need the second pause check from Task 2 step 2. The first check (top of loop) is sufficient:
- Agent completes → loop comes back to top → sees PAUSED → returns
- This ensures the agent finishes cleanly

Remove the second pause check added in Task 2. Only keep the first one.

**Step 3: Verify**

Run: `cd druppie && ruff check .`
Expected: No errors

**Step 4: Commit**

```bash
git add druppie/execution/orchestrator.py
git commit -m "fix: simplify pause detection — only check at top of loop"
```

---

## Task 11: End-to-End Verification

**Step 1: Start the dev environment**

```bash
docker compose --profile dev --profile init up -d
```

**Step 2: Reset DB (new columns need fresh schema)**

```bash
docker compose --profile reset-db run --rm reset-db
```

**Step 3: Verify backend starts without errors**

```bash
docker compose logs -f druppie-backend-dev
```

Look for: `druppie_initialized` log and NO zombie recovery warnings (fresh DB)

**Step 4: Manual test — pause/resume flow**

1. Log in as `developer` / `Developer123!`
2. Start a chat session (anything that takes a few seconds)
3. While it's running (status = active), click Pause
4. Verify: session status changes to "paused", the agent finishes its current run
5. Click Continue
6. Verify: session resumes and completes

**Step 5: Manual test — zombie recovery**

1. Start a chat session
2. While it's running, kill the backend: `docker compose stop druppie-backend-dev`
3. Restart: `docker compose start druppie-backend-dev`
4. Check logs for `zombie_sessions_recovered`
5. Open the session in UI — should show as "paused" with Continue button
6. Click Continue — should resume

**Step 6: Verify lint passes**

```bash
cd druppie && ruff check . && cd ../frontend && npm run lint
```

**Step 7: Final commit**

If any fixes were needed during testing, commit them.

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Add PAUSED/PAUSED_USER enums | `domain/common.py` |
| 2 | Add pause detection in orchestrator loop | `execution/orchestrator.py` |
| 3 | Add resume_paused_session() to orchestrator | `execution/orchestrator.py` |
| 4 | Add repository methods | `repositories/execution_repository.py` |
| 5 | Add pause endpoint | `api/routes/chat.py` |
| 6 | Add resume endpoint | `api/routes/sessions.py` |
| 7 | Add zombie detection on startup | `api/main.py` |
| 8 | Add frontend API calls | `frontend/src/services/api.js` |
| 9 | Add frontend UI (buttons, status) | `frontend/src/components/chat/SessionDetail.jsx` |
| 10 | Simplify orchestrator pause check | `execution/orchestrator.py` |
| 11 | End-to-end verification | All |
