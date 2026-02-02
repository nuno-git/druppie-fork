# Domain Layer

The domain layer defines the Pydantic models that represent Druppie's business entities. These models are the canonical data structures exchanged between layers: repositories return them, services operate on them, and API routes serialize them to JSON.

## Key Pattern: Summary / Detail

Every entity follows a **Summary/Detail** naming convention:

- **Summary** models are lightweight, used in list endpoints and as embedded references. They contain only the fields needed to display an item in a list.
- **Detail** models inherit from their Summary counterpart and add full data, used in single-item "get by ID" endpoints.

```python
class ProjectSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    repo_url: str | None
    created_at: datetime

class ProjectDetail(ProjectSummary):
    owner_id: UUID
    repo_name: str | None
    token_usage: TokenUsage
    session_count: int
    deployment: DeploymentInfo | None
    sessions: list[SessionSummary] = []
```

## Files

### `__init__.py`
Central export hub. All domain models are imported here and re-exported via `__all__`. Other layers should import from `druppie.domain` rather than individual submodules. Calls `model_rebuild()` at the bottom to resolve forward references between `ProjectDetail` and `SessionDetail`.

### `common.py`
Shared enums and base models used across all entities:

- **Status Enums**: `SessionStatus`, `AgentRunStatus`, `ToolCallStatus`, `ApprovalStatus`, `QuestionStatus`, `DeploymentStatus` -- string enums that map directly to database status columns.
- **TokenUsage**: Tracks prompt/completion/total token counts for LLM cost transparency.
- **TimestampMixin**: Provides `created_at` and `updated_at` fields.
- **LLMMessage**: Represents a single message in an LLM conversation (role, content, tool_calls).

### `session.py`
Models for conversation sessions:

- **Message**: A single message (user, assistant, or system) in a session. Maps 1:1 to the `messages` table.
- **TimelineEntry**: A union type for the session timeline -- either a `Message` or an `AgentRunDetail`. Provides the chronologically sorted view the frontend renders.
- **TimelineEntryType**: Enum distinguishing `message` from `agent_run`.
- **SessionSummary**: ID, title, status, project_id, token_usage, timestamps.
- **SessionDetail**: Extends Summary with `user_id`, `project` (embedded `ProjectSummary`), and the full `timeline` list.

### `project.py`
Models for projects (each backed by a Gitea repository):

- **ProjectSummary**: Name, description, repo_url, created_at.
- **ProjectDetail**: Adds owner_id, repo_name, token_usage, session_count, deployment info, and recent sessions.
- **DeploymentInfo**: Embedded deployment status (container_name, app_url, host_port).
- **DeploymentSummary**: Deployment info enriched with project metadata for list views.

### `user.py`
- **UserInfo**: Current user data (id, username, email, display_name, roles). Used for auth context, not for user management.

### `approval.py`
Models for tool approval requests:

- **ApprovalSummary**: Lightweight (id, status, required_role, resolver info). Embedded in `ToolCallDetail`.
- **ApprovalDetail**: Full context including session_id, tool info, arguments, agent_id, rejection_reason.
- **PendingApprovalList**: Wrapper with `items` and `total` for paginated lists.

### `question.py`
Models for HITL (Human-in-the-Loop) questions:

- **QuestionChoice**: A single option in a multiple-choice question (index, text, is_selected).
- **QuestionDetail**: Full question with type (text/multiple_choice), choices, status, answer.
- **PendingQuestionList**: Wrapper with `items` and `total`.

### `agent_run.py`
Models for agent execution traces:

- **ToolCallDetail**: A tool invocation with its result, status, optional approval, optional question_id.
- **LLMRawResponse**: Raw LLM API response (content, tool_calls, token counts) for debugging.
- **LLMCallDetail**: One LLM round-trip including messages sent, raw response, and executed tool_calls.
- **AgentRunSummary**: Lightweight (id, agent_id, status, planned_prompt, token_usage).
- **AgentRunDetail**: Extends Summary with `llm_calls` -- the full execution trace.

### `agent_definition.py`
Models loaded from agent YAML files (not from the database):

- **ApprovalOverride**: Per-tool override for approval requirements (requires_approval, required_role).
- **AgentDefinition**: Full agent config (id, name, system_prompt, mcps, approval_overrides, LLM settings). Methods like `get_allowed_tools()` and `get_approval_override()` support the layered approval system.

## Layer Connections

- **Depends on**: Nothing (pure Pydantic models, no database imports).
- **Depended on by**: `repositories` (return domain models), `services` (operate on domain models), `api` (serialize to JSON), `execution` (uses status enums and agent definitions).

## Conventions

1. All exports go through `druppie/domain/__init__.py`.
2. Summary models are used for lists and embedding; Detail models for single-item views.
3. Detail inherits from Summary to avoid field duplication.
4. Status fields use string enums that match database column values exactly.
5. Forward references between modules (e.g., `SessionDetail` references `ProjectSummary`) are resolved via `model_rebuild()` in `__init__.py`.
