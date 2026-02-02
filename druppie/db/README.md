# Database Layer

The database layer defines SQLAlchemy ORM models and manages database connections. It provides the low-level schema that the repository layer maps to domain models.

## Architecture

```
Repository Layer
      |
      v
  db/models/*.py  (SQLAlchemy ORM models)
      |
      v
  db/database.py  (engine, session factory)
      |
      v
  PostgreSQL / SQLite
```

**Important**: No other layer accesses the database directly. All queries go through repositories.

## Design Principles

1. **No migrations** -- SQLAlchemy models are updated directly. Database is reset with `./setup.sh clean && ./setup.sh all`.
2. **No JSON/JSONB columns for queryable data** -- Normalized relational tables. The exceptions are `arguments` (tool call parameters for display only) and `agent_state` (opaque resumption data).
3. **1:1 mapping with domain models** -- Each table has corresponding domain model(s) in `druppie/domain/`.

## Files

### `__init__.py`
Central export hub. Re-exports all models and database utilities:
- Database: `get_db`, `init_db`, `SessionLocal`, `engine`.
- Models: `Base`, `User`, `UserRole`, `UserToken`, `Project`, `Session`, `AgentRun`, `Message`, `ToolCall`, `Approval`, `Question`, `LlmCall`.

### `database.py`
Database connection and session management:

```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./druppie.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

Key functions:
- `get_db()` -- generator that yields a database session with proper cleanup. Rolls back on errors, always closes the connection. Used as a FastAPI dependency.
- `init_db()` -- creates all tables from model metadata. Called once at startup from `api/deps.py`.

Supports both SQLite (development) and PostgreSQL (production). SQLite gets `check_same_thread=False` for async compatibility.

## Models (`models/` subdirectory)

### `models/__init__.py`
Documents the full schema mapping:

```
Database Table    SQLAlchemy Model    Domain Model(s)
sessions          Session             SessionSummary, SessionDetail
messages          Message             Message
agent_runs        AgentRun            AgentRunSummary, AgentRunDetail
llm_calls         LlmCall             LLMCallDetail
tool_calls        ToolCall            ToolCallDetail
approvals         Approval            ApprovalSummary, ApprovalDetail
questions         Question            QuestionDetail
users             User                UserInfo
projects          Project             ProjectSummary, ProjectDetail
```

### `models/base.py`
Foundation for all models:
- `Base` -- SQLAlchemy declarative base.
- `utcnow()` -- returns current UTC timestamp (used as column defaults).
- `new_uuid()` -- generates UUID strings.

### `models/user.py`
**User** (`users` table): Synced from Keycloak. Fields: id (UUID, primary key -- matches Keycloak sub), username, email, display_name, timestamps. Has relationships to `UserRole` and `UserToken`.

**UserRole** (`user_roles` table): Composite primary key (user_id, role). Stores roles like "admin", "developer", "architect".

**UserToken** (`user_tokens` table): OBO (on-behalf-of) tokens for external services (Gitea, SharePoint). Fields: service, access_token, refresh_token, expires_at.

### `models/project.py`
**Project** (`projects` table): A project with a Gitea repository. Fields: name, description, repo_name (just the name, e.g., "todo-app-abc12345"), repo_owner (Gitea username), repo_url (full public URL), clone_url, owner_id (FK to users), status.

### `models/session.py`
**Session** (`sessions` table): A conversation session. Fields: user_id (FK), project_id (FK), title, status (active/paused_approval/paused_hitl/completed/failed), intent (create_project/update_project/general_chat), branch_name, aggregated token counts, timestamps.

### `models/agent_run.py`
**AgentRun** (`agent_runs` table): Tracks each agent execution within a session. Fields: session_id (FK), agent_id (e.g., "router", "planner", "architect"), parent_run_id (FK for hierarchical runs), status (pending/running/paused_tool/paused_hitl/completed/failed), iteration_count, planned_prompt, sequence_number, token counts, timestamps. Has relationships to `Message` and `ToolCall`.

**Message** (`messages` table): A message in the conversation. Fields: session_id (FK), agent_run_id (FK), role (user/assistant/system/tool), content, agent_id, tool_name, tool_call_id, sequence_number.

### `models/tool_call.py`
**ToolCall** (`tool_calls` table): An MCP or builtin tool invocation. Fields: session_id (FK), agent_run_id (FK), llm_call_id (FK), mcp_server, tool_name, tool_call_index (order in LLM response), arguments (JSONB), status, result (text), error_message, timestamps. The `arguments` column uses JSONB because tool parameters are only used for display, never queried individually.

### `models/approval.py`
**Approval** (`approvals` table): An approval request for a tool call. Fields: session_id (FK), agent_run_id (FK), tool_call_id (FK), approval_type, mcp_server, tool_name, title, description, required_role (comma-separated), danger_level, status (pending/approved/rejected), resolved_by (FK to users), resolved_at, rejection_reason, arguments (JSONB), agent_state (JSONB), agent_id.

Properties provide API compatibility: `required_roles` (splits comma string), `approved_by`, `approved_at`, `rejected_by`.

### `models/question.py`
**Question** (`questions` table): A HITL question from an agent. Fields: session_id (FK), agent_run_id (FK), tool_call_id (FK), agent_id, question (text), question_type (text/single_choice/multiple_choice), choices (JSONB array of `{"text": "..."}` objects), selected_indices (JSONB array of ints), status (pending/answered), answer, answered_at, agent_state (JSONB).

### `models/llm_call.py`
**LlmCall** (`llm_calls` table): Tracks LLM API calls for cost transparency. Fields: session_id (FK), agent_run_id (FK), provider, model, prompt_tokens, completion_tokens, total_tokens, duration_ms, request_messages (JSONB), response_content, response_tool_calls (JSONB), tools_provided (JSONB). Has relationship to `ToolCall` for linking tool calls to the LLM call that requested them.

## Table Relationships

```
users ──< user_roles
users ──< user_tokens
users ──< projects (owner_id)
users ──< sessions (user_id)
projects ──< sessions (project_id)
sessions ──< agent_runs
sessions ──< messages
sessions ──< tool_calls
sessions ──< approvals
sessions ──< questions
agent_runs ──< messages
agent_runs ──< tool_calls
agent_runs ──< approvals
agent_runs ──< questions
llm_calls ──< tool_calls
```

## Layer Connections

- **Depends on**: Nothing (foundation layer).
- **Depended on by**: `druppie.repositories` (queries ORM models), `druppie.execution.tool_context` (lazy-loads session/project/user for injection).

## Conventions

1. All models have a `to_dict()` method for debugging/logging (not used for API responses -- domain models handle that).
2. UUID primary keys use `UUID(as_uuid=True)` with `default=uuid4`.
3. Timestamps use `DateTime(timezone=True)` with `default=utcnow`.
4. Foreign keys use `ondelete="CASCADE"` for session-scoped data.
5. Status columns are plain `String(20)` matching the domain enum values.
