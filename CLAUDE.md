# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions and approval workflows. Agents can only act through MCP tools - no direct file output.

## Development Commands

### Backend (Python/FastAPI)
```bash
# Dev mode with hot reload (recommended)
./setup_dev.sh              # Start infra + backend + frontend
./setup_dev.sh backend      # Backend only (port 8100)

# Manual backend
cd druppie && uvicorn api.main:app --reload --port 8100

# Tests & linting
cd druppie && pytest
cd druppie && ruff check .
cd druppie && black .
```

### Frontend (React/Vite)
```bash
cd frontend
npm install
npm run dev      # Dev server (port 5273)
npm run lint
npm test
npm run test:e2e # Playwright
```

### Infrastructure
```bash
./setup_dev.sh infra    # Start DBs, Keycloak, Gitea, MCP servers
./setup_dev.sh stop     # Stop all
./setup_dev.sh status   # Check status
```

## Architecture

```
druppie/
├── api/           # FastAPI routes - thin layer, delegates to services
├── services/      # Business logic, orchestrates repositories
├── repositories/  # Data access, returns domain models
├── domain/        # Pydantic models (Summary/Detail pattern)
├── db/models/     # SQLAlchemy ORM models
├── execution/     # Agent orchestrator, LangGraph loop
├── agents/        # YAML agent definitions
├── core/          # MCP client, config loading
└── mcp-servers/   # Coding (9001), Docker (9002) microservices

frontend/
├── src/pages/     # React pages
├── src/services/  # API client, Keycloak, WebSocket
└── tests/e2e/     # Playwright tests
```

### Data Flow
Repository → Domain Model → Service → API Route

Domain models use Summary/Detail naming:
- `SessionSummary` for lists, `SessionDetail` for single items
- All exports through `druppie/domain/__init__.py`

## Critical Rules

1. **NO database migrations** - Update SQLAlchemy models directly, reset DB with `./setup.sh clean && ./setup.sh all`
2. **NO JSON/JSONB columns** - Normalize everything into proper relational tables
3. **NO legacy/fallback code** - Clean architecture only, no backwards compatibility hacks
4. **Config in YAML files** - Agent definitions in `agents/definitions/*.yaml`, not database
5. **Always commit and push** - Keep changes in git

## Test Users (Keycloak)

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |

## Environment

Required in `.env`:
```
LLM_PROVIDER=zai
ZAI_API_KEY=your_key
GITEA_TOKEN=your_token
```
