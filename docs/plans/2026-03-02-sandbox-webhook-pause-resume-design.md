# Design: Sandbox Webhook + Pause/Resume

**Date:** 2026-03-02
**Branch:** feature/execute-coding-task
**Status:** Approved

## Problem

`execute_coding_task` holds an HTTP connection open for up to 25 hours (90,000s timeout in tool_executor.py). The MCP coding server polls the sandbox control plane every 5s in a blocking loop. This blocks the agent loop, the orchestrator, and ties up a DB session. Any network hiccup or container restart kills the task with no recovery.

## Solution

Replace the long-running MCP tool with a **built-in tool + webhook callback + pause/resume** pattern:

1. Built-in tool creates sandbox session, sends prompt, pauses the agent
2. Control plane sends a webhook to Druppie when the sandbox completes
3. Druppie receives the webhook, fetches results, resumes the agent

## Status Model

Three levels get a new status, following existing naming patterns:

| Level | Existing pause states | New state |
|-------|----------------------|-----------|
| `ToolCallStatus` | `WAITING_APPROVAL`, `WAITING_ANSWER` | `WAITING_SANDBOX` |
| `AgentRunStatus` | `PAUSED_TOOL`, `PAUSED_HITL` | `PAUSED_SANDBOX` |
| `SessionStatus` | `PAUSED_APPROVAL`, `PAUSED_HITL` | `PAUSED_SANDBOX` |

### Flow

```
Agent calls execute_coding_task
  -> ToolCall created, status = WAITING_SANDBOX
  -> AgentRun status = PAUSED_SANDBOX
  -> Session status = PAUSED_SANDBOX
  -> Agent loop returns (frees the thread)

Webhook arrives from control plane
  -> ToolCall status = COMPLETED (result filled with sandbox output)
  -> AgentRun status = RUNNING
  -> Session status = ACTIVE
  -> Agent loop resumes via continue_run()
```

## Built-in Tool

`execute_coding_task` moves from MCP tool (coding server) to built-in tool. It does only quick work:

1. **Create sandbox session** - POST to control plane with `callbackUrl` and `callbackSecret` (~1s)
2. **Send prompt** - POST to control plane (~1s)
3. **Register ownership** - POST to Druppie backend (~1s)
4. **Return `WAITING_SANDBOX`** - agent loop pauses, thread freed

```
execute_coding_task (built-in tool)
  +-- POST /sessions  {callbackUrl, callbackSecret, ...}
  +-- POST /sessions/{id}/prompt  {task, agent}
  +-- POST /api/sandbox-sessions/internal/register  {ownership}
  +-- return WAITING_SANDBOX + {sandbox_session_id}
```

The `callbackUrl` is `http://druppie-backend:8000/api/sandbox-sessions/{sandbox_session_id}/complete`.

No git pull here - that moves to the resume handler (after webhook confirms completion).

Context injection (session_id, repo_name, user_id) extends through `execute_builtin()` which already receives session_id and agent_run_id. Project context (repo info, user_id) is passed alongside.

## Control Plane Webhook (background-agents fork)

When creating a session, accept optional `callbackUrl` and `callbackSecret` fields. Store on the session row. When `notifyComplete()` fires, check for `callbackUrl` first - if set, POST directly instead of routing through Slack/Linear service bindings.

```typescript
// POST /sessions accepts:
callbackUrl?: string    // direct HTTP callback target
callbackSecret?: string // shared HMAC secret for signing

// On completion, CallbackNotificationService does:
if (session.callback_url) {
  const payload = { sessionId, messageId, success, timestamp };
  const signature = await signPayload(payload, session.callback_secret);
  await fetch(session.callback_url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Signature": signature },
    body: JSON.stringify(payload),
  });
  return;
}
// ... existing Slack/Linear routing
```

Webhook payload is intentionally small (no events/files). The resume handler fetches those itself. Retry: 2 attempts, 1s delay (matching existing behavior).

## Druppie Webhook Receiver & Resume

New endpoint: `POST /api/sandbox-sessions/{sandbox_session_id}/complete`

```
POST /api/sandbox-sessions/{id}/complete
  +-- verify HMAC signature
  +-- find WAITING_SANDBOX tool_call
  +-- GET /sessions/{id}/events (final fetch from control plane)
  +-- extract changed_files + agent_output
  +-- git pull (sync workspace)
  +-- tool_call.result = {success, changed_files, agent_output, ...}
  +-- tool_call.status = COMPLETED
  +-- orchestrator.resume_after_sandbox(tool_call_id)
        +-- agent_run.status = RUNNING
        +-- session.status = ACTIVE
        +-- agent.continue_run()
```

Error cases:
- **Sandbox failed:** Same flow, `success=false`. Tool call completes with failure info. Agent decides how to handle.
- **Webhook never arrives:** Tool call stays WAITING_SANDBOX. UI shows stale warning after X hours. User can manually cancel.

## File Map

### Druppie repo

| File | Change |
|------|--------|
| `druppie/domain/common.py` | Add `PAUSED_SANDBOX` to `SessionStatus` and `AgentRunStatus` |
| `druppie/execution/tool_executor.py` | Add `WAITING_SANDBOX` to `ToolCallStatus`. Remove 90,000s timeout hack |
| `druppie/agents/builtin_tools.py` | Add `execute_coding_task` to `BUILTIN_TOOLS`. Implement create-session + send-prompt + register-ownership |
| `druppie/agents/loop.py` | Handle `WAITING_SANDBOX` (pause and return, same as WAITING_APPROVAL). Keep `_enrich_execute_coding_task` |
| `druppie/execution/orchestrator.py` | Add `resume_after_sandbox(tool_call_id)` following `resume_after_approval` pattern |
| `druppie/api/routes/sandbox.py` | Add `POST /sandbox-sessions/{id}/complete` webhook with HMAC verification. Event fetching, file extraction, git pull logic moves here |
| `druppie/mcp-servers/coding/server.py` | Remove `execute_coding_task` function (~400 lines deleted) |
| `druppie/core/mcp_config.yaml` | Remove `execute_coding_task` from coding MCP tools |
| `druppie/core/tool_registry.py` | Move registration to builtin |
| `druppie/tools/params/coding.py` | Keep `ExecuteCodingTaskParams` (still needed for schema) |

### background-agents repo (fork)

| File | Change |
|------|--------|
| `packages/control-plane/src/session/types.ts` | Add `callback_url`, `callback_secret` to `SessionRow` |
| `packages/control-plane/src/router.ts` | Accept `callbackUrl` + `callbackSecret` in POST /sessions |
| `packages/control-plane/src/session/session-instance.ts` | Pass callback fields through to session DO |
| `packages/control-plane/src/session/callback-notification-service.ts` | Add direct HTTP POST path when `callback_url` is set |
| DB schema / D1 migration | Add two columns to sessions table |

### Net effect

- ~400 lines removed from `server.py`
- ~150 lines added across builtin tool + webhook handler + orchestrator resume
- ~30 lines changed in background-agents
- 90,000s timeout hack deleted
