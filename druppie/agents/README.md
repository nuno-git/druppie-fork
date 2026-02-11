# Agents

This folder contains the agent system for Druppie. Agents are LLM-powered workers that execute tasks through tool calls.

## Overview

```
agents/
├── runtime.py          # Main Agent class and execution loop
├── builtin_tools.py    # Built-in tool handlers (done, hitl_*, make_plan, invoke_skill)
├── definitions/        # YAML agent definitions
│   ├── _common.md      # Shared instructions injected into all prompts
│   ├── router.yaml     # Routes tasks to appropriate agents
│   ├── planner.yaml    # Creates multi-step plans
│   ├── developer.yaml  # Code development agent
│   └── ...
└── README.md           # This file
```

## How It Works

### 1. Agent Definitions (YAML)

Each agent is defined in a YAML file in `definitions/`. Example:

```yaml
name: developer
description: Software development agent
system_prompt: |
  You are a developer agent...
mcps:
  - coding    # MCP servers this agent can access
  - docker
skills:
  - deploy    # Skills this agent can invoke
max_iterations: 15
max_tokens: 8192
extra_builtin_tools:
  - make_plan
```

### 2. Runtime Loop (`runtime.py`)

The `Agent` class handles the core execution:

```python
agent = Agent("developer", db=session)
result = await agent.run(prompt="Build a login page", session_id=uuid, agent_run_id=uuid)
```

**The loop:**
1. Build system prompt with tool instructions
2. Call LLM with available tools (OpenAI function calling format)
3. For each tool call in response:
   - Create tool call record in DB
   - Execute via `ToolExecutor`
   - Handle status (completed, waiting_approval, waiting_answer, failed)
4. If `done` tool called → return result
5. If waiting for user → pause and return state
6. If failed → add error to messages, let LLM retry
7. Continue until done or max iterations

### 3. Tool System

**Tool sources:**
- **Built-in tools**: `done`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`, `make_plan`, `invoke_skill`
- **MCP tools**: From MCP servers (coding, docker, etc.) defined in `mcp_config.yaml`

**Tool flow:**
```
LLM Response → Tool Call → ToolExecutor → MCP Server (or builtin handler) → Result → LLM
```

All tools are registered in `ToolRegistry` with Pydantic models for type-safe validation.

### 4. Skills System

Skills are predefined workflows that grant temporary access to additional tools.

```yaml
# Agent definition
skills:
  - deploy
  - analyze
```

When an agent calls `invoke_skill(skill_name="deploy")`:
1. Skill definition is loaded
2. Skill's `allowed_tools` are dynamically added to the agent's tools
3. Skill instructions are returned to guide the LLM
4. Agent can now use the skill's tools until task completion

### 5. HITL (Human-in-the-Loop)

When an agent needs user input:

1. Agent calls `hitl_ask_question` or `hitl_ask_multiple_choice_question`
2. `ToolExecutor` creates a Question record
3. Agent pauses, returns `{ "status": "paused", "reason": "waiting_answer" }`
4. User answers via API
5. Agent resumes with `agent.resume(state, answer, ...)`

### 6. Tool Approval

Some MCP tools require approval:

1. Agent calls tool marked `requires_approval: true`
2. Creates Approval record
3. Agent pauses with `{ "reason": "waiting_approval" }`
4. User approves/denies via API
5. If approved, agent resumes with `resume_from_approval()`

## Key Classes

| Class | Location | Purpose |
|-------|----------|---------|
| `Agent` | `runtime.py` | Main agent, handles loop and state |
| `ToolExecutor` | `execution/tool_executor.py` | Executes tools, handles HITL/approval |
| `ToolRegistry` | `core/tool_registry.py` | Unified tool definitions |
| `MCPHttp` | `execution/mcp_http.py` | HTTP client for MCP servers |

## Adding a New Agent

1. Create `definitions/my_agent.yaml`:
   ```yaml
   name: my_agent
   description: Does something useful
   system_prompt: |
     [COMMON_INSTRUCTIONS]
     You are an agent that...
   mcps:
     - coding
   max_iterations: 10
   ```

2. Use it:
   ```python
   agent = Agent("my_agent", db=session)
   result = await agent.run(prompt="Do the thing", session_id=sid, agent_run_id=rid)
   ```

## Design Principles

1. **Tool-only output**: Agents communicate ONLY through tool calls, never plain text
2. **Native tool calling**: Uses LiteLLM's native OpenAI function calling (no XML parsing)
3. **Unified registry**: All tools (builtin + MCP) go through `ToolRegistry`
4. **Type-safe**: Tool arguments validated with Pydantic models
5. **Pausable**: Agents can pause for HITL/approval and resume later
6. **Database tracking**: All LLM calls and tool calls recorded for debugging
