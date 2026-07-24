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

When making significant changes, use the formal documentation framework:
- `docs/adrs/` - Architectural decisions (ADRs)
- `docs/prds/` - Product requirements (PRDs)
- `docs/research/` - Research and analysis
- `docs/specs/` -Executable behavioral specs (Gherkin)
- `docs/guides/` - Operational guides

### Documentation standard (PBI 9742–9744)

Documentation flow & templates: see [`AGENTS.md`](AGENTS.md) (tool-agnostic entry point) / [`docs/guides/documentation-framework.md`](docs/guides/documentation-framework.md) (full details). A PR that changes feature code should include documentation, or be marked `docs-exempt`. Validate: `docker compose --profile docs-validator run --rm docs-validator`.

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
docker compose --profile dev up -d --build   # Always --build after reset (MCP servers have no volume mount)

# Full nuke & rebuild (destroys everything including images, rebuilds from scratch)
docker compose --profile nuke run --rm nuke

# Purge sandbox dependency cache (npm, pnpm, bun, uv, pip)
docker compose --profile reset-cache run --rm reset-cache

# Scan dependency cache for vulnerabilities (OSV)
docker compose --profile scan-cache run --rm cache-scanner
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

## Agent Subagent Policy (MUST FOLLOW)

- **NEVER read files yourself. EVER.** Use subagents (explore, librarian) for ALL codebase exploration. This includes `read`, `grep`, `glob`, and any other file-reading tools.
- If you need to understand a file, delegate to an explore subagent. Period.
- There is NO exception. "Already know where it is" is not an exception. "It's a quick look" is not an exception.
- Direct file reads are FORBIDDEN. The only time you may read is if YOU wrote the file earlier in this session.
- **ALWAYS use subagents (deep, unspecified-high, quick, etc.) for ALL writing and coding tasks** — delegate implementation work, never do it yourself.
- You are an orchestrator. Your job is to decompose, delegate, and verify — not to read, write, or search code yourself.

## Subagent Usage Rules (for Sisyphus / the orchestrator)

- **Always include `load_skills=[]` in ALL delegate_task calls** — the API requires it.
- **Always include `run_in_background=true` in ALL background explore/librarian delegate_task calls**.
- **For codebase analysis tasks, prefer "general" or subagent_type with run_in_background=false** — avoid "explore" entirely since the model it needs doesn't exist in this environment.
- **For implementation/writing tasks, prefer sisyphus-junior or general subagents** — don't write files yourself.

## Development Workflow (MUST FOLLOW)

**Always test your work end-to-end after implementation.** The flow is:

1. **Analyze** → Use explore/librarian subagents to understand the codebase
2. **Develop** → Delegate implementation to subagents (deep, quick, etc.)
3. **Rebuild + Test E2E** → Delegate to a single subagent that rebuilds AND tests

Do NOT rebuild or test yourself — delegate everything to save context. Do NOT mark work as done until e2e testing passes. The test subagent MUST also handle rebuilding before testing.

## E2E Testing Reference (subagents read this)

### Service Ports (instance-specific — from `.env`)

Host ports are set per-instance in `.env`. Read your own values; the numbers below
are the `.env.example` defaults, not guaranteed for your instance.

| Service | `.env` variable | Default |
|---------|-----------------|---------|
| Keycloak | `KEYCLOAK_PORT` | 8180 |
| Backend API | `BACKEND_PORT` | 8100 |
| Frontend | `FRONTEND_PORT` | 5273 |

Export them before running the curl blocks below:
```bash
# Load ports from your .env (falls back to .env.example defaults)
KEYCLOAK_PORT=${KEYCLOAK_PORT:-8180}
BACKEND_PORT=${BACKEND_PORT:-8100}
FRONTEND_PORT=${FRONTEND_PORT:-5273}
```

### Auth

```bash
TOKEN=$(curl -s -X POST "http://localhost:${KEYCLOAK_PORT}/realms/druppie/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=druppie-frontend&username=admin&password=Admin123!" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Rebuild Commands

```bash
# Backend container
docker compose --profile dev up -d --build druppie-backend-dev

# Wait for healthy
docker compose exec druppie-backend-dev curl -s http://localhost:8000/health
```

### E2E Test: API (setup test → retry-from developer)

The fast pattern: run a setup test that creates a session ending at a pending developer agent, then retry-from that developer with a targeted prompt.

```bash
# 1. Run setup test
curl -s -X POST "http://localhost:${BACKEND_PORT}/api/evaluations/run-tests" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"test_name": "setup-yaml-flow-hello-world"}'
# → {"run_id": "...", "status": "running"}

# 2. Poll until complete (usually <30s)
curl -s "http://localhost:${BACKEND_PORT}/api/evaluations/run-status/$TEST_RUN_ID" -H "Authorization: Bearer $TOKEN"
# → {"status": "completed", "message": "1/1 passed"}

# 3. Find session (test results don't include session_id)
SESSION_ID=$(curl -s "http://localhost:${BACKEND_PORT}/api/sessions" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
for s in json.load(sys.stdin):
  if 'setup-yaml-flow-hello-world' in s.get('title',''): print(s['id']); break")

# 4. Find pending developer agent run (field is agent_id, not agent_name)
curl -s "http://localhost:${BACKEND_PORT}/api/sessions/$SESSION_ID" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
for item in json.load(sys.stdin).get('timeline',[]):
  ar = item.get('agent_run')
  if ar and isinstance(ar, dict) and ar.get('agent_id') == 'developer' and ar.get('status') == 'pending':
    print(ar['id']); break"

# 5. Retry from developer
curl -s -X POST "http://localhost:${BACKEND_PORT}/api/sessions/$SESSION_ID/retry-from/$AGENT_RUN_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"planned_prompt": "Use the planner flow to create a hello world page"}'

# 6. Monitor (poll every 10s, max 4min)
curl -s "http://localhost:${BACKEND_PORT}/api/sessions/$SESSION_ID" -H "Authorization: Bearer $TOKEN"
docker compose logs --tail=30 druppie-backend-dev 2>&1 | grep -i error

# 7. Stop if failing
curl -s -X POST "http://localhost:${BACKEND_PORT}/api/chat/$SESSION_ID/cancel" -H "Authorization: Bearer $TOKEN"
```

**Available setup tests** (in `testing/tools/`):
- `setup-yaml-flow-hello-world` — Full pipeline to pending developer
- `setup-project-with-fd` — Pipeline to BA completed, ready for planner
- `setup-vergunningzoeker-with-fd` — Realistic BA elicitation, ready for planner
- `setup-todo-app-pipeline` — Full pipeline to builder planning

**Available agent tests** (in `testing/agents/`) — run setup + execute agent with real LLM:
- `yaml-flow-agent-summaries` — Runs developer in the setup-yaml-flow session

### E2E Test: Playwright (browser)

Best for: frontend changes, full UI flows, visual verification. Use the `/playwright` skill.

Login: `http://localhost:${FRONTEND_PORT}` (default 5273) with `admin` / `Admin123!`

Same pattern — setup test via API first, then retry via UI:

1. Run setup test via API (steps above) to create a session with a pending developer
2. Open the app → Login with admin/Admin123!
3. Find the session in the chat list
4. Click the retry button (↺ amber) on the developer agent run
5. Enter custom prompt in the retry dialog
6. Watch the agent run appear with live events
7. Stop if failing — click cancel on the session
8. Verify the result

## Critical Rules

1. **NO database migrations** - Update SQLAlchemy models directly, reset DB with `docker compose --profile reset-db run --rm reset-db`
2. **Prefer relational tables over JSON/JSONB columns** - Normalize data with a stable, queryable schema into proper tables. `Column(JSON)` is allowed for genuinely variable/open-ended payloads (raw LLM messages, dynamic tool arguments) — document the expected shape in a code comment when you use it.
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
