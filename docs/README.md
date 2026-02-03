# Druppie Documentation

Druppie is a governance platform for AI agents. Users chat with AI agents that build software through MCP (Model Context Protocol) tools, with human approval workflows for dangerous operations. Every LLM call, tool execution, and approval is tracked and auditable.

---

## Quick Start

```bash
# Start everything (infrastructure + backend + frontend)
./setup_dev.sh

# Or start components individually
./setup_dev.sh infra       # Databases, Keycloak, Gitea, MCP servers
./setup_dev.sh backend     # FastAPI backend on port 8100
./setup_dev.sh frontend    # React frontend on port 5273

# Check status / stop
./setup_dev.sh status
./setup_dev.sh stop
```

**Access points:**
- Frontend: http://localhost:5273
- Backend API: http://localhost:8100/api
- Keycloak: http://localhost:8080

**Test users (Keycloak):**

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |

---

## Documentation Map

### Getting Started

| Document | Description |
|----------|-------------|
| [OVERVIEW.md](./OVERVIEW.md) | Master summary of the entire system -- start here |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System architecture, data flow diagrams, and how all components interact |
| [FOLDER_STRUCTURE.md](./FOLDER_STRUCTURE.md) | What each folder contains and why it exists |

### Core Systems

| Document | Description |
|----------|-------------|
| [EXECUTION_ENGINE.md](./EXECUTION_ENGINE.md) | How the execution engine works: orchestrator, agent loop, pause/resume |
| [AGENTS.md](./AGENTS.md) | All agent definitions (router, planner, architect, developer, deployer, etc.) and their roles |
| [MCP_SERVERS.md](./MCP_SERVERS.md) | MCP server tools, configuration, and approval rules |
| [LLM_PROVIDERS.md](./LLM_PROVIDERS.md) | LLM provider support (ZAI, DeepInfra), tool call parsing, and known issues |

### API and Data

| Document | Description |
|----------|-------------|
| [API.md](./API.md) | Complete API endpoint reference with request/response examples |
| [DATABASE.md](./DATABASE.md) | Database schema, table definitions, entity relationships, and common queries |
| [FRONTEND.md](./FRONTEND.md) | Frontend architecture: React pages, services, WebSocket integration |

### Planning and Operations

| Document | Description |
|----------|-------------|
| [ROADMAP.md](./ROADMAP.md) | What works, what does not, known issues, and future plans |
| [DATABASE_REDESIGN.md](./DATABASE_REDESIGN.md) | Proposed schema simplification: tables to remove, rename, and keep |
| [DOMAIN_MODELS_PROPOSAL.md](./DOMAIN_MODELS_PROPOSAL.md) | Clean architecture proposal: domain models, repositories, services, orchestrator |
| [MIGRATION_PLAN.md](./MIGRATION_PLAN.md) | Step-by-step migration from current architecture to clean architecture |

### Research

| Document | Description |
|----------|-------------|
| [research-deployer-summary-fix.md](./research-deployer-summary-fix.md) | Deep research into deployer summary bug and LLM tool call parsing issues |

---

## Folder READMEs

Each major backend module has (or will have) its own README with module-specific details.

| Folder | README | Description |
|--------|--------|-------------|
| `druppie/execution/` | [README.md](../druppie/execution/README.md) | Execution engine: orchestrator, tool executor, MCP HTTP client |
| `druppie/agents/` | `README.md` | Agent definitions, runtime, built-in tools |
| `druppie/domain/` | `README.md` | Pydantic domain models (Summary/Detail pattern) |
| `druppie/repositories/` | `README.md` | Database access layer, returns domain models |
| `druppie/services/` | `README.md` | Business logic, permissions, orchestration |
| `druppie/api/` | `README.md` | FastAPI routes, dependency injection, error handling |
| `druppie/core/` | `README.md` | MCP client, config loading, shared utilities |
| `druppie/db/` | `README.md` | SQLAlchemy ORM models and database session management |
| `frontend/` | `README.md` | React/Vite frontend application |

---

## Key Concepts

**Agents** -- AI agents defined in YAML files. Each has a role (router, planner, architect, developer, deployer), allowed MCP tools, and a system prompt. Agents can only act through tool calls.

**MCP Servers** -- Separate Docker containers that provide tools. The coding server (port 9001) handles file and git operations. The docker server (port 9002) handles container builds and deployments.

**Sessions** -- A session is one conversation containing messages, agent runs, LLM calls, tool executions, approvals, and HITL questions in a unified timeline.

**Approvals** -- Dangerous tool calls (like running commands or deploying containers) require human approval before execution. Approvals are role-gated.

**HITL Questions** -- Agents can pause execution to ask the user questions. Supports free-text and multiple-choice formats.

---

## Development Commands

```bash
# Backend
cd druppie && pytest              # Run tests
cd druppie && ruff check .        # Lint
cd druppie && black .             # Format

# Frontend
cd frontend && npm run dev        # Dev server
cd frontend && npm run lint       # Lint
cd frontend && npm test           # Unit tests
cd frontend && npm run test:e2e   # Playwright E2E tests
```

---

## Environment

Required in `.env`:

```
LLM_PROVIDER=zai
ZAI_API_KEY=your_key
GITEA_TOKEN=your_token
```
