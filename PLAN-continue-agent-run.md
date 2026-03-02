# Continue/Resume Failed Agent Runs - Feature Plan

## Problem Statement

Agent runs can fail mid-execution (LLM errors, tool failures, timeouts) or appear "stuck" in RUNNING/ACTIVE status while actually being dead. Currently there is **no way** to resume or retry these runs — users must start a completely new session and lose all prior context and work.

### Current Gaps
- No "Continue" or "Retry" button in the UI
- No API endpoint to resume/retry a failed run
- No detection of "zombie" runs (stuck in RUNNING)
- Failed runs lose all accumulated context (tool results, LLM history)

### What Already Exists (foundations we can reuse)
- `Agent.continue_run()` — reconstructs full message history from DB and resumes
- `reconstruct_from_db()` — rebuilds LLM conversation from stored LLM calls
- Approval/HITL resume workflow — proven pattern for pause→resume
- `execute_pending_runs()` — orchestrates sequential agent execution
- Full audit trail in DB (LLM calls, tool calls, results)

---

## Approach 1: Retry Failed Agent Run (Fresh Start)

### Concept
When an agent run fails, allow the user to **restart that specific agent** from scratch with the same `planned_prompt`. The failed run is marked as superseded, and a new agent run is created in its place.

### How It Works
1. **API**: `POST /api/sessions/{session_id}/runs/{run_id}/retry`
2. Mark the failed run as `SUPERSEDED` (new status)
3. Create a new AgentRun with same `agent_id`, `planned_prompt`, `sequence_number`
4. Set `parent_run_id` → original failed run (for audit trail)
5. Call `Agent.run()` (fresh start, no history from failed attempt)
6. If the agent completes, continue with `execute_pending_runs()` for subsequent agents

### Backend Changes
- New endpoint in `api/routes/sessions.py` or new file `api/routes/retry.py`
- New status `SUPERSEDED` in `AgentRunStatus`
- New orchestrator method: `retry_failed_run(session_id, run_id)`
- Use existing `parent_run_id` field for tracking

### Frontend Changes
- "Retry" button on failed agent runs in DebugChat timeline
- Button triggers POST, then polls for updates
- Show retry lineage (original → retry 1 → retry 2)

### Pros
- **Simple to implement** — reuses existing `Agent.run()` directly
- **Clean state** — no risk of corrupted/partial state carrying over
- **Safe** — doesn't touch complex message reconstruction
- **Audit trail** — failed + retried runs both visible in timeline

### Cons
- **Loses all progress** — if the agent made 5 successful tool calls before failing on the 6th, all are re-executed
- **Wasted tokens** — re-runs the entire agent from scratch
- **Side effects** — tools that already executed (e.g., file creation) may conflict
- **No modification** — can't adjust the prompt before retrying

### Complexity: Low (~2-3 days)

---

## Approach 2: Continue From Last Successful State

### Concept
Resume a failed agent run **exactly where it left off**, using the same `continue_run()` pattern already used for approval/HITL resumes. Reconstructs the full message history from DB and appends a system message about the retry before continuing.

### How It Works
1. **API**: `POST /api/sessions/{session_id}/runs/{run_id}/continue`
2. Validate the run is in FAILED status
3. Set run status back to RUNNING
4. Call `Agent.continue_run(session_id, run_id)` — same method used by approval resume
5. The LLM sees all previous messages + tool results and continues naturally
6. If the last LLM call had a failed tool call, inject the error as a tool result so the LLM can adapt

### Backend Changes
- New endpoint: `POST /api/sessions/{session_id}/runs/{run_id}/continue`
- New orchestrator method: `continue_failed_run(session_id, run_id)`
- Handle edge case: if failure was during LLM call (no tool result to inject), retry from last complete state
- Handle edge case: if failure was during tool execution, inject error result and let LLM decide next step

### Frontend Changes
- "Continue" button on failed agent runs
- Same polling mechanism as current approval flow
- Show continuation point in timeline

### Pros
- **Preserves all progress** — doesn't re-execute successful steps
- **Token efficient** — only pays for new LLM calls from failure point
- **Natural for LLM** — sees full context and can adapt to the error
- **Reuses existing code** — `continue_run()` and `reconstruct_from_db()` already work
- **No side effects** — tools already executed aren't re-run

### Cons
- **State corruption risk** — if failure corrupted internal state, continuing may hit the same error
- **Complex failure modes** — need to handle different failure points (LLM call vs tool call vs orchestrator)
- **No prompt modification** — continues with same instructions
- **Zombie detection needed** — must also handle runs stuck in RUNNING (not just FAILED)

### Complexity: Medium (~3-4 days)

---

## Approach 3: Continue With User Guidance

### Concept
Like Approach 2, but allows the user to **add a message/instruction** when continuing. This gives the LLM additional context about what went wrong and how to proceed differently. Think of it like the HITL flow but for failures.

### How It Works
1. **API**: `POST /api/sessions/{session_id}/runs/{run_id}/continue`
   - Body: `{ "guidance": "The Docker container was not running. Try starting it first." }` (optional)
2. Reconstruct message history from DB
3. If guidance provided: append it as a special system/user message
4. If the last action was a failed tool call: inject error as tool result
5. Resume the LLM loop — it now has context about the failure + user guidance
6. Continue execution normally

### Backend Changes
- New endpoint with optional `guidance` field in request body
- New orchestrator method: `continue_with_guidance(session_id, run_id, guidance=None)`
- Modify `Agent.continue_run()` to accept optional additional messages
- Add guidance message to message history reconstruction

### Frontend Changes
- "Continue" button on failed runs opens a small modal/form
- Optional text field: "Add instructions for the agent (optional)"
- "Continue" and "Continue without instructions" buttons
- Show the guidance message in the timeline

### Pros
- **Best of both worlds** — preserves progress + allows course correction
- **User agency** — user can explain what went wrong or suggest alternatives
- **Natural interaction** — similar to how you'd guide a human colleague
- **Flexible** — guidance is optional, so simple retry is still possible
- **Handles edge cases** — user can work around known issues

### Cons
- **More UI complexity** — needs modal/form for guidance input
- **Prompt engineering** — need to carefully format the guidance so LLM understands it
- **Same state risks** as Approach 2
- **Scope creep risk** — users might expect full chat-like interaction on retries

### Complexity: Medium (~4-5 days)

---

## Approach 4: Smart Retry with Zombie Detection and Auto-Recovery

### Concept
A comprehensive solution that handles **all failure modes** automatically:
- Detects zombie runs (RUNNING but no activity for X minutes)
- Automatically marks them as FAILED with appropriate error
- Provides a "Continue" button that intelligently decides the best retry strategy
- Includes health monitoring for active runs

### How It Works
1. **Zombie Detection**: Background task or on-demand check
   - Query runs with status=RUNNING where last LLM call was > 5 minutes ago
   - Mark as FAILED with error "Agent run timed out — no activity detected"
   - Update session status accordingly

2. **Smart Continue**: `POST /api/sessions/{session_id}/runs/{run_id}/continue`
   - Analyzes the failure to determine best strategy:
     - If failed during LLM call → retry the LLM call
     - If failed during tool execution → inject error, let LLM adapt
     - If zombie timeout → continue from last good state
     - If too many iterations → warn user, allow override
   - Optional user guidance (like Approach 3)

3. **Health Endpoint**: `GET /api/sessions/{session_id}/health`
   - Returns run health status, last activity time, iteration count
   - Frontend uses this to show "stuck" indicator

### Backend Changes
- Zombie detection utility (can be called on-demand or scheduled)
- Smart continue orchestrator method with failure analysis
- Health check endpoint
- New fields: `last_activity_at` on AgentRun (track heartbeat)
- Background heartbeat: update `last_activity_at` during LLM calls

### Frontend Changes
- "Continue" button with smart behavior (no user decision needed)
- Optional guidance modal
- "Stuck" indicator on runs that haven't had activity
- Health status badge on active runs
- Auto-detection: if viewing a zombie session, show "This run appears stuck" banner

### Pros
- **Handles all failure modes** — crashes, timeouts, tool failures, LLM errors
- **Better UX** — users don't need to understand failure modes
- **Proactive** — detects problems before users notice
- **Robust** — smart retry strategy reduces repeat failures
- **Complete solution** — solves the full problem space

### Cons
- **Most complex** — significantly more code to write and test
- **Over-engineering risk** — may be solving problems that rarely occur
- **Background task complexity** — zombie detection needs careful implementation
- **Database changes** — needs `last_activity_at` heartbeat field
- **Testing difficulty** — hard to test all failure scenarios

### Complexity: High (~6-8 days)

---

## Approach 5: Session-Level Retry with Selective Agent Re-execution

### Concept
Instead of retrying individual agent runs, work at the **session level**. When a session fails, present the user with a list of all agent runs and let them choose which ones to re-execute. Already-completed agents can be skipped, and their results are carried forward.

### How It Works
1. **API**: `POST /api/sessions/{session_id}/retry`
   - Body: `{ "from_run_id": "uuid-of-failed-run", "guidance": "..." }`
   - Or: `{ "retry_all": true }` for full session retry
2. Show session's agent run list with checkboxes (completed=checked, failed=unchecked)
3. User selects which agents to re-run
4. For skipped (completed) agents: carry forward their results as context
5. For re-run agents: execute fresh with full prior context
6. Failed agent and all subsequent agents are re-executed by default

### Backend Changes
- New endpoint: `POST /api/sessions/{session_id}/retry`
- New orchestrator method: `retry_session(session_id, from_run_id, guidance)`
- Logic to build context from completed agents' results
- Create new agent runs for retried agents (keep originals for audit)
- New session field: `retry_of_session_id` or reuse same session

### Frontend Changes
- "Retry Session" button on failed sessions
- Agent run selector modal (checkboxes for which agents to re-run)
- "Retry from here" shortcut on specific failed agent run
- Guidance text field
- Show retry history in session detail

### Pros
- **Granular control** — user decides exactly what to re-run
- **Preserves completed work** — successful agents aren't wasted
- **Session-level thinking** — matches how users think about "my request failed"
- **Flexible** — supports full retry, partial retry, and skip-ahead
- **Clean separation** — original and retried runs are distinct

### Cons
- **Complex UI** — agent selector, retry configuration
- **Context management** — carrying forward results from completed agents is tricky
- **Ordering issues** — skipping agents may break dependencies between them
- **User confusion** — too many options may overwhelm users
- **Doesn't fix in-flight** — only works after failure, not for stuck runs

### Complexity: High (~5-7 days)

---

## Comparison Matrix

| Criteria                    | Approach 1 | Approach 2 | Approach 3 | Approach 4 | Approach 5 |
|-----------------------------|:----------:|:----------:|:----------:|:----------:|:----------:|
| **Implementation effort**   | Low        | Medium     | Medium     | High       | High       |
| **Preserves progress**      | No         | Yes        | Yes        | Yes        | Partial    |
| **User can guide retry**    | No         | No         | Yes        | Yes        | Yes        |
| **Handles zombie runs**     | No         | No         | No         | Yes        | No         |
| **Token efficiency**        | Poor       | Good       | Good       | Good       | Mixed      |
| **Risk of re-side-effects** | High       | None       | None       | None       | Low        |
| **Code reuse**              | High       | Very High  | High       | Medium     | Medium     |
| **UX simplicity**           | Simple     | Simple     | Moderate   | Simple     | Complex    |
| **Covers all failure modes**| Partial    | Partial    | Most       | All        | Partial    |
| **Extensibility**           | Limited    | Good       | Very Good  | Excellent  | Good       |

## My Assessment

**Approach 3 (Continue With User Guidance)** offers the best balance of value vs. effort:
- It reuses the proven `continue_run()` mechanism
- The optional guidance makes it powerful without being complex
- It naturally extends to zombie handling later (just mark zombie as FAILED, then continue)
- The UI is familiar (similar to existing HITL answer flow)
- It can be enhanced incrementally toward Approach 4 features

**Approach 2** is a great starting point if you want the minimal viable feature first.

**Approach 4** is the "complete" solution but risks over-engineering for the initial release — better to evolve toward it from Approach 3.

---

## Pick your approach and I'll implement it!
