# Entities

High-level inventory of every persistent entity. Grouped by aggregate.

## User aggregate

- **users** — identity. One row per Keycloak user (PK = token `sub`).
- **user_roles** — `(user_id, role)` composite PK. Cascade delete on user removal.
- **user_tokens** — external service credentials (Gitea, SharePoint). Service-scoped with expiry.

## Project aggregate

- **projects** — one Gitea repo. Has owner_id → users.
- **project_dependencies** — discovered packages per project (manager, name, version).

Cascade: deleting a project deletes dependencies.

## Session aggregate

The core workflow aggregate. All agent work is scoped to a session.

- **sessions** — a conversation. Has user_id, optional project_id, status, intent, tokens aggregate.
- **messages** — user/assistant/system/tool messages. Sequenced.
- **agent_runs** — one execution of one agent. Sequenced within session.
- **llm_calls** — one LLM invocation within an agent run. Has provider, model, tokens, duration.
- **llm_retries** — one per retry attempt before a successful/final-failed llm_calls row.
- **tool_calls** — one tool invocation within an LLM call. Has status, arguments, result.
- **tool_call_normalizations** — audit rows for argument auto-corrections.
- **approvals** — one approval gate instance, tied to a specific tool_call.
- **questions** — one HITL question instance, tied to a specific tool_call.
- **sandbox_sessions** — one `execute_coding_task` invocation, tied to a specific tool_call.

Cascade: deleting a session deletes all of the above.

## Evaluation aggregate

Separate from sessions — built around benchmark runs:

- **benchmark_runs** — groups evaluation_results OR test_runs from a single batch.
- **evaluation_results** — legacy v1 evaluation rows (judge-scored).
- **test_runs** — v2 test run rows (from YAML test execution).
- **test_run_tags** — many-to-many tags.
- **test_assertion_results** — per-assertion result within a test run (completed, tool_called, verify, judge_check, etc.).
- **test_batch_runs** — batch-level progress row (UI polls this).

Cascade: deleting a benchmark_run cascades to results/test_runs.

## Standalone

- (no session FK) — `test_batch_runs` (lives for the duration of a batch run), user_tokens.

## Principles

- **UUID PKs everywhere** — default `uuid.uuid4`.
- **Timestamps are timezone-aware UTC**.
- **JSON only for opaque payloads** — arguments, result, request_messages, response_tool_calls, tools_provided, choices, selected_indices.
- **Queryable data is a proper column** — status, agent_id, tool_name, rubric_name, etc. get their own columns with indexes.
- **Cascade deletes on parent aggregate removal** — session delete removes all children, project delete removes dependencies.

## Typical row counts

For a single-user team using Druppie actively for a month:

| Table | ~rows |
|-------|-------|
| users | 5-20 |
| projects | 10-50 |
| sessions | 100-500 |
| agent_runs | 1,000-5,000 |
| llm_calls | 5,000-20,000 |
| tool_calls | 20,000-100,000 |
| approvals | 500-2,000 |
| questions | 200-1,000 |
| test_runs | 500-5,000 |
| test_assertion_results | 5,000-50,000 |

PostgreSQL on default config handles this easily. Indexes on `created_at` + `agent_id` + `session_id` keep list queries fast.
