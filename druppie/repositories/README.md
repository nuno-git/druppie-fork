# Repositories Layer

The repositories layer is the **sole point of database access** in Druppie. It encapsulates all SQLAlchemy queries behind clean interfaces that accept and return domain models. No other layer touches the database directly.

## Architecture

```
Service / Execution
       |
       v
  Repository  (accepts/returns domain models)
       |
       v
  SQLAlchemy ORM  (db/models/*.py)
       |
       v
  PostgreSQL / SQLite
```

## Key Pattern: Repository per Aggregate

Each repository manages a logical group of related database tables. Repositories accept a SQLAlchemy `Session` via constructor injection and expose methods that return domain models (from `druppie/domain/`), never raw ORM objects.

## Files

### `base.py`
The `BaseRepository` base class that all repositories extend:

```python
class BaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def flush(self):
        self.db.flush()
```

Transaction control (`commit`, `rollback`, `flush`) is exposed so services and the orchestrator can manage transaction boundaries.

### `__init__.py`
Central export hub. All repositories are imported and re-exported:
`BaseRepository`, `SessionRepository`, `ApprovalRepository`, `QuestionRepository`, `ProjectRepository`, `ExecutionRepository`, `UserRepository`.

### `session_repository.py`
Manages the `sessions` table and assembles `SessionSummary`/`SessionDetail` domain models.

Key methods:
- `create(user_id, project_id, title)` -- creates a new session, returns `SessionSummary`.
- `get_by_id(session_id)` -- returns `SessionSummary` or None.
- `get_detail(session_id)` -- returns full `SessionDetail` including the timeline (messages + agent runs).
- `get_by_user(user_id)` -- list sessions for a user, returns `list[SessionSummary]`.
- `update_status(session_id, status)` -- updates session status.

The `get_detail` method is the most complex -- it assembles the timeline by querying messages, agent runs, LLM calls, tool calls, approvals, and questions, then merging them chronologically.

### `project_repository.py`
Manages the `projects` table.

Key methods:
- `create(name, description, owner_id)` -- creates project, returns `ProjectSummary`.
- `get_by_id(project_id)` -- returns `ProjectSummary` or None.
- `get_detail(project_id)` -- returns `ProjectDetail` with session count and token totals.
- `get_by_user(user_id)` -- list user's projects.
- `update(project_id, **fields)` -- partial update (name, description, repo_name, repo_url, etc.).

### `user_repository.py`
Manages the `users`, `user_roles`, and `user_tokens` tables.

Key methods:
- `get_or_create(user_id, username, email, display_name)` -- idempotent user sync from Keycloak. Called on every authenticated request to ensure the user exists in the DB.
- `get_by_id(user_id)` -- returns `UserInfo` or None.
- `sync_roles(user_id, roles)` -- replaces all user roles.

### `approval_repository.py`
Manages the `approvals` table.

Key methods:
- `create(session_id, tool_call_id, mcp_server, tool_name, arguments, required_role)` -- creates a pending approval.
- `get_by_id(approval_id)` -- returns the raw Approval model (used by ToolExecutor).
- `get_pending_for_user(user_roles)` -- returns approvals the user can act on based on their roles.
- `approve(approval_id, user_id)` -- marks as approved.
- `reject(approval_id, user_id, reason)` -- marks as rejected.

### `question_repository.py`
Manages the `questions` table (HITL questions from agents to users).

Key methods:
- `create(session_id, agent_run_id, tool_call_id, question, question_type, choices)` -- creates a pending question.
- `get_by_id(question_id)` -- returns raw Question model.
- `get_pending_for_session(session_id)` -- returns unanswered questions for a session.
- `update_answer(question_id, answer)` -- records the user's answer.

### `execution_repository.py`
The largest repository -- manages `agent_runs`, `tool_calls`, `llm_calls`, and `messages`. This is a "combined repository" because these tables form a tightly coupled execution graph.

**Agent Run methods:**
- `create_agent_run(session_id, agent_id, status, planned_prompt, sequence_number)` -- returns `AgentRunSummary`.
- `get_next_pending(session_id)` -- returns the next pending run ordered by sequence_number.
- `update_status(agent_run_id, status)` -- auto-sets `started_at`/`completed_at` timestamps.
- `update_planned_prompt(agent_run_id, prompt)` -- used by `set_intent` to update planner context.
- `get_done_summary_for_run(agent_run_id)` -- extracts the summary from a completed agent's `done()` tool call.

**Tool Call methods:**
- `create_tool_call(session_id, agent_run_id, mcp_server, tool_name, arguments)` -- returns tool_call UUID.
- `update_tool_call(tool_call_id, status, result, error)` -- updates execution outcome.
- `get_tool_calls_for_run(agent_run_id)` -- returns all tool calls for an agent run.

**LLM Call methods:**
- `create_llm_call(session_id, agent_run_id, provider, model, messages)` -- records an LLM API call.
- `update_llm_response(llm_call_id, response_content, tool_calls, tokens, duration)` -- records the response.

**Message methods:**
- `create_message(session_id, role, content, agent_run_id, sequence_number)` -- creates a timeline message.

## Layer Connections

- **Depends on**: `druppie.db.models` (SQLAlchemy ORM), `druppie.domain` (Pydantic models).
- **Depended on by**: `druppie.services` (business logic), `druppie.execution` (orchestrator and tool executor), `druppie.api.deps` (dependency injection).

## Conventions

1. Repositories never raise HTTP exceptions -- they return `None` or empty lists. The service/API layer handles 404s.
2. Methods that modify data call `flush()` (not `commit()`) so the caller controls transaction boundaries.
3. The `_to_summary()` / `_to_detail()` private methods convert ORM models to domain models.
4. All repositories are instantiated via FastAPI dependency injection in `api/deps.py`.
