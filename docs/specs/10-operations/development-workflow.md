# Development Workflow

## Branch policy

Per `CLAUDE.md`:

- **Default branch**: `colab-dev` (NOT `main`).
- **Always branch from**: `colab-dev`.
- **PRs target**: `colab-dev`.
- **Note**: `main` is deprecated and will be deleted.

Starting a feature:
```bash
git checkout colab-dev
git pull origin colab-dev
git checkout -b feature/your-feature-name
```

Opening a PR:
```bash
gh pr create --base colab-dev --title "..." --body "..."
```

## First-time setup

```bash
cp .env.example .env
# Edit .env: set at least LLM_PROVIDER + matching API key
docker compose --profile dev --profile init up -d
```

First boot takes 3–5 min (postgres + keycloak + gitea init + image builds).

Verify:
- Frontend: http://localhost:5273
- Backend: http://localhost:8100/health
- Keycloak admin: http://localhost:8180/admin (admin/admin)
- Gitea: http://localhost:3100
- Adminer: http://localhost:8081

## Daily dev loop

Backend changes (`druppie/`):
- Mounted in dev profile with `uvicorn --reload`. Save a Python file; uvicorn restarts.
- MCP server changes (`druppie/mcp-servers/module-*/`) are NOT mounted — rebuild:
  ```
  docker compose --profile dev up -d --build module-coding
  ```

Frontend changes (`frontend/`):
- Vite HMR picks up changes instantly.

Agent YAML changes (`druppie/agents/definitions/*.yaml`):
- `--reload` picks them up on next request (the loader re-reads per request).

MCP config changes (`druppie/core/mcp_config.yaml`):
- Requires backend restart to re-run `ToolRegistry.initialize()`.
  ```
  docker compose restart druppie-backend-dev
  ```

## Logs

```bash
docker compose logs -f druppie-backend-dev       # backend
docker compose logs -f druppie-frontend-dev      # frontend
docker compose logs -f module-coding             # a specific MCP
docker compose logs -f sandbox-control-plane     # control plane
docker compose logs -f                            # everything
```

## Tests

Backend unit:
```bash
cd druppie && pytest
```

Frontend unit:
```bash
cd frontend && npm run test
```

Frontend e2e:
```bash
cd frontend && npm run test:e2e
# or headed for debugging
cd frontend && npm run test:e2e:headed
```

Evaluations (via UI at /admin/evaluations, or API):
```bash
curl -X POST http://localhost:8100/api/evaluations/run-tests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_names": ["create-todo-app"], "execute": true, "judge": true}'
```

## Linting / formatting

```bash
cd druppie && ruff check .
cd druppie && black .

cd frontend && npm run lint
```

Not enforced in CI yet but expected locally.

## Documentation discipline

When making significant changes, update:
- `docs/FEATURES.md` — new features or feature changes.
- `docs/BACKLOG.md` — bugs, tech debt, improvement ideas.
- `docs/TECHNICAL.md` — architecture or technical changes.
- `docs/specs/` — this folder when spec-level changes.

PRs touching agent behaviour should include sample sessions or test additions.

## Common commands

Drop application tables (keep users):
```bash
docker compose --profile reset-db run --rm reset-db
```

Full reset (volumes, keycloak, gitea):
```bash
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile dev up -d --build
```

Nuke everything (images, volumes, containers):
```bash
docker compose --profile nuke run --rm nuke
```

Purge sandbox dep cache:
```bash
docker compose --profile reset-cache run --rm reset-cache
```

OSV scan sandbox deps:
```bash
docker compose --profile scan-cache run --rm cache-scanner
```

## Git hygiene

- Always commit and push after a working change (memory: user feedback prefers this).
- Prefer conventional commit messages: `feat: …`, `fix: …`, `refactor: …`, `docs: …`, `test: …`.
- Don't skip hooks unless explicitly needed.
- Create new commits rather than amending (amend if hook fails → risk of losing work).

## When things go wrong

- Backend won't start → check `docker compose logs druppie-backend-dev`.
- "Zombie session" on resume → startup recovery already handled; click Resume in UI.
- LLM returns errors consistently → check `ZAI_API_KEY` or equivalent.
- MCP call timeouts → check the module's `/health` endpoint, then its logs.
- Sandbox stuck → watch the 30-min timeout, or manually `docker stop <sandbox-container>`.

Fuller troubleshooting in `troubleshooting.md`.
