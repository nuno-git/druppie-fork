# Druppie Documentation

Druppie is a governance platform where AI agents execute tasks through MCP (Model Context Protocol) tools with approval workflows.

## Quick Links

| Document | Description |
|----------|-------------|
| [Architecture](./ARCHITECTURE.md) | System overview and how components interact |
| [Folder Structure](./FOLDER_STRUCTURE.md) | What each folder contains and why |
| [API Reference](./API.md) | All API endpoints |
| [Database](./DATABASE.md) | Schema and data model |

## What is Druppie?

Druppie lets you build applications by chatting with AI agents. But unlike typical AI assistants:

1. **Agents can only act through tools** - They can't just output code. They must call MCP tools to write files, build containers, etc.
2. **Actions require approval** - Dangerous operations (like running commands) need human approval first
3. **Everything is tracked** - Every LLM call, tool execution, and approval is logged

## Core Concepts

### Agents

AI agents are defined in YAML files. Each has a specific role:

| Agent | Role | MCP Tools | Built-in Tools |
|-------|------|-----------|----------------|
| Router | Classifies user intent | None | done |
| Planner | Creates execution plans | None | done |
| Architect | Designs system structure | coding | ask_question, done |
| Developer | Writes code | coding | ask_question, done |
| Deployer | Deploys apps | docker | ask_question, done |
| Tester | Runs tests | coding | ask_question, done |
| Reviewer | Reviews code | coding | ask_question, done |

### MCP Servers (External Microservices)

MCP servers are separate Docker containers that provide tools for file operations, containers, etc:

| Server | Port | Tools | What It Does |
|--------|------|-------|--------------|
| coding | 9001 | read_file, write_file, run_command, commit_and_push, run_tests | File, git, and test operations |
| docker | 9002 | build, run, stop, logs | Container operations |

### Built-in Tools (Part of Agent Runtime)

These tools are built into the agent runtime - no external server needed:

| Tool | Description |
|------|-------------|
| `hitl_ask_question` | Ask user a free-form text question. Pauses execution until answered. |
| `hitl_ask_multiple_choice_question` | Ask user to choose from options. Supports "Other" option for custom answers. Can allow multiple selections. |
| `done` | Signal that the agent has completed its task. Must be called when finished. |
| `execute_agent` | Call another agent to perform a sub-task. Allows agents to delegate work. |

### Sessions

A session is one conversation. It contains everything that happened:
- Messages (user and assistant)
- Agent runs (which agents executed)
- Raw LLM requests and responses
- Tool calls (both successful and failed)
- Approvals (what needed approval)
- HITL questions (what the agent asked the user)

### Workflows

A workflow is a multi-step plan. Example:
```
User: "Build me a todo app"
  └── Workflow: [architect → developer → deployer]
```

## Project Structure

```
cleaner-druppie/
├── druppie-backend/         # Python/FastAPI backend
├── druppie-frontend/        # React/Vite frontend
├── docs/                    # Documentation (you are here)
├── scripts/                 # Setup scripts
└── setup.sh                 # Main setup script
```

## Getting Started

```bash
# Full setup
./setup.sh all

# Access
# Frontend: http://localhost:5273
# Backend:  http://localhost:8100
```

## Test Users

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |
