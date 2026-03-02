# Pause / Resume Agent Runs — Design

**Date:** 2026-03-02
**Branch:** feature/continue-agent-run

## User Story

As a Druppie team member, I want to pause, interrupt, and resume a conversation in Druppie Chat, so all users can continue a running conversation later without losing context.

## Acceptance Criteria

1. Any user can **pause** a session (stops execution without losing context)
2. Any user can **resume** a paused session with full context preserved
3. Session status (**active / paused**) is visible in the UI
4. Pause/resume works for **all users**, not just developers or admins
5. Survives **system reboot** — crashed sessions detected and resumable

## Design Decisions

- **Pause granularity:** Wait for current LLM call + tool execution to complete, then pause before the next iteration. No interrupted partial state.
- **Resume behavior:** Simple continue button, no guidance message. Just picks up where it left off.
- **Reboot recovery:** Auto-detect zombie sessions (ACTIVE with no background task) on startup and mark them as paused/recoverable.
- **Existing pause types untouched:** `PAUSED_APPROVAL` and `PAUSED_HITL` keep their existing flows. This design adds a new user-initiated pause alongside them.

## Approach: Piggyback on Cancellation Pattern

The existing cancel flow uses DB-polling in the orchestrator loop — the cancel endpoint sets `session.status = CANCELLED` and the background task detects it. Pause uses the identical mechanism but sets `PAUSED` instead and does NOT cancel pending runs.

## Status Model

### New Statuses

| Level | Status | Description |
|-------|--------|-------------|
| Session | `PAUSED` | User-initiated pause |
| AgentRun | `PAUSED_USER` | Agent run interrupted by user pause |

### State Transitions

```
Session:
  ACTIVE ──pause──► PAUSED ──resume──► ACTIVE
  ACTIVE ──crash──► (zombie, still ACTIVE in DB) ──startup──► PAUSED

AgentRun:
  RUNNING ──pause detected──► PAUSED_USER ──resume──► RUNNING
```

Existing statuses (`PAUSED_APPROVAL`, `PAUSED_HITL`, `PAUSED_TOOL`) are unchanged.

## Backend: Pause Endpoint

**`POST /chat/{session_id}/pause`**

1. Lock session row (`get_by_id_for_update`) — prevents race with concurrent operations
2. Validate ownership (owner or admin)
3. Validate status is `ACTIVE` — can only pause an active session
4. Set `session.status = PAUSED`
5. Commit and return immediately

The orchestrator's `execute_pending_runs()` loop detects the pause:
- After the existing cancellation check, add a pause check
- If `session.status == PAUSED`: mark running agent run as `PAUSED_USER`, exit loop
- **Pending runs stay PENDING** (not cancelled — unlike cancel which kills them)
- The agent finishes its current step naturally, then the loop sees PAUSED and exits

## Backend: Resume Endpoint

**`POST /sessions/{session_id}/resume`**

1. Lock session row
2. Validate ownership (owner or admin)
3. Validate status is `PAUSED`
4. Set session status to `ACTIVE`
5. Find agent run with status `PAUSED_USER`
6. Spawn background task:
   a. Mark agent run as `RUNNING`
   b. Call `agent.continue_run()` — reconstructs state from DB LLM calls
   c. Handle result (may pause again for approval/HITL, or complete)
   d. Call `execute_pending_runs()` for remaining pending runs
7. Return immediately

This mirrors the exact pattern of `resume_after_approval()` and `resume_after_answer()`.

## Zombie Detection on Startup

On FastAPI `lifespan` startup:

1. Query sessions where `status = 'active'` AND they have agent runs with `status = 'running'`
2. For each zombie: mark session `PAUSED`, mark running agent run `PAUSED_USER`
3. Log warning for each recovered session

Simple startup hook — no ongoing background process. Sessions appear as "paused" in user's list with a resume button.

## Frontend Changes

1. **Pause button** — shown when session is `active` (alongside or replacing Stop button)
2. **Resume/Continue button** — shown when session is `paused`
3. **Status indicator** — amber/paused visual for `paused` status
4. **Session list** — paused sessions visible with status badge

## Key Files to Modify

| File | Change |
|------|--------|
| `druppie/domain/common.py` | Add `PAUSED` to SessionStatus, `PAUSED_USER` to AgentRunStatus |
| `druppie/execution/orchestrator.py` | Add pause check in `execute_pending_runs()`, add `resume_paused_session()` method |
| `druppie/api/routes/chat.py` | Add `POST /chat/{session_id}/pause` endpoint |
| `druppie/api/routes/sessions.py` | Add `POST /sessions/{session_id}/resume` endpoint |
| `druppie/repositories/execution_repository.py` | Add `get_paused_user_run()`, `get_zombie_sessions()` methods |
| `druppie/core/lifespan.py` (or equivalent) | Add zombie detection on startup |
| `frontend/src/services/api.js` | Add `pauseSession()`, `resumeSession()` API calls |
| `frontend/src/components/chat/SessionDetail.jsx` | Add pause/resume buttons, paused status styling |
