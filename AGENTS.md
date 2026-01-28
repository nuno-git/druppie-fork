# Druppie Agents Documentation

## Overview

Druppie uses a multi-agent system where specialized AI agents collaborate to complete tasks. Each agent has a specific role, access to certain MCP tools, and defined approval requirements.

**Key Principle**: Agents can ONLY act through MCP tools. No direct code output is allowed.

---

## Table of Contents

1. [Agent Catalog](#agent-catalog)
2. [Agent Runtime](#agent-runtime)
3. [Tool Access & Approvals](#tool-access--approvals)
4. [HITL Integration](#hitl-integration)
5. [Execution Flow](#execution-flow)
6. [Configuration](#configuration)

---

## Agent Catalog

### Router

**Purpose**: Classifies user intent and routes to appropriate workflow.

**Location**: `druppie/agents/definitions/router.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 2048 |
| Max Iterations | 5 |

**MCP Tools**: None (JSON output only)

**Classification Actions**:
- `create_project` - Build/create new applications
- `update_project` - Modify existing work
- `deploy_project` - Deployment requests
- `ask_clarification` - Ambiguous requests needing clarification
- `general_chat` - Q&A conversations

**Output Format**: JSON with `action` and `details`

---

### Planner

**Purpose**: Creates execution plans with agent steps.

**Location**: `druppie/agents/definitions/planner.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 4096 |
| Max Iterations | 5 |

**MCP Tools**: None (JSON output only)

**Plan Types**:

| Type | Steps |
|------|-------|
| CREATE_PROJECT | architect → developer → deployer |
| UPDATE_PROJECT | developer → (optional) deployer |
| DEPLOY_PROJECT | deployer |
| STATIC WEB PAGES | architect → developer → deployer |
| SIMPLE FILE OPS | developer |

**Output Format**: JSON with `plan_name` and `steps` array

---

### Architect

**Purpose**: Designs system architecture and technical specifications.

**Location**: `druppie/agents/definitions/architect.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.2 |
| Max Tokens | 8192 |
| Max Iterations | 15 |

**MCP Tools**:
- `coding`: read_file, write_file, list_dir
- `hitl`: ask_question, ask_choice

**Approval Overrides**:
```yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

**Workflow**:
1. Analyze requirements
2. Present architecture via HITL question
3. Wait for user confirmation
4. Create `architecture.md` with write_file

**Output**: Only `architecture.md` (never implementation files)

---

### Developer

**Purpose**: Writes and modifies code in git workspaces.

**Location**: `druppie/agents/definitions/developer.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 16384 |
| Max Iterations | 25 |

**MCP Tools**:
- `coding`: read_file, write_file, batch_write_files, commit_and_push, list_dir, delete_file, run_command
- `hitl`: ask_question, ask_choice

**Approval Overrides**: None (uses global defaults)

**Workflow**:
1. Read architecture.md if available
2. Create files using batch_write_files
3. Commit and push with commit_and_push

**Code Patterns**:

For **Static Pages** (HTML/CSS/JS):
```dockerfile
FROM nginx:alpine
COPY . /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

For **Vite/React Apps** (multi-stage build required):
```dockerfile
# Build stage
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

### Deployer

**Purpose**: Handles Docker build and deployment.

**Location**: `druppie/agents/definitions/deployer.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 4096 |
| Max Iterations | 15 |

**MCP Tools**:
- `docker`: build, run, stop, logs, list_containers, inspect
- `coding`: read_file, write_file, list_dir
- `hitl`: ask_question, ask_choice

**Approval Overrides**: None (uses global defaults)

**Workflow**:
1. Check for existing containers
2. Verify Dockerfile exists
3. `docker:build` (requires developer approval)
4. `docker:run` (requires developer approval)
5. `docker:logs` to verify running
6. Report success with URL

**Resume Logic** (important for multi-approval):
- If `deployment_complete: True` in context → Skip all, output success
- If `last_approved_tool: docker:run` → Skip both, output success
- If `last_approved_tool: docker:build` → Continue with docker:run

---

### Reviewer

**Purpose**: Reviews code quality, security, and best practices.

**Location**: `druppie/agents/definitions/reviewer.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 4096 |
| Max Iterations | 25 |

**MCP Tools**:
- `coding`: read_file, list_dir, write_file

**Review Checklist**:
- **Code Quality**: Readability, error handling, DRY principle
- **Security**: Input validation, SQL injection, XSS, sensitive data
- **Best Practices**: Language conventions, design patterns, testing

**Output**: `REVIEW.md` with pass/fail status and recommendations

---

### Tester

**Purpose**: Runs tests and validates implementations.

**Location**: `druppie/agents/definitions/tester.yaml`

| Setting | Value |
|---------|-------|
| Model | glm-4 |
| Temperature | 0.1 |
| Max Tokens | 4096 |
| Max Iterations | 10 |

**MCP Tools**:
- `coding`: read_file, list_dir, run_tests

**Supported Frameworks** (auto-detected):
- Python: pytest, unittest
- Node.js: jest, mocha, vitest
- Go: go test
- Rust: cargo test
- Ruby: rspec, minitest
- Java: maven, gradle

**Output**: Test results summary with pass/fail counts

---

## Agent Runtime

### Loading Agents

```python
from druppie.agents.runtime import Agent

# Load agent by ID
agent = Agent("developer")

# List available agents
agents = Agent.list_agents()  # ["router", "planner", ...]
```

### Running Agents

```python
# Execute agent with prompt
result = await agent.run(
    prompt="Build a todo app",
    context={
        "workspace_id": "...",
        "project_id": "...",
        "user_id": "..."
    }
)

# Check result status
if result["status"] == "completed":
    print(result["response"])
elif result["status"] == "paused":
    # Agent is waiting for HITL answer or approval
    agent_state = result["agent_state"]
```

### Resuming Agents

```python
# Resume after HITL answer
result = await agent.resume(agent_state, answer="yes")

# Resume after MCP approval
result = await agent.resume_from_approval(agent_state, tool_result)
```

### Agent State

When an agent pauses, it saves state for resumption:

```python
{
    "agent_id": "developer",
    "messages": [...],           # Conversation history
    "prompt": "...",             # Original prompt
    "context": {...},            # Execution context
    "iteration": 3,              # Current iteration
    "tool_call_id": "...",       # Pending tool call
    "question": "...",           # For HITL pauses
    "tool_name": "...",          # For approval pauses
    "tool_args": {...},          # For approval pauses
    "workflow_id": "...",
    "workflow_step": 2
}
```

---

## Tool Access & Approvals

### Layered Approval System

**Layer 1: Global Defaults** (`mcp_config.yaml`)
```yaml
mcps:
  coding:
    tools:
      - name: write_file
        requires_approval: false  # Default
      - name: run_command
        requires_approval: true
        required_role: developer
  docker:
    tools:
      - name: build
        requires_approval: true
        required_role: developer
```

**Layer 2: Agent Overrides** (agent YAML)
```yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

### Resolution Order

1. Check agent's `approval_overrides["{server}:{tool}"]`
2. Fall back to `mcp_config.yaml` defaults
3. Default: `requires_approval: false`

### Approval Examples

| Agent | Tool | Override? | Result |
|-------|------|-----------|--------|
| architect | write_file | Yes | Needs architect approval |
| developer | write_file | No | No approval (default) |
| developer | docker:build | No | Needs developer approval (global) |
| deployer | docker:run | No | Needs developer approval (global) |

### Tool Categories

**No Approval Required**:
- `read_file`, `list_dir`, `get_git_status`
- `run_tests`, `commit_and_push`
- `docker:stop`, `docker:logs`, `docker:list_containers`
- All HITL tools

**Developer Approval Required**:
- `run_command` (shell execution)
- `docker:build`, `docker:run`, `docker:remove`, `docker:exec_command`

**Architect Approval Required**:
- `merge_to_main`
- `write_file` (when architect agent writes)

---

## HITL Integration

### Built-in HITL Tools

All agents have access to HITL tools for human interaction:

#### hitl_ask_question

Ask a free-form text question.

```python
# Agent calls:
hitl_ask_question(
    session_id="...",
    question="What database should I use?",
    context="Building a web app"
)
```

#### hitl_ask_multiple_choice_question

Ask a multiple-choice question.

```python
# Agent calls:
hitl_ask_multiple_choice_question(
    session_id="...",
    question="Which framework?",
    choices=["React", "Vue", "Angular"],
    allow_other=True
)
```

### HITL Flow

1. Agent calls HITL tool
2. Question saved to database
3. WebSocket event sent to frontend
4. Workflow pauses with `status: "paused"`
5. User answers in UI
6. Backend resumes agent with answer
7. Agent receives answer as tool result

### Question Storage

Questions are stored in `hitl_questions` table:
- `id` - Question UUID
- `session_id` - Parent session
- `agent_run_id` - Agent that asked
- `question` - Question text
- `question_type` - text, single_choice, multiple_choice
- `status` - pending, answered
- `answer` - User's answer
- `agent_state` - Saved state for resumption

---

## Execution Flow

### Complete Workflow Example

**User Request**: "Build me a todo app"

```
1. ROUTER
   ├─ Classifies: create_project
   └─ Returns: { action: "create_project", details: {...} }

2. PLANNER
   ├─ Creates plan: architect → developer → deployer
   └─ Returns: { steps: [...] }

3. ARCHITECT
   ├─ Designs architecture
   ├─ Calls hitl:ask_question ("Does this look good?")
   ├─ PAUSED: waiting for user
   ├─ User answers: "yes"
   ├─ Calls coding:write_file (architecture.md)
   ├─ PAUSED: waiting for architect approval
   ├─ User approves
   └─ Completes

4. DEVELOPER
   ├─ Reads architecture.md
   ├─ Calls coding:batch_write_files (all source files)
   ├─ Calls coding:commit_and_push
   └─ Completes

5. DEPLOYER
   ├─ Calls docker:build
   ├─ PAUSED: waiting for developer approval
   ├─ User approves
   ├─ Calls docker:run
   ├─ PAUSED: waiting for developer approval
   ├─ User approves
   ├─ Calls docker:logs (verify running)
   └─ Completes with app URL
```

### Tool Execution Loop

```
┌─────────────────────────────────────────┐
│            Agent.run(prompt)            │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│         Build messages + tools          │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│            Call LLM with tools          │
└─────────────────┬───────────────────────┘
                  │
         ┌────────┴────────┐
         ▼                 ▼
    Tool Calls?        No Tools
         │                 │
         ▼                 ▼
┌─────────────────┐  ┌─────────────────┐
│  Execute Tools  │  │    Complete     │
└────────┬────────┘  └─────────────────┘
         │
    ┌────┴────────────────┐
    ▼                     ▼
 Success?              Paused?
    │                     │
    ▼                     ▼
┌─────────────────┐  ┌─────────────────┐
│ Continue Loop   │  │  Return State   │
└─────────────────┘  └─────────────────┘
```

---

## Configuration

### Agent YAML Structure

```yaml
name: agent_name
description: What the agent does

system_prompt: |
  You are an AI agent...

  [TOOL_DESCRIPTIONS_PLACEHOLDER]

  Your instructions...

mcps:
  - coding      # MCP server access
  - docker
  - hitl

settings:
  model: glm-4
  temperature: 0.1
  max_tokens: 8192
  max_iterations: 15

# Optional: Override global approval rules
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

### Dynamic Tool Descriptions

The `[TOOL_DESCRIPTIONS_PLACEHOLDER]` marker is replaced at runtime with:

```
## Available Tools

### coding:read_file
Read a file from the workspace

### coding:write_file
Write content to a file

### docker:build
Build a Docker image
...
```

### Shared Tool Instructions

All agents (except router/planner) receive shared instructions:

```
## Tool Usage Guidelines

1. Always use tools to perform actions
2. Provide all required parameters
3. Handle errors gracefully
4. Check tool results before proceeding
...
```

### Execution Context

Agents receive context with:

```python
{
    "session_id": "...",
    "workspace_id": "...",
    "project_id": "...",
    "user_id": "...",
    "current_agent_run_id": "...",
    "clarifications": [...],    # Previous HITL answers
    "emit_event": callable,     # Send WebSocket events
}
```

---

## File Structure

```
druppie/agents/
├── definitions/
│   ├── router.yaml
│   ├── planner.yaml
│   ├── architect.yaml
│   ├── developer.yaml
│   ├── deployer.yaml
│   ├── reviewer.yaml
│   └── tester.yaml
├── runtime.py          # Agent class and execution
├── builtin_tools.py    # HITL and done tools
└── hitl.py            # HITL tool implementations

druppie/core/
├── mcp_config.yaml    # Global tool configuration
├── mcp_client.py      # MCP communication
├── execution_context.py
└── loop.py           # Workflow orchestration
```

---

## Agent Categories

| Category | Agents | Purpose |
|----------|--------|---------|
| System | router, planner | Intent classification and planning |
| Execution | architect, developer | Design and implementation |
| Quality | reviewer, tester | Code review and testing |
| Deployment | deployer | Build and deploy |

---

## Best Practices

### For Agent Development

1. **Clear System Prompts**: Be specific about what the agent should do
2. **Minimal Tool Access**: Only grant tools the agent needs
3. **Approval Overrides**: Use for sensitive operations
4. **Max Iterations**: Set reasonable limits to prevent loops
5. **Temperature**: Lower for deterministic tasks, higher for creative

### For Workflow Design

1. **Single Responsibility**: Each agent does one thing well
2. **Clear Handoffs**: Pass context between agents via workspace files
3. **Approval Gates**: Place at critical points (deploy, merge)
4. **HITL for Ambiguity**: Ask users when requirements are unclear

### For Error Handling

1. **Validation Errors**: Agent retries with corrected arguments
2. **Tool Failures**: Agent decides how to proceed
3. **Max Iterations**: Workflow fails gracefully
4. **State Preservation**: Always save state before pausing
