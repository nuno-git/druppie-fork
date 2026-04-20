# DB Models

`druppie/db/models/` — SQLAlchemy 2.0 ORM classes. All use a single `Base` from `base.py`; all tables are created by `Base.metadata.create_all()` at startup. No migrations — schema changes ship with a reset.

## Common column patterns

- Every table has a UUID primary key (default `uuid.uuid4`).
- Timestamps are timezone-aware UTC (`DateTime(timezone=True)` with `server_default=func.now()`).
- Cascade: every child table has `ondelete="CASCADE"` on its FK to the parent aggregate (e.g. session, project).
- JSON columns: only for opaque payloads never queried — tool `arguments`, `result`, LLM `request_messages`, `response_tool_calls`, `tools_provided`, choice arrays. Everything queryable is a proper column.

## Entities

### `users` (`user.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | = Keycloak `sub` |
| username | VARCHAR(255) UNIQUE NOT NULL | |
| email | VARCHAR(255) | |
| display_name | VARCHAR(255) | |
| created_at, updated_at | TIMESTAMP | |

Children (cascade delete):
- `user_roles`: `(user_id, role)` composite PK. One row per role the user has.
- `user_tokens`: external service tokens (service, access_token, refresh_token, expires_at).

### `projects` (`project.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | VARCHAR(255) NOT NULL | |
| description | TEXT | |
| repo_name | VARCHAR(255) | Gitea repo slug |
| repo_owner | VARCHAR(255) | Gitea owner (usually "druppie") |
| repo_url | VARCHAR(512) | Full public URL |
| clone_url | VARCHAR(512) | |
| owner_id | UUID FK users(id) | |
| status | VARCHAR(20) | `active`, `archived` |
| created_at, updated_at | TIMESTAMP | |

### `sessions` (`session.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK users(id) | |
| project_id | UUID FK projects(id) ON DELETE CASCADE | Nullable for general_chat |
| title | VARCHAR(500) | Derived from first user message |
| status | VARCHAR(20) | SessionStatus values |
| error_message | TEXT | Set when FAILED |
| intent | VARCHAR(50) | `create_project`, `update_project`, `general_chat` |
| branch_name | VARCHAR(255) | For update_project sessions |
| language | VARCHAR(10) | Detected; e.g. "nl", "en" |
| prompt_tokens, completion_tokens, total_tokens | INT | Aggregate |
| created_at, updated_at | TIMESTAMP | |

### `agent_runs` + `messages` (`agent_run.py`)

`agent_runs`:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_id | VARCHAR(100) NOT NULL | e.g. `business_analyst` |
| parent_run_id | UUID FK agent_runs(id) | For nested runs (execute_coding_task sub-agents) |
| status | VARCHAR(20) | AgentRunStatus values |
| error_message | TEXT | |
| iteration_count | INT | How many LLM calls this run has made |
| planned_prompt | TEXT | Planner writes this; actual LLM prompt is larger |
| sequence_number | INT | Execution order within session (0, 1, 2…) |
| prompt_tokens, completion_tokens, total_tokens | INT | |
| started_at, completed_at, created_at | TIMESTAMP | |

`messages`:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_run_id | UUID FK agent_runs(id) | Nullable for user messages |
| role | VARCHAR(20) | `user`, `assistant`, `system`, `tool` |
| content | TEXT NOT NULL | |
| agent_id | VARCHAR(100) | Which agent produced an `assistant` message |
| tool_name | VARCHAR(200) | For `tool` messages |
| tool_call_id | VARCHAR(100) | For `tool` messages, links to tool call |
| sequence_number | INT NOT NULL | Ordering within session |
| created_at | TIMESTAMP | |

### `llm_calls` (`llm_call.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_run_id | UUID FK agent_runs(id) | |
| provider | VARCHAR(50) NOT NULL | `zai`, `deepinfra`, `openai`, `deepseek`, `foundry`, `ollama` |
| model | VARCHAR(100) NOT NULL | |
| prompt_tokens, completion_tokens, total_tokens | INT | |
| duration_ms | INT | |
| request_messages | JSON | Full conversation sent |
| response_content | TEXT | LLM's text output |
| response_tool_calls | JSON | Raw tool calls from LLM |
| tools_provided | JSON | Tool schemas available |
| created_at | TIMESTAMP | |

Has many `tool_calls` (ordered by `tool_call_index`) and `llm_retries`.

### `llm_retries` (`llm_retry.py`)

One row per failed attempt that preceded a successful or final-failed `llm_calls` row. Columns: `id, llm_call_id, attempt, provider, model, error_message, duration_ms, created_at`.

### `tool_calls` (`tool_call.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_run_id | UUID FK agent_runs(id) | |
| llm_call_id | UUID FK llm_calls(id) | |
| mcp_server | VARCHAR(100) NOT NULL | `"builtin"` for builtin tools |
| tool_name | TEXT NOT NULL | |
| tool_call_index | INT | Order in the LLM response (0, 1, 2…) |
| arguments | JSON | As provided by LLM (possibly normalised) |
| status | VARCHAR(20) | ToolCallStatus values |
| result | TEXT | Tool output (truncated if huge) |
| error_message | TEXT | |
| created_at, executed_at | TIMESTAMP | |
| sandbox_waiting_at | TIMESTAMP | Watchdog uses this to detect stuck calls |

Properties on the ORM class:
- `definition` — looks up the tool in `ToolRegistry`.
- `full_name` — `"server_tool"` or just `"tool"` for builtin.

### `tool_call_normalizations` (`tool_call_normalization.py`)

Audit trail for argument normalization. One row per field that was auto-corrected. Used in the admin UI to debug schema drift.

### `approvals` (`approval.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_run_id | UUID FK agent_runs(id) | |
| tool_call_id | UUID FK tool_calls(id) | |
| mcp_server | VARCHAR(100) | |
| tool_name | VARCHAR(200) | |
| required_role | VARCHAR(50) | Realm role or `"session_owner"` |
| status | VARCHAR(20) | ApprovalStatus |
| resolved_by | UUID FK users(id) | |
| resolved_at | TIMESTAMP | |
| rejection_reason | TEXT | |
| arguments | JSON | Snapshot of tool args at approval time |
| agent_id | VARCHAR(100) | For audit |
| created_at | TIMESTAMP | |

### `questions` (`question.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| session_id | UUID FK sessions(id) ON DELETE CASCADE | |
| agent_run_id | UUID FK agent_runs(id) | |
| tool_call_id | UUID FK tool_calls(id) | |
| agent_id | VARCHAR(50) | |
| question | TEXT NOT NULL | |
| question_type | VARCHAR(20) | `text`, `single_choice`, `multiple_choice` |
| choices | JSON | `[{"text": "…"}, …]` |
| selected_indices | JSON | `[0, 2]` |
| status | VARCHAR(20) | QuestionStatus |
| answer | TEXT | |
| answered_at | TIMESTAMP | |
| agent_state | JSON | State snapshot for resumption |
| created_at | TIMESTAMP | |

### `sandbox_sessions` (`sandbox_session.py`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | Sandbox session ID (not Druppie session) |
| tool_call_id | UUID FK tool_calls(id) | |
| druppie_session_id | UUID FK sessions(id) | |
| user_id | UUID FK users(id) | |
| webhook_secret | VARCHAR(255) | Random per-session HMAC key |
| control_plane_url | VARCHAR(512) | |
| events_snapshot | JSON | Last fetched event list (for offline replay) |
| status | VARCHAR(20) | running, completed, failed, timeout |
| started_at, completed_at, created_at | TIMESTAMP | |

### `project_dependencies` (`project_dependency.py`)

Discovered in sandbox output (npm/pip/pnpm/bun/uv installs). One row per `(project, manager, name, version)`:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK projects(id) ON DELETE CASCADE | |
| manager | VARCHAR(30) | `npm`, `pnpm`, `pip`, `uv`, `bun` |
| name | VARCHAR(255) | |
| version | VARCHAR(100) | |
| discovered_at | TIMESTAMP | |

## Evaluation tables

### `benchmark_runs`
Groups a set of `evaluation_results` or `test_runs`. Columns: id, name, run_type (batch/live/manual), git_commit, git_branch, judge_model, config_summary, started_at, completed_at.

### `evaluation_results`
Per-rubric judge scoring. Columns: id, benchmark_run_id, session_id, agent_run_id, agent_id, evaluation_name, rubric_name, score_type (binary/graded), score_binary, score_graded, max_score, judge_model, judge_prompt/response/reasoning, llm_model/provider, judge_duration_ms, judge_tokens_used. Indexes: agent_id, rubric_name, benchmark_run_id, created_at.

### `test_runs`
One row per test execution. Columns: id, benchmark_run_id, test_name, test_description, test_user, hitl_profile, judge_profile, sessions_seeded, assertions_total/passed, judge_checks_total/passed, session_id, status (passed/failed/error), duration_ms, batch_id, agent_id, mode (tool/agent), created_at. Indexes: created_at, agent_id.

### `test_batch_runs`
Batch-level status (persists across process restarts). Columns: id (batch_id), status (running/completed/failed), message, current_test, total_tests, started_at, completed_at.

### `test_assertion_results`
Per-assertion result. Columns: id, test_run_id, assertion_type (completed, tool_called, judge_check, result_valid, verify, status_check), agent_id, tool_name, eval_name, passed, message, judge_reasoning/raw_input/raw_output, created_at. Indexes: test_run_id, agent_id, eval_name, tool_name, assertion_type.

### `test_run_tags`
`(test_run_id, tag)` rows for filtering.

## Relationship cardinalities

```
users 1 ─── * sessions ─── * agent_runs ─── * llm_calls ─── * tool_calls
                                         ─── * messages
                                         ─── * approvals (1 per paused tool call)
                                         ─── * questions
                                         ─── * sandbox_sessions

projects 1 ─── * sessions
           ─── * project_dependencies

benchmark_runs 1 ─── * evaluation_results
                ─── * test_runs ─── * test_assertion_results
                                ─── * test_run_tags
```
