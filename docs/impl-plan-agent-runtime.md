# Implementation Plan: Agent Runtime Library

> Implements [agent-runtime-spec.md](./agent-runtime-spec.md).
> The new library lives in `druppie/agent_runtime/`, is storage-agnostic, and coexists with the old code without modifying it.

## 1. Module Structure

```
druppie/agent_runtime/
├── __init__.py              # Public API re-exports
├── types.py                 # Core data types (no framework deps)
├── definition.py            # AgentDefinition YAML parsing (new schema)
├── events.py                # EventEmitter for real-time event streaming
├── loop.py                  # AgentLoop - main execution loop
├── subagents.py             # SubagentsMCP - in-process MCP server
├── sandbox.py               # SandboxWarmPool, sandbox_resolver helpers
└── tools/
    ├── __init__.py
    ├── provider.py           # ToolProvider protocol + MCPToolProvider
    ├── done.py               # done() builtin: dynamic schema + validation
    └── mcp.py                # MCPConnection type
```

### Module Responsibilities

#### `types.py` — Core data types (zero deps beyond stdlib)

Contains:
- `AgentEvent` — Immutable event record (type, timestamp, data)
- `AgentResult` — Final run result (status, done_result, error, events)
- `LoopConfig` — Tunable configuration with sensible defaults
- `CancellationToken` — Thread-safe cancellation primitive
- `DoneResult` — Structured result from done() (summary, variables)
- `CompletionPrecondition` — Rule for done() validation
- `CompletionSummaryRequirement` — Required status keywords in summary
- `RequiredToolCall` — Tool call count requirement
- `AgentCancelledError` — Raised on cancellation
- `AgentLoopError` — Base error for runtime failures

No imports from druppie/ outside this package. No DB imports. No Pydantic.

#### `definition.py` — Enhanced YAML parsing

Contains:
- `AgentDefinition` — Dataclass parsing the new YAML schema from the spec:
  - `role`: Literal["primary", "subagent", "both"]
  - `mcps`: New nested format `{sandbox: {tools: [...], git: str}, core-tools: [...], ...}`
  - `done_variables`: JSON Schema for custom done() parameters
  - `subagents`: List of agent_ids this agent can spawn
  - `completion_preconditions`: Conditional tool call requirements
  - `required_summary_status`: Required status keywords
  - `approval_overrides`: Per-tool approval rule overrides
  - Backward-compatible fields: `system_prompt`, `temperature`, `max_tokens`, `max_iterations`, `llm_profile`, `skills`
- `load_definition(yaml_path: str) -> AgentDefinition` — Load from YAML file
- `parse_definition(data: dict) -> AgentDefinition` — Parse from dict
- `build_done_schema(definition: AgentDefinition) -> dict` — Generate done() JSON Schema from definition

This is a **new model** — it does NOT replace `druppie/domain/agent_definition.py`. The existing `AgentDefinition` Pydantic model stays untouched for backward compatibility.

#### `events.py` — EventEmitter

Contains:
- `EventEmitter` — Collects events in memory and fires real-time callbacks
  - `emit(event: AgentEvent) -> None` — Record + dispatch to callbacks
  - `get_events() -> list[AgentEvent]` — Return all collected events
  - `on(callback: Callable) -> None` — Register a real-time callback
  - `off(callback: Callable) -> None` — Unregister a callback
- Helper to create `AgentEvent` with auto-timestamp

#### `tools/mcp.py` — MCPConnection type

Contains:
- `MCPConnection` — Dataclass representing a connection to an MCP server
  - `server_name: str`
  - `endpoint: str | None` — URL for out-of-process servers
  - `tools: list[dict]` — Available tools in OpenAI function-calling format
  - `async call_tool(tool_name: str, arguments: dict) -> dict` — Execute a tool

This is the universal connection type used by both in-process and remote MCP servers.

#### `tools/provider.py` — ToolProvider

Contains:
- `ToolProvider` — Protocol defining the tool routing interface:
  - `async list_tools() -> list[dict]`
  - `async execute(tool_name: str, arguments: dict) -> dict`
  - `async close() -> None`
- `MCPToolProvider` — Concrete implementation:
  - Holds a dict of `{server_name: MCPConnection}`
  - `list_tools()` aggregates all tools from all MCP connections
  - `execute(tool_name, args)` routes to the correct MCP server by tool name
  - Supports approval overrides: checks if tool requires approval, returns `{"_pending": true}` if so
  - Supports pre-validation hooks: calls validation tool before execution
  - Tool name routing: maintains a `{tool_name: server_name}` mapping built from `list_tools()`

#### `tools/done.py` — done() builtin

Contains:
- `DoneTool` — Generates and validates the done() tool:
  - `build_schema(definition: AgentDefinition) -> dict` — Dynamic schema from done_variables
  - `validate(call_args: dict, definition: AgentDefinition, tool_call_history: dict[str, int]) -> tuple[bool, str | None]` — Full validation:
    1. Schema validation (required fields, types, enums)
    2. `required_summary_status` check
    3. `completion_preconditions` check (summary_contains trigger, unless_summary_contains bypass, tool call counts)
  - `build_result(summary: str, variables: dict) -> dict` — Format done result

#### `loop.py` — AgentLoop

Contains:
- `AgentLoop` — The main execution loop:
  - `async run(...)` — Main entry point (see spec §Agent Loop)
  - Turn execution: LLM call → tool execution → result processing
  - `done()` enforcement: injects error if LLM responds without tool calls
  - Context overflow detection: estimates tokens, forces done() when limit approached
  - LLM retry with exponential backoff
  - Pause detection: checks for `_pending` in tool results
  - Cancellation: checks CancellationToken between turns
  - Tool filtering: filters provider tools by agent's `mcps`, adds done/subagents dynamically
  - Skill expansion: detects `allowed_tools` in tool results, expands available tool set

#### `subagents.py` — SubagentsMCP

Contains:
- `SubagentsMCP` — In-process MCP server providing the `subagents()` tool:
  - Holds `agent_loader: Callable[[str], AgentDefinition]`
  - Holds `sandbox_resolver: Callable[[str], Awaitable[MCPConnection]]`
  - `build_schema(allowed_agents: list[str], agent_loader: Callable) -> dict` — Dynamic schema with enum restriction
  - `async execute(agents: list[dict], parent_context: dict) -> list[dict]` — Spawn subagents:
    - Validates agent names against allowed list
    - Enforces role restrictions
    - Resolves sandbox connections (share or new based on git scope)
    - Spawns child `AgentLoop` instances via `asyncio.gather()`
    - Tracks recursion depth, detects circular references
    - Returns results list

#### `sandbox.py` — SandboxWarmPool

Contains:
- `SandboxWarmPool` — Pre-warmed sandbox container pool:
  - `async get_container(git_scope: str) -> MCPConnection` — Get warm container or create new
  - `async release_container(connection: MCPConnection)` — Stop and discard used container
  - Background recycling of idle containers
- `sandbox_resolver` helper factory — Creates a resolver closure from pool + config

#### `__init__.py` — Public API

```python
from druppie.agent_runtime.types import (
    AgentEvent, AgentResult, LoopConfig, CancellationToken,
    DoneResult, CompletionPrecondition, CompletionSummaryRequirement,
    RequiredToolCall, AgentCancelledError, AgentLoopError,
)
from druppie.agent_runtime.definition import AgentDefinition, load_definition, parse_definition
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.loop import AgentLoop
from druppie.agent_runtime.tools.provider import ToolProvider, MCPToolProvider
from druppie.agent_runtime.tools.done import DoneTool
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.subagents import SubagentsMCP
from druppie.agent_runtime.sandbox import SandboxWarmPool
```

---

## 2. Dependency Graph & Implementation Order

```
Layer 0 ─── types.py                    [no deps]
  │
Layer 1 ─── tools/mcp.py                [no deps]
  │
Layer 2 ─── definition.py               [depends on: types]
  │
Layer 3 ─── events.py                   [depends on: types]
  │
Layer 4 ─── tools/done.py               [depends on: types, definition]
  │
Layer 5 ─── tools/provider.py           [depends on: types, tools/mcp]
  │
Layer 6 ─── loop.py                     [depends on: types, definition, events, tools/*]
  │
Layer 7 ─── subagents.py                [depends on: loop, definition, tools/*]
  │
Layer 8 ─── sandbox.py                  [depends on: tools/mcp]
```

### Implementation order rationale

| Layer | Module | Why this order |
|-------|--------|----------------|
| 0 | `types.py` | Foundation. Everything depends on these types. No external deps. |
| 1 | `tools/mcp.py` | Standalone connection type. No framework deps. Needed early for mocking. |
| 2 | `definition.py` | Needs `CompletionPrecondition`, `RequiredToolCall`, etc. from types. Required by done tool and loop. |
| 3 | `events.py` | Simple event collector. Depends only on `AgentEvent`. Needed by loop. |
| 4 | `tools/done.py` | Needs `AgentDefinition` for schema generation and `CompletionPrecondition` for validation. |
| 5 | `tools/provider.py` | Needs `MCPConnection` and types. Core routing layer for the loop. |
| 6 | `loop.py` | The orchestrator. Depends on all of the above. |
| 7 | `subagents.py` | Spawns child `AgentLoop` instances. Must come after loop.py. |
| 8 | `sandbox.py` | Pool management. Depends only on `MCPConnection`. Can be parallelized with layers 4-7 but logically last. |

### Parallelization opportunities

Within a layer, tests can be written and run in parallel. Between layers:
- Layers 0-1 can be implemented in parallel
- Layers 2-3 can be implemented in parallel
- Layers 4-5 can be implemented in parallel
- Layer 6 must wait for layers 2-5
- Layer 7 must wait for layer 6
- Layer 8 can be done anytime after layer 1

---

## 3. Test Plan

All tests live in `druppie/tests/agent_runtime/`. Each test file maps to one module.

### Test infrastructure

```
druppie/tests/agent_runtime/
├── __init__.py
├── conftest.py                # Shared fixtures
├── test_types.py
├── test_definition.py
├── test_events.py
├── test_tools_mcp.py
├── test_tools_done.py
├── test_tools_provider.py
├── test_loop.py
├── test_subagents.py
└── test_sandbox.py
```

**`conftest.py` shared fixtures:**
- `sample_yaml_dir` — tmp_path with sample YAML agent definitions
- `mock_llm` — Async callable that returns configurable responses
- `mock_mcp_connection` — MCPConnection with stubbed `call_tool`
- `sample_definition_dict` — Dict matching the new YAML schema
- `event_collector` — EventEmitter subclass that captures events for assertions

---

### 3.1 `test_types.py` — Core types

**File:** `druppie/tests/agent_runtime/test_types.py`
**Depends on:** `druppie/agent_runtime/types.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_agent_event_creation` | AgentEvent stores type, timestamp (auto), data |
| `test_agent_event_immutable` | AgentEvent is frozen / fields cannot be reassigned |
| `test_agent_result_completed` | AgentResult with status="completed" has done_result |
| `test_agent_result_error` | AgentResult with status="error" has error string |
| `test_agent_result_cancelled` | AgentResult with status="cancelled" |
| `test_agent_result_paused` | AgentResult with status="paused", empty done_result |
| `test_agent_result_events_list` | AgentResult.events is a list, defaults to empty |
| `test_loop_config_defaults` | LoopConfig has correct default values from spec |
| `test_loop_config_custom` | LoopConfig accepts overrides for all fields |
| `test_cancellation_token_initial` | CancellationToken starts un-cancelled |
| `test_cancellation_token_cancel` | cancel() sets is_cancelled to True |
| `test_cancellation_token_idempotent` | Multiple cancel() calls are safe |
| `test_done_result_creation` | DoneResult with summary and variables |
| `test_done_result_variables_default` | DoneResult variables defaults to empty dict |
| `test_completion_precondition_defaults` | summary_contains=None, unless_summary_contains=None, required_tools=[], error_message="" |
| `test_completion_precondition_full` | All fields populated |
| `test_required_summary_requirement` | one_of list, error_message |
| `test_required_tool_call_defaults` | min_calls defaults to 1 |
| `test_agent_cancelled_error` | AgentCancelledError is subclass of AgentLoopError |
| `test_agent_loop_error` | Base error class |

#### Mock strategy
No mocks needed. Pure dataclass/data creation tests.

#### Done criteria
All 20 tests pass. Every type in `types.py` can be instantiated and fields accessed.

---

### 3.2 `test_definition.py` — YAML parsing

**File:** `druppie/tests/agent_runtime/test_definition.py`
**Depends on:** `druppie/agent_runtime/definition.py`, `druppie/agent_runtime/types.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_parse_minimal_definition` | Only required fields: id, name, description, system_prompt, mcps |
| `test_parse_full_definition` | All fields including role, subagents, done_variables, completion_preconditions, approval_overrides |
| `test_parse_role_primary` | role="primary" parsed correctly |
| `test_parse_role_subagent` | role="subagent" parsed correctly |
| `test_parse_role_both` | role="both" parsed correctly |
| `test_parse_role_default` | role defaults to "primary" when absent |
| `test_parse_mcps_sandbox_with_tools_and_git` | `mcps.sandbox.tools` and `mcps.sandbox.git` |
| `test_parse_mcps_core_tools_list` | `mcps.core-tools: [tool1, tool2]` |
| `test_parse_mcps_mixed` | sandbox (dict), core-tools (list), docker (list) |
| `test_parse_done_variables` | Custom done_variables with type, enum, required |
| `test_parse_done_variables_empty` | No done_variables → empty |
| `test_parse_completion_preconditions` | summary_contains, unless_summary_contains, required_tools |
| `test_parse_required_summary_status` | one_of list with error_message |
| `test_parse_approval_overrides` | Key format "server:tool", requires_approval, required_role |
| `test_parse_subagents_list` | List of allowed subagent agent_ids |
| `test_parse_subagents_empty` | No subagents → empty list |
| `test_parse_llm_settings` | temperature, max_tokens, max_iterations, llm_profile |
| `test_parse_skills` | skills list |
| `test_load_from_yaml_file` | load_definition reads YAML from disk |
| `test_load_from_yaml_file_not_found` | FileNotFoundError for missing file |
| `test_parse_invalid_role` | ValidationError for invalid role value |
| `test_parse_missing_required_fields` | ValidationError when id/name/description missing |
| `test_parse_system_prompts_list` | system_prompts: [prompt_id, ...] |
| `test_build_done_schema_no_variables` | Schema with only summary (always required) |
| `test_build_done_schema_with_variables` | Schema with summary + custom variables, required reflects done_variables |
| `test_build_done_schema_enum_variable` | Enum constraint appears in generated schema |
| `test_build_done_schema_optional_variable` | Optional variable not in required list |

#### Mock strategy
No mocks. Uses tmp_path fixtures for YAML files.

#### Done criteria
All 27 tests pass. Every YAML field from the spec is parsed. `build_done_schema` produces correct JSON Schema.

---

### 3.3 `test_events.py` — EventEmitter

**File:** `druppie/tests/agent_runtime/test_events.py`
**Depends on:** `druppie/agent_runtime/events.py`, `druppie/agent_runtime/types.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_emit_records_event` | emit() adds event to internal list |
| `test_emit_fires_callbacks` | Registered callbacks are called with the event |
| `test_emit_multiple_callbacks` | Multiple callbacks all fire |
| `test_emit_no_callbacks` | emit() works with zero callbacks (no error) |
| `test_get_events_returns_all` | All emitted events returned in order |
| `test_get_events_immutable` | Returned list is a copy (modifying it doesn't affect internal state) |
| `test_on_registers_callback` | on() adds callback |
| `test_off_removes_callback` | off() removes specific callback |
| `test_off_nonexistent_callback` | off() with unknown callback is a no-op |
| `test_callback_exception_isolation` | One callback raising doesn't prevent others from firing |
| `test_event_timestamp_auto` | Events get auto-generated timestamps |
| `test_event_ordering` | Events are returned in emission order |

#### Mock strategy
No mocks needed. Uses simple callable fixtures (lambda, MagicMock).

#### Done criteria
All 12 tests pass. EventEmitter correctly records events and dispatches to callbacks.

---

### 3.4 `test_tools_mcp.py` — MCPConnection

**File:** `druppie/tests/agent_runtime/test_tools_mcp.py`
**Depends on:** `druppie/agent_runtime/tools/mcp.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_mcp_connection_creation` | All fields set: server_name, endpoint, tools |
| `test_mcp_connection_in_process` | endpoint=None for in-process servers |
| `test_mcp_connection_tools_list` | tools is list of dicts in OpenAI format |
| `test_mcp_connection_call_tool` | call_tool delegates correctly |
| `test_mcp_connection_call_tool_error` | call_tool returns error dict on failure |

#### Mock strategy
No mocks needed for creation tests. `call_tool` tested with simple stubs.

#### Done criteria
All 5 tests pass. MCPConnection can represent both in-process and remote servers.

---

### 3.5 `test_tools_done.py` — done() builtin

**File:** `druppie/tests/agent_runtime/test_tools_done.py`
**Depends on:** `druppie/agent_runtime/tools/done.py`, `druppie/agent_runtime/definition.py`, `druppie/agent_runtime/types.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_build_schema_no_done_variables` | Only summary in schema |
| `test_build_schema_with_done_variables` | summary + custom fields, required list correct |
| `test_build_schema_summary_always_required` | summary is always in required array |
| `test_build_schema_enum_restriction` | enum values from done_variables appear in schema |
| `test_build_schema_type_preservation` | string, number, boolean types preserved |
| `test_validate_summary_present` | Pass: summary provided |
| `test_validate_summary_missing` | Fail: summary not provided |
| `test_validate_required_variable_present` | Pass: all required done_variables provided |
| `test_validate_required_variable_missing` | Fail: missing required variable returns error message |
| `test_validate_optional_variable_omitted` | Pass: optional variable not provided |
| `test_validate_wrong_type` | Fail: string value for number field |
| `test_validate_invalid_enum` | Fail: value not in enum list |
| `test_validate_all_types_valid` | Pass: correct types for all fields |
| `test_validate_no_preconditions` | Pass: no completion_preconditions defined |
| `test_validate_precondition_summary_contains_match` | Triggered: summary contains keyword, tool was called enough |
| `test_validate_precondition_summary_contains_no_match` | Skipped: summary doesn't contain keyword |
| `test_validate_precondition_unless_bypass` | Skipped: summary contains unless_summary_contains |
| `test_validate_precondition_tool_not_called` | Fail: required tool not called enough times |
| `test_validate_precondition_tool_called_enough` | Pass: tool call count >= min_calls |
| `test_validate_precondition_multiple_tools` | All required tools must be called |
| `test_validate_required_summary_status_match` | Pass: summary contains one of the allowed keywords |
| `test_validate_required_summary_status_no_match` | Fail: summary doesn't contain any keyword |
| `test_validate_required_summary_status_error_message` | Custom error_message returned |
| `test_build_result_basic` | Returns {summary, variables} |
| `test_build_result_empty_variables` | variables defaults to {} |
| `test_full_done_flow_valid` | Complete flow: schema → validate → result |
| `test_full_done_flow_invalid_retry` | Validation fails, returns error for LLM to retry |

#### Mock strategy
Uses `AgentDefinition` instances built directly (no YAML). `tool_call_history` is a plain dict.

#### Done criteria
All 27 tests pass. DoneTool handles all validation cases from the spec:
- Dynamic schema generation
- Required/optional variable validation
- Type and enum checking
- Summary status keyword enforcement
- Completion preconditions with trigger/bypass logic
- Tool call count tracking

---

### 3.6 `test_tools_provider.py` — ToolProvider

**File:** `druppie/tests/agent_runtime/test_tools_provider.py`
**Depends on:** `druppie/agent_runtime/tools/provider.py`, `druppie/agent_runtime/tools/mcp.py`

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_list_tools_aggregates_all` | list_tools returns tools from all MCP connections |
| `test_list_tools_empty` | No connections → empty list |
| `test_execute_routes_to_correct_server` | Tool name maps to correct MCP connection |
| `test_execute_tool_not_found` | Unknown tool_name returns error dict |
| `test_execute_success` | Successful tool execution returns result |
| `test_execute_error_returns_error_dict` | MCP server error → {"success": False, "error": ...} |
| `test_tool_name_mapping_built` | Internal {tool_name: server_name} mapping correct |
| `test_close_closes_all_connections` | close() calls close on all MCP connections |
| `test_approval_gate_pending` | Tool with requires_approval returns {"_pending": true} |
| `test_approval_gate_approved` | Tool with approval granted executes normally |
| `test_prevalidation_hook_pass` | Pre-validate tool passes, execution continues |
| `test_prevalidation_hook_fail` | Pre-validate tool fails, returns error to caller |
| `test_multiple_mcp_same_tool_name` | Last registered wins (or error — decide during impl) |
| `test_execute_preserves_pending_flag` | _pending flag in result is passed through |
| `test_protocol_compliance` | MCPToolProvider satisfies ToolProvider protocol |

#### Mock strategy
Uses `MCPConnection` instances with stubbed `call_tool`. Approval/prevalidation tested with mock connections returning configurable responses.

#### Done criteria
All 15 tests pass. MCPToolProvider correctly routes, handles approvals, and supports pre-validation hooks.

---

### 3.7 `test_loop.py` — AgentLoop

**File:** `druppie/tests/agent_runtime/test_loop.py`
**Depends on:** `druppie/agent_runtime/loop.py`, all other modules

This is the largest test file. Tests are grouped by concern.

#### Mock strategy
- `mock_llm` — Configurable async callable that returns predetermined responses
- `mock_tool_provider` — ToolProvider with stubbed tools
- `sample_definition` — AgentDefinition for a test agent
- No real LLM calls, no real MCP servers, no DB.

#### Test cases — Basic execution

| Function | What it tests |
|----------|---------------|
| `test_run_basic_done` | LLM calls done() on first turn → AgentResult(status="completed") |
| `test_run_tool_then_done` | LLM calls a tool, then done() on second turn |
| `test_run_multiple_turns` | Multiple tool calls across several turns |
| `test_run_with_prompt` | New run with prompt string → wrapped as first user message |
| `test_run_with_initial_messages` | Resume run with pre-built message list |
| `test_run_requires_prompt_or_messages` | Error if neither prompt nor initial_messages provided |

#### Test cases — done() enforcement

| Function | What it tests |
|----------|---------------|
| `test_enforcement_text_response` | LLM responds with text only → injected error, enforcement retry |
| `test_enforcement_max_retries` | Max enforcement retries → auto-generated done result |
| `test_enforcement_emits_event` | enforcement_retry event emitted on text-only response |
| `test_done_validates_preconditions` | done() with failed preconditions → error returned to LLM |
| `test_done_accepts_valid_preconditions` | done() with satisfied preconditions → completed |

#### Test cases — Tool filtering

| Function | What it tests |
|----------|---------------|
| `test_tool_filtering_by_mcps` | Only tools from agent's mcps are included |
| `test_done_always_included` | done() tool always in tool list |
| `test_subagents_included_when_configured` | subagents tool present when agent has subagents field |
| `test_subagents_excluded_when_not_configured` | subagents tool absent when agent has no subagents field |
| `test_skill_expansion` | allowed_tools in tool result → tools added for next turn |
| `test_tool_list_rebuilt_each_turn` | Tool list is re-queried before each LLM call |

#### Test cases — Pause/Resume

| Function | What it tests |
|----------|---------------|
| `test_pause_on_pending` | Tool returns _pending → AgentResult(status="paused") |
| `test_pause_preserves_events` | All events before pause are in AgentResult.events |
| `test_resume_continues_from_messages` | initial_messages from previous run → loop continues |
| `test_multi_tool_one_pending` | Multiple tool calls, one pending → all results saved, status=paused |

#### Test cases — Error handling

| Function | What it tests |
|----------|---------------|
| `test_llm_retry_on_error` | LLM error → retry with backoff |
| `test_llm_retry_exhausted` | Max retries → AgentResult(status="error") |
| `test_llm_retry_emits_event` | llm_retry event emitted on each retry |
| `test_tool_error_continues` | Tool execution error → error in messages, LLM retries |
| `test_unexpected_exception` | Unexpected error → AgentResult(status="error") |

#### Test cases — Context overflow

| Function | What it tests |
|----------|---------------|
| `test_context_overflow_forces_done` | Estimated tokens > max → forces done with only done tool |
| `test_context_overflow_auto_generates` | LLM doesn't call done after overflow → auto-generated result |
| `test_context_overflow_emits_event` | System message about context limit emitted |

#### Test cases — Cancellation

| Function | What it tests |
|----------|---------------|
| `test_cancellation_between_turns` | Token cancelled between turns → AgentResult(status="cancelled") |
| `test_cancellation_before_start` | Already cancelled token → immediate return |
| `test_no_cancellation_token` | None token → normal execution |

#### Test cases — Event emission

| Function | What it tests |
|----------|---------------|
| `test_event_turn_start_end` | turn_start and turn_end emitted per turn |
| `test_event_tool_call_result` | tool_call and tool_result events emitted |
| `test_event_done` | done event emitted on completion |
| `test_event_callbacks_fire` | Registered callbacks receive events |
| `test_events_in_result` | All events collected in AgentResult.events |

#### Done criteria
All ~35 tests pass. AgentLoop correctly:
- Executes the LLM ↔ tool loop
- Enforces done() calls
- Handles tool filtering per agent definition
- Supports pause/resume
- Retries LLM errors with backoff
- Detects and handles context overflow
- Respects cancellation
- Emits all required events

---

### 3.8 `test_subagents.py` — SubagentsMCP

**File:** `druppie/tests/agent_runtime/test_subagents.py`
**Depends on:** `druppie/agent_runtime/subagents.py`, `druppie/agent_runtime/loop.py`

#### Mock strategy
- `mock_agent_loader` — Returns AgentDefinition for known agent names
- `mock_loop` — Patched AgentLoop.run() that returns immediately with mock results
- `mock_sandbox_resolver` — Returns mock MCPConnection

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_build_schema_single_agent` | Schema with one allowed agent |
| `test_build_schema_multiple_agents` | Schema with enum of multiple agents |
| `test_build_schema_includes_descriptions` | Each agent's description in tool description |
| `test_execute_single_subagent` | Spawns one subagent, returns result |
| `test_execute_multiple_subagents_parallel` | Spawns multiple via asyncio.gather, all complete |
| `test_execute_agent_not_in_allowed_list` | Returns error for disallowed agent |
| `test_role_enforcement_subagent_only` | Rejects subagent-only agent at top level |
| `test_role_enforcement_both_role` | Allows "both" role agents |
| `test_depth_limit_exceeded` | Returns error when depth > max_subagent_depth |
| `test_circular_reference_detection` | Returns error when same agent ID in chain |
| `test_sandbox_sharing_same_git` | Parent and child with same git scope share MCP connection |
| `test_sandbox_new_different_git` | Different git scope → calls sandbox_resolver |
| `test_sandbox_no_sandbox` | Child with no mcps.sandbox → no sandbox connection |
| `test_partial_failure` | One subagent fails → others succeed, results include error |
| `test_subagent_result_format` | Result has agent, status, result/error fields |

#### Done criteria
All 15 tests pass. SubagentsMCP correctly validates, spawns, and collects results from child agents.

---

### 3.9 `test_sandbox.py` — SandboxWarmPool

**File:** `druppie/tests/agent_runtime/test_sandbox.py`
**Depends on:** `druppie/agent_runtime/sandbox.py`, `druppie/agent_runtime/tools/mcp.py`

#### Mock strategy
- `_create_container` mocked to return mock MCPConnection
- No real container operations.

#### Test cases

| Function | What it tests |
|----------|---------------|
| `test_get_container_from_pool` | Returns pre-warmed container when available |
| `test_get_container_creates_new` | Creates new when pool empty |
| `test_release_container_stops` | release_container stops and discards |
| `test_pool_size_limit` | Pool maintains configured size |
| `test_recycle_idle_containers` | Containers recycled after timeout |
| `test_sandbox_resolver_factory` | Factory creates correct closure |

#### Done criteria
All 6 tests pass. SandboxWarmPool manages container lifecycle correctly.

---

## 4. Verification Criteria

The implementation is "done" when ALL of the following pass:

### Automated checks

| Check | Command | Expected |
|-------|---------|----------|
| All tests pass | `cd druppie && pytest tests/agent_runtime/ -v` | 0 failed |
| Lint clean | `cd druppie && ruff check agent_runtime/` | 0 errors |
| Format clean | `cd druppie && black --check agent_runtime/` | 0 files changed |
| Import works | `python -c "from druppie.agent_runtime import AgentLoop, AgentResult"` | No error |
| Full name used | `python -c "from druppie.agent_runtime import LoopConfig, CancellationToken, EventEmitter"` | No error |

### Structural checks

| Check | How to verify |
|-------|---------------|
| Storage-agnostic | `grep -r "from druppie.db" agent_runtime/` returns nothing |
| No DB imports | `grep -r "from druppie.repositories" agent_runtime/` returns nothing |
| No ORM imports | `grep -r "from druppie.domain" agent_runtime/` returns nothing |
| Old code untouched | `git diff druppie/agents/ druppie/execution/` shows no changes |
| New package only | All new code is under `druppie/agent_runtime/` |

### Test coverage

| Module | Min tests | Key scenarios |
|--------|-----------|---------------|
| types.py | 20 | All types instantiable, defaults correct |
| definition.py | 27 | Full YAML parsing, done schema generation |
| events.py | 12 | Emit, callbacks, ordering |
| tools/mcp.py | 5 | Connection creation |
| tools/done.py | 27 | Schema gen, validation, preconditions |
| tools/provider.py | 15 | Routing, approval, prevalidation |
| loop.py | ~35 | Full loop lifecycle |
| subagents.py | 15 | Spawning, validation, sandbox sharing |
| sandbox.py | 6 | Pool management |
| **Total** | **~162** | |

---

## 5. Migration Strategy

### Principle: Clean coexistence

The new `agent_runtime` package is added **alongside** the existing code. No existing files are modified during this implementation phase.

### What changes

```
NEW:   druppie/agent_runtime/          ← Entire new package
NEW:   druppie/tests/agent_runtime/    ← All new tests
```

### What does NOT change

```
UNCHANGED: druppie/agents/loop.py
UNCHANGED: druppie/agents/builtin_tools.py
UNCHANGED: druppie/agents/runtime.py
UNCHANGED: druppie/agents/definition_loader.py
UNCHANGED: druppie/domain/agent_definition.py
UNCHANGED: druppie/execution/orchestrator.py
UNCHANGED: druppie/execution/tool_executor.py
UNCHANGED: druppie/agents/definitions/*.yaml   ← Current YAML format unchanged
```

### Why two AgentDefinition models

The existing `druppie/domain/agent_definition.py` (Pydantic) is used by the current runtime. The new `druppie/agent_runtime/definition.py` uses a separate model with the new YAML schema (role, mcps with tools/git, done_variables, subagents). They coexist because:

1. The new model has a different schema (nested mcps, role, done_variables)
2. The old model is used by running code that should not be disrupted
3. During migration, YAML files will be updated to the new format incrementally

### Integration phase (later, not this PR)

After the new library is complete and tested:

1. Create a `druppie/agent_runtime/compat.py` that adapts the new library to the old caller interface
2. Update the orchestrator to use the new runtime via the compat layer
3. Migrate YAML definitions to the new format
4. Remove old loop.py and any remaining legacy prototype code
5. Remove compat.py once fully migrated

### Dependency rules for the new library

```
druppie/agent_runtime/  MAY import:
  ✓ stdlib (asyncio, dataclasses, json, typing, yaml, etc.)
  ✓ third-party (pydantic, structlog, jsonschema)
  ✓ druppie/agent_runtime/* (internal)

druppie/agent_runtime/  MUST NOT import:
  ✗ druppie/db/*
  ✗ druppie/repositories/*
  ✗ druppie/domain/*
  ✗ druppie/agents/*
  ✗ druppie/execution/*
  ✗ druppie/core/*
  ✗ druppie/api/*
  ✗ druppie/services/*
```

This ensures the library is truly standalone and reusable by external applications.

### Testing isolation

Tests in `druppie/tests/agent_runtime/`:
- Only import from `druppie.agent_runtime.*`
- Use mocks/stubs for all external dependencies
- Do NOT import from `druppie.agents`, `druppie.execution`, `druppie.domain`
- Do NOT require a running database, Docker, or any infrastructure
- Run with: `cd druppie && pytest tests/agent_runtime/ -v`
- Can also run the full suite: `cd druppie && pytest` (both old and new tests)

### CI integration

No changes to CI configuration needed. The new tests are discovered automatically by pytest. The existing test suite continues to work as before.
