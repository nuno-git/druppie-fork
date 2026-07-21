# Agent Runtime Specification

> **Status: Historical planning doc (technical spec).** As-built reference: `docs/TECHNICAL.md` §11. Retained for the detailed design.

> This document contains the final architecture decisions for the Druppie agent runtime library.
> For research context, alternatives considered, and rationale, see `docs/research-agent-runtime.md`.

## Overview

The agent runtime is a Python library that replaces `loop.py` and the old sandbox-based execution prototype, providing a unified agent execution environment with `done()` enforcement, MCP tools, subagent spawning, and per-agent sandbox containers. The library is usable by both the Druppie backend and external applications.

## Architecture

The runtime consists of these core components:

- **AgentLoop** - The main execution loop that enforces `done()`, manages tools, handles LLM calls
- **ToolProvider** - Router that aggregates tools from MCP servers and routes tool calls to the correct MCP server, with approval gates and pre-validation hooks
- **EventEmitter** - Tracks and emits events during execution for streaming and persistence
- **AgentDefinition** - YAML-based agent configuration with tool access, LLM settings, and role

The caller (Druppie backend or application) provides:
- Agent definitions (loaded from YAML)
- MCP connections (ToolProvider instances for each MCP server)
- LLM callable (litellm-compatible, pre-configured with profiles and fallbacks)
- Event callbacks (for real-time streaming to frontend)
- Sandbox pool management (warm container pool for faster startup)

The runtime handles:
- Turn-based LLM interaction with tool execution
- `done()` enforcement and validation
- Pause/resume for long-running operations
- Event tracking and serialization
- Context overflow handling (forces done() when context limit approached)
- Context compaction (LLM summarization when context pressure exceeds threshold)
- Cancellation support

## Agent Definition Format (YAML)

All agents use a unified YAML format. The `mcps` field declares which MCP servers and tools the agent can access. The `role` field restricts where the agent can appear in flows. The `done_variables` field (optional) defines what custom variables beyond `summary` the agent must/may set when calling `done()`, using full JSON Schema syntax. Note: `summary` is always required and never defined in `done_variables`.

**Note on field naming**: Throughout the spec, `agent` (in tool parameters like `subagents` and `make_plan`) and `agent_id` (in agent_runs table) both refer to the agent's name as defined in the YAML file (e.g., 'developer', 'planner'). The YAML field name for the agent is `id`, but tool calls use the `agent` parameter, and storage uses the `agent_id` column. They all mean the same thing: the agent name.

### Complete AgentDefinition YAML Reference

```yaml
# Complete AgentDefinition YAML Reference
# All fields shown below. Only 'id', 'name', 'description', 'system_prompt' are required.

id: agent_id                    # Required. Unique identifier (kebab-case)
name: Agent Display Name        # Required. Human-readable name
description: "Short purpose"    # Required. Used in subagent tool descriptions
role: primary | subagent | both # Optional, default: primary. Whether this agent can be used as subagent

system_prompt: |                # Required. Main system prompt (string)
  You are...

# OR use system_prompts (array of named prompts from prompts/ directory):
# system_prompts:
#   - tool_only_communication
#   - summary_relay
#   - done_tool_format

temperature: 0.1               # Optional, default: 0.1. LLM temperature
max_tokens: 4096               # Optional, default: 4096. Max tokens per response
max_iterations: 20             # Optional, default: 20. Max turns before forcing done()

llm_profile: default           # Optional, default: "default". LLM profile from llm_profiles.yaml

skills:                        # Optional. List of skill names the agent can invoke
  - code-review

subagents:                     # Optional. List of agent_ids this agent can spawn as subagents
  - builder                    # Only agents listed here can be spawned
  - verifier                   # If absent or empty, agent cannot use subagents() tool

required_summary_status:       # Optional. Summary must contain at least one keyword
  one_of:
    - "STATUS_ONE"
    - "STATUS_TWO"
  error_message: "Your summary must contain one of: STATUS_ONE, STATUS_TWO"

completion_preconditions:      # Optional. Conditional tool call requirements
  - summary_contains: "STATUS_KEYWORD"   # Only check when summary contains this
    unless_summary_contains: "EXCEPTION" # Skip precondition when summary contains this
    required_tools:
      - tool_name: "some_tool"           # Tool must have been called
        min_calls: 1                      # At least this many times
    error_message: "You must call some_tool before calling done()"

done_variables:                # Optional. Custom variables for done() (beyond summary)
  next_agent:                  # Variable name becomes done() parameter
    type: string
    enum: [architect, developer]
    required: true
  confidence:
    type: number
    required: false

mcps:                          # Required. MCP server configuration
  sandbox:                     # Sandbox MCP (file operations, per-agent containers)
    tools: [read_file, write_file, edit_file, bash, push_changes, submit_design_for_review]
    git: current_project | other_projects | update_core  # Git scope for sandbox
  core-tools: [hitl_ask_question, make_plan, set_intent]  # Core tools (list of allowed tools)
  docker: [deploy]             # Docker MCP (optional, shared infrastructure)
  web: [search_web, fetch_url] # Web MCP (optional, web access)

approval_overrides:            # Override default approval behavior for specific tools. Key format: "mcp_server_name:tool_name". Only tools needing overrides need listing.
  "sandbox:push_changes":
    requires_approval: true
    required_role: "architect"
  "sandbox:submit_design_for_review":
    requires_approval: false
    pre_validate: "validate_mermaid"

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| requires_approval | boolean | Yes | Override default approval for this tool |
| required_role | string | No | Role required to approve (e.g., "architect") |
| pre_validate | string | No | Validation tool to call before execution |
```

### Agent Definitions Overview

The following table provides a broad overview of all agents for quick reference. Full YAML definitions with complete system prompts are in `druppie/agents/definitions/*.yaml`. The system prompts should be migrated as-is without changes.

| Agent | Role | Purpose | Key Tools |
|-------|------|---------|-----------|
| router | primary | Classifies user intent, creates/selects projects | set_intent, done |
| planner | primary | Creates execution plans, re-evaluates after each agent | make_plan, done |
| business_analyst | primary | Gathers requirements, creates functional design | hitl_ask_question, submit_design_for_review, done |
| architect | primary | Creates technical design | submit_design_for_review, done |
| developer | primary | Implements features, spawns coding subagents | subagents, done |
| coding_planner | subagent | Plans coding tasks within developer | subagents, done |
| builder | subagent | Executes coding tasks | sandbox file tools, bash, done |
| tester | subagent | Runs tests and validates implementations | sandbox bash, done |
| verifier | subagent | Verifies implementation against design | sandbox file tools, done |
| summarizer | primary | Summarizes session, creates final message | create_message, done |

### Core Agents (Business Analyst, Architect, Developer)

```yaml
id: business_analyst
name: Business Analyst
description: "Gathers requirements and creates functional designs"
role: primary
system_prompt: |
  You are a business analyst. Gather requirements from the user,
  ask clarifying questions via hitl_ask_question, and create
  functional designs using submit_design_for_review.
system_prompts:
  - professional_tone
  - requirement_gathering
skills: [code-review]
mcps:
  sandbox:
    tools: [read_file, submit_design_for_review]
    git: current_project
  core-tools: [hitl_ask_question, invoke_skill]
llm_profile: standard
temperature: 0.7
max_tokens: 4000
max_iterations: 10
completion_preconditions:
  - summary_contains: "DESIGN_APPROVED"
    unless_summary_contains: "REQUIREMENT_CHALLENGE outcome: HARD"
    required_tools:
      - tool_name: "submit_design_for_review"
        min_calls: 1
    error_message: >
      PRECONDITION FAILED: You cannot call done() with DESIGN_APPROVED without
      first creating docs/functional-design.md.
approval_overrides:
  "sandbox:submit_design_for_review":
    requires_approval: false
```

```yaml
id: architect
name: Architect
description: "Creates technical designs and architecture decisions"
role: primary
subagents: [update_core_builder]
done_variables:
  design_approved:
    type: boolean
    required: true
  core_update_needed:
    type: boolean
    required: false
system_prompt: |
  You are an architect. Review technical designs, approve them
  via submit_design_for_review, and oversee deployment using docker MCP tools.
system_prompts:
  - professional_tone
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, submit_design_for_review, push_changes]
    git: current_project
  docker: [build, run, compose_up]
  core-tools: [hitl_ask_question, make_plan]
llm_profile: standard
temperature: 0.7
approval_overrides:
  "sandbox:submit_design_for_review":
    requires_approval: true
    required_role: architect
    pre_validate: "validate_mermaid"
  "docker:build":
    requires_approval: true
    required_role: architect
```

```yaml
id: developer
name: Developer
description: "Orchestrates the development flow, delegates to coding planner"
role: both
subagents: [coding_planner]
system_prompt: |
  You are a developer. Read functional designs and implement
  features using file operations, bash, and git.
system_prompts:
  - professional_tone
  - code_quality
skills: [git-workflow]
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, grep, find, ls, push_changes]
    git: current_project
  core-tools: [invoke_skill]
llm_profile: standard
temperature: 0.5
completion_preconditions:
  - summary_contains: "IMPLEMENTATION_COMPLETE"
    required_tools:
      - tool_name: "write_file"
        min_calls: 1
      - tool_name: "push_changes"
        min_calls: 1
```

### Coding Subagents (Planner, Builder, Tester, Verifier)

```yaml
id: coding_planner
name: Coding Planner
description: "Creates detailed implementation plans from requirements"
role: subagent
subagents: [builder, tester]
system_prompt: |
  You are a coding planner. Break down tasks and coordinate
  builder and tester subagents via the subagents tool.
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash]
    git: current_project
  core-tools: [make_plan]
llm_profile: fast
temperature: 0.7
max_iterations: 15
```

```yaml
id: builder
name: Builder
description: "Implements code changes based on a plan"
role: subagent
# no done_variables → done() just needs summary (always required), variables is empty dict
system_prompt: |
  You are a builder. Implement code according to the plan
  using read, write, edit, and bash tools.
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, grep, find, ls]
    git: current_project
  core-tools: [make_plan]
llm_profile: fast
temperature: 0.3
max_iterations: 20
```

```yaml
id: tester
name: Tester
description: "Runs tests and validates implementations"
role: subagent
system_prompt: |
  You are a tester. Run tests using bash and grep to verify
  implementations work correctly.
mcps:
  sandbox:
    tools: [read_file, bash, grep, find, ls]
    git: current_project
llm_profile: fast
temperature: 0.3
max_iterations: 10
```

```yaml
id: verifier
name: Verifier
description: "Builds and verifies the complete implementation"
role: subagent
system_prompt: |
  You are a verifier. Build the project and run all tests
  to ensure the implementation is complete and working.
mcps:
  sandbox:
    tools: [read_file, bash, grep, find, ls]
    git: current_project
llm_profile: fast
temperature: 0.3
max_iterations: 5
```

### Special Agents

```yaml
id: planner
name: Planner
description: "Coordinates agent flow, makes routing decisions"
role: primary
subagents: [architect, developer]
done_variables:
  next_agent:
    type: string
    enum: [architect, developer]
    required: true
  confidence:
    type: number
    required: false
system_prompt: |
  You are a planner. Coordinate the agent flow by routing tasks
  to architect and developer agents as needed.
mcps:
  core-tools: [make_plan, hitl_ask_question]
llm_profile: standard
temperature: 0.7
max_iterations: 15
```

```yaml
id: update_core_builder
name: Update Core Builder
description: "Modifies Druppie's core codebase via GitHub PRs"
role: subagent
system_prompt: |
  You modify Druppie's core codebase. Work on the GitHub
  repository cloned in your sandbox. Use push_changes to submit changes.
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, push_changes]
    git: update_core
  core-tools: [make_plan]
llm_profile: standard
temperature: 0.5
```

```yaml
id: explore_other_projects
name: Explorer
description: "Explores other projects for reference"
role: subagent
system_prompt: |
  You explore other projects for reference. Read files to
  understand existing implementations. This is read-only.
mcps:
  sandbox:
    tools: [read_file]
    git: other_projects
llm_profile: fast
temperature: 0.3
```

## Core Types

### LoopConfig

```python
@dataclass
class LoopConfig:
    max_turns: int = 50
    max_retries: int = 3
    retry_base_delay: float = 1.0
    respect_retry_after: bool = True
    max_context_tokens: int = 150000  # Default context limit
    max_subagent_depth: int = 10
    sandbox_pool_size: int = 3
    sandbox_pool_recycle_s: int = 3600
```

- `max_turns` - Maximum number of LLM calls (turns). The done() call counts toward this limit. If max_turns=10, the agent gets 10 total turns including the one where it calls done().
- `max_retries` - Maximum LLM retry attempts
- `retry_base_delay` - Base delay for exponential backoff (seconds)
- `respect_retry_after` - Honor Retry-After headers from LLM providers
- `max_context_tokens` - Context window limit, forces done() when approached
- `max_subagent_depth` - Maximum recursion depth for subagent spawning
- `sandbox_pool_size` - Number of warm sandbox containers to maintain
- `sandbox_pool_recycle_s` - Recycle idle containers after this timeout (seconds)

### DoneResult

**Note:** done() produces a standard tool_result event where content = JSON with summary + variables. No special event type needed.

### AgentResult

```python
@dataclass
class AgentResult:
    status: Literal["completed", "error", "cancelled", "paused"]
    done_result: dict | None = None  # Present when status="completed" — {summary: str, variables: dict}
    error: str | None = None  # Present when status="error"
    events: list[AgentEvent] = []  # All events emitted during this run
```

- `status` - Final execution status
- `done_result` - The done tool result if completed (dict with summary and variables)
- `error` - Error message if failed
- `events` - All events from the run (stateful storage)

When status is "paused", the caller reconstructs the conversation history from the saved events to resume.

**Resume from events** — When an agent pauses (HITL question, approval gate), the caller does NOT save a serialized state blob. Instead, on resume the caller loads agent state entries from a single append-only table (`agent_state_events`). Each entry IS an LLM message with added metadata (timestamp, sequence_number, tokens, etc.). Events are the single source of truth — the timeline, streaming, and resume all derive from them.

Reconstruction: The caller queries all `agent_state_events` entries for this agent_run from DB, filters to LLM roles (system/user/assistant/tool), and maps them directly to LLM message format. No complex reconstruction needed — entries already ARE messages with metadata. The agent continues exactly where it left off.

**Event types** — Events are stored as `agent_state_events` entries. The event types map directly to the `role` field:

| Role/Type | Description | Key Fields |
|-----------|-------------|------------|
| system | Agent's system prompt | content |
| user | User message or injected prompt | content |
| assistant | LLM response | content, tool_calls |
| tool | Tool execution result | tool_call_id, content, _pending | _pending values:
  true    → Tool is pauseable, execution pauses, approval/question flow starts
  false   → Tool was pauseable, completed normally  
  omitted → Tool is not pauseable, always completes inline |
| approval | Approval gate | approval_status, required_role |
| question | HITL question | question_id, answer |

### AgentEvent

```python
@dataclass
class AgentEvent:
    type: str
    timestamp: datetime
    data: dict

# Event types with their data schemas:
# - turn_start: {turn_number: int}
# - turn_end: {turn_number: int, tokens_used: int}
# - tool_call: {tool_name: str, arguments: dict, call_id: str}
# - tool_result: {tool_name: str, result: dict, call_id: str, _pending: bool | None}
# - subagent_start: {agent: str, task: str, depth: int, parent_agent_id: str}
# - subagent_end: {agent: str, result: dict, depth: int, parent_agent_id: str}
# - done: {summary: str, variables: dict}
# - enforcement_retry: {reason: str}
# - llm_retry: {attempt: int, error: str, delay: float}
# - pending: {resume_id: str, pause_reason: str | None}
# - error: {message: str, traceback: str | None}
```

All events are stored internally in `AgentResult.events` and emitted via callbacks for real-time streaming.

### Session State Persistence

**Event storage — single append-only table**:

```sql
CREATE TABLE agent_state_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    parent_agent_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,

    -- Event type (maps directly to LLM message roles + approval/question)
    role VARCHAR(20) NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool', 'approval', 'question')),

    -- Content
    content TEXT,
    tool_calls JSONB,           -- For assistant: [{id, name, arguments}]
    tool_call_id VARCHAR(100),   -- For tool/approval/question: links to assistant's tool_call.id

    -- Ordering
    sequence_number INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- Rich metadata (varies by role)
    metadata JSONB DEFAULT '{}'
);

-- Indexes
CREATE INDEX idx_ase_session ON agent_state_events(session_id);
CREATE INDEX idx_ase_agent_run ON agent_state_events(agent_run_id);
CREATE INDEX idx_ase_sequence ON agent_state_events(agent_run_id, sequence_number);
CREATE INDEX idx_ase_tool_call_id ON agent_state_events(tool_call_id);
CREATE INDEX idx_ase_timeline ON agent_state_events(session_id, created_at);
```

**Metadata schema by role**:

| Field | system | user | assistant | tool | approval | question |
|-------|--------|------|-----------|------|----------|----------|
| model | - | - | ✅ | - | - | - |
| prompt_tokens | - | - | ✅ | - | - | - |
| completion_tokens | - | - | ✅ | - | - | - |
| total_tokens | - | - | ✅ | - | - | - |
| duration_ms | - | - | ✅ | ✅ | - | - |
| mcp_server | - | - | - | ✅ | ✅ | ✅ |
| tool_name | - | - | - | ✅ | ✅ | ✅ |
| status | - | - | - | ✅ | - | - |
| error_message | - | - | - | ✅ | - | - |
| approval_status | - | - | - | - | ✅ | - |
| required_role | - | - | - | - | ✅ | - |
| resolved_by | - | - | - | - | ✅ | - |
| resolved_at | - | - | - | - | ✅ | - |
| question_type | - | - | - | - | - | ✅ |
| question_status | - | - | - | - | - | ✅ |
| answer | - | - | - | - | - | ✅ |
| answered_at | - | - | - | - | - | ✅ |
| subagent_run_id | - | - | - | ✅ | - | - |
| context_overflow | - | - | ✅ | - | - | - |

**agent_runs table still exists for status/summary/variables**:

```python
agent_run = {
    "id": UUID,
    "session_id": UUID,
    "agent": str,             # Agent name from YAML definition (e.g., "developer", "planner", "router")
    "parent_agent_run_id": UUID | None,
    "source_tool_call_id": str | None,  # The tool_call ID from the parent's tool_calls JSONB array in agent_state_events. NOT a FK to a separate table — it's the call_id string from an assistant event's tool_calls array.
    "status": "pending" | "running" | "completed" | "paused" | "cancelled",
    "sequence_number": int | None,
    "planned_prompt": str,
    "summary": str | None,
    "variables": dict | None,
}
```

`agent_id` stores the agent's name as defined in the YAML filename (e.g., 'developer'). This is the same value used in `subagents()` tool calls and `make_plan` plans.

Note: `agent_runs` still tracks status/summary/variables. `agent_state_events` stores the conversation history. No more separate `llm_calls`, `tool_calls` tables — those are now entries in `agent_state_events`.

**Design Decisions**

**Q: Assistant + tool_calls — ONE row or MULTIPLE?**
A: ONE row. The assistant's turn is a single entry with `tool_calls` as a JSONB array. This matches the LLM API's response format.

**Q: Tool results — one row per tool or batched?**
A: One row per tool result. Each `role="tool"` entry has its own `tool_call_id` linking back to the assistant's `tool_calls[].id`.

**Q: Approval/question — separate roles or tool with status?**
A: Separate roles (`role="approval"`, `role="question"`). These are NOT part of the LLM conversation — they're excluded when filtering for resume. They serve as timeline markers for UI. When resumed, the row is UPDATED (add answer/approval status), then a `role="tool"` entry is inserted with the simulated result.

**Q: Subagent events — separate rows or tool call + result?**
A: Subagent is just a tool call + tool result in the PARENT's event stream. The subagent has its OWN events (same table, different `agent_run_id`). The parent's tool result includes `metadata.subagent_run_id` linking to the child's agent_run.

**Q: Metadata — JSONB or separate columns?**
A: JSONB. Different roles need different metadata. Most is display-only, not queried. Simpler schema, no migrations for new fields.

**Event-to-message mapping** — Entries already use LLM roles, so the mapping is simple:

| Entry Role | LLM Message | Notes |
|------------|-------------|-------|
| system | system message | Agent's system prompt |
| user | user message | Injected prompt or user input |
| assistant | assistant message | May include tool_calls |
| tool | tool message | Linked by tool_call_id |
| approval | excluded from LLM messages | Timeline-only |
| question | excluded from LLM messages | Timeline-only |

**Key Queries**

```sql
-- Resume: get LLM messages for an agent run
SELECT * FROM agent_state_events
WHERE agent_run_id = 'run-001'
  AND role IN ('system', 'user', 'assistant', 'tool')
ORDER BY sequence_number;

-- Timeline: get all events for a session
SELECT * FROM agent_state_events
WHERE session_id = 'sess-001'
ORDER BY created_at;

-- Subagent events: get all events for a subagent
SELECT * FROM agent_state_events
WHERE agent_run_id = 'run-002'
ORDER BY sequence_number;

-- Find subagents of a parent
SELECT DISTINCT agent_run_id FROM agent_state_events
WHERE parent_agent_run_id = 'run-001';

-- Pending questions/approvals
SELECT * FROM agent_state_events
WHERE agent_run_id = 'run-001'
  AND role IN ('question', 'approval')
  AND (metadata->>'question_status' = 'pending'
   OR metadata->>'approval_status' = 'pending');
```

**Resume Projection**

```python
def to_llm_messages(entries: list[AgentStateEvent]) -> list[dict]:
    """Convert event log to LLM messages — just filter and map."""
    messages = []
    for entry in entries:
        if entry.role == "system":
            messages.append({"role": "system", "content": entry.content})
        elif entry.role == "user":
            messages.append({"role": "user", "content": entry.content})
        elif entry.role == "assistant":
            msg = {"role": "assistant", "content": entry.content or ""}
            if entry.tool_calls:
                msg["tool_calls"] = entry.tool_calls
            messages.append(msg)
        elif entry.role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": entry.tool_call_id,
                "content": entry.content or ""
            })
        # approval/question: excluded
    return messages
```

Resume is simply: `filter(entry.role in ["system", "user", "assistant", "tool"])` then map to LLM format.

#### Approval/Question Resume Flow

When a user answers a question or approves a tool:

1. **Find the pending entry**: Look up the approval/question event for this agent_run that has status "pending".
2. **Update with user's response**: Update the event's metadata with the answer/approval status and who resolved it.
3. **Insert simulated tool result**: Add a new `role="tool"` event with the tool_call_id from the original pending tool call. For approvals, the content contains the original tool arguments (re-executed). For questions, the content is the user's answer.
4. **Resume the agent run**: Reconstruct `initial_messages` from all events. The approval/question row is excluded from LLM messages — only the tool result is included.
5. **The LLM sees** the tool result as if the tool completed normally and continues.

### CancellationToken

```python
class CancellationToken:
    def cancel(self) -> None: ...

    @property
    def is_cancelled(self) -> bool: ...
```

Passed to `run()` for cancellation support. The runtime checks this between turns and raises `AgentCancelledError` if set.

## Context Compaction

When the conversation grows large, the compactor replaces the entire conversation body with an LLM-generated summary. This gives the agent a clean slate while preserving the system prompt and original user instruction.

### When It Fires

At the start of each turn, `MessageCompactor.compress()` estimates token count from message content. If tokens exceed `summarization_threshold * max_context_tokens`, the entire conversation (minus header) is serialized and sent to the LLM for summarization. The summary replaces all body messages.

**Header** = leading `system` + `user` messages (agent prompt + initial instruction). These are always preserved.

**Body** = everything after the header (assistant responses, tool calls, tool results). This is what gets replaced.

The result is always: `[system, user, summary_message]` — three messages, minimal context, agent starts fresh.

### CompactionConfig

```python
@dataclass
class CompactionConfig:
    max_context_tokens: int = 150_000
    summarization_threshold: float = 0.70
    max_compactions: int = 10
    max_input_chars: int = 30_000
    max_output_tokens: int = 1024
    tool_result_max_chars: int = 15_000
```

| Field | Default | Description |
|-------|---------|-------------|
| `max_context_tokens` | 150000 | Context window size estimate |
| `summarization_threshold` | 0.70 | Fraction of max_context_tokens that triggers compaction (e.g., 0.70 = 105K tokens) |
| `max_compactions` | 10 | Maximum compactions before forcing done(). After this, agent is forced to finish |
| `max_input_chars` | 30000 | Max characters of conversation history sent to LLM for summarization |
| `max_output_tokens` | 1024 | Max tokens for the summary response |
| `tool_result_max_chars` | 15000 | Truncation limit for individual tool results in the conversation |

### max_compactions Limit

Each successful compaction increments a counter on `CompactionState.compactions_performed`. When the counter reaches `max_compactions`:

1. The loop restricts tools to `done()` only
2. A system message is injected: *"You have reached the maximum number of context compactions. Call done() NOW with a summary of your progress so far."*
3. The agent gets one turn to comply
4. If the agent does not call `done()`, the loop AUTO-DONEs with `reason: "max_compactions_exceeded"`

This prevents infinite compaction loops where summarization quality degrades with each cycle.

### YAML Configuration

Compaction is configured per-agent via the `compression` key:

```yaml
id: developer
# ... other fields ...
compression:
  summarization_threshold: 0.65
  max_compactions: 10
```

If `compression` is omitted, defaults apply (`threshold=0.70`, `max_compactions=10`).

### Compaction Events

Each compaction emits a `context_compressed` event with:

```python
{
    "phase": "summarized",          # or "summarized_fallback" if LLM failed
    "tokens_before": 105000,         # Estimated tokens before compaction
    "tokens_after": 3200,            # Estimated tokens after compaction
    "turns_compressed": 42,          # Number of messages replaced
    "summary_text": "...",           # The LLM-generated summary (absent in fallback)
}
```

Events are persisted to the `compaction_events` table via `CompactionEventRepository` and surfaced in the session detail API as `compaction_events` on each `AgentRunDetail`.

### Tool Result Truncation

Large tool results are truncated before they enter the conversation to delay compaction:

```python
MessageCompactor.truncate_tool_result(content, max_chars=15_000)
```

- Content under 15K chars: unchanged
- Content 15K–50K chars: first 5K + last 2K with truncation notice
- Content over 50K chars: first 3K + last 1K with truncation notice

### Fallback Behavior

If the LLM call for summarization fails (network error, rate limit, etc.), the compactor falls back to a generic placeholder message: `"[CONVERSATION SUMMARY — older turns dropped due to context limit]"`. The fallback still counts toward `max_compactions`.

## LLM Interface

The runtime accepts any async callable compatible with the litellm `acompletion()` signature:

```python
async def acompletion(
    messages: list[dict],
    tools: list[dict] | None = None,
    **kwargs
) -> dict
```

The caller provides a pre-configured callable that handles:
- LLM provider selection (OpenAI, Anthropic, ZAI, etc.)
- Profile resolution (from agent definition's `llm_profile`)
- Fallback configuration (primary + secondary providers)
- Model selection

The runtime does not know about profiles, providers, or fallbacks. It just calls `await llm(messages=..., tools=..., **kwargs)`.

### Example Caller Configuration

```python
# Caller-side (Druppie backend)
from druppie.llm import ChatLiteLLM, FallbackLLM

def resolve_llm(profile_name: str) -> Callable:
    profile_config = load_llm_profile(profile_name)
    primary = ChatLiteLLM(
        provider=profile_config.primary.provider,
        model=profile_config.primary.model
    )
    if profile_config.secondary:
        secondary = ChatLiteLLM(
            provider=profile_config.secondary.provider,
            model=profile_config.secondary.model
        )
        return FallbackLLM(primary, secondary)
    return primary

# When running agent
llm = resolve_llm(agent_def.llm_profile)
result = await loop.run(agent_def, prompt, ..., llm=llm)
```

## Builtin Tools

The runtime provides TWO builtin tools: `done` and `subagents`. Both are always available (when configured). The key difference: `done` is implemented directly by the runtime loop. `subagents` is implemented as an in-process MCP server (SubagentsMCP) — it's still builtin (ships with the library, cannot be swapped), but follows the MCP protocol for consistency. All other tools come from external MCP servers routed through the ToolProvider.

### done()

The `done()` builtin is a **RUNTIME builtin**, NOT a ToolProvider tool. It is always included for every agent. Every agent MUST call done() per D9 enforcement. It serves three purposes:

1. **Exit signal** - Tells the loop to stop
2. **Result capture** - Captures `summary` and `variables` from the tool call
3. **Precondition validation** - Checks agent-specific rules before accepting

#### Dynamic Schema Generation

The runtime generates the `done()` tool schema dynamically based on the agent's `done_variables` YAML field:

- **`summary` is ALWAYS required in every done() call** — hardcoded, not configurable, never in done_variables YAML
- **`done_variables` in YAML defines ONLY the custom variables beyond summary**
- **The generated done() tool schema always has `summary: {type: string, required: true}` plus whatever done_variables defines**
- **Summary is never in done_variables YAML — it's implicit**

The LLM sees the schema and knows exactly what variables to set.

#### Function Signature (no done_variables)

When no `done_variables` is defined in the agent YAML:

```python
done(
    summary: str,      # Always required — summary of work completed
    variables: dict    # Optional key-value pairs for downstream agents (default: empty dict)
) -> DoneResult
```

#### Function Signature (with done_variables)

When `done_variables` IS defined in the agent YAML, the runtime generates a tool schema with `summary` (always) plus each variable from `done_variables` as a parameter. The function signature depends on the defined schema.

#### Example Generated Schema

For an agent with this YAML:

```yaml
done_variables:
  next_agent:
    type: string
    enum: [architect, developer]
    required: true
  confidence:
    type: number
    required: false
```

The runtime generates this tool schema (note: `summary` is always added implicitly):

```json
{
  "name": "done",
  "description": "Signal completion. Provide a summary of what you accomplished.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "summary": {"type": "string", "description": "What you accomplished"},
      "next_agent": {"type": "string", "enum": ["architect", "developer"]},
      "confidence": {"type": "number"}
    },
    "required": ["summary", "next_agent"]
  }
}
```

Note: `summary` is always in `properties` and always in `required`. Everything else comes from `done_variables`.

#### Validation Flow

When an agent calls `done()`, the runtime validates:

1. **Schema validation** - If `done_variables` is defined, the runtime validates the call against the generated JSON Schema:
    - **Missing required variable** → enforcement retry with error message
    - **Wrong type** (e.g., string instead of number) → enforcement retry with error message
    - **Invalid enum value** → enforcement retry with error message
    - Agent must retry with correct values

2. **Completion preconditions** - The runtime tracks ALL tool calls per agent run (tool_name and call count). When done() is called, the runtime checks ALL preconditions:

3. Completion preconditions (if defined in agent YAML):
   a. First check required_summary_status (if defined):
      - Summary must contain at least one of the `one_of` keywords
      - If missing → reject done() with error_message
   b. Then check each completion_precondition:
      - If `summary_contains` is defined and NOT in summary → skip this precondition (not triggered)
      - If `unless_summary_contains` is defined and IS in summary → skip this precondition (exception case)
      - Otherwise: verify all `required_tools` were called at least `min_calls` times
      - If any tool call count < min_calls → reject done() with error_message
   c. If ANY check fails → reject done() with the specific error_message
   d. The error is returned as a tool result — the LLM sees it and must correct before calling done() again

#### What done() Does NOT Do

The runtime does NOT handle:
- Summary accumulation across agents (collecting previous agent summaries, deduplication)
- Next agent routing (inserting agent runs, manipulating sequence numbers)
- Inter-agent context passing (relaying summaries to next pending agent)
- Git enforcement (committing or pushing changes)

These are handled by the caller after `done()` returns.

#### Preconditions Data Model

```python
@dataclass
class RequiredToolCall:
    tool_name: str
    min_calls: int = 1

@dataclass
class CompletionPrecondition:
    summary_contains: str | None = None
    unless_summary_contains: str | None = None
    required_tools: list[RequiredToolCall] = field(default_factory=list)
    error_message: str = ""

@dataclass
class CompletionSummaryRequirement:
    one_of: list[str]  # e.g., ["DESIGN_APPROVED", "DESIGN_REJECTED"]
```

## MCP Tool Architecture

### ToolProvider Interface

The ToolProvider is the abstraction layer between the runtime and MCP servers.

```python
class ToolProvider(Protocol):
    async def list_tools(self) -> list[dict]:
        """Return ALL tools from connected MCP servers (no filtering)."""
        ...

    async def execute(
        self,
        tool_name: str,
        arguments: dict
    ) -> dict:
        """Execute a tool with pre-validation and approval gates.

        Pipeline:
        1. Pre-validation hook (if configured) - run validation tool first
        2. Approval gate - check if tool needs approval, return _pending if yes
        3. Execute - call the MCP server

        Returns:
        - Success: {"success": True, "data": ...}
        - Error: {"success": False, "error": "description"}
        - Approval pending: {"success": True, "_pending": True, "resume_id": "..."}

        ToolProvider errors are returned as error dicts, never raised.
        """
        ...

    async def close(self) -> None:
        """Clean up MCP connections."""
        ...
```

#### Responsibilities

| Concern | Handled by |
|---------|-----------|
| Tool filtering (what LLM sees) | Agent runtime - filters provider's tool list by agent's `mcps` |
| Skill tool expansion | Agent runtime - adds tools on `allowed_tools` response |
| Pre-validation (mermaid check) | ToolProvider - pre-execution hook (routes to validation tool on MCP server) |
| Approval gates | ToolProvider - checks rules, returns `_pending` if needed |
| Tool routing | ToolProvider - routes `execute(tool_name, args)` to the correct MCP server |
| Subagent spawning | Subagents MCP server - in-process server that loads definitions, checks roles, spawns runtime instances, returns results |
| Sandbox creation and sharing | Sandbox MCP server - creates/resolves sandboxes based on git scope |

#### Pre-Validation + Approval Flow

Example: `submit_design_for_review` needs mermaid validation + architect approval.

```
1. LLM calls submit_design_for_review(content="graph TD...")
2. Runtime calls provider.execute("submit_design_for_review", {content: "..."})
3. Provider: pre-validation hook
   ├── Call mermaid_validate(content) on MCP server
   ├── If validation fails → return error to LLM immediately
   └── If validation passes → continue
4. Provider: approval gate
   ├── Check: does submit_design_for_review need approval for this agent?
   ├── Yes → return {"_pending": true, "_resume_id": "approval_xxx"}
   └── User approves (hours later)
5. Provider: actual execution
   └── Call submit_design_for_review(content) on MCP server → return result
```

#### Role Enforcement for Subagents

Role enforcement happens in the **subagents MCP server**, not in the ToolProvider. When the subagents MCP server receives a `subagents()` call (routed from the ToolProvider):

1. Load target agent definitions from the call
2. Check each target's `role` field
3. Reject if a `subagent`-only agent is called at top level
4. Resolve sandboxes for each subagent (based on git scope matching)
5. Spawn new agent runtime instances for each subagent (calls `run()` for each)
6. Wait for all subagent results using `asyncio.gather()` for parallel execution
7. Return combined results to the parent agent

This ensures agents designed as subagents cannot be invoked directly as top-level agents. The ToolProvider simply routes the call to the subagents MCP server, which handles all the validation and spawning logic.

### subagents() Tool

The `subagents()` tool is NOT a ToolProvider tool — it's a tool on its own **in-process MCP server** (the subagents MCP server). The ToolProvider routes calls to this MCP server just like it routes `read_file` to the sandbox MCP. The subagents tool is only included when the agent YAML has a `subagents` field.

#### Function Signature

```python
subagents(
    agents: list[dict]  # [{agent: "builder", prompt: "..."}, ...]
) -> list[dict]
```

#### Dynamic Schema Generation

The **subagents MCP server** generates the tool schema dynamically based on the agent's `subagents` list. For an agent with `subagents: [coding_planner]`, the subagents MCP server generates:

```json
{
  "name": "subagents",
  "description": "Spawn subagents to accomplish tasks. Available agents:\n- coding_planner: Creates detailed implementation plans from requirements\n\nEach subagent runs independently and returns results.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "agents": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "agent": {"type": "string", "enum": ["coding_planner"]},
            "prompt": {"type": "string"}
          },
          "required": ["agent", "prompt"]
        }
      }
    },
    "required": ["agents"]
  }
}
```

The tool description includes each available agent's name + description (from their YAML `description` field). The `agent` parameter has an `enum` restricted to only the allowed agents, preventing 99% of invalid calls at the LLM framework level.

#### Two-Layer Validation

1. **Schema validation**: The LLM framework rejects tool calls with agent names not in the `enum` (catches 99% of errors)
2. **Server-side validation**: The subagents MCP server checks that the called agent is in the allowed list (safety net)

If validation fails at the subagents MCP server:
```python
return {"success": false, "error": "Agent 'invalid_agent' not in allowed subagents list"}
```

#### Flow

When an agent calls the `subagents()` tool:

1. The agent's LLM generates a tool call to `subagents(agents=[...])`
2. The runtime calls `tool_provider.execute("subagents", {agents: [...]})`
3. The ToolProvider routes the call to the **subagents MCP server**
4. The subagents MCP server validates that each `agent` is in the parent's `subagents` list
5. The subagents MCP server loads target agent definitions from `agent_loader`
6. The subagents MCP server checks role enforcement (rejects if `subagent`-only agent called at top level)
7. The subagents MCP server resolves sandboxes for each subagent (based on git scope matching):
   - Compares child's `mcps.sandbox.git` to parent's git scope
   - If same → shares parent's MCP connection
   - If different → calls `sandbox_resolver(child_git_scope)` for new connection
   - Passes `sandbox_resolver` to child `run()` calls for nested subagent spawning
8. The subagents MCP server spawns NEW agent runtime instances for each subagent (calls `run()` for each)
9. The subagents MCP server waits for all subagent results (using `asyncio.gather()` for parallel execution)
10. The subagents MCP server returns results to the ToolProvider
11. The ToolProvider returns the results to the runtime, which returns them to the parent agent

The runtime (AgentLoop) only sees this as a regular tool call — it calls the ToolProvider, gets a result, and continues. It doesn't know about subagent spawning or which MCP server handled the call.

#### Parallel Execution

The **subagents MCP server** executes subagents concurrently using `asyncio.gather()`. Each subagent gets:

- Its own `AgentDefinition` (loaded via `agent_loader`)
- A scoped `ToolProvider` (resolved from the parent's ToolProvider based on the subagent's `mcps`)
- Event callbacks with `parent_agent_id` linkage
- An LLM callable (same as parent, or per-agent if configured)
- A sandbox container (if the subagent's definition has `mcps.sandbox`):
  - If git scope matches parent → shares parent's MCP connection
  - If different git scope → `sandbox_resolver` creates new connection
- The `sandbox_resolver` callback (passed through for nested subagent spawning)

#### Results

The **subagents MCP server** returns a list of results, one per subagent:

```python
[
    {"agent": "builder_1", "status": "success", "result": AgentResult(...)},
    {"agent": "builder_2", "status": "error", "error": "LLM timeout after 3 retries"}
]
```

Each item has:
- `agent` (str) - Agent name/ID
- `status` ("success" | "error") - Execution status
- `result` (AgentResult if success) - Agent result from the subagent run
- `error` (str if error) - Error description if status is "error"

#### Error Handling

If one subagent fails:
- All subagents run to completion (no cancellation of siblings)
- Results include both successes and errors
- The parent agent sees full details and decides how to proceed

#### Depth Limits

The **subagents MCP server** tracks recursion depth. If `depth > max_subagent_depth`, the subagent call returns an error instead of spawning.

#### Circular Reference Detection

The **subagents MCP server** tracks agent IDs in the current chain. If the same agent ID appears twice, the subagent call returns an error.

#### Sandbox Sharing

Sandbox containers are shared based on git scope matching (see Sandbox Management section). The **subagents MCP server** resolves this — subagents with the same `mcps.sandbox.git` value share a sandbox.

### Sandbox MCP

Per-agent sandbox containers provide isolated file operations. Each agent that needs file access gets its own sandbox.

#### Tool List

The sandbox MCP exposes these tools (representative list, defined during implementation):

```python
[
    "read_file",
    "write_file",
    "edit_file",
    "bash",
    "grep",
    "find",
    "ls",
    "list_dir",
    "batch_write_files",
    "delete_file",
    "search_files",
    "get_file_info",
    "submit_design_for_review",  # Auto-commits
    "push_changes"       # Runs outside sandbox via ToolProvider
]
```

#### Agent Configuration

Agents declare which sandbox tools they need in YAML:

```yaml
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, submit_design_for_review, push_changes]
    git: current_project
```

The runtime filters the full sandbox tool list to only the tools in the agent's `mcps.sandbox.tools`.

#### Tool Schema: submit_design_for_review

```json
{
  "name": "submit_design_for_review",
  "description": "Create or update design documents. Path implies type (e.g., /docs/technical_design.md). Auto-commits after write.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "File path, e.g. /docs/technical_design.md or /docs/functional_design.md"
      },
      "content": {
        "type": "string",
        "description": "Markdown content for the design document"
      }
    },
    "required": ["path", "content"]
  }
}
```

**Returns:** `{"path": "...", "committed": true, "commit_sha": "..."}`

**Behavior:** Writes design file to repo, validates mermaid diagrams, auto-commits. Only available for architect and business_analyst roles. The path itself implies the design type (e.g. `/docs/functional_design.md` = functional design).

#### Git Scopes

Each agent can have one git scope:

- `current_project` - The user's project being worked on (cloned from Gitea)
- `other_projects` - Other projects for reference (read-only, all accessible projects cloned)
- `update_core` - Druppie's core repository (cloned from GitHub for self-modification)

If no `mcps.sandbox` section, the agent has no sandbox and no file tools.

#### Read-Only Enforcement

For `git: other_projects`, the `tools` list only includes read tools:

```yaml
mcps:
  sandbox:
    tools: [read_file]  # No write_file, edit_file, bash, push_changes
    git: other_projects
```

This is mechanical enforcement. The LLM cannot call write tools because they are not in its tool list.

### Core-Tools MCP

The Druppie core-tools MCP server runs **in-process** inside the Druppie backend, not as a separate container. It connects directly to the database using existing ORM models and repositories.

#### Tools

```python
[
    "hitl_ask_question",
    "hitl_ask_multiple_choice",
    "make_plan",
    "set_intent",
    "invoke_skill",
    "create_message"
]
```

#### Data Access

The core-tools MCP server:
- Imports `druppie/db/models/` and `druppie/repositories/`
- Uses the same SQLAlchemy session management
- Shares existing `druppie/domain/` models for input/output
- For `invoke_skill`, uses existing `druppie/skills/` loading infrastructure

#### Tool Expansion

The `invoke_skill` tool returns:

```json
{
    "content": "Skill instructions in markdown...",
    "allowed_tools": {
        "sandbox": ["read_file", "list_dir"]
    }
}
```

The runtime detects `allowed_tools` and dynamically expands the agent's available tool set.

#### Tool Schemas

**hitl_ask_question**

```json
{
  "name": "hitl_ask_question",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string", "description": "The question to ask the user"},
      "context": {"type": "string", "description": "Optional context for why this question is being asked"}
    },
    "required": ["question"]
  }
}
```

**Returns:** `{"_pending": true, "pending_token": "..."}`

**Behavior:** Pauses agent run, sends question to user. Resumes when user answers.

---

**hitl_ask_multiple_choice**

```json
{
  "name": "hitl_ask_multiple_choice",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "options": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of options for the user to choose from"
      },
      "allow_multiple": {"type": "boolean", "default": false}
    },
    "required": ["question", "options"]
  }
}
```

**Returns:** Same as `hitl_ask_question` but user picks from options.

---

**make_plan**

```json
{
  "name": "make_plan",
  "parameters": {
    "type": "object",
    "properties": {
      "steps": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "agent": {"type": "string", "description": "Agent name from YAML (e.g., 'developer', 'builder_1')"},
            "prompt": {"type": "string", "description": "The prompt for that agent"}
          },
          "required": ["agent", "prompt"]
        },
        "description": "Ordered list of steps. Each plan should end with planner for re-evaluation."
      },
      "rationale": {"type": "string", "description": "Why this plan was chosen"}
    },
    "required": ["steps"]
  }
}
```

**Returns:** `{"plan_summary": "...", "steps_created": N, "stale_steps_cancelled": M}`

`stale_steps_cancelled`: When a new plan is created, any previously pending agent runs from the last plan are cancelled. This count tracks how many were cancelled.

**Side effects:** Cancels stale pending runs, creates new pending AgentRun records.

---

**set_intent**

```json
{
  "name": "set_intent",
  "parameters": {
    "type": "object",
    "properties": {
      "intent": {
        "type": "string",
        "enum": ["create_project", "update_project", "general_chat"],
        "description": "The classified user intent"
      },
      "project_name": {
        "type": "string",
        "description": "Name for the new project (kebab-case). Required for create_project."
      },
      "project_id": {
        "type": "string",
        "description": "UUID of existing project. Required for update_project."
      }
    },
    "required": ["intent"]
  }
}
```

**Returns:** `{"intent": "...", "project_id": "...", "created": true}`

**Behavior:** See "Session Initialization & Project Selection" section for full details.

---

**invoke_skill**

```json
{
  "name": "invoke_skill",
  "parameters": {
    "type": "object",
    "properties": {
      "skill_name": {"type": "string", "description": "Name of the skill to invoke"},
      "context": {"type": "string", "description": "Additional context for the skill"}
    },
    "required": ["skill_name"]
  }
}
```

**Returns:**
```json
{
  "skill_name": "string",
  "instructions": "The full skill text/instructions to inject into the agent's context",
  "allowed_tools": ["tool_name_1", "tool_name_2"],
  "message": "Skill loaded. Tools available: tool_name_1, tool_name_2"
}
```

**Behavior:**
- Returns skill instructions as a standard tool call result (text content). No system prompt modification.
- If `allowed_tools` is present, those tool names are added to the agent's available tool list for the rest of the run (until done()).
- Multiple invoke_skill calls accumulate tools (union of all allowed_tools).
- This is a regular core-tools MCP tool — no special runtime integration needed.
- If an agent needs tools for a skill, they should already be configured in the agent's YAML `mcps` section. `allowed_tools` is just a way to explicitly activate/enumerate which of the agent's already-configured tools are relevant for the skill.

**Note:** The skill's `instructions` text is injected into the agent's context (system prompt or next user message). The `allowed_tools` are added to the tool list for subsequent turns. Skills are NOT just tools — they are instructions + tools.

---

**create_message**

```json
{
  "name": "create_message",
  "parameters": {
    "type": "object",
    "properties": {
      "content": {"type": "string", "description": "Message content (supports markdown)"},
      "message_type": {"type": "string", "enum": ["info", "warning", "success", "error"], "default": "info"}
    },
    "required": ["content"]
  }
}
```

**Returns:** `{"message_id": "...", "created": true}`

**Behavior:** Creates a user-visible message in the session timeline.

### Docker MCP

The Docker MCP server provides infrastructure deployment and container management tools. It runs as a separate service and is shared across all agents that need Docker access.

#### Tools

```python
[
    "build",
    "run",
    "compose_up",
    "compose_down",
    "logs",
    "exec"
]
```

#### Usage

Agents declare Docker tools in YAML:

```yaml
mcps:
  docker: [build, run, compose_up]
```

The Docker MCP server:
- Connects to the Docker daemon (via Docker socket or API)
- Executes Docker commands on behalf of the agent
- Returns container logs, status, and execution results
- Is shared across all agents (no per-agent isolation for Docker operations)

#### Shared Access

Unlike the sandbox MCP (which provides per-agent isolation), the Docker MCP is a shared service. All agents with Docker tool access can:
- Build images from the same Dockerfiles
- Run containers on the same Docker host
- Access shared Docker networks and volumes

This is intentional for infrastructure deployment flows where multiple agents need to collaborate on the same Docker environment.

### Subagents MCP

The subagents MCP server runs **in-process** inside the Druppie backend. It provides the `subagents()` tool that allows agents to spawn child agent runtime instances.

#### Tools

```python
[
    "subagents"
]
```

#### Functionality

The subagents MCP server:
- Dynamically generates tool schema based on the agent's `subagents` list
- Validates that called agents are in the allowed list (two-layer validation: schema enum + server-side check)
- Enforces role restrictions (prevents `subagent`-only agents from being called at top level)
- Resolves sandboxes for each subagent based on git scope matching using the `sandbox_resolver` callback:
  - If child's `mcps.sandbox.git` matches parent's git scope → share parent's MCP connection (no resolver call)
  - If different git scope → call `sandbox_resolver(child_git_scope)` to get a new MCP connection
  - If child has no `mcps.sandbox` → no sandbox needed
- Spawns new agent runtime instances for each subagent (via `asyncio.gather()` for parallel execution)
- Tracks recursion depth (enforces `max_subagent_depth`)
- Detects circular references (prevents same agent ID from appearing twice in chain)
- Collects and returns results from all subagents

#### In-Process Execution

Like core-tools, the subagents MCP server runs in-process:
- It has direct access to the agent runtime library
- It can spawn new `AgentLoop` instances directly
- It shares the same LLM callable and event callbacks as the parent
- It does not require network communication (unlike sandbox or Docker MCP servers)

## Sandbox Management

### Sandbox Creation (Sandbox MCP Server Responsibility)

The **sandbox MCP server** creates sandboxes based on agent YAML `mcps.sandbox.git`. The caller (backend) manages a warm pool of pre-started containers. When the ToolProvider routes a tool call to the sandbox MCP, the sandbox MCP resolves or creates the appropriate sandbox.

#### Sharing Logic

| Parent Git | Subagent Git | Result |
|---|---|---|
| none (no sandbox) | current_project | New sandbox for subagent |
| current_project | current_project | Share parent's sandbox |
| current_project | update_core | New sandbox (different git) |
| none | none | No sandbox |
| update_core | update_core | Share parent's sandbox |
| any | other_projects | New sandbox (read-only) |

Same git scope means share sandbox. Different git scope means new sandbox.

#### Example Flow

```
planner (no sandbox)
  └→ subagents(developer)
      developer (git: current_project → ToolProvider creates sandbox, clones project X)
        └→ subagents(coding_planner)
            coding_planner (git: current_project → ToolProvider shares developer's sandbox)
              └→ subagents([builder, builder])
                  both builders (git: current_project → share same sandbox)
```

### Sandbox Resolution

The `sandbox_resolver` callback is the mechanism for creating and managing sandbox MCP connections. It's provided by the caller and used in two places: primary agent startup and subagent spawning.

#### Callback Signature

```python
async def sandbox_resolver(git_scope: str) -> MCPConnection:
    """Resolve a git scope to an MCP connection for a sandbox container."""
    # Caller implementation:
    # - Check if connection already exists for this git_scope (warm pool)
    # - If not, create new container, clone the git repository
    # - Return MCPConnection object
    pass
```

**Note:** `sandbox_resolver` is a closure created by the caller that captures session context. The runtime only sees: `async def sandbox_resolver(git_scope: str) -> MCPConnection`. Internally the closure has access to `session.project_id`, Gitea client, etc.

Example of how the caller creates it:

```python
async def make_sandbox_resolver(session: Session, gitea: GiteaClient):
    async def sandbox_resolver(git_scope: str) -> MCPConnection:
        if git_scope == "current_project":
            project = project_repo.get(session.project_id)
            return await start_sandbox(repo_url=project.repo_url, ...)
        elif git_scope == "other_projects":
            return await start_sandbox(...)
        elif git_scope == "update_core":
            return await start_sandbox(repo_url=DRUPPIE_CORE_REPO, ...)
    return sandbox_resolver
```

#### Usage in Primary Agent Startup

Before calling `run()` for the primary agent, the caller resolves the sandbox connection:

```python
# Caller-side (Druppie backend)
sandbox_conn = await sandbox_resolver("current_project")
tool_provider = MCPToolProvider({
    "sandbox": sandbox_conn,           # Per-session sandbox
    "core-tools": CoreToolsMCP(db),    # In-process
    "subagents": SubagentsMCP(...),    # In-process
    "docker": docker_conn,             # Shared infrastructure
})

result = await runtime.run(
    agent=agent,
    agent_loader=agent_loader,
    tool_provider=tool_provider,
    prompt=prompt,
    llm=llm,
    sandbox_resolver=sandbox_resolver,  # Pass the resolver
    ...
)
```

The `sandbox_resolver` is passed to `run()` so the subagents MCP server can use it when spawning child agents.

#### Usage in Subagent Spawning

The **subagents MCP server** receives `sandbox_resolver` via closure (passed through from `run()`). When spawning a subagent, it:

1. Checks the child agent's `mcps.sandbox.git` value
2. Compares it to the parent agent's git scope:
   - **Same git scope**: Passes the **SAME** MCPConnection to the child runtime — no resolver call needed
   - **Different git scope**: Calls `sandbox_resolver(child_git_scope)` → gets a **NEW** MCPConnection → passes to child runtime
   - **No sandbox**: If child has no `mcps.sandbox`, no sandbox connection is passed

#### Sharing vs. New Sandbox

| Parent Git | Subagent Git | Sandbox Resolution |
|---|---|---|
| current_project | current_project | Share parent's MCP connection (no resolver call) |
| current_project | update_core | Call resolver → new MCP connection for update_core |
| none | current_project | Call resolver → new MCP connection |
| update_core | update_core | Share parent's MCP connection |
| any | other_projects | Call resolver → new MCP connection (read-only) |

This ensures:
- Sandboxes with the same git scope share a single container (efficient)
- Different git scopes get different containers (isolated)
- The resolver is called only when a new container is needed

#### MCPConnection Type

```python
@dataclass  
class MCPConnection:
    """Connection to an MCP server (in-process or out-of-process)."""
    server_name: str
    endpoint: str | None  # URL for out-of-process servers (e.g., "http://localhost:9001")
    tools: list[dict]     # Available tools in OpenAI function calling format
    
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool on this MCP server. Returns result dict."""
        ...
```

### Sandbox Resolution — Complete Flow

```python
# 1. Caller creates sandbox_resolver (closure over session context)
async def make_sandbox_resolver(session: Session, gitea: GiteaClient):
    async def sandbox_resolver(git_scope: str) -> MCPConnection:
        if git_scope == "current_project":
            project = project_repo.get(session.project_id)
            return await start_sandbox(repo_url=project.repo_url, ...)
        elif git_scope == "other_projects":
            return await start_sandbox(...)
        elif git_scope == "update_core":
            return await start_sandbox(repo_url=DRUPPIE_CORE_REPO, ...)
    return sandbox_resolver

# 2. Before running an agent, resolve sandbox and build ToolProvider
sandbox_resolver = await make_sandbox_resolver(session, gitea)

# For agents with sandbox:
if agent_def.mcps and "sandbox" in agent_def.mcps:
    sandbox_conn = await sandbox_resolver(agent_def.mcps.sandbox.git)
else:
    sandbox_conn = None

# 3. Build ToolProvider with all MCP connections
tool_provider = MCPToolProvider({
    "sandbox": sandbox_conn,                          # Out-of-process (container)
    "core-tools": CoreToolsMCP(db),                   # In-process
    "subagents": SubagentsMCP(agent_loader, sandbox_resolver),  # In-process
    "docker": MCPClient("http://docker:9002"),        # Out-of-process
})

# 4. Run the agent
result = await runtime.run(
    agent=agent_def,
    agent_loader=agent_loader,
    tool_provider=tool_provider,
    prompt=prompt,
    llm=resolve_llm(agent_def.llm_profile),
    sandbox_resolver=sandbox_resolver,  # Passed for nested subagent sandbox resolution
    event_callbacks=[lambda e: db.save_event(agent_run_id, e)],
)

# When a subagent is spawned, the SubagentsMCP uses sandbox_resolver
# to get a sandbox for the child (sharing if same git scope)
```

#### Subagents MCP Implementation

The subagents MCP server uses `sandbox_resolver` like this:

```python
# In subagents MCP server
async def spawn_subagent(self, agent_def, parent_git_scope, parent_sandbox_conn):
    child_git_scope = agent_def.mcps.sandbox.git if agent_def.mcps.sandbox else None

    if child_git_scope is None:
        # No sandbox needed
        child_sandbox_conn = None
    elif child_git_scope == parent_git_scope:
        # Share parent's sandbox
        child_sandbox_conn = parent_sandbox_conn
    else:
        # Different git scope → need new sandbox
        child_sandbox_conn = await self.sandbox_resolver(child_git_scope)

    # Create scoped ToolProvider for child
    child_tool_provider = self.create_tool_provider(agent_def, child_sandbox_conn)

    # Spawn child runtime
    result = await AgentLoop().run(
        agent=agent_def,
        agent_loader=self.agent_loader,
        tool_provider=child_tool_provider,
        prompt=prompt,
        llm=self.llm,
        sandbox_resolver=self.sandbox_resolver,  # Pass through for nested subagents
        event_callbacks=[...],
        config=self.config,
    )
```

### Git Scopes

#### current_project

- Clones the user's project from Gitea
- Full read/write access
- Changes committed via `push_changes` tool (or agent commits manually)
- Next agent's sandbox pulls latest from Gitea

#### other_projects

- Clones all projects the session user can access from Gitea
- Read-only access
- Agent gets a project listing tool to know what's available
- No push access
- Useful for reference and exploration

#### update_core

- Clones Druppie's core repository from GitHub
- Used for self-modification flows
- Changes pushed via `push_changes` tool to GitHub
- Requires GitHub App authentication

### Warm Pool

The caller maintains a configurable warm pool of pre-started sandbox containers.

#### Configuration

```python
LoopConfig(
    sandbox_pool_size: int = 3,          # Number of warm containers
    sandbox_pool_recycle_s: int = 3600   # Recycle after 1 hour
)
```

#### Behavior

- Pool is pre-started when the backend initializes
- When an agent needs a sandbox, ToolProvider pulls from the pool
- If pool is empty, fall back to creating a new container
- Idle containers are recycled after `sandbox_pool_recycle_s` seconds
- Warm containers do NOT git fetch/pull until actually used
  - This prevents stale state accumulation
  - Git sync happens when the agent starts using the container

#### Implementation

```python
class SandboxWarmPool:
    """Pre-warmed sandbox containers for fast startup."""

    def __init__(self, pool_size: int = 3, recycle_timeout_s: int = 300):
        self.pool_size = pool_size
        self.recycle_timeout_s = recycle_timeout_s
        self._pools: dict[str, list] = {}  # git_scope → [containers]

    async def get_container(self, git_scope: str) -> Container:
        """Get a warm container, or create one if pool empty."""
        if git_scope in self._pools and self._pools[git_scope]:
            return self._pools[git_scope].pop(0)
        return await self._create_container(git_scope)

    async def release_container(self, container: Container):
        """Container was used by agent. Stop and discard (pool creates fresh ones)."""
        await container.stop()

    async def _create_container(self, git_scope: str) -> Container:
        """Create and start a fresh container for the given git scope."""
        ...
```

### Push/PR Tool

The `push_changes` tool is exposed on the sandbox MCP, but the actual push/PR operation runs **outside** the sandbox container.

#### Flow

1. Agent calls `push_changes` tool (inside sandbox)
2. ToolProvider routes the call to the sandbox MCP
3. The sandbox MCP extracts changes from the sandbox via `git bundle`
4. The sandbox MCP pushes to Gitea/GitHub directly (has credentials)
5. The sandbox MCP creates PR via API

This keeps git credentials out of the sandbox while allowing agents to trigger pushes.

### Sandbox Lifecycle

**Start**: The sandbox_resolver callback creates or reuses a sandbox container when the agent first calls a sandbox tool. The container clones the repo from git.

**Stop on done()**: When an agent calls done(), the sandbox container is stopped and destroyed. The next agent always starts fresh — a git pull from the latest state. The warm pool ensures fresh containers are always ready.

**Stop on pause**: When an agent pauses (HITL question, approval gate), the sandbox container is stopped. On resume, a new container is created from the latest git state. Any uncommitted changes are lost.

**Stop on error/cancel**: The sandbox container is stopped and destroyed immediately.

**Soft constraint (prompt-based)**: Coding agents that use sandbox tools should be instructed in their system prompt to commit their changes before calling done() or any tool that causes a pause (hitl_ask_question, approval gates). This is a soft constraint enforced via the agent's system prompt, not mechanically by the runtime. Example prompt addition:

"In sandbox sessions, ALWAYS commit and push your changes to git before calling done() or any tool that waits for user input (hitl_ask_question, approval gates). Uncommitted changes are lost when the sandbox stops on completion or pause."

## The Agent Loop

### run() Method Signature

```python
async def run(
    self,
    agent: AgentDefinition,
    agent_loader: Callable[[str], AgentDefinition],
    tool_provider: ToolProvider,
    prompt: str | None = None,           # For new runs
    initial_messages: list[dict] | None = None,  # For resumed runs — loaded from agent_state_events, filtered to LLM roles. No reconstruction needed — entries ARE messages with metadata.
    llm: Callable,  # litellm.acompletion compatible
    sandbox_resolver: Callable[[str], Awaitable[MCPConnection]],  # Callback for sandbox resolution
    event_callbacks: list[Callable[[AgentEvent], None]] = [],
    config: LoopConfig = LoopConfig(),
    cancellation_token: CancellationToken | None = None,
) -> AgentResult
```

- `agent` - The agent definition to run
- `agent_loader` - Function to load subagent definitions by name
- `tool_provider` - ToolProvider instance for routing tool calls to MCP servers (created by caller)
- `prompt` - Initial user prompt (for new runs, gets wrapped as the first user message)
- `initial_messages` - Loaded from agent_state_events for resumed runs, filtered to LLM roles. Entries ARE messages with metadata — no complex reconstruction needed.
- `llm` - Pre-configured litellm callable
- `sandbox_resolver` - Async callback that resolves a git scope to an MCP connection for a sandbox
- `event_callbacks` - Callbacks for real-time event streaming
- `config` - Loop configuration
- `cancellation_token` - Optional token for cancellation

Either `prompt` or `initial_messages` must be provided. `prompt` for new runs (gets wrapped as the first user message). `initial_messages` for resumed runs (loaded from agent_state_events, filtered to LLM roles — entries ARE messages with metadata).

### Main Loop Behavior

The loop executes these steps each turn:

1. **Build tool list** - Query `tool_provider.list_tools()` to get ALL tools, then filter by agent's `mcps` to get allowed tools. If a previous tool result contained `allowed_tools` (skill expansion), add those tools to the filtered list. Then add `done` (always added for every agent). Then add `subagents` only if the agent YAML has a `subagents` field. This happens BEFORE EACH LLM CALL (not once at start).
2. **Call LLM** - Send conversation history + available tools
3. **Process response**
   - If tool_calls: execute tools via ToolProvider
   - If text-only: inject error, continue (enforcement)
4. **Check for pause** - If any tool returned `_pending`, return AgentResult(status="paused")
5. **Check for done** - If `done()` called, validate and return result
6. **Check limits** - Max turns? Context overflow? Handle accordingly
7. **Repeat** until done, pause, or error

Tool filtering happens BEFORE EACH LLM CALL (not once at start):
- The runtime calls `tool_provider.list_tools()` to get all available tools
- Then filters by `agent_definition.mcps` to get the agent's allowed tools
- If a previous tool result contained `allowed_tools` (skill expansion), those tools are added to the filtered list
- `done` is always added (every agent gets it)
- `subagents` is only added if the agent YAML has a `subagents` field
- The filtered tool list is passed to the LLM for that call only
- Next call repeats the process (re-query, re-filter, re-expand)

### done() Enforcement

The loop mechanically enforces that `done()` is called before the agent exits.

#### Enforcement Logic

```
If LLM response has no tool calls:
  - Inject error: "You must call done() to signal completion."
  - Increment enforcement retry counter
  - Continue to next turn
  - Emit enforcement_retry event

If max_retries reached:
  - Auto-generate done result: "Agent did not call done(). Summary: [last response]"
  - Return AgentResult with this done_result
```

The agent cannot exit without calling `done()`. The loop forces it.

### Pause/Resume

The loop supports pause/resume for long-running operations (HITL questions, approvals, sandbox tasks).

#### Pause Detection

Any MCP tool can trigger a pause by returning `_pending: true`:

```json
{"_pending": true, "_resume_id": "hitl_abc123", "message": "Question sent to user"}
```

#### Pause Behavior

When `_pending` is detected:
1. Events are already saved via callbacks to DB (all events so far are persisted)
2. Return `AgentResult(status="paused")` with all events
3. Caller marks agent_run status as "paused", frees resources

**Note:** No state serialization. The caller reconstructs the conversation history from saved events on resume.

#### Resume Behavior

The runtime does NOT provide a separate `resume()` method. Resume is handled by the caller:

1. Caller queries all events for the agent_run from DB
2. Caller reconstructs LLM message history from events (see "Resume Flow" in "Caller Integration" section)
3. Caller calls `run()` with `initial_messages` containing the reconstructed history
4. The loop continues from where it paused

#### Multi-Tool Pause

If the LLM calls multiple tools and one returns `_pending`:
- Execute all tools in parallel
- Collect ALL results (both completed and pending)
- If ANY tool returned `_pending`, the entire turn is paused
- All events (including completed tool results) are saved to DB
- On resume, the caller reconstructs the full message history including all tool results, then the loop re-executes only pending tools

### LLM Retry

The runtime handles LLM retries internally.

#### Retry Configuration

```python
LoopConfig(
    max_retries: int = 3,
    retry_base_delay: float = 1.0,  # Exponential backoff: base * 2^attempt
    respect_retry_after: bool = True
)
```

#### Retry Logic

```
On ANY LLM error: retry up to 3 times with exponential backoff
  - All errors are retried (rate limits, timeouts, server errors, auth errors, bad requests)
  - Backoff: 1s, 2s, 4s (with jitter)
  - If retry_count < max_retries:
    - Delay = retry_base_delay * 2^retry_count
    - If respect_retry_after and error has Retry-After header, use that
    - Wait for delay
    - Retry the LLM call
    - Emit llm_retry event
  - Else (all 3 retries failed):
    - Agent run fails with status="error", error message from last attempt
    - The caller handles the error (stops session)
```

### Context Overflow

Before each LLM call, estimate total tokens from messages. If estimated tokens exceed max_context_tokens:

1. Inject system message: "You have reached the context limit. Call done() NOW with a summary."
2. Force one more LLM call with ONLY the done tool available
3. If LLM calls done() → normal completion
4. If LLM doesn't call done() → auto-generate done result with "Context limit reached"

Context overflow is visible in the event history — the runtime injects a system message before forcing done(). No special field needed on AgentResult.

When context overflow forces an auto-generated done(), completion preconditions are NOT enforced (emergency exit). The auto-generated summary includes 'Context limit reached — agent did not complete all work.'

### Cancellation

The runtime supports cancellation via `CancellationToken`.

#### Cancellation Flow

```
Caller creates token, passes to run():
  token = CancellationToken()
  result = await loop.run(..., cancellation_token=token)

User clicks "stop":
  token.cancel()

Runtime checks token between turns:
  if cancellation_token and cancellation_token.is_cancelled:
    raise AgentCancelledError("Agent execution was cancelled")

On AgentCancelledError:
  - When a session is cancelled, the CancellationToken is triggered
  - The runtime propagates cancellation to ALL active subagents immediately
  - Each subagent runtime receives the same CancellationToken
  - Subagents stop mid-execution — results are discarded
  - No cleanup of partial work — that's the caller's responsibility
  - The runtime returns AgentResult(status="cancelled") to the parent
  - No partial state saved
```

The runtime checks the CancellationToken before each LLM call. If cancelled, it returns immediately with AgentResult(status='cancelled').

## Events

### Event Types

All events are stored internally in `AgentResult.events` and emitted via callbacks for real-time streaming.

| Event Type | Data Fields | Description |
|------------|-------------|-------------|
| `turn_start` | `turn_number` | Beginning of an LLM turn |
| `turn_end` | `turn_number`, `tokens_used` | End of an LLM turn |
| `tool_call` | `tool_name`, `arguments`, `call_id` | Tool invocation |
| `tool_result` | `tool_name`, `result`, `call_id`, `_pending` | Tool execution result |
| `subagent_start` | `agent`, `task`, `depth`, `parent_agent_id` | Subagent spawn |
| `subagent_end` | `agent`, `result`, `depth`, `parent_agent_id` | Subagent completion |
| `done` | `summary`, `variables` | Agent called `done()` |
| `enforcement_retry` | `reason` | Loop forced another turn |
| `llm_retry` | `attempt`, `error`, `delay` | LLM call was retried |
| `pending` | `resume_id`, `pause_reason` | Agent paused for external event |
| `error` | `message`, `traceback` | Error occurred |

**Note on `_pending` field in tool_result events:**
- `true` - Tool triggered a pause (awaiting approval or HITL response)
- `false` - Tool completed successfully
- `absent/None` - Tool is not pauseable, always completes inline

### Event Storage

**Storage Contract:**

The agent runtime is storage-agnostic. It does NOT touch any database.

- Events are stored in memory as a list during execution
- Events are returned in `AgentResult.events` after completion
- `event_callbacks` fire in real-time for streaming and persistence
- The CALLER handles persistence (Druppie backend saves to its DB, external apps save wherever they want)

**Two ways to access events:**
1. **Real-time** - Via `event_callbacks` as events occur
2. **After completion** - Via `AgentResult.events` list

This makes the runtime reusable by any application without being tied to a specific storage backend.

**Event usage by callers:**
- Debugging and logging
- Timeline visualization
- Audit trails
- Analysis of agent behavior
- Database persistence (caller's responsibility)

### Crash Recovery Contract

The runtime does NOT provide built-in crash recovery. All state is in-memory. The contract is:

- **Events**: Caller persists via `event_callbacks` in real-time. If the caller crashes, already-persisted events are safe. Only the event being processed at crash time is lost.
- **Pause state**: When an agent pauses, all events so far are already persisted. On resume, the caller reconstructs message history from saved events. If caller crashes after a pause, the agent can still resume because events are already in DB.
- **Mid-turn state**: If the runtime crashes mid-turn, in-progress tool results and partial subagent results are lost. Caller reconstructs from persisted events.
- **Subagent results**: Each subagent's events are persisted independently via callbacks. If the parent crashes after some subagents complete, their events are already in the caller's storage.

This is intentional: the runtime stays simple and storage-agnostic. Crash recovery is the caller's responsibility.

### Druppie Persistence Strategy

Druppie backend persists events in real-time so end users see results appearing as they happen:

1. **Event callbacks write directly to DB**: Each event callback fires → Druppie writes to `agent_state_events` table via the existing repository layer. The event appears in the session timeline immediately.

2. **Tool call events**: `assistant` role entries (with `tool_calls` field) and `tool` role entries are written directly to the `agent_state_events` table. Users see tool execution in real-time.

3. **Subagent events**: `subagent_start` creates a new agent run record. All subsequent events from the subagent are stored under that run. `subagent_end` marks it complete. Users see subagent progress appearing live.

4. **Done events**: `done` event updates the agent run status and stores the summary in the session.

5. **Pause/resume**: When an agent pauses, events are already persisted. On resume, the backend queries all events for the agent_run, reconstructs the message history, and calls `run()` with `initial_messages`. No serialized state is stored.

6. **WebSocket notifications**: After each DB write, the backend pushes a notification via WebSocket so the frontend updates in real-time without polling.

This means end users see events appearing one by one as the agent works — tool calls, subagent starts, results — all live in the UI.

## Session Initialization & Project Selection

### The Router Agent

The router agent is the first agent in every session. Its purpose is to analyze user intent and set up the session context.

**Tools:**
- `set_intent` - Classifies user intent and creates/selects projects
- `done` - Signals completion
- `hitl_ask_question` - Asks user clarifying questions if needed

**Reference:** Full definition in `druppie/agents/definitions/router.yaml`. The system prompt should not be changed during migration — just reference the existing one.

### The set_intent Tool

The `set_intent` tool is provided by the core-tools MCP server.

**Parameters:**
```json
{
  "name": "set_intent",
  "parameters": {
    "type": "object",
    "properties": {
      "intent": {
        "type": "string",
        "enum": ["create_project", "update_project", "general_chat"],
        "description": "The classified user intent"
      },
      "project_name": {
        "type": "string",
        "description": "Name for the new project (kebab-case). Required for create_project."
      },
      "project_id": {
        "type": "string",
        "description": "UUID of existing project. Required for update_project."
      }
    },
    "required": ["intent"]
  }
}
```

**Behavior by intent:**
- `create_project`: Creates Project DB record, creates Gitea user + repo, pushes project template, links project to session
- `update_project`: Links existing project (by project_id) to session
- `general_chat`: Just sets intent, no project

**After set_intent:** Updates the pending planner's `planned_prompt` with intent context.

**Error handling:** Project name conflicts, invalid project_id, Gitea failures.

### Project Creation Flow (create_project)

1. Router classifies intent as `create_project`
2. Calls `set_intent(intent="create_project", project_name="todo-app")`
3. set_intent on core-tools MCP:
   a. Creates Project DB record (name, owner_id)
   b. Ensures Gitea user exists (`gitea.ensure_user_exists`)
   c. Creates Gitea repo: `{project_name}-{project_id[:8]}`
   d. Pushes project template from `druppie/templates/project/`
   e. Updates Project record with `repo_name`, `repo_url`, `repo_owner`
   f. Links session to project: `session.project_id = project.id`
4. Updates pending planner prompt with project context

### Project Selection Flow (update_project)

1. Router sees user wants to update existing project
2. Calls `set_intent(intent="update_project", project_id="uuid")`
3. Links session to existing project

### Reference

Current implementation in `druppie/agents/builtin_tools.py:361-580` and `druppie/core/gitea.py`.

## Caller Integration — Druppie Core Loop

### Two Agent Chaining Patterns

Druppie uses **two patterns** for chaining agents, each serving a different need:

| Pattern | Mechanism | When Used | Execution |
|---------|-----------|-----------|-----------|
| **DB-driven** | `make_plan` tool creates pending agent_run DB records | Planner re-evaluation loop | Async — loop picks up later |
| **Inline** | `subagents()` tool spawns child runtime instances | Coding tasks, parallel work | Sync — parent waits for results |

The planner uses `make_plan` to schedule agents asynchronously (it re-evaluates after each agent). Coding agents use `subagents` to spawn builders inline (parent waits for completion). Subagents are for parallel work and information queries within a parent agent's execution. make_plan creates primary agents who do most of the session's work, with the planner re-evaluating after each one.

### The Core Loop: execute_pending_runs()

The caller (Druppie backend) runs this loop. It is NOT part of the runtime — the runtime is just the agent execution engine.

```python
async def execute_pending_runs(session_id: UUID):
    while True:
        # 1. Check if user paused/cancelled
        session = session_repo.get(session_id)
        if session.status in (PAUSED, CANCELLED):
            return

        # 2. Get next pending agent run (ordered by sequence_number)
        next_run = execution_repo.get_next_pending(session_id)
        if not next_run:
            session.status = COMPLETED
            return

        # 3. Load agent definition
        agent_def = agent_loader(next_run.agent_id)

        # 4. Build the prompt — includes accumulated history
        prompt = build_agent_prompt(session_id, next_run.planned_prompt)
        # build_agent_prompt() collects all completed agent_run summaries from DB
        # and prepends them: "PREVIOUS AGENT SUMMARY:\nAgent BA: ...\nAgent architect: ...\n\n---\n\n"

        # 5. Resolve sandbox for this agent
        tool_provider = build_tool_provider(agent_def, session, sandbox_resolver)

        # 6. Resolve LLM from agent's profile
        llm = resolve_llm(agent_def.llm_profile)

        # 7. Run the agent
        result = await runtime.run(
            agent=agent_def,
            agent_loader=agent_loader,
            tool_provider=tool_provider,
            prompt=prompt,
            llm=llm,
            sandbox_resolver=sandbox_resolver,
            event_callbacks=[lambda e: db.save_event(next_run.id, e)],
            cancellation_token=session.cancellation_token,
        )

        # 8a. Handle paused (HITL, approval gate)
        if result.status == "paused":
            execution_repo.update_status(next_run.id, status="paused")
            session.status = "paused"
            return  # Caller will resume later by reconstructing from events

        # 8b. Handle error
        if result.status == "error":
            execution_repo.fail_run(next_run.id, error=result.error)
            session.status = "error"
            session.error_message = result.error
            return  # Stop session

        # 9. Agent completed — save summary and variables
        execution_repo.complete_run(
            next_run.id,
            summary=result.done_result.summary,
            variables=result.done_result.variables,
        )

        # 10. Handle next_agent direct routing
        if result.done_result.variables.get("next_agent"):
            caller = result.done_result.variables["next_agent"]
            # Create new pending run BEFORE the existing planner run
            execution_repo.insert_before_next_planner(session_id, caller)

        # Loop continues — picks up next pending run
```

### Resume Flow

```python
async def resume_agent_run(session_id: UUID, agent_run_id: UUID, user_response: str):
    # 1. Load the agent_run
    agent_run = execution_repo.get_by_id(agent_run_id)

    # 2. Load conversation history from saved events
    events = execution_repo.get_agent_state_events(agent_run_id)
    messages = filter_llm_messages(events, user_response)
    # filter_llm_messages converts agent_state_events to LLM message format:
    # - filter to LLM roles (system/user/assistant/tool)
    # - map directly to LLM message format (entries ARE messages with metadata)
    # - inject user_response as final tool result if answering pending tool

    # 3. Resolve fresh sandbox (previous one was stopped on pause)
    tool_provider = build_tool_provider(agent_run)  # sandbox_resolver creates new container

    # 4. Resume the run
    result = await runtime.run(
        agent=agent_loader(agent_run.agent_id),
        agent_loader=agent_loader,
        tool_provider=tool_provider,
        prompt=None,  # Not needed — messages already reconstructed
        initial_messages=messages,  # Reconstructed history
        llm=resolve_llm(agent_run.agent_id),
        sandbox_resolver=make_sandbox_resolver(session, gitea),
        event_callbacks=[lambda e: db.save_event(agent_run.id, e)],
    )

    # 4. Handle result (same as execute_pending_runs)
    ...
```

### Summary Accumulation — Caller Builds Prompt

The runtime's done() is minimal — it returns `summary` and `variables`. The caller handles accumulation:

1. Before each `run()` call, `build_agent_prompt()` queries all completed agent_runs for this session
2. Collects their summaries: "Agent business_analyst: Created functional design. DESIGN_APPROVED."
3. Prepends them to the agent's planned_prompt: "PREVIOUS AGENT SUMMARY:\n{accumulated}\n\n---\n\n{planned_prompt}"
4. The agent receives the full context in its prompt
5. **All summaries are always included in full — no truncation, no limit on count**
6. **If the total context (accumulated summaries + prompt) exceeds the agent's context window, the runtime's context overflow mechanism kicks in and forces done()**
7. **This is self-regulating — the runtime handles overflow, the caller doesn't need to truncate**

This means done() doesn't need to know about other agents — it just returns its own summary. The caller handles cross-agent context.

### How make_plan Works (DB-Driven Pattern)

`make_plan` is a Druppie-specific tool on the **core-tools MCP** (in-process, has DB access).

When the planner calls:
```python
make_plan(steps=[
    {"agent": "business_analyst", "prompt": "Gather requirements for a todo app..."},
    {"agent": "planner", "prompt": "Evaluate BA output and decide next step"}
])
```

The core-tools MCP:
1. Cancels any stale pending runs from previous plans (they become 'stale')
2. Creates **pending AgentRun records** in the DB — one per step
3. Each record: `agent_id`, `planned_prompt`, `status=pending`, `sequence_number` (incremented)
4. Returns plan summary to the planner

The new plan's steps replace the cancelled stale pending runs.

The planner then calls `done()`. The execute_pending_runs loop picks up the newly created pending runs.

**Every plan is 2 steps**: [working_agent, planner]. The planner always includes itself to re-evaluate after the working agent completes. Exception: summarizer runs alone (terminates the session).

### How subagents Works (Inline Pattern)

When a coding agent calls:
```python
subagents([{"agent": "builder", "prompt": "Build the API..."}])
```

The subagents MCP:
1. Spawns a new runtime instance for the builder
2. Waits for it to complete (asyncio.gather for parallel)
3. Returns results to the parent agent immediately

**Subagent events ARE saved to the database.** They are NOT invisible. The subagent run:
- Gets its own agent_run DB record with `parent_agent_run_id` pointing to the parent
- Also sets `source_tool_call_id` pointing to the specific tool_call that spawned this subagent
- Emits events via the same event callback → saved to DB in real-time
- Appears in the session timeline API as a nested entry under the parent's tool_call
- Has its own summary, status, and events — same as any primary agent run

The difference from make_plan is execution model, not visibility:
- **make_plan**: Creates pending DB records, execute_pending_runs loop picks them up asynchronously
- **subagents**: Spawns inline (parent waits), but still creates DB records and emits events

In the session API response, subagents appear as nested entries:
```json
{
  "timeline": [
    {
      "type": "agent_run",
      "agent": "developer",
      "status": "running",
      "events": [
        {"type": "tool_call", "tool": "subagents", "arguments": {...}},
        {
          "type": "subagent_run",
          "agent": "coding_planner",
          "status": "completed",
          "summary": "...",
          "events": [
            {"type": "tool_call", "tool": "subagents", ...},
            {
              "type": "subagent_run",
              "agent": "builder",
              "status": "completed",
              "summary": "...",
              "events": [...]
            }
          ]
        }
      ]
    }
  ]
}
```

### Direct Routing — Bypassing the Planner

Agents can route directly to the next agent using `done(next_agent="developer")`:

1. The runtime's done() includes `next_agent` in `variables`
2. After the run completes, the caller reads `done_result.variables["next_agent"]`
3. If present, the caller creates a new pending agent_run with sequence_number BEFORE the existing planner
4. **Sequence numbers are integers, incremented normally. When inserting before the planner, the caller shifts the planner's sequence_number up.**
5. **Example:** architect at seq=4, planner at seq=5. When architect routes to developer, developer gets seq=5, planner gets seq=6.
6. The loop executes the routed agent first, then the planner re-evaluates

**Renumbering**: When inserting an agent before an existing sequence N, increment all sequences >= N by 1. Example: inserting at position 5 in [1,2,3,4,5,6] gives [1,2,3,4,5,6,7]. Gaps are allowed after cancellations.

This allows agents like the architect to route directly to `developer` instead of going back through the planner.

### Full Session Flow Example

```
User: "Build me a todo app"
  ↓
POST /api/chat → Orchestrator.process_message()
  ↓
Create: Session, Message(user), AgentRun(router, seq=0), AgentRun(planner, seq=1)
  ↓
execute_pending_runs() starts
  ↓
━━━ Run router (seq=0) ━━━
  Router: set_intent(intent="create_project", project_name="todo-app")
  Router: done(summary="Intent set for todo-app")
  ↓
━━━ Run planner (seq=1) ━━━
  Prompt: "INTENT: create_project\n\n..."
  Planner: make_plan(steps=[
    {agent: "business_analyst", prompt: "Gather requirements..."},
    {agent: "planner", prompt: "Evaluate BA output"}
  ])
  Planner: done(summary="Planned BA")
  ↓
━━━ Run business_analyst (seq=2) ━━━
  Prompt: "PREVIOUS AGENT SUMMARY:\nAgent router: Intent set...\n\n---\n\nGather requirements..."
  BA: Asks questions, writes functional design
  BA: done(summary="DESIGN_APPROVED\nAgent BA: Created functional design")
  ↓
━━━ Run planner (seq=3) ━━━
  Prompt: "PREVIOUS AGENT SUMMARY:\n...all summaries...\n\n---\n\nEvaluate BA output"
  Planner reads DESIGN_APPROVED → make_plan(steps=[
    {agent: "architect", prompt: "Create technical design..."},
    {agent: "planner", prompt: "Evaluate architect output"}
  ])
  ↓
━━━ Run architect (seq=4) ━━━
  Architect: submit_design_for_review(path="docs/technical-design.md", ...) → auto-committed
  Architect: done(summary="DESIGN_APPROVED", next_agent="developer")
    → Caller creates developer run (seq=5) BEFORE planner (seq=6)
  ↓
━━━ Run developer (seq=5) ━━━ — direct routed by architect
  Developer: subagents({agent: "coding_planner", prompt: "Implement..."})
    → Subagents MCP spawns coding_planner (inline, same sandbox)
    → Coding_planner: subagents([builder, builder]) — parallel, same sandbox
    → Builders complete, coding_planner calls done()
  Developer: done(summary="Implementation complete")
  ↓
━━━ Run planner (seq=6) ━━━
  Planner evaluates developer output
  → make_plan(test_executor, planner)
  ↓
...continues until...
  ↓
Planner: make_plan(steps=[{agent: "summarizer", prompt: "Summarize session"}])
  ↓
Summarizer: create_message(content="Your todo app is ready!")
Summarizer: done(summary="Session complete")
  ↓
No more pending runs → session.status = COMPLETED
```

### Pause/Resume in the Core Loop

When an agent pauses (HITL question, approval gate, submit_design_for_review approval):
1. `run()` returns with `result.status == "paused"`
2. Events are already saved to DB via event callbacks (all events so far are persisted)
3. Caller marks agent_run status as "paused", session status → PAUSED, `execute_pending_runs()` returns

When user answers/resumes:
1. Caller queries all events for this agent_run from DB
2. Caller reconstructs LLM message history from events (see "Resume Flow" section above)
3. Caller calls `run()` with `initial_messages` containing the reconstructed history
4. Agent continues from where it paused
5. Loop continues

### Session State Persistence

```python
# Per session
session = {
    "id": UUID,
    "project_id": str,
    "status": "running" | "completed" | "paused",
}

# Per agent run (created by make_plan, direct routing, or initial request)
agent_run = {
    "id": UUID,
    "session_id": UUID,
    "agent": str,            # Agent name from YAML definition (e.g., "developer", "planner", "router")
    "parent_agent_run_id": UUID | None,       # Set by subagents MCP for inline subagents
    "source_tool_call_id": str | None,         # The tool_call ID from the parent's tool_calls JSONB array in agent_state_events. NOT a FK to a separate table — it's the call_id string from an assistant event's tool_calls array.
    "status": "pending" | "running" | "completed" | "paused" | "cancelled",
    "sequence_number": int | None,             # Only for primary agents (make_plan ordering). NULL for subagents.
    "planned_prompt": str,
    "summary": str | None,
    "variables": dict | None,
    # Note: No serialized state field. Resume state is reconstructed from events.
}

# Per event (real-time via callbacks)
# All events are stored as agent_state_events entries with LLM roles
agent_state_event = {
    "id": UUID,
    "session_id": UUID,
    "agent_run_id": UUID | None,
    "role": "system" | "user" | "assistant" | "tool" | "approval" | "question",
    "content": str | None,
    "tool_calls": list | None,           # [{id, name, arguments}] for assistant entries
    "tool_call_id": str | None,          # For tool entries
    "sequence_number": int,
    "timestamp": datetime,
    "metadata": {
        "model": str | None,
        "prompt_tokens": int | None,
        "completion_tokens": int | None,
        "total_tokens": int | None,
        "duration_ms": int | None,
    } | None
}
```

### Subagent Timeline Assembly

The session API returns a nested timeline built from DB records.

**Bi-directional links:**
- `agent_runs.source_tool_call_id` → which tool call (in agent_state_events) spawned this run
- `agent_runs.parent_agent_run_id` → which agent is the parent

**Building the tree:**
1. Start with all primary agent runs (where parent_agent_run_id is NULL), ordered by sequence_number
2. For each agent run, query its agent_state_events entries, ordered by sequence_number
3. For each assistant entry with tool_calls, check if any agent runs have source_tool_call_id matching one of the tool_call IDs — those are the subagent runs, ordered by started_at
4. Recurse: each subagent run may have its own assistant entries with tool_calls and further nested subagent runs

**Parallel subagents:** When coding_planner calls `subagents([builder1, builder2])`, there's one assistant entry with tool_calls in agent_state_events and two child agent runs both pointing to that same source_tool_call_id. They're ordered by started_at.

**Depth:** The nesting can go arbitrarily deep (limited by max_subagent_depth). Developer → coding_planner → builder is 3 levels deep. Each level has its own agent_run with parent_agent_run_id pointing up.

## What Gets Removed

These components are removed and replaced by the new agent runtime:

| Component | Replaced by |
|-----------|-------------|
| `druppie/agents/loop.py` | `agent_runtime.loop.AgentLoop` |
| Legacy `pi_agent/` (TypeScript codebase) | `agent_runtime.loop.AgentLoop` |
| `@mariozechner/pi-coding-agent` SDK | Nothing (loop is pure Python) |
| Legacy pi_agent journal.ts (HTTP ingest) | Event callbacks → direct DB writes |
| Legacy pi_agent sandbox-ops.ts (raw HTTP) | Sandbox MCP server |
| Legacy pi_agent done.ts | Built into the loop |
| Legacy pi_agent subagents.ts | Subagents MCP server (in-process) |
| `execute_coding_task` | Removed, replaced by recursive subagents |
| `druppie/mcp-servers/coding/` (global coding MCP) | Per-agent sandbox MCP |
| `druppie/agents/builtin_tools.py` (most tools) | MCP tools on core-tools server |
| Skills as builtin meta-tool | Skills as MCP tool with dynamic tool expansion |

## Migration Notes

### Agent YAML Changes

- Add `role` field: `primary`, `subagent`, or `both`
- Update `mcps` structure: new nested format with `tools` and `git` for sandbox
- `coding` MCP references → `sandbox` MCP
- Move all builtin tools (except done) to `core-tools` MCP
- Add `completion_preconditions` for done() validation
- Add `approval_overrides` for tool-level approval rules

### Tool Routing Changes

- All tools now go through ToolProvider (MCP connections)
- No direct tool execution in the runtime
- ToolProvider routes tool calls to the correct MCP server
- ToolProvider handles pre-validation hooks and approval gates (routing logic)
- Role enforcement for subagents happens in the subagents MCP server

### Calling the New Runtime

```python
# Old way (loop.py)
result = await agent_loop.run(
    agent=ba_definition,
    prompt="Gather requirements",
    tool_provider=tool_provider,
    llm=llm_client
)

# New way (agent_runtime)
tool_provider = ToolProvider()
tool_provider.add_mcp("sandbox", MCPClient("http://sandbox-xyz:9001"))
tool_provider.add_mcp("core-tools", MCPClient(in_process=True))  # In-process server
tool_provider.add_mcp("subagents", MCPClient(in_process=True))  # In-process server
tool_provider.add_mcp("docker", MCPClient("http://docker:9002"))

result = await agent_loop.run(
    agent=ba_definition,
    agent_loader=lambda name: load_definition(name),
    tool_provider=tool_provider,  # Caller creates ToolProvider
    prompt="Gather requirements",
    llm=llm_callable,  # Pre-configured litellm callable
    sandbox_resolver=sandbox_resolver,  # Callback for sandbox resolution
    event_callbacks=[on_event],
    config=LoopConfig(max_subagent_depth=10),
    cancellation_token=token
)
```

### Key Differences

1. **Agent loader** - Must provide function to load subagent definitions
2. **ToolProvider** - Caller creates ToolProvider with MCP connections, not a dict
3. **LLM callable** - Pass pre-configured litellm callable, not internal ChatLiteLLM
4. **sandbox_resolver** - Callback for resolving git scopes to sandbox MCP connections
5. **Event callbacks** - Add callbacks for real-time streaming
6. **Configuration** - Pass LoopConfig with sandbox pool, depth limits, etc.
7. **Cancellation** - Optional token for clean shutdown

---

For research context, alternatives considered, and detailed rationale for each decision, see `docs/research-agent-runtime.md`.
