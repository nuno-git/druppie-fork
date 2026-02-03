# Agent System

This document describes how the Druppie agent system works, including agent definitions, the runtime loop, builtin tools, and tool routing.

## Overview

Druppie agents are LLM-powered autonomous actors that execute tasks through tool calls. Each agent is defined by a YAML file in `druppie/agents/definitions/` and executed by the runtime in `druppie/agents/runtime.py`. Agents interact with the outside world exclusively through tools -- they cannot produce direct file output or side effects. All tool calls are routed through a `ToolExecutor` which handles builtin tools locally, HITL (human-in-the-loop) tools by pausing for user input, and MCP tools by dispatching HTTP requests to MCP server containers.

## Agent Definitions (YAML Format)

Each agent is defined in a YAML file at `druppie/agents/definitions/<agent_id>.yaml`. The YAML is loaded into an `AgentDefinition` Pydantic model (`druppie/domain/agent_definition.py`).

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique identifier (e.g., `router`, `developer`) |
| `name` | string | yes | Human-readable name |
| `description` | string | no | Brief description of agent's purpose |
| `system_prompt` | string | yes | The system prompt sent to the LLM |
| `mcps` | list or dict | no | MCP servers/tools this agent can use |
| `extra_builtin_tools` | list[str] | no | Additional builtin tools beyond the defaults |
| `approval_overrides` | dict | no | Per-tool approval rule overrides |
| `model` | string | no | LLM model identifier |
| `temperature` | float | no | LLM temperature (default: 0.1) |
| `max_tokens` | int | no | Max tokens for LLM response (default: 4096) |
| `max_iterations` | int | no | Max tool-calling loop iterations (default: 10) |

### MCP Configuration Formats

The `mcps` field supports two formats:

**List format** -- all tools from each server are available:
```yaml
mcps:
  - coding
  - docker
```

**Dict format** -- only specific tools from each server are available:
```yaml
mcps:
  coding:
    - read_file
    - write_file
    - list_dir
  docker:
    - build
    - run
```

### Approval Overrides

Agents can override the global approval rules from `mcp_config.yaml`. The key format is `"server:tool_name"`:

```yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

This layered system means:
1. Agent-specific overrides are checked first.
2. Global defaults from `mcp_config.yaml` are the fallback.

## Common Instructions (`_common.md`)

The file `druppie/agents/definitions/_common.md` contains shared instructions that are injected into every agent's system prompt that includes the `[COMMON_INSTRUCTIONS]` placeholder.

### How Injection Works

1. The runtime calls `_load_common_prompt()` to read `_common.md` from the definitions directory.
2. During `_build_system_prompt()`, if the agent's `system_prompt` contains the literal string `[COMMON_INSTRUCTIONS]`, it is replaced with the contents of `_common.md`.
3. If the placeholder is absent, the common instructions are not injected.

### What `_common.md` Contains

The shared instructions cover three critical topics:

- **Summary Relay**: How the accumulated summary pipeline works. Each agent writes a one-line summary starting with `Agent <role>:`, and the system auto-prepends previous agent summaries when relaying to the next agent.
- **done Tool Format**: The mandatory format for calling `done()` with a detailed, specific summary. Vague summaries like "Task completed" are explicitly forbidden.
- **Workspace State**: Informs agents that the workspace is shared across all agents in a session. If a prior agent created a feature branch, the current agent is already on that branch.

## Runtime (`runtime.py`)

The `Agent` class in `runtime.py` is the core execution engine.

### Loading Definitions

1. `Agent.__init__(agent_id)` calls `_load_definition(agent_id)` which reads `definitions/{agent_id}.yaml`.
2. Definitions are cached in `Agent._cache` (class-level dict) to avoid re-reading YAML on every instantiation.
3. `Agent._load_common_prompt()` reads `_common.md` once and caches it.
4. `Agent.list_agents()` scans the definitions directory for all `.yaml`/`.yml` files.

### The LLM Loop (`_run_loop`)

The core execution logic runs in `_run_loop()`:

```
1. Build tool list:
   - Get MCP tools from mcp_config.yaml (filtered to agent's allowed set)
   - Convert to OpenAI function-calling format
   - Add builtin tools (DEFAULT_BUILTIN_TOOLS + extra_builtin_tools)

2. For each iteration (up to max_iterations):
   a. Record LLM call in database
   b. Call LLM with messages + tools
   c. Record response in database
   d. If no tool calls:
      - Router/planner: parse output as JSON, return
      - Others: remind agent to use tools, retry
   e. For each tool call in response:
      - Classify tool: builtin, HITL, or MCP
      - Create ToolCall record in database
      - Execute via ToolExecutor
      - Handle status:
        - WAITING_ANSWER: pause, return agent state
        - WAITING_APPROVAL: pause, return agent state
        - COMPLETED (done tool): return success result
        - Other: append result to messages, continue loop

3. If max_iterations exceeded, raise AgentMaxIterationsError
```

### Resume Capabilities

The runtime supports three resume mechanisms:

- **`resume()`**: Resumes after a HITL question is answered. Adds the user's answer as a tool response message and continues the loop.
- **`resume_from_approval()`**: Resumes after an MCP tool is approved. Adds the tool execution result and continues.
- **`continue_run()`**: Reconstructs full message history from the database (all stored LLM calls and tool results) and continues from where it left off.

### System Prompt Construction (`_build_system_prompt`)

1. Start with the agent's `system_prompt` from YAML.
2. Replace `[COMMON_INSTRUCTIONS]` with `_common.md` contents (if placeholder present).
3. Generate dynamic tool descriptions from `mcp_config.yaml` and inject them (replaces `[TOOL_DESCRIPTIONS_PLACEHOLDER]` or the `AVAILABLE TOOLS:` / `TOOLS:` sections).
4. For router/planner agents: optionally add XML format instructions if the LLM does not support native tool calling.
5. For all other agents: append shared tool usage instructions documenting the builtin tools (`hitl_ask_question`, `hitl_ask_multiple_choice_question`, `done`) and critical usage rules.

## Builtin Tools (`builtin_tools.py`)

Builtin tools are executed directly in the agent runtime process -- no HTTP call to an MCP server is needed.

### Default Builtin Tools (every agent gets these)

| Tool | Description |
|---|---|
| `done` | Signal task completion with a detailed summary. The summary is the sole mechanism for passing information to the next agent in the pipeline. Auto-collects and prepends previous agent summaries. |
| `hitl_ask_question` | Ask the user a free-form text question. Pauses the agent until the user responds. |
| `hitl_ask_multiple_choice_question` | Ask the user a multiple-choice question with predefined options. |

### Extra Builtin Tools (agent-specific)

| Tool | Used By | Description |
|---|---|---|
| `set_intent` | router | Declares the user's intent (`create_project`, `update_project`, `general_chat`). Creates projects and Gitea repos for `create_project`. |
| `make_plan` | planner | Creates an execution plan as a sequence of pending `AgentRun` records in the database. |
| `create_message` | summarizer | Posts a user-visible message in the chat timeline. |

### How Agents Declare Builtin Tools

Every agent automatically receives `DEFAULT_BUILTIN_TOOLS`:
```python
DEFAULT_BUILTIN_TOOLS = ["done", "hitl_ask_question", "hitl_ask_multiple_choice_question"]
```

Agents that need additional builtin tools declare them via `extra_builtin_tools` in their YAML:
```yaml
extra_builtin_tools:
  - make_plan
```

The runtime combines them: `builtin_tool_names = DEFAULT_BUILTIN_TOOLS + definition.extra_builtin_tools`.

## Tool Routing

When the LLM emits a tool call, the runtime classifies it and routes accordingly:

| Classification | `mcp_server` field | Execution path |
|---|---|---|
| Builtin tool | `"builtin"` | Executed via `builtin_tools.execute_builtin()` or HITL handler |
| HITL tool | `"builtin"` | Creates a `Question` record and pauses the agent |
| MCP tool | Server name (e.g., `"coding"`) | Dispatched via `MCPHttp` to the MCP server container |

### Tool Name Resolution

The LLM may emit tool names in different formats. The runtime resolves them:

1. **Builtin tools**: Recognized by name (e.g., `done`, `hitl_ask_question`). Server is set to `"builtin"`.
2. **Colon-separated**: `coding:read_file` is split into server=`coding`, tool=`read_file`.
3. **Underscore-separated**: `coding_read_file` is split at the first underscore: server=`coding`, tool=`read_file`.

## Agent Definitions Index

| Agent ID | Name | Purpose |
|---|---|---|
| `router` | Router Agent | Classifies user intent into `create_project`, `update_project`, or `general_chat` |
| `planner` | Planner Agent | Creates execution plans (sequences of agent steps) based on intent |
| `business_analyst` | Business Analyst Agent | Gathers functional requirements from the user, writes `functional_design.md` |
| `architect` | Architect Agent | Designs system architecture, writes `architecture.md` |
| `developer` | Developer Agent | Writes code, creates branches, commits, creates/merges PRs |
| `deployer` | Deployer Agent | Builds Docker images and deploys containers |
| `reviewer` | Reviewer Agent | Reviews code for quality, security, and best practices |
| `tester` | Tester Agent | Runs tests and validates implementations |
| `summarizer` | Summarizer Agent | Creates a user-friendly completion message in the chat timeline |

## File Reference

| File | Purpose |
|---|---|
| `druppie/agents/runtime.py` | Agent class and LLM loop execution |
| `druppie/agents/builtin_tools.py` | Builtin tool definitions and implementations |
| `druppie/agents/definitions/*.yaml` | Individual agent YAML definitions |
| `druppie/agents/definitions/_common.md` | Shared instructions injected via `[COMMON_INSTRUCTIONS]` |
| `druppie/domain/agent_definition.py` | `AgentDefinition` Pydantic model |
| `druppie/core/mcp_config.py` | MCP configuration loader (approval rules, injection rules) |
| `druppie/core/mcp_config.yaml` | MCP server and tool configuration |
| `druppie/execution/tool_executor.py` | Tool execution dispatcher |
| `druppie/execution/mcp_http.py` | HTTP client for MCP server communication |
