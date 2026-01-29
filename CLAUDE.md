# Druppie Governance Platform - Claude Code Instructions

## Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions, approval workflows, and project management integrated with Gitea.
workflow: always push and commit changes to git!

## Design Principles

### Database Rules
1. **NO JSON/JSONB columns** - Everything must be normalized into proper relational tables
2. **Config stays in files** - Agent definitions (`agents/*.yaml`), MCP configs (`mcp_config.yaml`), workflows stay in YAML files, not database
3. **Single source of truth** - Database schema is defined in SQLAlchemy models (`druppie/db/models/`)
4. **Agent isolation** - Messages are linked to `agent_run_id` so agents don't share history by default
5. **NO migrations** - We don't use database migrations. For schema changes, just update the SQLAlchemy models and reset the database with `./setup.sh clean && ./setup.sh all`

### Code Quality Rules
1. **NO legacy/fallback code** - We are refactoring to a new normalized database architecture. Do not add backwards compatibility, fallback logic, or "legacy" code paths. Keep the code clean and focused on the new architecture only.
2. **NO mock LLM in production paths** - Always use real LLM providers (zai, deepinfra). Mock is only for tests.
3. **Error on missing config** - If required configuration (API keys, etc.) is missing, throw an error immediately. Do not silently fall back to defaults.

## Repository Structure

```
cleaner-druppie/
├── druppie/                   # FastAPI backend
│   ├── agents/                # YAML agent definitions
│   │   └── definitions/       # Agent YAML files (router.yaml, developer.yaml, etc.)
│   ├── workflows/             # YAML workflow definitions
│   │   └── definitions/       # Workflow YAML files
│   ├── mcp-servers/           # MCP microservices (Docker containers)
│   │   ├── coding/            # File ops + git (port 9001)
│   │   ├── docker/            # Container ops (port 9002)
│   │   └── hitl/              # Human-in-the-loop (port 9003)
│   ├── core/                  # Main loop, execution context, MCP client
│   │   ├── loop.py            # LangGraph main execution flow
│   │   ├── mcp_client.py      # HTTP client for MCP servers
│   │   └── mcp_config.yaml    # MCP tool definitions & approval rules
│   ├── llm/                   # LLM providers (zai, mock)
│   ├── api/                   # FastAPI routes
│   ├── db/                    # SQLAlchemy models & CRUD
│   ├── docker-compose.yml     # Full stack compose
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                  # React + Vite frontend
│   ├── src/
│   │   ├── pages/             # Dashboard, Chat, Tasks, Projects, Plans
│   │   ├── services/          # API, Keycloak, WebSocket
│   │   └── components/
│   ├── tests/e2e/             # Playwright E2E tests
│   └── Dockerfile
│
├── scripts/                   # Setup scripts
│   ├── setup_keycloak.py      # Keycloak realm/user setup
│   ├── setup_gitea.py         # Gitea organization setup
│   └── run_tests.sh           # Test runner
│
├── iac/                       # Infrastructure as Code
│   ├── realm.yaml             # Keycloak realm config
│   └── users.yaml             # Test user definitions
│
├── setup.sh                   # Main setup script
└── CLAUDE.md                  # This file
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Druppie Backend (FastAPI)                       │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────────┐ │
│  │ Main Loop   │───▶│  MCP Client  │───▶│  HTTP + Bearer Token   │ │
│  │ (LangGraph) │    │(mcp_config)  │    │                        │ │
│  └─────────────┘    └──────────────┘    └────────────────────────┘ │
│         │                                                           │
│         ▼                                                           │
│  ┌─────────────┐   Built-in HITL tools (no separate server)        │
│  │ Agent       │   - hitl_ask_question                             │
│  │ Runtime     │   - hitl_ask_multiple_choice_question             │
│  └─────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
         ┌──────────────────┐    ┌──────────────────┐
         │  Coding MCP      │    │   Docker MCP     │
         │  (FastMCP)       │    │  (FastMCP)       │
         │  Port 9001       │    │  Port 9002       │
         │                  │    │                  │
         │  - Workspace     │    │  - build/run     │
         │  - File ops      │    │  - stop/logs     │
         │  - Git ops       │    │  - Docker socket │
         │  - Auto-commit   │    │                  │
         └──────────────────┘    └──────────────────┘
```

**Key Principle**: Agents can ONLY act through MCP tools. No direct code output.

## Key Components

### 1. Agents (`druppie/agents/definitions/*.yaml`)

```yaml
# Example: druppie/agents/definitions/developer.yaml
name: developer
description: Writes and modifies code
system_prompt: |
  You are a senior developer. You write clean, working code.
  You can ONLY act through MCP tools.
mcps:
  - coding      # Read/write files, git ops
  - docker      # Build, run containers
  - hitl        # Ask user questions
settings:
  model: glm-4
  temperature: 0.1
```

### 2. MCP Servers (Microservices)

MCP servers run as separate Docker containers. Configuration is in `druppie/core/mcp_config.yaml`.

| Server | Port | Tools | Description |
|--------|------|-------|-------------|
| coding | 9001 | read_file, write_file, batch_write_files, list_dir, run_command, run_tests, commit_and_push | File, git, and test operations in workspace |
| docker | 9002 | build, run, stop, logs, list_containers | Container operations |

**NOTE**: HITL (Human-in-the-Loop) is now built into the agent runtime (`druppie/agents/hitl.py`). No separate MCP server is needed. Built-in tools: `hitl_ask_question`, `hitl_ask_multiple_choice_question`.

### 3. MCP Configuration & Layered Approval System (per goal.md)

**Two layers of approval rules:**

1. **mcp_config.yaml** = Global defaults for ALL agents
2. **agent.yaml** = Agent-specific overrides

#### Layer 1: Global Defaults (`druppie/core/mcp_config.yaml`)

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    tools:
      - name: write_file
        requires_approval: false  # DEFAULT: no approval
      - name: run_command
        requires_approval: true
        required_role: developer  # Singular, not array

  docker:
    tools:
      - name: build
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
      - name: run
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
```

#### Layer 2: Agent Overrides (`druppie/agents/definitions/*.yaml`)

```yaml
# architect.yaml - OVERRIDES write_file to require architect approval
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect

# developer.yaml - NO overrides, uses global defaults
# write_file: no approval (default)
# docker:build/run: developer approval (global)
```

#### How It Works

```
Agent calls tool (e.g., coding:write_file)
    │
    ▼
Check agent's approval_overrides for this tool
    │
    ├─► Override exists? → Use override rules
    │
    └─► No override? → Use mcp_config.yaml defaults
```

| Agent | Tool | Override? | Result |
|-------|------|-----------|--------|
| architect | write_file | YES | Needs architect approval |
| developer | write_file | NO | No approval (default) |
| developer | docker:build | NO | Needs developer approval (global) |

### 4. LLM Service (`druppie/llm/`)

- `zai.py` - Z.AI GLM-4.7 provider with retry logic
- `mock.py` - Mock provider for testing
- `base.py` - Abstract interface

### 5. API (`druppie/api/`)

FastAPI endpoints:
- `POST /api/chat` - Main chat interface
- `GET /api/sessions` - List sessions
- `GET /api/approvals` - List pending approvals
- `POST /api/approvals/{id}/approve` - Approve action
- `GET /api/mcps` - List available MCP tools
- `WS /ws/session/{id}` - Real-time updates
- `POST /api/hitl/response` - Submit HITL answers

## Setup & Running

### Full Stack Setup (Recommended)

Uses:
- Frontend: http://localhost:5273
- Backend: http://localhost:8100
- Keycloak: http://localhost:8180
- Gitea: http://localhost:3100

```bash
# Full setup from project root
./setup.sh all

# Or individual steps:
./setup.sh infra      # Start DBs, Keycloak, Gitea
./setup.sh configure  # Configure Keycloak & Gitea
./setup.sh mcp        # Build & start MCP servers
./setup.sh app        # Build & start frontend/backend
```

### Other Commands

```bash
./setup.sh start      # Start all services
./setup.sh stop       # Stop all services
./setup.sh restart    # Restart all services
./setup.sh logs       # View logs (optionally specify service)
./setup.sh status     # Show service status
./setup.sh clean      # Remove all containers and volumes
./setup.sh build      # Build all services
```

## Test Users (Keycloak)

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin (full access) |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |
| juniordev | Junior123! | developer (limited) |

## LLM Configuration

Set in environment or `.env`:

```bash
LLM_PROVIDER=zai          # or 'mock' for testing
ZAI_API_KEY=your_api_key
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
```

## MCP Permission Model

Tools have approval requirements defined in `mcp_config.yaml`:

| Config | Description | Example |
|--------|-------------|---------|
| requires_approval: false | No approval needed | read_file |
| requires_approval: true + roles | Role required | run_command needs [developer] |
| danger_level: high | High-risk operation | run_command, merge_to_main |

When AI requests a tool that `requires_approval: true`:
1. Execution pauses
2. Approval record created in DB
3. Frontend shows approval request
4. User approves (must have required role)
5. Execution resumes

## Development Workflow

### Adding a New Agent

1. Create YAML in `druppie/agents/definitions/`:
```yaml
name: my_agent
description: What it does
system_prompt: |
  Your instructions...
mcps:
  - coding
  - hitl
settings:
  model: glm-4
  temperature: 0.1
```

2. The agent is automatically loaded by the runtime

### Adding a New MCP Tool

1. Add tool function in `druppie/mcp-servers/{server}/server.py`
2. Add tool config in `druppie/core/mcp_config.yaml`
3. Set approval requirements

### Modifying the Frontend

```bash
cd frontend
npm install
npm run dev  # Dev server on port 5173
```

## Key Design Decisions

1. **Agents can only act through MCPs** - No direct LLM output to files
2. **YAML-defined agents** - System prompts and settings in YAML
3. **MCP Microservices** - MCP servers run as separate Docker containers
4. **Permission-based tool access** - Role-based approval workflows via mcp_config.yaml
5. **Human-in-the-loop (HITL)** - Agents can ask questions via Redis pub/sub
6. **Session-based state** - Execution can pause and resume via LangGraph checkpoints

## Troubleshooting

### Slow VM / Keycloak takes long to initialize

**IMPORTANT**: On slow VMs or machines with limited resources, Keycloak can take 30-60 seconds or more to fully initialize. If the frontend login page shows errors or the Keycloak login doesn't appear:

1. **Wait longer** - Keycloak needs time to start up fully
2. Check Keycloak health: `curl http://localhost:8180/health/ready`
3. Wait for "status: UP" before trying to log in
4. The frontend will automatically retry authentication once Keycloak is ready

Don't assume something is broken - just wait and refresh the page after 30+ seconds.

### Backend won't start
```bash
docker logs druppie-new-backend
```

### MCP servers won't start
```bash
# Check individual MCP server logs
docker logs mcp-coding
docker logs mcp-docker
docker logs mcp-hitl
```

### Keycloak issues
```bash
# Check health
curl http://localhost:8180/health/ready

# Reimport realm
python scripts/setup_keycloak.py
```

### Database issues
```bash
# Reset database
./setup.sh clean
./setup.sh all
```

### Check all service status
```bash
./setup.sh status
```
