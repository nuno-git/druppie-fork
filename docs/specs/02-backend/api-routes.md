# API Routes

Every HTTP endpoint exposed by the backend. All routes are mounted under `/api` unless noted. Auth headers: `Authorization: Bearer <keycloak_token>` unless noted.

Conventions:
- **Status codes** — 200 OK default; 202 Accepted for background-spawning routes; 401 on missing/invalid token; 403 on authz failure; 404 on NotFoundError; 409 on ConflictError; 422 on ValidationError.
- **Admin bypass** — any endpoint that filters by user_id also returns all rows when the caller has the `admin` role.

## Health / status

`druppie/api/main.py:178-285`

| Method | Path | Purpose | Returns |
|--------|------|---------|---------|
| GET | `/health` | Liveness | `{status: "healthy", version: "2.0.0"}` |
| GET | `/health/ready` | Readiness (DB + agents loaded) | 200 or 503 |
| GET | `/api/status` | Full system health | `{keycloak, database, llm, gitea, agent_count}` |

## Chat

`druppie/api/routes/chat.py` (289 lines)

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| POST | `/api/chat` | `{message, session_id?, project_id?}` | Create session or continue; spawn orchestrator task; return immediately |
| POST | `/api/chat/{session_id}/cancel` | — | Soft pause the session (sets status PAUSED) |

Response: `{success, session_id, status, message}`. Background task: `_run_orchestrator_background()` (line 83) runs `orchestrator.process_message()` and lets the DB session lifecycle be handled by `run_session_task()`.

## Sessions

`druppie/api/routes/sessions.py` (370 lines)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sessions` | Paginated list; `?page=&limit=&status=` |
| GET | `/api/sessions/{id}` | Full `SessionDetail` with chronological timeline |
| DELETE | `/api/sessions/{id}` | Cascade delete session + all children |
| POST | `/api/sessions/{id}/retry-from/{agent_run_id}` | Revert to a past run and re-execute (optional `planned_prompt`) |
| POST | `/api/sessions/{id}/resume` | Resume a PAUSED or FAILED session |

Retry and Resume both use `SessionService.lock_for_retry()` / `lock_for_resume()` which acquire a row-level lock (SELECT … FOR UPDATE) and raise `ConflictError` if the session is already ACTIVE.

Owner-only unless admin. Admins bypass ownership. Invalid state transitions (e.g. resume an ACTIVE session) → 409.

## Approvals

`druppie/api/routes/approvals.py` (264 lines)

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| GET | `/api/approvals` | — | Pending approvals the user can act on |
| GET | `/api/approvals/history` | `?page=&limit=` | Resolved approvals (role-filtered) |
| POST | `/api/approvals/{id}/approve` | — | Update to APPROVED, spawn resume task |
| POST | `/api/approvals/{id}/reject` | `{reason: str 1-1000}` | Update to REJECTED, spawn resume task |

Filtering: returns approvals where `required_role IN user_roles` OR `required_role = "session_owner" AND session.user_id = current_user`. Admin sees everything.

Two-phase workflow: DB update commits, then `_resume_workflow_after_approval()` spawns the orchestrator resume.

## Questions (HITL)

`druppie/api/routes/questions.py` (168 lines)

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| GET | `/api/questions[?session_id=]` | — | Pending questions |
| GET | `/api/questions/{id}` | — | Detail |
| POST | `/api/questions/{id}/answer` | `{answer: str 1-10000, selected_choices?: [int]}` | Answer + resume agent |
| POST | `/api/questions/{id}/cancel` | — | Cancel without answering |

Authorization: session owner, or admin.

## Projects

`druppie/api/routes/projects.py` (153 lines)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects` | Paginated list (owner or admin) |
| GET | `/api/projects/{id}` | Full detail: metadata, tokens, sessions, deployments |
| PATCH | `/api/projects/{id}` | Update project fields |
| DELETE | `/api/projects/{id}` | Delete + async delete Gitea repo |
| GET | `/api/projects/{id}/dependencies` | ProjectDependency rows grouped by manager |
| GET | `/api/projects/{id}/commits?branch=&limit=` | Git commit log via Gitea API |
| GET | `/api/projects/{id}/branches` | Gitea branches |
| GET | `/api/projects/{id}/files?path=&branch=` | File tree |
| GET | `/api/projects/{id}/file?path=&branch=` | File content |
| GET | `/api/projects/{id}/sessions?limit=` | Sessions for this project |
| GET | `/api/projects/{id}/status` | Deployment status summary |

## Deployments

`druppie/api/routes/deployments.py` (378 lines)

Bridges to `module-docker` MCP for running containers.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/deployments[?project_id=]` | Containers; non-admin filtered by `druppie.user_id` label |
| GET | `/api/deployments/{container_name}` | Inspect |
| GET | `/api/deployments/{container_name}/logs?tail=` | Logs |
| POST | `/api/deployments/{container_name}/stop?remove=true` | Stop/remove |

Ownership checked via the `druppie.user_id` Docker label; 403 if mismatch.

## MCPs

`druppie/api/routes/mcps.py` (319 lines)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/mcps` | Servers + role-filtered tools |
| GET | `/api/mcps/servers` | Servers with health status (via each `/health`) |
| GET | `/api/mcps/tools` | Flat list of tools |
| GET | `/api/mcps/tools/{tool_id}` | Single tool details |
| GET | `/api/mcps/{server_id}` | Single server details |
| POST | `/api/mcps/check` | Given `{server, tool}`, return approval requirements |

Tool filtering: check `required_roles`. Admins see all.

## Agents

`druppie/api/routes/agents.py` (160 lines)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/agents` | List all agents (loads from `druppie/agents/definitions/*.yaml`) |
| GET | `/api/agents/{id}` | Single agent YAML as JSON |

Returns `{id, name, description, model, temperature, max_tokens, max_iterations, mcps, category}`. Sorted by category (system, execution, quality, deployment).

## Sandbox

`druppie/api/routes/sandbox.py` (804 lines — large because of webhook + extract logic)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/sandbox-sessions/internal/register` | Internal API key (HMAC) | Sandbox registers ownership (user_id + session_id → sandbox_session_id) |
| POST | `/api/sandbox-sessions/{id}/complete` | HMAC signature in header | Control plane webhook (see `data-flow.md`) |
| GET | `/api/sandbox-sessions/{id}/events` | User token | Proxy events from control plane (or snapshot on failure) |

The complete webhook is the heart of sandbox integration — it extracts file changes, git operations, and agent output, then resumes the paused agent run.

## Evaluations (barrel)

`druppie/api/routes/evaluations.py` (17-line barrel). Mounts three sub-routers:

### Benchmarks (`evaluations_benchmarks.py`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/evaluations/benchmark-runs?page=&limit=&run_type=` | List |
| GET | `/api/evaluations/benchmark-runs/{id}` | Detail with results |
| DELETE | `/api/evaluations/benchmark-runs/{id}` | Cascade delete |
| POST | `/api/evaluations/trigger-benchmark` | Kick off a benchmark |
| GET | `/api/evaluations/config` | Read `evaluation_config.yaml` |
| GET | `/api/evaluations/results?[filters]` | List EvaluationResult rows |
| GET | `/api/evaluations/results/{id}` | Detail |
| GET | `/api/evaluations/agent-summary/{agent_id}` | Aggregated pass rates |

### Tests (`evaluations_tests.py`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/evaluations/available-tests` | Discover YAML tests in `testing/tools/` + `testing/agents/` |
| GET | `/api/evaluations/available-setups` | Setup-only tests (for extending) |
| POST | `/api/evaluations/run-tests` | Enqueue batch, return `{batch_id}` |
| GET | `/api/evaluations/run-status/{batch_id}` | Progress polling |
| GET | `/api/evaluations/active-run` | Is a batch currently running? |
| GET | `/api/evaluations/test-runs?page=&limit=&tag=` | List TestRun rows |
| GET | `/api/evaluations/test-runs/{id}` | Detail |
| GET | `/api/evaluations/test-runs/{id}/assertions` | Assertion breakdown |
| GET | `/api/evaluations/test-batches?page=&limit=&tag=` | Batch list |
| POST | `/api/evaluations/seed` | Seed sessions from fixtures |
| DELETE | `/api/evaluations/test-users` | Clean up test users in Keycloak + Gitea |
| POST | `/api/evaluations/run-unit-tests` | Run pytest suite |
| GET | `/api/evaluations/tags` | Distinct tags |

### Analytics (`evaluations_analytics.py`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/evaluations/analytics/summary?days=` | Pass/fail counts over N days |
| GET | `/api/evaluations/analytics/trends?days=` | Time series |
| GET | `/api/evaluations/analytics/by-agent[?batch_id=]` | Agent-level breakdown |
| GET | `/api/evaluations/analytics/by-eval[?batch_id=]` | Eval-level breakdown |
| GET | `/api/evaluations/analytics/by-tool[?batch_id=]` | Tool-level breakdown |
| GET | `/api/evaluations/analytics/by-test[?batch_id=]` | Test-level breakdown |
| GET | `/api/evaluations/analytics/batch/{id}` | Detailed batch report |
| GET | `/api/evaluations/batch/{id}/assertions[?filters]` | Filtered assertions |
| GET | `/api/evaluations/batch/{id}/filters` | Distinct filter values |

## Admin

Admin routes require the `admin` role via `require_admin`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/admin/stats` | DB row counts, sizes |
| GET | `/api/admin/tables` | List all tables |
| GET | `/api/admin/table/{name}?page=&limit=&order_by=&order_dir=&filter_field=&filter_value=` | Generic paginated table view |
| GET | `/api/admin/table/{name}/{id}` | Single row with foreign-key-followed detail |

## Workspace

`druppie/api/routes/workspace.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/workspace[?session_id=]` | List files in a session workspace |
| GET | `/api/workspace/file?path=&session_id=` | File content |
| GET | `/api/workspace/file/download?path=&session_id=` | Download file |

These proxy to `module-coding`'s workspace for UI file previews (markdown designs, generated code).

## Cache

`druppie/api/routes/cache.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cache/packages` | List cached packages (from sandbox cache volume) |
| GET | `/api/cache/dependencies` | All ProjectDependency rows across projects |
| GET | `/api/cache/packages/{manager}/{name}/projects` | Which projects use a package |

## MCP bridge

`druppie/api/routes/mcp_bridge.py`

Allows the frontend DebugMCP page to call any MCP tool directly:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/mcp/call` | `{server, tool, arguments, session_id?}` → executes via ToolExecutor |
