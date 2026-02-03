# Execution Layer

The execution layer coordinates agent runs and tool execution. It is the runtime engine that drives Druppie's agent pipeline: receiving user messages, running agents in sequence, executing tools, and handling pauses for approvals and HITL questions.

## Architecture

```
User Message (via API)
       |
       v
  Orchestrator.process_message()
       |
       +--> Create Session
       +--> Save User Message
       +--> Create Router + Planner (both PENDING)
       +--> execute_pending_runs()
               |
               +--> Router agent --> set_intent()
               +--> Planner agent --> make_plan()
               +--> Architect/Developer/Deployer agents
                       |
                       v
               ToolExecutor.execute(tool_call_id)
                       |
                       +--> Builtin tool? --> Execute directly
                       +--> HITL tool? --> Create Question, pause
                       +--> MCP tool needs approval? --> Create Approval, pause
                       +--> MCP tool? --> MCPHttp.call(), save result
```

## Key Design Decisions

1. **Pending runs pattern**: Agent runs are created upfront as `pending`, then `execute_pending_runs()` processes them sequentially. This allows the planner to create a full execution plan before any agent starts.

2. **ToolExecutor is the single entry point**: All tool execution (builtin, HITL, MCP) goes through `ToolExecutor.execute()`. This ensures consistent approval checking, tool call recording, and status management.

3. **ToolCall is the central record**: `Question` and `Approval` records link back to a `ToolCall` via `tool_call_id`. This creates a single audit trail.

4. **Agent completion via `done` tool**: An agent only completes when it explicitly calls the `done` builtin tool. This prevents premature completion.

5. **Declarative injection**: Tool arguments are enriched at execution time via rules defined in `mcp_config.yaml`, not hardcoded logic.

## Files

### `__init__.py`
Exports: `Orchestrator`, `ToolExecutor`, `ToolCallStatus`, `MCPHttp`, `MCPHttpError`, `ToolContext`.

### `orchestrator.py`
The main entry point for processing user messages and coordinating agent execution.

**Orchestrator** class. Constructor takes four repositories: `session_repo`, `execution_repo`, `project_repo`, `question_repo`.

**`process_message(message, user_id, session_id, project_id)`**:
1. Gets or creates a session.
2. Saves the user message to the timeline.
3. Formats the user's project list for the router.
4. Creates router (sequence 0) and planner (sequence 1) as PENDING agent runs.
5. Calls `execute_pending_runs()`.

Returns the session ID.

**`execute_pending_runs(session_id)`**:
The core execution loop. Repeatedly:
1. Gets the next pending agent run (ordered by `sequence_number`).
2. Rebuilds project context from DB (picks up changes from previous agents).
3. Marks the run as RUNNING.
4. Runs the agent via `_run_agent()`.
5. If the agent pauses (approval/HITL), stops the loop.
6. If no more pending runs, marks session as COMPLETED.

**`_build_project_context(session_id)`**:
Queries the session's project for repo_name, repo_owner, intent, etc. Called before each agent run so later agents see changes from earlier ones (e.g., router creates repo, deployer needs repo_name).

**`resume_after_approval(session_id, approval_id)`**:
Called when a user approves a tool execution. Steps:
1. Executes the approved tool via `ToolExecutor.execute_after_approval()`.
2. Resumes the paused agent via `agent.continue_run()` (reconstructs state from DB).
3. Continues with remaining pending runs.

**`resume_after_answer(session_id, question_id, answer)`**:
Called when a user answers a HITL question. Same pattern as approval resumption:
1. Saves the answer via `ToolExecutor.complete_after_answer()`.
2. Resumes the paused agent.
3. Continues with remaining pending runs.

### `tool_executor.py`
Single entry point for ALL tool execution.

**ToolCallStatus** constants: `PENDING`, `EXECUTING`, `WAITING_APPROVAL`, `WAITING_ANSWER`, `COMPLETED`, `FAILED`.

**Builtin tools**: `done`, `make_plan`, `set_intent`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`, `create_message`.

**ToolExecutor** class. Constructor takes: `db` (SQLAlchemy session), `mcp_http` (MCPHttp client), `mcp_config` (MCPConfig).

**`execute(tool_call_id)`** -- the main entry point:
1. Loads the ToolCall from DB.
2. For MCP tools: validates agent access (checks agent definition's allowed tools), checks approval requirements (layered: agent override > global config). If approval needed, creates Approval record and returns `WAITING_APPROVAL`.
3. For HITL tools: creates Question record, returns `WAITING_ANSWER`.
4. For other builtin tools: executes via `builtin_tools.execute_builtin()`.
5. For MCP tools (no approval needed): applies injection rules, calls MCPHttp, saves result.

**`_apply_injection_rules(server, tool_name, args, session_id)`**:
Applies declarative injection from `mcp_config.yaml`. For hidden params, always overrides LLM-provided values (prevents guessing). For non-hidden params, only injects if not already provided. Uses `ToolContext` for resolution.

**`execute_after_approval(approval_id)`**: Runs the MCP tool after approval, skipping the approval check.

**`complete_after_answer(question_id, answer)`**: Records the answer and marks the tool call as completed.

### `mcp_http.py`
Simple HTTP client for MCP server containers. No business logic -- just HTTP communication.

**MCPHttpError**: Exception with `server`, `tool`, `retryable` attributes.

**MCPHttp** class. Constructor takes: `config` (MCPConfig).

**`call(server, tool, args, timeout_seconds)`**:
1. Gets the server URL from config.
2. Creates a FastMCP `Client` with `StreamableHttpTransport`.
3. Calls `client.call_tool(tool, args)` with timeout via `asyncio.wait_for`.
4. Parses the FastMCP response (list of content items) into a dict.
5. Raises `MCPHttpError` on failure (with `retryable=True` for timeouts and connection errors).

**`list_tools(server)`**: Queries an MCP server for its available tools and schemas.

**`_parse_result(result)`**: Handles FastMCP response parsing -- content items with `.text` (JSON string), `.content`, or `.data` attributes.

### `tool_context.py`
Resolves context paths for the declarative argument injection system.

**ToolContext** class. Constructor takes: `db` (session), `session_id`.

Lazily loads and caches database objects:
- `session` -- from the sessions table.
- `project` -- from the projects table (via session.project_id).
- `user` -- from the users table (via session.user_id).

**`resolve(path)`**: Resolves dotted paths like:
- `session.id`, `session.branch_name`, `session.user_id`
- `project.repo_name`, `project.repo_owner`, `project.name`
- `user.id`, `user.username`

Converts UUIDs to strings automatically.

**`resolve_all(paths)`**: Batch resolution returning only non-None values.

## Pause and Resume Flow

When a tool requires approval or a HITL answer:

```
Agent calls tool
    |
    v
ToolExecutor creates Approval/Question record
ToolExecutor sets ToolCall.status = waiting_approval/waiting_answer
    |
    v
Agent pauses (AgentRun.status = paused_tool/paused_hitl)
execute_pending_runs() stops
    |
    ... user acts in UI ...
    |
    v
API calls Orchestrator.resume_after_approval/answer()
    |
    v
ToolExecutor executes/completes the tool
Agent.continue_run() reconstructs state from DB
execute_pending_runs() continues with remaining agents
```

## Flow Examples

### Create Project Flow

```
User: "Build a todo app"

1. process_message() creates session
2. Save user message to timeline
3. Create router (seq 0) + planner (seq 1) as PENDING
4. execute_pending_runs() starts
5. Router runs -> set_intent(intent="create_project") creates project + repo
6. Planner runs (with updated prompt) -> make_plan() creates architect/developer/deployer
7. Architect runs -> reads requirements, designs architecture
8. Developer runs -> writes code via coding MCP
9. Deployer runs -> deploys via docker MCP
10. Session completed
```

### Approval Pause Flow

```
Developer agent calls coding:commit_and_push (requires approval)
    |
    v
ToolExecutor creates Approval record (status=pending)
ToolCall.status = waiting_approval
AgentRun.status = paused_tool
execute_pending_runs() stops
    |
    ... developer approves in UI ...
    |
    v
POST /api/approvals/{id}/approve triggers:
1. ApprovalService.approve() marks approval as approved
2. WorkflowService.resume_after_approval()
3. Orchestrator executes the tool via MCPHttp
4. Agent continues from where it paused
5. execute_pending_runs() resumes remaining agents
```

## Usage

```python
from druppie.execution import Orchestrator
from druppie.repositories import SessionRepository, ExecutionRepository, ProjectRepository, QuestionRepository

orchestrator = Orchestrator(
    session_repo=SessionRepository(db),
    execution_repo=ExecutionRepository(db),
    project_repo=ProjectRepository(db),
    question_repo=QuestionRepository(db),
)

# Process a message
session_id = await orchestrator.process_message(
    message="Build a todo API",
    user_id=user.id,
)

# Resume after approval
await orchestrator.resume_after_approval(session_id, approval_id)

# Resume after HITL answer
await orchestrator.resume_after_answer(session_id, question_id, answer)
```

## Layer Connections

- **Depends on**: `druppie.repositories` (ExecutionRepository, ApprovalRepository, QuestionRepository), `druppie.core.mcp_config` (MCPConfig), `druppie.domain` (status enums), `druppie.db.models` (ToolContext queries), `druppie.agents.runtime` (Agent class for running agents).
- **Depended on by**: `druppie.services.workflow_service` (wraps Orchestrator), `druppie.api.deps` (creates Orchestrator via DI).

## Conventions

1. The Orchestrator is intentionally "dumb" -- it just creates runs and executes them. All smart logic lives in builtin tools (set_intent, make_plan).
2. ToolExecutor handles all tool types uniformly through a single `execute()` method.
3. Context is rebuilt before each agent run to pick up changes from previous agents.
4. Transaction commits are explicit -- the orchestrator calls `commit()` at well-defined points.
5. All tool executions are recorded in the `tool_calls` table for audit and debugging.
