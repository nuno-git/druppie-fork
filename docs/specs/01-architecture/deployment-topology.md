# Deployment Topology

Druppie runs as a set of Docker containers on two bridge networks. Everything is defined in `docker-compose.yml` at the repo root; profiles gate which services come up.

## Networks

- **`druppie-new-network`** — main application network. Backend, frontend, MCP servers, Keycloak, Gitea, PostgreSQL, adminer, and the sandbox control plane all attach here.
- **`druppie-sandbox-network`** — isolated sandbox network. Only the sandbox control plane, the sandbox manager, and spawned sandbox containers attach here. Sandboxes cannot reach the main Druppie backend directly; they must go through the control plane.

The sandbox control plane is **dual-homed** (both networks) — it's the only bridge between agent containers and sandboxes.

## Ports (from `.env.example` defaults)

| Service | Internal | External | Notes |
|---------|----------|----------|-------|
| `druppie-db` (PostgreSQL app) | 5432 | **5533** | Exposed for local `psql`/adminer |
| `keycloak-db` / `gitea-db` | 5432 | — | Internal only |
| `keycloak` | 8080 | **8180** | Admin UI |
| `gitea` | 3000 / 22 | **3100** / **2223** | HTTP + SSH |
| `module-coding` | 9001 | 9001 | One of six MCP servers |
| `module-docker` | 9002 | 9002 | |
| `module-filesearch` | 9004 | 9004 | |
| `module-web` | 9005 | 9005 | |
| `module-archimate` | 9006 | 9006 | |
| `module-registry` | 9007 | 9007 | |
| `sandbox-control-plane` | 8787 | 8787 | |
| `sandbox-manager` | 8000 | — | Internal only |
| `druppie-backend` | 8000 | **8100** | FastAPI |
| `druppie-frontend` | 5173 | **5273** | Vite |
| `adminer` | 8080 | **8081** | PostgreSQL admin UI |

Port ranges reserved:
- 9001–9009 — core MCP modules
- 9010–9099 — user-added MCP modules
- 9100–9199 — deployed user app containers (managed by `module-docker` port allocator)

## Volumes

- `druppie_new_postgres` / `druppie_new_keycloak_postgres` / `druppie_new_gitea_postgres` — DB data
- `druppie_new_gitea` — Gitea data (repos, LFS)
- `druppie_new_workspace` — per-session working directories for module-coding
- `druppie_new_dataset` — `/dataset` mounted into filesearch + web modules
- `druppie_init_marker` — init idempotency flag
- `druppie_sandbox_data` — sandbox control plane SQLite + session DB
- `druppie_sandbox_snapshots` — sandbox snapshot tarballs (local runtime)
- `druppie_sandbox_dep_cache` — shared npm/pnpm/bun/uv/pip cache mounted into every sandbox (speeds up repeat installs)
- `cache_scan_results` — OSV scanner reports

## Profiles

```
--profile infra        DBs + Keycloak + Gitea + all MCP servers + sandbox infra + adminer
--profile dev          infra + druppie-backend-dev (--reload) + druppie-frontend-dev (HMR)
--profile prod         infra + druppie-backend (no reload) + druppie-frontend (built)
--profile init         runs druppie-init once (setup_keycloak.py + setup_gitea.py)
--profile reset-db     drops app tables, preserves users
--profile reset-hard   full reset: volumes + re-init
--profile nuke         destroy everything (containers + volumes + local images) and rebuild
--profile reset-cache  wipe sandbox dep cache volume
--profile scan-cache   run OSV vulnerability scan on sandbox dep cache
```

Typical commands:
```
docker compose --profile dev --profile init up -d
docker compose --profile reset-db run --rm reset-db
docker compose --profile dev down && docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile dev up -d --build
```

Why `--build` after `reset-hard`: MCP server containers are not volume-mounted; a rebuild is needed to pick up source changes.

## Startup sequence on a clean machine

```
1. `docker compose --profile dev --profile init up -d`
2. postgres × 3 → healthy (healthcheck: pg_isready)
3. keycloak → healthy (healthcheck: GET /health/ready)
4. gitea → healthy (healthcheck: GET /api/healthz)
5. druppie-init runs once:
   a. setup_keycloak.py → creates realm, roles, users, clients
   b. setup_gitea.py → creates admin user, OAuth2 client, org, seed repo
   c. writes GITEA_TOKEN to /project/.env
   d. touches /init-marker/.initialized
   e. exits 0
6. MCP servers start (coding depends on gitea + sandbox-control-plane)
7. sandbox-image-builder builds open-inspect-sandbox:latest and exits
8. sandbox-control-plane + sandbox-manager start
9. druppie-backend-dev runs uvicorn with --reload
10. druppie-frontend-dev runs vite dev server on 0.0.0.0:5173
```

On subsequent `up`, `druppie-init` sees the marker and exits immediately.

## Production vs dev differences

| Aspect | Dev | Prod |
|--------|-----|------|
| Backend image | Mount `./druppie:/app/druppie` | Built into image, no mount |
| Backend reload | `uvicorn --reload` | No reload |
| Frontend | Vite HMR on :5273 | Pre-built `dist/` served by nginx |
| `ENVIRONMENT` env var | `development` | `production` |
| `INTERNAL_API_KEY` | default `druppie-internal-secret-key` | must override or app refuses to start |
| `SANDBOX_API_SECRET` | default `sandbox-dev-secret` | must override |
| Testing volume mount | `./testing:/app/testing:ro` | not mounted |
| Keycloak | `start-dev` mode | `start-dev` still (no HA/edge cert setup yet) |

The prod profile is primarily for local prod-shaped testing. Real production deployments use `background-agents/terraform/` for the sandbox path (Cloudflare Workers + Modal) while Druppie itself has no prod terraform today.

## Sandbox runtime

Sandboxes are **not** managed by docker-compose. The `sandbox-manager` service spawns containers on demand via the Docker socket:

```
agent calls execute_coding_task
  → sandbox-control-plane receives request
  → calls sandbox-manager POST /api/create-sandbox
  → sandbox-manager runs `docker run --rm --network druppie-sandbox-network
                                   --security-opt=no-new-privileges
                                   --cap-drop=ALL --cap-add=NET_RAW
                                   --memory 4g --cpus 2 --pids-limit 8192
                                   --tmpfs /tmp:size=2g
                                   -v druppie_sandbox_dep_cache:/cache
                                   open-inspect-sandbox:latest`
  → sandbox runs entrypoint.py, connects back to control plane over WebSocket
```

Sandboxes are hardened:
- No new privileges (blocks setuid/setgid).
- All capabilities dropped except `NET_RAW`.
- AppArmor + Docker default seccomp profile.
- Non-root user `sandbox` (uid 1000) inside the container.
- PID limit 8192 (prevents fork bombs).
- Default lifetime 2 hours (`DEFAULT_SANDBOX_TIMEOUT_SECONDS=7200`); Druppie watchdog marks tool calls FAILED after 30 min (`SANDBOX_TIMEOUT_MINUTES=30`).

## External dependencies

- **LLM providers** — reached from the backend (`druppie/llm/`) and from sandboxes (via the control plane's LLM proxy). Supported: Z.AI, DeepInfra, DeepSeek, Azure Foundry, Ollama (local), Anthropic (sandbox only).
- **Gitea** — runs inside the stack. Agents clone/push via `module-coding`'s git tooling and create PRs via Gitea's API.
- **Keycloak** — identity provider for Druppie and Gitea (OAuth2). One realm: `druppie`.
- **Docker daemon** — the host's daemon, mounted as `/var/run/docker.sock` into `module-docker` and `sandbox-manager`. Running Druppie on a system without Docker is not supported.
