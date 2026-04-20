# Services

`druppie/services/` — business logic, authorization, orchestration across repositories. Each service is constructed per-request via FastAPI `Depends()`, receives a SQLAlchemy `Session` and the repositories it needs, and returns domain models (never ORM models).

## SessionService

`druppie/services/session_service.py` (132 lines)

| Method | Purpose | Notable detail |
|--------|---------|----------------|
| `get_detail(id, user_id, roles)` | Full SessionDetail with authz | Raises `AuthorizationError` if not owner and not admin |
| `list_for_user(user_id, page, limit, status)` | Paginated list | `user_id=None` returns all (admin path) |
| `delete(id, user_id, roles)` | Cascade delete | Owner or admin |
| `lock_for_retry(id)` | Atomic lock + set ACTIVE | `SELECT … FOR UPDATE`; raises plain `ValueError` if the session is missing or already `ACTIVE` (routes translate to HTTP 409) |
| `lock_for_resume(id)` | Atomic lock + set ACTIVE | Allows PAUSED_*, PAUSED_CRASHED, FAILED; raises `ValueError` for other states |
| `mark_failed(id, msg)` | Set FAILED status | Used when background task spawn fails |

Lock/unlock is important: without it, two users clicking "Retry" on the same session both spawn background tasks which race.

> **Exception-type caveat.** The "raises ConflictError" pattern advertised in `02-backend/errors.md` is not yet used by `SessionService` — the current implementation raises bare `ValueError`, and the route layer converts to `HTTPException(409, …)`. The user-visible behaviour is the same; the internal exception type is not `ConflictError`. (Tracked for cleanup.)

## ApprovalService

`druppie/services/approval_service.py` (~150 lines)

| Method | Purpose |
|--------|---------|
| `get_pending_for_roles(roles, user_id)` | Pending actionable approvals |
| `get_history_for_roles(roles, user_id, page, limit)` | Resolved approvals |
| `approve(id, user_id, roles)` | → APPROVED, returns ApprovalDetail |
| `reject(id, user_id, roles, reason)` | → REJECTED with reason |

Authorization (`_check_authorization`):
- admin → always allowed
- `required_role` matches any user role → allowed
- `required_role == "session_owner"` AND `session.user_id == user_id` → allowed
- else → `AuthorizationError`

The `session_owner` sentinel is stored literally in `approvals.required_role`; the repository joins the session table to supply `session_user_id` in `ApprovalDetail`.

## QuestionService

`druppie/services/question_service.py` (~120 lines)

| Method | Purpose |
|--------|---------|
| `list_pending(session_id?)` | Pending questions, optionally filtered |
| `get_detail(id)` | Detail with choices populated |
| `answer(id, user_id, answer, selected_choices, is_admin)` | Save answer, return detail |
| `cancel(id, user_id, is_admin)` | Cancel without answering |

Authorization: owner of the parent session, or admin. When `selected_choices` is provided, the stored `answer` is a display string built from the chosen option texts (so the agent sees a readable answer, not indices).

## ProjectService

`druppie/services/project_service.py` (~95 lines)

| Method | Purpose |
|--------|---------|
| `list_for_user(user_id, page, limit)` | Paginated |
| `list_all(page, limit)` | Admin path |
| `get_detail(id, user_id, roles)` | With tokens, sessions, deployment info |
| `delete(id, user_id, roles)` | Delete row + async delete Gitea repo |

`delete()` calls `gitea.delete_repo()` in a `try/except` — Gitea failures log warnings but don't block the DB deletion. This is deliberate: the project row in DB is the canonical record.

## DeploymentService

`druppie/services/deployment_service.py`

Proxies to `module-docker` over HTTP (using `MCPHttp`). Adds ownership filtering and label inspection:

| Method | Purpose |
|--------|---------|
| `list_deployments(user_id, roles, project_id?)` | Calls `docker:list_containers`, filters by `druppie.user_id` label for non-admins |
| `get_logs(container_name, user_id, roles, tail)` | Ownership check via inspect, then `docker:logs` |
| `stop(container_name, user_id, roles, remove)` | Ownership check, then `docker:stop` or `docker:remove` |
| `inspect(container_name, user_id, roles)` | Ownership check, return full inspect |

## EvaluationService

`druppie/services/evaluation_service.py` (~150 lines)

Split across three concerns:
- **Benchmark runs**: `list_benchmark_runs()`, `get_benchmark_run_detail()`, `delete_benchmark_run()`
- **Evaluation results**: `list_results(filters)`, `get_result_detail()`, `get_agent_summary(agent_id)`
- **Test runs** (v2): `list_test_runs()`, `get_test_run_detail()`, `list_test_batches()`

`get_agent_summary(agent_id)` returns `{total, binary_pass_rate, graded_avg}` — used by the Analytics page to show per-agent quality over time.

## WorkflowService

`druppie/services/workflow_service.py`

Higher-level operations composed from multiple services and MCP calls:

- `continue_after_approval(approval_id, user_id, roles)` — approve + spawn resume.
- `revert_session_to_run(session_id, agent_run_id)` — deletes downstream agent runs, tool calls, LLM calls, messages; used by retry-from-run flow.
- `recover_zombie_sessions()` — runs at startup; any session ACTIVE with no running task → PAUSED_CRASHED.

## RevertService

`druppie/services/revert_service.py`

Handles the git side of retry-from-run: calls `coding:_internal_revert_to_commit` to `git reset --hard` the workspace to the commit snapshot associated with the target run, then force-pushes.

Internal tool (name starts with `_internal_`) — not exposed to agents.

## QuestionService / ApprovalService: note on "two-phase"

Both services commit the state change to the DB before spawning the background task that resumes the orchestrator. This means:

- If Druppie crashes between `commit()` and `add_task(…)`, the approval/question is in its new state but the agent run is still PAUSED. The user must manually Resume.
- If the background task itself fails, the agent run's status will reflect the failure (FAILED) and the approval/question remains APPROVED/ANSWERED — which is correct (the user's decision stands).

## GithubAppService

`druppie/services/github_app_service.py`

Supports the `update_core_builder` agent's ability to clone the Druppie source repo and open a PR against it. Loads the GitHub App private key from `GITHUB_APP_PRIVATE_KEY_PATH`, generates installation tokens, and returns them to the sandbox via the control plane.

## SkillService

`druppie/services/skill_service.py`

Loads skill markdown from `druppie/skills/*/SKILL.md` for the `invoke_skill` builtin tool. Parses SKILL.md frontmatter (`name`, `description`, `allowed_tools`) and returns the body as the prompt injection.
