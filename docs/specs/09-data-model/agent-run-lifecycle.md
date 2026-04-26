# Agent Run Lifecycle

State machine for `agent_runs.status`.

```
      ┌─────────┐
      │ PENDING │ ◄── planner inserts (via make_plan) or router+planner seeded
      └────┬────┘
           │ orchestrator picks it up
           ▼
      ┌─────────┐
      │ RUNNING │
      └───┬──┬──┘
          │  │ iteration loop
          │  │ LLM call → tool executor → LLM call → ... → done()
          │  │
          │  │ tool returned a waiting status
          │  ▼
          │  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
          │  │ PAUSED_TOOL  │     │ PAUSED_HITL  │     │PAUSED_SANDBOX│
          │  │(approval gate│     │ (question)   │     │              │
          │  │              │     │              │     │              │
          │  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
          │         │                    │                    │
          │         │ resolved           │ answered           │ webhook
          │         └─────────┬──────────┴────────────────────┘
          │                   │
          │                   ▼
          │                RUNNING (continue loop)
          │
          │ done() called
          ▼
    ┌───────────┐
    │ COMPLETED │  agent added its summary to the relay
    └───────────┘

    RUNNING ──► FAILED  (max iterations OR unhandled exception)
    PENDING ──► CANCELLED (BoundedOrchestrator halts; retry deletes)
    PENDING ──► PAUSED_USER (zombie recovery; startup moved unfinished back)
```

## States

| State | Meaning |
|-------|---------|
| `PENDING` | Created, not yet started. Waiting for orchestrator. |
| `RUNNING` | Loop executing: LLM calls + tool calls. |
| `PAUSED_TOOL` | Tool call WAITING_APPROVAL — agent loop exited. |
| `PAUSED_HITL` | Tool call WAITING_ANSWER — agent loop exited. |
| `PAUSED_SANDBOX` | Tool call WAITING_SANDBOX — agent loop exited. |
| `PAUSED_USER` | Startup recovery moved this from RUNNING. |
| `COMPLETED` | Called `done()`. Terminal. |
| `FAILED` | Error or max iterations. Terminal. |
| `CANCELLED` | BoundedOrchestrator or session-cancel removed this before start. Terminal. |

## Transition code

- PENDING → RUNNING — `execute_pending_runs` picks it.
- RUNNING → PAUSED_* — mirrors the tool call's WAITING_* status.
- PAUSED_* → RUNNING — `resume_after_*()`.
- RUNNING → COMPLETED — `done()` handler.
- RUNNING → FAILED — max iterations or exception.
- PENDING → CANCELLED — `cancel_remaining_pending_runs()` (bounded orchestrator or explicit cancel).
- Any RUNNING → PAUSED_USER — startup zombie recovery.

## Planner runs

The planner is itself an agent run with the same lifecycle. It can PAUSE_HITL (via a `hitl_ask_question` when escalating), PAUSE_TOOL (rare — planner's only tools are `make_plan` + `done`), or COMPLETE normally.

## Nested runs

When an agent calls `execute_coding_task`, no nested agent run is created in the parent session — the sandbox has its own universe. But when a sub-agent within Druppie (e.g. a planner sub-run) is spawned, `parent_run_id` links the child.

## Iteration count

`agent_runs.iteration_count` increments once per LLM call. If an agent's YAML specifies `max_iterations: 50` and `iteration_count == 50` without `done()`, the run goes FAILED. Agents with budget-heavy work (builder: 100, business_analyst: 50) have higher caps.

## Retry behaviour

- If the planner decides to re-run the same agent (e.g. builder after test failure), a NEW PENDING run is inserted with a different `planned_prompt` reflecting the failure feedback. The original FAILED run stays for auditability.
- Retry-from-run (user action) deletes runs downstream of the target and inserts one new PENDING for the target agent.
