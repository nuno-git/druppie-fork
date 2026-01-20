# Druppie Governance Platform - Claude Code Instructions

## Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions, approval workflows, and project management integrated with Gitea.

## Architecture Philosophy

**Clean Code Principles:**
1. **Agents are the core abstraction** - All LLM interactions happen through defined agents
2. **Agents are defined in YAML** - System prompts, MCP tools, and behavior in `registry/agents/`
3. **Workflows orchestrate agents + MCPs** - Defined in `registry/workflows/`
4. **LLM Service is pure** - Only provides chat capability, no business logic
5. **Separation of concerns** - Parsing, execution, and LLM calls are separate

## Core Architecture

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│                    Main Workflow                         │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │   Router    │───▶│   Planner    │───▶│  Execute   │ │
│  │   Agent     │    │    Agent     │    │  Tasks     │ │
│  └─────────────┘    └──────────────┘    └────────────┘ │
│        │                   │                   │        │
│        ▼                   ▼                   ▼        │
│   MCP: ask_question   Select workflow    Run agents/   │
│   (if needed)         or agents          workflows     │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent Runtime                         │
│  - Loads agent definition from YAML                      │
│  - Executes agent with system prompt                     │
│  - Agent can call MCP tools                              │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    MCP Servers                           │
│  filesystem │ git │ gitea │ docker │ shell              │
└─────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Agents (`registry/agents/*.yaml`)

Agents are AI actors with:
- **System prompt**: Defines personality and capabilities
- **MCP tools**: List of tools the agent can use
- **Description**: What the agent does

```yaml
# Example: registry/agents/router_agent.yaml
id: router_agent
name: Router Agent
description: Analyzes user intent and routes to appropriate action
system_prompt: |
  You are an intent analysis system for Druppie.
  Analyze requests and classify as: create_project, update_project, general_chat
  ...
mcps:
  - interaction  # For asking clarifying questions
output_schema:
  type: object
  properties:
    action: { enum: [create_project, update_project, general_chat] }
    ...
```

### 2. Workflows (`registry/workflows/*.yaml`)

Workflows are sequences of:
- **Agent tasks**: Execute an agent with a specific task
- **MCP tool calls**: Direct tool invocations
- **Conditionals**: Branch based on step results

```yaml
# Example: registry/workflows/main_workflow.yaml
id: main_workflow
name: Main Request Processing
steps:
  analyze_intent:
    type: agent
    agent_id: router_agent
    on_success: plan_execution
    on_clarification_needed: ask_user

  plan_execution:
    type: agent
    agent_id: planner_agent
    on_success: execute_plan
```

### 3. MCP Servers (`registry/mcp/*.yaml`)

Tools available to agents:
- **filesystem**: Read/write files
- **git**: Version control operations
- **gitea**: Repository management
- **docker**: Build and run containers
- **shell**: Execute commands
- **interaction**: Ask user questions

### 4. LLM Service (`druppie/llm_service.py`)

**Pure LLM interaction - NO business logic:**
```python
class LLMService:
    def chat(self, messages: list[dict], call_name: str = None) -> str:
        """Send messages to LLM and return response."""
        # Only LLM communication, no parsing
```

### 5. Agent Runtime (`druppie/agents/runtime.py`)

Executes agents by:
1. Loading agent definition from registry
2. Building messages with system prompt
3. Calling LLM service
4. Parsing response according to output_schema
5. Executing any MCP tool calls the agent makes

### 6. Workflow Engine (`druppie/workflows/engine.py`)

Executes workflows by:
1. Loading workflow definition
2. Running steps in order
3. Handling success/failure transitions
4. Passing context between steps

## Directory Structure

```
backend/
├── app.py                    # Flask API routes
├── druppie/
│   ├── llm_service.py        # PURE LLM chat (no prompts, no parsing)
│   ├── agents/
│   │   └── runtime.py        # Executes agents from YAML definitions
│   ├── workflows/
│   │   └── engine.py         # Executes workflows from YAML definitions
│   ├── mcp/
│   │   ├── client.py         # MCP tool invocation
│   │   └── registry.py       # Loads MCP definitions
│   ├── plans.py              # Plan/Task management (uses AgentRuntime)
│   ├── project.py            # Project/Git operations
│   └── builder.py            # Docker build/run
├── registry/
│   ├── agents/
│   │   ├── router_agent.yaml      # Intent analysis
│   │   ├── planner_agent.yaml     # Execution planning
│   │   ├── code_generator.yaml    # Code generation
│   │   ├── developer.yaml         # General development
│   │   ├── tdd_agent.yaml         # Test-driven development
│   │   ├── implementer_agent.yaml # Code implementation
│   │   ├── reviewer_agent.yaml    # Code review
│   │   ├── devops_agent.yaml      # Build/deploy
│   │   └── git_agent.yaml         # Git operations
│   ├── workflows/
│   │   ├── main_workflow.yaml         # Main request processing
│   │   ├── development_workflow.yaml  # New project creation
│   │   └── update_workflow.yaml       # Existing project updates
│   └── mcp/
│       ├── filesystem.yaml
│       ├── git.yaml
│       ├── gitea.yaml
│       ├── docker.yaml
│       ├── shell.yaml
│       └── interaction.yaml
```

## Request Flow

1. **User sends message** → `POST /api/chat`

2. **Main workflow starts** → `main_workflow.yaml`

3. **Router Agent executes**:
   - Analyzes intent
   - Returns: `{ action, project_context, clarification_needed }`
   - If `clarification_needed`, uses `interaction.ask_question` MCP tool

4. **Planner Agent executes**:
   - Based on intent, selects workflow or creates agent tasks
   - Returns: `{ plan_type, workflow_id, tasks }`

5. **Execution**:
   - If workflow selected → WorkflowEngine runs it
   - If agent tasks → AgentRuntime executes them in parallel

6. **Results returned** to user

## Setup & Running

```bash
# Full setup (first time)
./setup.sh all

# Start all services
docker compose up -d

# Rebuild backend after changes
docker compose build druppie-backend && docker compose up -d druppie-backend

# View logs
docker compose logs -f druppie-backend
```

## Test Users (Keycloak)

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin (full access) |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |
| juniordev | Junior123! | developer (limited) |

## LLM Configuration

Configure in `.env`:
```bash
LLM_PROVIDER=zai
ZAI_API_KEY=your_api_key
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
```

## Adding New Agents

1. Create YAML file in `registry/agents/`:
```yaml
id: my_agent
name: My Agent
description: What this agent does
system_prompt: |
  You are a specialized agent for...
mcps:
  - filesystem
  - shell
output_schema:
  type: object
  properties:
    result: { type: string }
```

2. Reference in workflows or planner

## Adding New Workflows

1. Create YAML file in `registry/workflows/`:
```yaml
id: my_workflow
name: My Workflow
entry_point: step_one
steps:
  step_one:
    type: agent
    agent_id: my_agent
    task: "Perform the task"
    on_success: step_two
  step_two:
    type: mcp
    tool: git.commit
    params:
      message: "Done"
```

## E2E Testing with Playwright

Always use Playwright MCP tools for testing. Navigate to `http://localhost:5173`, login, and test chat functionality.

**IMPORTANT: Slow Server Warning**
- The server can be slow to respond. Pages may take up to 60 seconds to load.
- When waiting for page loads, use `browser_wait_for` with at least 15 seconds per wait.
- Don't assume the page is broken if it shows "Loading..." - just wait longer.
- LLM calls can take up to 3 minutes to complete - be patient!

## Key Design Decisions

1. **No hardcoded prompts in Python** - All prompts in YAML agents
2. **LLM service is stateless** - Just sends messages, returns responses
3. **Agents define their own output schema** - Runtime parses accordingly
4. **Workflows are declarative** - No Python code, just YAML
5. **MCP tools are the interface** - Agents interact with world through MCPs
