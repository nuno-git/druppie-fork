# Relationships

FK relationships and cardinalities. Lines below are `one : many` unless marked otherwise.

## Session + execution

```
users 1 ─── * sessions
sessions 1 ─── * agent_runs
sessions 1 ─── * messages
agent_runs 1 ─── * llm_calls
llm_calls 1 ─── * tool_calls
llm_calls 1 ─── * llm_retries
tool_calls 1 ─── 1 approvals  (when gated)
tool_calls 1 ─── 1 questions  (when HITL)
tool_calls 1 ─── 1 sandbox_sessions  (when execute_coding_task)
tool_calls 1 ─── * tool_call_normalizations
agent_runs 1 ─── * agent_runs  (parent_run_id — for nested runs e.g. sandbox sub-agents)
```

Cascade: on `DELETE FROM sessions WHERE id = ?`, everything downstream goes.

## Project

```
users 1 ─── * projects  (owner_id)
projects 1 ─── * sessions  (optional — general_chat has no project)
projects 1 ─── * project_dependencies
```

## Users + roles

```
users 1 ─── * user_roles  (composite PK, cascade delete)
users 1 ─── * user_tokens  (external services)
```

## Evaluation

```
benchmark_runs 1 ─── * evaluation_results  (v1)
benchmark_runs 1 ─── * test_runs            (v2)
test_runs 1 ─── * test_run_tags
test_runs 1 ─── * test_assertion_results
```

## Cross-aggregate references

- `approvals.resolved_by` → `users.id` — who approved/rejected.
- `test_runs.session_id` → `sessions.id` — the session the test exercised (nullable — session may be deleted after test completes).
- `evaluation_results.session_id` / `.agent_run_id` → respective. Nullable for the same reason.

## Diagram

```
           ┌─────────┐        ┌──────────┐
           │ users   │───────►│ projects │
           └────┬────┘        └────┬─────┘
                │                  │
                │  ┌───────────────┘
                ▼  ▼
           ┌─────────────┐
           │  sessions   │
           └──┬──────────┘
              │
    ┌─────────┼─────────────────────┐
    │         │                     │
    ▼         ▼                     ▼
┌─────────┐ ┌───────────┐     ┌─────────────────┐
│ messages│ │agent_runs │     │sandbox_sessions │
└─────────┘ └─┬─────────┘     └─────────────────┘
              │
        ┌─────┼─────────┐
        ▼     ▼         ▼
   ┌────────┐ ┌──────────┐ ┌───────────┐
   │llm_    │ │tool_calls│ │(sub)      │
   │ calls  │ │          │ │agent_runs │
   └────────┘ └──┬───────┘ └───────────┘
                 │
             ┌───┼─────────────┐
             ▼   ▼             ▼
         ┌─────────┐ ┌──────────┐
         │approvals│ │questions │
         └─────────┘ └──────────┘
```

## Read patterns

The UI's most expensive read is `GET /api/sessions/{id}` — returns `SessionDetail` with the full timeline. The repository builds it in one query by eager-loading agent_runs → llm_calls → tool_calls → approvals/questions. One session ≈ one round-trip + N smaller loads.

Other hot reads:
- `GET /api/approvals` — join `approvals ↔ sessions` for ownership filter.
- `GET /api/evaluations/analytics/*` — aggregates over `test_assertion_results`.
- `GET /api/admin/stats` — row counts per table.

## Delete impact

Because everything cascades from session or project, a user hitting "Delete project" removes:
- The project row.
- All sessions on it, and their entire execution trace.
- All discovered dependencies.
- Potentially: Gitea repo (async, best-effort).

Approvals and questions tied to those sessions are also deleted. This is the right default — without the session, the approval is orphaned.

To retain the approval history for audit, the approval row would need to survive session deletion. Today it doesn't. If audit retention becomes a requirement, the approvals table can be amended to NOT cascade (with application code handling cleanup differently).
