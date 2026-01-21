# Druppie Governance Platform - Claude Code Instructions

## Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions, approval workflows, and project management integrated with Gitea.

## Repository Structure

```
cleaner-druppie/
├── druppie/                   # NEW FastAPI backend (v2) - PRIMARY
│   ├── agents/                # YAML agent definitions
│   ├── workflows/             # YAML workflow definitions
│   ├── mcps/                  # MCP servers (coding, git, docker, hitl)
│   ├── core/                  # Main loop, state, models, auth
│   ├── llm/                   # LLM providers (zai, mock)
│   ├── api/                   # FastAPI routes
│   ├── db/                    # SQLAlchemy models & CRUD
│   ├── docker-compose.yml     # Dev compose (port 8001)
│   ├── docker-compose.full.yml # Full stack (ports 8100/5273/8180)
│   ├── Dockerfile
│   └── requirements.txt
│
├── backend/                   # LEGACY Flask backend (v1) - for reference only
│   ├── app.py                 # Flask API
│   ├── druppie/               # Old implementation
│   └── registry/              # Old agent/workflow definitions
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
├── docker-compose.yml         # Root compose (legacy Flask backend)
├── setup.sh                   # Main setup script
└── CLAUDE.md                  # This file
```

## Architecture (v2 - druppie/)

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│                    Main Loop (core/loop.py)             │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │   Router    │───▶│   Planner    │───▶│  Execute   │ │
│  │   Agent     │    │    Agent     │    │   Tasks    │ │
│  └─────────────┘    └──────────────┘    └────────────┘ │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Servers (mcps/*.py)                    │
│  coding │ git │ docker │ hitl (human-in-the-loop)       │
└─────────────────────────────────────────────────────────┘
```

**Key Principle**: Agents can ONLY act through MCP tools. No direct code output.

## Key Components (v2)

### 1. Agents (`druppie/agents/*.yaml`)

```yaml
# Example: druppie/agents/developer.yaml
name: developer
description: Writes and modifies code
system_prompt: |
  You are a senior developer. You write clean, working code.
  You can ONLY act through MCP tools.
mcps:
  - coding      # Read/write files
  - git         # Clone, commit, push
  - docker      # Build, run
  - hitl        # Ask user questions
settings:
  model: glm-4
  temperature: 0.1
```

### 2. MCP Servers (`druppie/mcps/`)

| Server | Tools | Description |
|--------|-------|-------------|
| coding | read_file, write_file, list_dir, run_command | File operations |
| git | clone, commit, push, branch, status | Version control |
| docker | build, run, stop, logs | Container operations |
| hitl | ask, approve, progress | Human-in-the-loop |

### 3. LLM Service (`druppie/llm/`)

- `zai.py` - Z.AI GLM-4.7 provider with retry logic
- `mock.py` - Mock provider for testing
- `base.py` - Abstract interface

### 4. API (`druppie/api/`)

FastAPI endpoints:
- `POST /api/chat` - Main chat interface
- `GET /api/sessions` - List sessions
- `GET /api/approvals` - List pending approvals
- `POST /api/approvals/{id}/approve` - Approve action
- `GET /api/mcps` - List available MCP tools
- `WS /ws/session/{id}` - Real-time updates

## Setup & Running

### Option 1: Full Stack (Recommended for Development)

Uses separate ports to avoid conflicts:
- Frontend: http://localhost:5273
- Backend: http://localhost:8100
- Keycloak: http://localhost:8180

```bash
# From project root
cd druppie
docker compose -f docker-compose.full.yml up -d --build

# View logs
docker logs -f druppie-new-backend
```

### Option 2: Dev Backend Only

Backend on port 8001, uses external Keycloak:

```bash
cd druppie
docker compose up -d --build
```

### Option 3: Legacy Flask Backend

Uses root docker-compose.yml (ports 8000/5173/8080):

```bash
docker compose up -d
```

### Initial Setup

```bash
# First time setup (Keycloak realm, users, Gitea org)
./setup.sh all

# Or individual components
./setup.sh keycloak
./setup.sh gitea
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

Tools have approval requirements:

| Type | Description | Example |
|------|-------------|---------|
| NONE | No approval needed | read_file |
| SELF | User confirmation | write_file |
| ROLE | Specific role required | docker:run |
| MULTI | Multiple roles required | deploy to prod |

## E2E Testing with Playwright

```bash
cd frontend
npm run test:e2e
```

Or use Playwright MCP tools in Claude Code:
1. Navigate to http://localhost:5273
2. Login with test user
3. Test chat functionality

**Note**: LLM calls can take up to 3 minutes. Be patient!

## Development Workflow

### Adding a New Agent

1. Create YAML in `druppie/agents/`:
```yaml
name: my_agent
description: What it does
system_prompt: |
  Your instructions...
mcps:
  - coding
  - git
settings:
  model: glm-4
  temperature: 0.1
```

2. The agent is automatically loaded by the main loop

### Adding a New MCP Tool

1. Add to appropriate server in `druppie/mcps/`
2. Register in `registry.py`
3. Set permission level

### Modifying the Frontend

```bash
cd frontend
npm install
npm run dev  # Dev server on port 5173
```

## Key Design Decisions

1. **Agents can only act through MCPs** - No direct LLM output to files
2. **YAML-defined agents** - System prompts and settings in YAML
3. **Permission-based tool access** - Role-based approval workflows
4. **Human-in-the-loop (HITL)** - Agents can ask questions and request approvals
5. **Session-based state** - Execution can pause and resume

## Troubleshooting

### Backend won't start
```bash
docker logs druppie-new-backend
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
docker compose -f druppie/docker-compose.full.yml down -v
docker compose -f druppie/docker-compose.full.yml up -d
```
