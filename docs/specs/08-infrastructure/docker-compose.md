# docker-compose.yml

Single file at the repo root, 894 lines. Defines every service, volume, network, and profile.

## Services (by category)

### Databases
- **druppie-db** — `postgres:15-alpine`, port 5533 external, volume `druppie_new_postgres`.
- **keycloak-db** — `postgres:15-alpine`, internal.
- **gitea-db** — `postgres:15-alpine`, internal.

Healthchecks: `pg_isready` every 5 s, 10 retries.

### Identity & VCS
- **keycloak** — `quay.io/keycloak/keycloak:24.0`, port 8180. Command: `start-dev`. Memory limit 768m. Healthcheck: `GET /health/ready` every 10s, 15 retries, 60s start period.
- **gitea** — `gitea/gitea:1.21`, port 3100 HTTP + 2223 SSH. OAuth2 auto-registration enabled. Healthcheck: `GET /api/healthz` every 10s.

### MCP microservices
- **module-coding** — port 9001, Dockerfile in `druppie/mcp-servers/module-coding/`. Workspace volume mounted at `/workspaces`. Depends on `gitea` + `sandbox-control-plane`.
- **module-docker** — port 9002. Mounts `/var/run/docker.sock`.
- **module-filesearch** — port 9004, `SEARCH_ROOT=/dataset`.
- **module-web** — port 9005, same `/dataset`.
- **module-archimate** — port 9006, `MODELS_DIR=/models` read-only.
- **module-registry** — port 9007, `DATA_DIR=/data` with RO mounts of `druppie/agents/definitions`, `mcp_config.yaml`, `skills`, `builtin_tools.py`.

### Sandbox infrastructure
- **sandbox-control-plane** — port 8787, `local-control-plane/Dockerfile`. Dual-homed on both networks. 30s start period.
- **sandbox-manager** — port 8000 internal, `local-sandbox-manager/Dockerfile`. Mounts Docker socket. On sandbox network.
- **sandbox-image-builder** — runs `docker build` for `open-inspect-sandbox:latest`, exits. Not long-running.

### Application
- **druppie-backend-dev** (dev profile) — port 8100. `uvicorn --reload`. Mounts `./druppie:/app/druppie`, `./testing:/app/testing:ro`, `./secrets:/app/secrets:ro`, Docker socket. LLM config via env vars.
- **druppie-backend** (prod profile) — port 8100. No reload, no mount. `ENVIRONMENT=production`.
- **druppie-frontend-dev** (dev) — port 5273, `frontend/Dockerfile.dev`. Vite HMR.
- **druppie-frontend** (prod) — port 5273, `frontend/Dockerfile` (nginx-alpine + built dist).

### Admin
- **adminer** — `adminer:latest`, port 8081. Default server: `druppie-db`. Theme: `pepa-linha-dark`.

### Initialization
- **druppie-init** (init profile) — `Dockerfile.init`. Runs `setup_keycloak.py` + `setup_gitea.py`. Writes `GITEA_TOKEN` to `.env`. Marker volume prevents re-run.

### Reset services
- **reset-db** — `docker:cli`. Connects to druppie-db via psql and drops application tables (projects, sessions, agent_runs, messages, tool_calls, llm_calls, approvals, questions). Preserves user tables.
- **reset-hard** (`Dockerfile.reset`) — host network mode. Stops all services, removes volumes, re-runs init.
- **nuke** (`Dockerfile.reset`) — destroys everything including volumes + built images, optionally rebuilds if `START_AFTER=true`.
- **reset-cache** — wipes `druppie_sandbox_dep_cache`.
- **cache-scanner** (`Dockerfile.cache-scanner`) — OSV scan on dep cache.

## Profiles

| Profile | What comes up |
|---------|---------------|
| `infra` | DBs + Keycloak + Gitea + all MCPs + sandbox infra + adminer |
| `dev` | infra + druppie-backend-dev + druppie-frontend-dev |
| `prod` | infra + druppie-backend + druppie-frontend |
| `init` | druppie-init (runs once) |
| `reset-db` | reset-db (one-shot) |
| `reset-hard` | reset-hard (one-shot) |
| `nuke` | nuke (one-shot) |
| `reset-cache` | reset-cache (one-shot) |
| `scan-cache` | cache-scanner (one-shot) |

## Networks

- **druppie-new-network** — main application network.
- **druppie-sandbox-network** — isolated sandbox network. Only sandbox-control-plane, sandbox-manager, and spawned sandbox containers.

## Volumes

```
druppie_new_postgres           druppie app DB
druppie_new_keycloak_postgres  Keycloak DB
druppie_new_gitea_postgres     Gitea DB
druppie_new_gitea              Gitea repos + LFS
druppie_new_workspace          /workspaces for module-coding
druppie_new_dataset            /dataset for filesearch + web
druppie_init_marker            init idempotency flag
druppie_sandbox_data           control plane SQLite
druppie_sandbox_snapshots      sandbox snapshot tarballs
druppie_sandbox_dep_cache      shared npm/pnpm/bun/uv/pip cache
druppie_cache_scan_results     OSV scan reports
```

## Typical commands

```bash
# First run
docker compose --profile dev --profile init up -d

# Later runs (after init completed)
docker compose --profile dev up -d

# Rebuild after MCP code change (MCPs are NOT volume-mounted)
docker compose --profile dev up -d --build

# DB reset (preserves users)
docker compose --profile reset-db run --rm reset-db

# Full reset
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile dev up -d --build

# Nuke (destroys everything)
docker compose --profile nuke run --rm nuke
```

## Memory limits

Most services don't set memory limits; Keycloak does (768m/384m). Sandbox containers get 4 GB by default (`SANDBOX_MEMORY_LIMIT`). On low-memory hosts, adjust via `.env`.

## Restart policy

- `unless-stopped` — databases, Keycloak, Gitea, MCPs, sandbox infra, backend, frontend.
- `no` — druppie-init and all reset services. They should run once and exit.

## Shell into a service

```bash
docker compose exec druppie-backend-dev bash
docker compose exec module-coding sh
docker compose logs -f sandbox-control-plane
```
