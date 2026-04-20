# Repositories

`druppie/repositories/` — data access. Each repository owns one aggregate (session, project, approval, …) and is responsible for translating between SQLAlchemy ORM models and Pydantic domain models.

## Base pattern

```python
class BaseRepository:
    def __init__(self, db: Session):
        self.db = db
    def commit(self): self.db.commit()
    def rollback(self): self.db.rollback()
```

Every concrete repository extends `BaseRepository` and exposes methods that return either domain models or lists of them. Private `_to_summary()` / `_to_detail()` methods do the conversion (pattern enforced by code review, not a linter).

## SessionRepository

`druppie/repositories/session_repository.py` (~200 lines)

| Method | Returns | Notes |
|--------|---------|-------|
| `get_by_id(id)` | `Session` ORM or `None` | Cheap |
| `get_by_id_for_update(id)` | `Session` ORM | `SELECT … FOR UPDATE`; used by SessionService locks |
| `list_for_user(user_id, limit, offset, status)` | `list[SessionSummary]` | Paginated + status filter; `user_id=None` for admin |
| `create(user_id, title, project_id)` | `Session` | `INSERT … FLUSH` (no commit; service commits) |
| `update_status(id, status, error_message=None)` | None | Status transitions |
| `recalculate_token_totals(id)` | None | `SUM(prompt_tokens, completion_tokens)` across non-pending agent_runs |
| `get_with_chat(id)` | `SessionDetail` | Alias for `get_detail()` |
| `get_detail(id)` | `SessionDetail` | Timeline-built |
| `delete(id)` | None | Cascades via FK |

### `_build_timeline(session_id)`

Merges `messages` and `agent_runs` into a single chronological list of `TimelineEntry` objects (`type=MESSAGE` or `type=AGENT_RUN`). Logic:

1. Fetch all messages for session, ordered by `sequence_number`.
2. Fetch all non-pending agent runs with their LLM calls and tool calls eager-loaded.
3. Merge by created_at. Agent runs in `PENDING` state still show up (so the UI can preview the upcoming step).
4. For AGENT_RUN entries, embed an `AgentRunDetail` with full `llm_calls` including every `ToolCallDetail` (with linked approval/question).

This is the single source of truth for the chat UI. The frontend doesn't reconstruct the order client-side.

## ApprovalRepository

`druppie/repositories/approval_repository.py` (195 lines)

| Method | Purpose |
|--------|---------|
| `create(...)` | Insert pending approval |
| `get_by_id(id)` | Fetch |
| `get_pending_for_roles(roles, user_id)` | Query: `status=pending AND (required_role IN roles OR (required_role='session_owner' AND session.user_id=user_id))` |
| `get_resolved_for_roles(roles, page, limit, user_id)` | Same filter, `status IN (APPROVED, REJECTED)` |
| `update_status(id, status, resolved_by, rejection_reason=None)` | `UPDATE + resolved_at = now()` |
| `_to_detail(approval)` | Build `ApprovalDetail` including `session_user_id` |

For `session_owner` approvals, `_to_detail` joins to `sessions` to populate `session_user_id` so the frontend can render "Approve as session owner" only for the current user.

## QuestionRepository

`druppie/repositories/question_repository.py`

| Method | Purpose |
|--------|---------|
| `get_by_id(id)` | Fetch |
| `list_pending(session_id?)` | Filter by session if given |
| `create(...)` | Insert pending question with `choices` JSON |
| `update_answer(id, answer, selected_indices)` | Save + mark ANSWERED |
| `cancel(id)` | Set status CANCELLED |
| `_to_detail(question)` | Build `QuestionDetail` with `QuestionChoice` objects (text + is_selected) |

Choices format:
- `choices: JSON` = `[{"text": "Option A"}, {"text": "Option B"}]`
- `selected_indices: JSON` = `[0, 2]`
- `answer: TEXT` = either a free-text answer OR a display string joined from selected choice texts

## ProjectRepository

`druppie/repositories/project_repository.py` (~150 lines)

| Method | Purpose |
|--------|---------|
| `get_by_id(id)` | Fetch |
| `get_by_user(user_id)` | All projects for a user |
| `create(name, user_id, description)` | Insert |
| `list_for_user(user_id, limit, offset)` | Paginated |
| `list_all(limit, offset)` | Admin path |
| `get_detail(id, session_limit=5)` | With token aggregate + recent sessions |
| `update_repo(id, repo_name, repo_url, repo_owner)` | After Gitea repo creation |
| `delete(id)` | Delete |

Token aggregation: sums `prompt_tokens`, `completion_tokens`, `total_tokens` across all sessions for the project. Used in `ProjectDetail.token_usage`.

## AgentRunRepository / ExecutionRepository

`druppie/repositories/execution_repository.py` holds the write path for the orchestrator and the zombie/stuck detection queries:

| Method | Purpose |
|--------|---------|
| `create_agent_run(session_id, agent_id, planned_prompt, sequence_number, parent_run_id?)` | Create PENDING |
| `update_agent_run_status(id, status, error_message?)` | Status transitions |
| `create_message(session_id, agent_run_id, role, content, tool_name?, tool_call_id?)` | Insert message |
| `create_llm_call(...)` | Insert LLM call with full request_messages and response |
| `create_tool_call(...)` | Insert tool call linked to llm_call |
| `update_tool_call(id, status, result?, error_message?)` | Tool call lifecycle |
| `get_running_agent_runs_for_recovery()` | Used at startup to detect zombies |
| `get_stuck_sandbox_tool_calls(cutoff_dt)` | Used by watchdog |

## ToolCallRepository

Separate concerns (queries used mostly by admin + analytics):

| Method | Purpose |
|--------|---------|
| `list_by_session(session_id)` | Ordered by index |
| `get_with_normalizations(id)` | Include `tool_call_normalizations` for debug |
| `get_by_id_for_update(id)` | Lock for webhook idempotency |

## EvaluationRepository

`druppie/repositories/evaluation_repository.py`

Backs the evaluation API routes. Methods for benchmark runs, results, test runs, test batches, test assertion results, test run tags.

Key aggregation query: `get_agent_summary(agent_id)` joins `evaluation_results` and computes pass rates over all rubrics grouped by `score_type`.

## SandboxSessionRepository

`druppie/repositories/sandbox_session_repository.py`

Owns the sandbox_sessions table. Used by:
- `sandbox.py:internal_register` — creates a row mapping `sandbox_session_id → (tool_call_id, user_id, webhook_secret)`.
- `sandbox.py:complete_webhook` — `get_by_id_for_update(sandbox_session_id)` for idempotency, then `update(events_snapshot, completed_at, status)`.
- Watchdog cleanup.

## UserRepository

| Method | Purpose |
|--------|---------|
| `get_or_create(sub, username, email, display_name, roles)` | Upsert on every authenticated request |
| `get_by_id(id)` | Fetch |
| `list_by_role(role)` | For the "approvers by role" endpoint |
| `sync_roles(user_id, roles)` | Reconcile realm roles from Keycloak token |
| `delete_by_username_pattern(pattern)` | Cleanup for test users |

Roles are stored as `(user_id, role)` composite PK rows in `user_roles` — cascade deletes on user deletion.

## UserTokenRepository

Stores OAuth tokens for external services (Gitea, SharePoint). Methods: `save`, `get`, `delete`, `refresh_if_expired`. Called when an MCP tool needs to act as the user in an external system.
