# Domain Models

`druppie/domain/` — Pydantic models used across routes, services, and repositories. All exports flow through `druppie/domain/__init__.py`.

## Naming pattern

- `XxxSummary` — list-view fields (id, name, status, counts, created_at). Cheap.
- `XxxDetail` — detail-view fields (inherits from Summary, adds heavy relations).

The same model name is never reused at different layers. When a different shape is needed (e.g. frontend-facing "pending" view), it gets its own name.

## Common enums (`common.py`)

```python
class SessionStatus(str, Enum):
    ACTIVE, PAUSED, PAUSED_APPROVAL, PAUSED_HITL, PAUSED_SANDBOX,
    PAUSED_CRASHED, COMPLETED, FAILED

class AgentRunStatus(str, Enum):
    PENDING, RUNNING, PAUSED_TOOL, PAUSED_HITL, PAUSED_SANDBOX,
    PAUSED_USER, COMPLETED, FAILED, CANCELLED

class ToolCallStatus(str, Enum):
    PENDING, WAITING_APPROVAL, WAITING_ANSWER, WAITING_SANDBOX,
    EXECUTING, COMPLETED, FAILED

class ApprovalStatus(str, Enum):
    PENDING, APPROVED, REJECTED

class QuestionStatus(str, Enum):
    PENDING, ANSWERED, CANCELLED

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: list[dict] | None
    tool_call_id: str | None
    tool_name: str | None
```

## Session (`session.py`)

```python
class Message(BaseModel):
    id, session_id, agent_run_id, role, content,
    agent_id, tool_name, tool_call_id, sequence_number, created_at

class TimelineEntry(BaseModel):
    type: Literal["MESSAGE", "AGENT_RUN"]
    timestamp: datetime
    message: Message | None
    agent_run: AgentRunDetail | None

class SessionSummary(BaseModel):
    id, title, status, error_message, project_id,
    token_usage: TokenUsage, created_at, updated_at

class SessionDetail(SessionSummary):
    user_id
    project: ProjectSummary | None
    timeline: list[TimelineEntry]   # chronological
```

Timeline is pre-sorted by the repository; no client-side reordering is required.

## Project (`project.py`)

```python
class ProjectSummary(BaseModel):
    id, name, description, repo_url, created_at

class DeploymentInfo(BaseModel):
    container_name, status, port, url, branch

class ProjectDetail(ProjectSummary):
    owner_id
    repo_name
    repo_owner
    token_usage: TokenUsage
    session_count
    deployment: DeploymentInfo | None
    sessions: list[SessionSummary]
```

## Approval (`approval.py`)

```python
class ApprovalSummary(BaseModel):
    id, status: ApprovalStatus, required_role,
    resolved_by, resolved_at

class ApprovalDetail(ApprovalSummary):
    session_id, agent_run_id, tool_call_id,
    mcp_server, tool_name, arguments,
    agent_id, rejection_reason, created_at,
    session_user_id: UUID | None   # set when required_role == 'session_owner'

class PendingApprovalList(BaseModel):
    items: list[ApprovalDetail]
    total: int

class ApprovalHistoryList(BaseModel):
    items: list[ApprovalDetail]
    total, page, limit
```

## Question (`question.py`)

```python
class QuestionChoice(BaseModel):
    index: int
    text: str
    is_selected: bool

class QuestionDetail(BaseModel):
    id, session_id, agent_run_id, agent_id,
    question, question_type: Literal["text", "single_choice", "multiple_choice"],
    choices: list[QuestionChoice],
    status: QuestionStatus,
    answer, answered_at, created_at
```

## AgentRun (`agent_run.py`)

The most complex aggregate — carries the full execution trace for one agent step:

```python
class LLMRetryDetail(BaseModel):
    attempt, provider, model, error_message, duration_ms, created_at

class ToolCallDetail(BaseModel):
    id, index, tool_type: Literal["builtin", "mcp"],
    mcp_server, tool_name, full_name, description,
    arguments, status: ToolCallStatus, result, error,
    approval: ApprovalSummary | None,       # if tool required approval
    question_id: UUID | None,               # if tool was HITL
    normalizations: list[dict],             # if LLM mistakes were normalised
    child_run: AgentRunSummary | None       # e.g. for execute_coding_task sub-runs

class LLMCallDetail(BaseModel):
    id, model, provider,
    token_usage: TokenUsage, duration_ms,
    messages: list[LLMMessage],             # full prompt
    tools_provided: list[dict],             # schemas sent to LLM
    response_content: str | None,
    response_tool_calls: list[dict] | None,
    retries: list[LLMRetryDetail],
    tool_calls: list[ToolCallDetail]        # one per parsed tool call

class AgentRunSummary(BaseModel):
    id, session_id, agent_id, status, error_message,
    planned_prompt,         # text planner wrote into the prompt
    sequence_number,
    token_usage: TokenUsage,
    started_at, completed_at

class AgentRunDetail(AgentRunSummary):
    llm_calls: list[LLMCallDetail]
```

The UI's debug/inspect mode (`/chat?session=X&mode=inspect`) renders the whole `AgentRunDetail` tree.

## Tool (`tool.py`)

```python
class ToolType(str, Enum):
    BUILTIN, MCP

class ToolDefinition(BaseModel):
    name: str
    tool_type: ToolType
    server: str | None        # None for builtin
    description: str
    json_schema: dict         # from MCP tools/list or BUILTIN_TOOL_DEFS
    requires_approval: bool
    required_role: str | None

    @property
    def full_name(self) -> str:
        return f"{self.server}_{self.name}" if self.server else self.name

    def get_json_schema(self, strict: bool = True) -> dict: ...
    def validate_arguments(self, args: dict) -> tuple[bool, str|None, dict, dict]: ...
    def to_openai_format(self, strict: bool = True) -> dict: ...
    def get_param_descriptions(self) -> dict[str, str]: ...

class ToolDefinitionSummary(BaseModel):
    name, full_name, tool_type, server, description, requires_approval
```

Schema helpers cover three edge cases:
1. **OpenAI strict mode** — `additionalProperties=false`, all properties `required`, optional fields made nullable.
2. **`$defs` inlining** — Pydantic-generated schemas with references are flattened for LLMs that don't resolve refs.
3. **Argument normalization** — string `"null"` → None, string `"{}"` → {}, string `"true"` → True, strip unknown fields.

## AgentDefinition (`agent_definition.py`)

Loaded from YAML:

```python
class AgentDefinition(BaseModel):
    id, name, description, category,
    model: str | None,            # optional override
    llm_profile: str,             # e.g. "cheap", "standard"
    temperature, max_tokens, max_iterations,
    mcps: list[str],              # server IDs agent can use
    builtin_tools: list[str],     # overrides default set
    system_prompts: list[str],    # snippet names to concatenate
    approval_overrides: dict[str, ApprovalRule],
    skills: list[str],            # skill names for invoke_skill
    system_prompt: str            # main agent prompt body
```

## User (`user.py`)

```python
class User(BaseModel):
    id: UUID            # from Keycloak token sub
    username: str
    email: str | None
    display_name: str | None
    roles: list[str]
    created_at, updated_at
```

The `User` domain model's `id` is always the Keycloak `sub` claim (a UUID), persisted verbatim — that way the backend never needs its own sequence and can upsert on every request.

## Skill (`skill.py`)

```python
class SkillDefinition(BaseModel):
    name: str
    description: str
    allowed_tools: list[str]
    body: str           # markdown content of SKILL.md
```

## Evaluation (`evaluation.py`)

Evaluation-layer shapes used by the analytics dashboard:

```python
class EvaluationResultSummary: id, agent_id, rubric_name, score_type, score_binary, score_graded, created_at
class EvaluationResultDetail: + judge_model, judge_prompt, judge_response, judge_reasoning, llm_model, duration_ms, tokens
class BenchmarkRunSummary: id, name, run_type, git_commit, git_branch, started_at, completed_at
class BenchmarkRunDetail: + config_summary, results: list[EvaluationResultSummary]
class TestRunSummary: id, test_name, status, assertions_total, assertions_passed, duration_ms, created_at
class TestRunDetail: + judge_model, session_id, agent_id, mode, tags, assertion_results
```
