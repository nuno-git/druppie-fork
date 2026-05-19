# Druppie Codebase Structure

## Overview

**Druppie** is an AI agent governance platform that implements Model Context Protocol (MCP) tool permissions and approval workflows. Agents operate exclusively through MCP tools—no direct file output is allowed. The platform provides structured control over AI agent actions via permissions, multi-level approvals, and sandboxed execution environments.

---

## Top-Level Directories

### `druppie/` - Core Backend Application

| Directory | Purpose |
|-----------|---------|
| `api/` | FastAPI routes - thin layer that delegates to services |
| `services/` | Business logic, orchestrates repositories |
| `repositories/` | Data access layer, returns domain models |
| `domain/` | Pydantic models using Summary/Detail pattern |
| `db/models/` | SQLAlchemy ORM models (database schema) |
| `db/` | Database connection and seeding utilities |
| `execution/` | Agent orchestrator (LangGraph loop) |
| `agents/` | YAML agent definitions (not database) |
| `core/` | MCP client, config loading |
| `mcp-servers/` | Microservices (Coding: 9001, Docker: 9002) |
| `mcps/` | MCP tools definitions |
| `tools/` | Tool implementations |
| `llm/` | LLM provider integration (Z.AI, DeepInfra via LiteLLM) |
| `templates/` | Code generation templates |
| `skills/` | Druppie-specific agent skills |
| `opencode/` | OpenCode integration for sandbox code generation |
| `tests/` | Backend test suite (pytest) |

### `frontend/` - React/Vite Application

| Directory | Purpose |
|-----------|---------|
| `src/pages/` | React page components |
| `src/services/` | API client, Keycloak auth, WebSocket |
| `tests/e2e/` | Playwright end-to-end tests |
| `public/` | Static assets |
| `tests/` | Frontend unit tests (Vitest) |

### `background-agents/` - Sandbox Infrastructure

Managed by nuno120/background-agents (branch `druppie`). Provides:
- **Sandbox Control Plane** - Kubernetes-based sandbox management
- **Sandbox Manager** - Orchestrates kata containers
- Terraform infrastructure
- Puppeteer automation for OpenCode UI interaction

### `iac/` - Infrastructure as Code

- `realm.yaml` - Keycloak realm configuration
- `users.yaml` - Test user accounts and roles

### `docs/` - Documentation

- `FEATURES.md` - Functional capabilities (agents, approvals, sandbox)
- `TECHNICAL.md` - Architecture and technical details
- `SANDBOX.md` - Sandbox infrastructure, OpenCode, Kata Containers
- `BACKLOG.md` - Bugs, technical debt, improvement ideas
- Various presentation and module specification documents

### `scripts/` - Development utilities

- Build, test, and deployment scripts

### `.github/` - GitHub workflows

CI/CD pipelines and automation

---

## Architecture Pattern

```
Repository → Domain Model → Service → API Route
```

**Key Principles:**
- **Clean Architecture**: No JSON/JSONB columns, all normalized tables
- **No Migrations**: Reset DB directly via `docker compose --profile reset-db`
- **Config in YAML**: Agent definitions in `agents/definitions/*.yaml`, not database
- **Summary/Detail Models**: Lists use `*Summary`, single items use `*Detail`

---

## Key Technologies

- **Backend**: Python, FastAPI, SQLAlchemy, LangGraph
- **Frontend**: React, Vite, Tailwind CSS, Playwright
- **Orchestration**: Docker Compose (dev/prod profiles)
- **Identity**: Keycloak (OAuth2/OIDC)
- **Git**: Gitea (for repository management)
- **LLM**: Z.AI or DeepInfra (via LiteLLM)
- **Sandboxing**: Kata Containers, OpenCode UI

---

## Development Commands

```bash
# Start full dev environment (first time includes --profile init)
docker compose --profile dev --profile init up -d --build

# Daily usage
docker compose --profile dev up -d

# View logs
docker compose logs -f druppie-backend-dev

# Reset database (soft reset)
docker compose --profile reset-db run --rm reset-db

# Hard reset (wipe all data)
docker compose --profile reset-hard run --rm reset-hard
```

---

## Testing

- **Backend**: `cd druppie && pytest`
- **Frontend**: `cd frontend && npm test`
- **E2E**: `cd frontend && npm run test:e2e`
