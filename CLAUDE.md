# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important: Branch Policy

- **Default branch**: `colab-dev` (NOT `main`)
- **Always branch from**: `colab-dev`
- **PRs target**: `colab-dev`
- **Note**: `main` is deprecated and will be deleted in the future

When creating new branches:
```bash
git checkout colab-dev
git pull origin colab-dev
git checkout -b feature/your-feature-name
```

## Documentation Reminder

When making significant changes, remember to update the `/docs` folder:
- `docs/FEATURES.md` - New features or feature changes
- `docs/BACKLOG.md` - Bugs, technical debt, and improvement ideas
- `docs/TECHNICAL.md` - Architecture or technical changes

## Project Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions and approval workflows. Agents can only act through MCP tools - no direct file output.

## Development Commands

### Docker Compose (primary workflow)
```bash
# Start full dev environment (hot reload)
docker compose --profile dev --profile init up -d

# Start infrastructure only
docker compose --profile infra --profile init up -d

# Stop everything
docker compose --profile dev down

# View logs
docker compose logs -f druppie-backend-dev

# Reset application database
docker compose --profile reset-db run --rm reset-db

# Hard reset (wipe all data + re-initialize)
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard

# Rebuild after Dockerfile changes
docker compose --profile dev up -d --build
```

### Backend (Python/FastAPI)
```bash
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

vendor/
└── open-inspect/  # Git submodule — sandbox infrastructure (background-agents)

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

1. **NO database migrations** - Update SQLAlchemy models directly, reset DB with `docker compose --profile reset-db run --rm reset-db`
2. **NO JSON/JSONB columns** - Normalize everything into proper relational tables
3. **NO legacy/fallback code** - Clean architecture only, no backwards compatibility hacks
4. **Config in YAML files** - Agent definitions in `agents/definitions/*.yaml`, not database
5. **Always commit and push** - Keep changes in git

## Test Users (Keycloak)

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

## Environment

Copy `.env.example` to `.env` and set:
```
LLM_PROVIDER=zai
ZAI_API_KEY=your_key
GITEA_TOKEN=your_token
```
