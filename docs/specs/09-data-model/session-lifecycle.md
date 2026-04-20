# Session Lifecycle

State machine for `sessions.status`.

```
                   ┌────────────────────┐
                   │      (new)         │
                   └──────────┬─────────┘
                              │ POST /api/chat
                              ▼
                   ┌────────────────────┐
                   │      ACTIVE        │◄───────────────────────┐
                   └──┬────┬────┬───┬───┘                        │
                      │    │    │   │                            │
           paused on  │    │    │   │ resume / approval / answer │
                      │    │    │   │                            │
                      ▼    ▼    ▼   │                            │
         ┌────────────────┐ ┌────────────┐ ┌─────────────────┐   │
         │PAUSED_APPROVAL │ │ PAUSED_HITL│ │ PAUSED_SANDBOX  │───┘
         └────────────────┘ └────────────┘ └─────────────────┘
                  │               │                  │
                  ▼               ▼                  ▼
              (wait approval)  (wait answer)    (wait webhook)
                              │
                      user clicks Cancel
                              │
                              ▼
                   ┌────────────────────┐
                   │      PAUSED        │
                   └─────────┬──────────┘
                             │ Resume
                             ▼
                          ACTIVE

                   ┌────────────────────┐
                   │   PAUSED_CRASHED   │◄── startup recovery
                   └─────────┬──────────┘
                             │ Resume
                             ▼
                          ACTIVE

  ACTIVE ────► COMPLETED   (planner done, no more agents)
  ACTIVE ────► FAILED      (unrecoverable error)
```

## States

| State | Meaning | How to exit |
|-------|---------|-------------|
| `ACTIVE` | Orchestrator is running | Agent run pauses → PAUSED_*. Plan empty → COMPLETED. Error → FAILED. |
| `PAUSED_APPROVAL` | Tool call awaits role-gated approval | POST /api/approvals/{id}/approve\|reject → ACTIVE |
| `PAUSED_HITL` | Agent asked a question | POST /api/questions/{id}/answer → ACTIVE |
| `PAUSED_SANDBOX` | execute_coding_task awaits webhook | Control plane POST /sandbox-sessions/{id}/complete → ACTIVE |
| `PAUSED` | User-initiated cancel | POST /api/sessions/{id}/resume → ACTIVE |
| `PAUSED_CRASHED` | Zombie recovered at startup | POST /api/sessions/{id}/resume → ACTIVE |
| `COMPLETED` | Pipeline finished successfully | Terminal. Retry-from-run recreates runs and returns to ACTIVE. |
| `FAILED` | Unrecoverable error | Terminal. Retry-from-run or Resume can revive. |

## Transition code

- ACTIVE → PAUSED_* — `ToolExecutor.execute()` returning a WAITING_ status.
- PAUSED_* → ACTIVE — `Orchestrator.resume_after_*()` after the external event resolves.
- ACTIVE → COMPLETED — `Orchestrator.execute_pending_runs()` loop finds no more runs after a planner's empty `make_plan`.
- ACTIVE → FAILED — agent run FAILED + planner can't recover.
- Any → PAUSED_CRASHED — `recover_zombie_sessions()` at startup.
- PAUSED → ACTIVE — `SessionService.lock_for_resume()` → orchestrator resumes.

## Retry-from-run

`POST /api/sessions/{id}/retry-from/{agent_run_id}`:
1. `WorkflowService.revert_session_to_run()` deletes agent_runs, llm_calls, tool_calls, messages with `sequence_number > target`.
2. `RevertService` runs `coding:_internal_revert_to_commit` on the workspace.
3. Insert new PENDING agent run for the target agent (optionally with override `planned_prompt`).
4. `SessionService.lock_for_retry()` → session ACTIVE.
5. Background task → orchestrator resumes.

Retry can be invoked on any status except ACTIVE (to prevent double-drive).

## Cancel

`POST /api/chat/{id}/cancel` → `session.status = PAUSED`. The orchestrator checks status at each iteration and exits cleanly when it sees PAUSED. Mid-flight tool calls (LLM requests, MCP calls) complete but no new ones are issued.

## Error handling

- If a tool call fails: `ToolCall.status = FAILED`. The LLM sees the error message as the tool result. It may recover on the next iteration.
- If max_iterations reached without `done()`: AgentRun FAILED. Planner re-evaluates; may retry or escalate.
- If planner itself fails repeatedly: session FAILED with `error_message`.

## Database guarantees

Every status transition is in a transaction that also updates `updated_at`. Row-level locks (`lock_for_retry`, `lock_for_resume`) prevent concurrent drivers.
