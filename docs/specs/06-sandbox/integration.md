# Druppie ↔ Sandbox Integration

How Druppie's agents call sandboxes and handle their results.

## Trigger

An agent calls `execute_coding_task(task, agent?, repo_target?)`. The builtin handler:

1. Looks up the session's associated project repo.
2. Generates a per-session `webhook_secret` (random 32 bytes hex).
3. Calls Druppie's OWN internal `POST /api/sandbox-sessions/internal/register` (verified with `INTERNAL_API_KEY` HMAC) to create the `SandboxSession` DB row. This gives it a `sandbox_session_id`.
4. Calls the sandbox control plane (`POST {SANDBOX_CONTROL_PLANE_URL}/sessions`) with payload:
   ```
   {
     session_id: <sandbox_session_id>,
     repo_owner, repo_name, branch,
     task, agent_name,
     control_plane_url: <druppie_url>,        # webhook target
     webhook_secret: <secret>,
     sandbox_auth_token: <random_token>,
   }
   ```
5. Marks the current `tool_call.status = WAITING_SANDBOX`.
6. Returns from the tool handler. The agent run pauses.

## Sandbox execution

The control plane calls `local-sandbox-manager` which spawns a Docker container from `open-inspect-sandbox:latest`. The container:
- Clones the repo via GitHub App token.
- Runs OpenCode with the task prompt.
- Streams events (tool_call, tool_result, token, git_sync) over WebSocket to the control plane.
- On completion: commits, pushes, emits `completed` event, exits.

## Webhook

When the sandbox finishes, the control plane calls:

```
POST {DRUPPIE_URL}/api/sandbox-sessions/{sandbox_session_id}/complete
X-Druppie-Signature: hmac-sha256(body, webhook_secret)
body: {
  status: "completed"|"failed"|"timeout",
  completed_at: <iso>,
  reason?: <string>,
  events_url?: <string>,
  artifacts?: [...],
}
```

## Druppie webhook handler (`druppie/api/routes/sandbox.py`)

800+ lines because of idempotency + result extraction:

1. Verify HMAC against the session's `webhook_secret`. 401 if mismatch.
2. `SELECT … FOR UPDATE` on `tool_calls` row for idempotency. If already COMPLETED, return 200 no-op.
3. Fetch full event list from control plane (`GET {control_plane_url}/sessions/{id}/events`).
4. Extract:
   - `_extract_changed_files()` — find writes/edits via file system events.
   - `_extract_git_operations()` — commits, branches, PR URLs from git_sync events.
   - `_extract_agent_output()` — concatenate token events, strip `<think>` tags.
   - `_extract_tool_results_summary()` — summarise tool call outputs.
5. Build a human-readable `agent_result_text` — this becomes the tool call's `result` field.
6. Update `tool_call.status = COMPLETED|FAILED`, `.result`.
7. Update `sandbox_session.events_snapshot` and `completed_at`.
8. Extract discovered packages and insert `ProjectDependency` rows.
9. If the parent `agent_run.status == PAUSED_SANDBOX`, spawn a resume task.
10. Return 200.

## Events snapshot

The full event list is persisted in `sandbox_sessions.events_snapshot` as JSON. The frontend uses this to render the `SandboxEventCard` timeline even after the live connection is gone. Paginated via `GET /api/sandbox-sessions/{id}/events?cursor=…&limit=500`.

## Watchdog

`sandbox_watchdog_loop()` (runs every 5 min by default):
1. Query `tool_calls WHERE status = WAITING_SANDBOX AND sandbox_waiting_at < NOW() - SANDBOX_TIMEOUT_MINUTES`.
2. For each: mark tool call FAILED, parent agent run FAILED, parent session FAILED.
3. Call `DELETE {control_plane_url}/sessions/{id}` to clean up.
4. Clean up orphan Gitea sandbox accounts.

`SANDBOX_TIMEOUT_MINUTES` default 30. `DEFAULT_SANDBOX_TIMEOUT_SECONDS` in sandbox-manager is 7200 (2 h) — so Druppie will mark a tool call failed long before the sandbox hits its own ceiling.

## Env vars

On Druppie backend:
- `SANDBOX_CONTROL_PLANE_URL=http://sandbox-control-plane:8787`.
- `SANDBOX_MANAGER_URL=http://sandbox-manager:8000` (not called by Druppie directly, but referenced).
- `SANDBOX_API_SECRET` — shared HMAC with the control plane (for the sandbox register endpoint).
- `SANDBOX_TIMEOUT_MINUTES=30`.
- `SANDBOX_WATCHDOG_INTERVAL_SECONDS=300`.

## Result extraction example

A builder-sandbox run that edited 3 files and pushed 1 commit produces:

```
Agent druppie-builder completed:

Files changed:
- app/routes.py (modified): added /tasks POST endpoint
- app/models.py (modified): added Task ORM model
- tests/test_tasks.py (created): 5 test cases

Git:
- Commit: feature/add-tasks @ abc1234
- Pushed to origin

Tool call summary:
- 12 file operations
- 3 bash commands (pytest runs)
- 2 git operations
```

This text becomes the builder agent's tool call result. The builder then calls `coding:run_git(command="pull")` to sync the sandbox's commits and `done()` with its summary.
