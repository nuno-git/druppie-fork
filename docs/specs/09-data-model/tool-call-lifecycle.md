# Tool Call Lifecycle

State machine for `tool_calls.status`.

```
      ┌─────────┐
      │ PENDING │ ◄── LLM emitted the tool call; row inserted
      └────┬────┘
           │ ToolExecutor.execute()
           ▼
      ┌───────────────────────────┐
      │ classification & approval │
      └──┬──┬──┬───────────┬──────┘
         │  │  │           │
         │  │  │           │ builtin or MCP without approval
         │  │  │           ▼
         │  │  │      ┌─────────┐
         │  │  │      │EXECUTING│
         │  │  │      └──┬──────┘
         │  │  │         │ result
         │  │  │         ▼
         │  │  │    COMPLETED / FAILED
         │  │  │
         │  │  └─────────────┐  execute_coding_task
         │  │                ▼
         │  │       ┌──────────────────┐
         │  │       │WAITING_SANDBOX   │
         │  │       └────────┬─────────┘
         │  │                │ webhook
         │  │                ▼
         │  │          COMPLETED / FAILED
         │  │
         │  └─────────────┐  HITL tool
         │                ▼
         │       ┌──────────────────┐
         │       │ WAITING_ANSWER   │
         │       └────────┬─────────┘
         │                │ user answer
         │                ▼
         │                COMPLETED
         │
         └────────────────┐  approval-gated MCP
                          ▼
                 ┌──────────────────┐
                 │WAITING_APPROVAL  │
                 └────────┬─────────┘
                          │ approve → executes
                          │ reject  → FAILED
                          ▼
                    EXECUTING → COMPLETED / FAILED
```

## States

| State | Meaning |
|-------|---------|
| `PENDING` | Inserted, not yet dispatched. |
| `WAITING_APPROVAL` | Approval gate fired; row in `approvals` awaits. |
| `WAITING_ANSWER` | HITL question row in `questions` awaits. |
| `WAITING_SANDBOX` | Sandbox spawned, awaiting webhook. |
| `EXECUTING` | In flight (MCP call or builtin handler). |
| `COMPLETED` | Result stored. Terminal. |
| `FAILED` | Error stored. Terminal. |

## How PENDING moves

`ToolExecutor.execute()` classifies the tool:
1. HITL tool → create Question → WAITING_ANSWER.
2. Needs approval → create Approval → WAITING_APPROVAL.
3. `execute_coding_task` → create SandboxSession + call control plane → WAITING_SANDBOX.
4. Builtin — run in-process → EXECUTING → COMPLETED.
5. MCP — call HTTP → EXECUTING → COMPLETED.

## Approval resolution path

1. Approval row UPDATEd to APPROVED.
2. `_resume_workflow_after_approval()` spawns the resume task.
3. Resume task executes the tool (same args stored in `approvals.arguments`).
4. Tool call → EXECUTING → COMPLETED.

If REJECTED, the tool call goes directly to FAILED with a `rejection_reason` in the result. The agent sees the rejection and can react (typically by giving up or asking the user).

## Sandbox webhook path

1. Control plane POSTs `/sandbox-sessions/{id}/complete` with HMAC.
2. Webhook handler locks the tool_call FOR UPDATE, extracts result, sets COMPLETED.
3. Sandbox session row updated with events snapshot.
4. Resume task fires if parent agent run is PAUSED_SANDBOX.

## Idempotency

The webhook handler checks `tool_call.status` under the row lock. If already COMPLETED, returns 200 noop. This tolerates duplicate webhooks (control plane retries).

## Watchdog

`sandbox_watchdog_loop()` queries `tool_calls WHERE status = WAITING_SANDBOX AND sandbox_waiting_at < NOW() - SANDBOX_TIMEOUT_MINUTES`. For each: FAILED + propagate to agent run + session.

## Long-running tools

`LONG_RUNNING_TOOLS` map overrides the default 60 s HTTP timeout:
- `coding:run_tests` → 1200 s.
- `coding:install_test_dependencies` → 1200 s.
- `docker:compose_up` → 1200 s.

Set in `druppie/execution/tool_executor.py`. Exceeding the timeout marks the tool call FAILED.

## Normalizations

`tool_call_normalizations` rows capture argument auto-corrections. Example row: `(tool_call_id, field_name="deps_list", original_value='"null"', normalized_value=None, reason="LLM supplied string 'null'")`. Viewed in the admin DB browser for debugging LLM schema drift.
