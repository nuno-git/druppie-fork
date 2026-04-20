# Dockerfiles

Inventory of every Dockerfile in the repo.

## Repo root

### `Dockerfile` (backend)

Base: `python:3.11-slim`. Installs:
- System: `git, curl, docker.io, nodejs, npm, chromium`.
- npm global: `@mermaid-js/mermaid-cli`.
- Python: via `pip install -r druppie/requirements.txt`.

Env:
- `PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium`, `PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true`.
- `PYTHONPATH=/app`, `PYTHONUNBUFFERED=1`.

Copies `druppie/` → `/app/druppie/`. Creates `/app/workspace`. Exposes 8000.

Healthcheck: `curl http://localhost:8000/health` every 30s.

CMD: `uvicorn druppie.api.main:app --host 0.0.0.0 --port 8000`.

### `Dockerfile.init`

Base: `python:3.11-slim`. Installs `curl`, `docker.io`. Pip: `requests`, `pyyaml`.

Copies `scripts/setup_keycloak.py`, `scripts/setup_gitea.py`, `scripts/init-entrypoint.sh`, `iac/`. Fixes line endings (for Windows hosts), `chmod +x` on scripts. Creates `/init-marker`.

ENTRYPOINT: `/app/scripts/init-entrypoint.sh`.

### `Dockerfile.reset`

Base: `python:3.11-slim`. Installs `curl`, `docker.io`, Docker Compose plugin (downloaded from GitHub releases). Pip: `requests`, `pyyaml`.

Copies `scripts/setup_keycloak.py`, `setup_gitea.py`, `reset-hard.sh`, `nuke.sh`, `iac/`.

ENTRYPOINT: `/app/scripts/reset-hard.sh` (for reset-hard profile).

For the nuke profile, docker-compose overrides the entrypoint to `/app/scripts/nuke.sh`.

### `Dockerfile.cache-scanner`

Base: `debian:bookworm-slim`. Installs `ca-certificates, jq, curl` (then purges `curl`). Downloads `osv-scanner v2.3.3` with SHA256 verification.

Copies `scripts/scan-cache.sh` to `/usr/local/bin/`.

ENTRYPOINT: `/usr/local/bin/scan-cache.sh`.

## Frontend

### `frontend/Dockerfile` (prod)

Multi-stage:
1. `node:22-alpine` — run `npm ci && npm run build` → produces `/app/dist/`.
2. `nginx:alpine` — copy `/app/dist/` to `/usr/share/nginx/html/`.

Build args baked in: `VITE_API_URL`, `VITE_KEYCLOAK_URL`, `VITE_GITEA_URL`, `VITE_KEYCLOAK_REALM`, `VITE_KEYCLOAK_CLIENT_ID`.

### `frontend/Dockerfile.dev`

Base: `node:22-alpine`. Just `npm ci`; source is volume-mounted. CMD: `npm run dev -- --host 0.0.0.0`.

## MCP servers

Each `druppie/mcp-servers/module-<name>/Dockerfile` follows the same pattern:
- Base: `python:3.11-slim` (or with module-specific deps).
- Install module's `requirements.txt`.
- Copy module directory → `/app/module-<name>/`.
- Copy shared `module_router.py` → `/app/mcp-servers/`.
- Expose the module's port.
- CMD: `python /app/module-<name>/server.py`.

Key differences per module:
- `module-coding` — also installs `git`, `nodejs`, `npm`, `chromium`, mermaid-cli globally.
- `module-docker` — installs Docker CLI from `get.docker.com`.
- `module-filesearch`, `module-web`, `module-archimate`, `module-registry` — minimal Python-only.

## Background-agents

### `background-agents/packages/local-control-plane/Dockerfile`

Base: `node:22-bookworm-slim` (glibc needed for `better-sqlite3`).

Installs `python3, make, g++` (native module build).

`npm ci` (respects lockfile). Copies workspace package.json files for all packages. Copies `packages/shared/` + `packages/local-control-plane/`. Runs `npm run build --workspace=packages/shared`.

`mkdir /data`. `ENV DATA_DIR=/data`. Expose 8787.

CMD: `npx tsx packages/local-control-plane/src/index.ts`.

### `background-agents/packages/local-sandbox-manager/Dockerfile`

Base: `python:3.12-slim-bookworm`. Installs Docker CLI from official repo (GPG-verified). Pip: `fastapi, uvicorn, httpx, pydantic, PyJWT`.

Copies `src/` → `./src/`. `mkdir /data/snapshots`. Expose 8000.

CMD: `uvicorn src.main:app --host 0.0.0.0 --port 8000`.

### `background-agents/packages/local-sandbox-manager/Dockerfile.sandbox`

The `open-inspect-sandbox:latest` image. See `06-sandbox/sandbox-image.md` — ~145 lines, includes Python 3.12, Node.js 22, pnpm, bun, OpenCode CLI 1.2.22, Playwright with Chromium, uv, git, gh CLI. Non-root user `sandbox (uid 1000)`.

## Build chain

```
Backend:       Dockerfile            → druppie-backend, druppie-backend-dev
Frontend:      frontend/Dockerfile*  → druppie-frontend, druppie-frontend-dev
Init:          Dockerfile.init       → druppie-init
Reset:         Dockerfile.reset      → reset-hard, nuke
Cache scan:    Dockerfile.cache-scanner → cache-scanner
MCPs:          druppie/mcp-servers/module-*/Dockerfile → module-coding, etc.
Sandbox CP:    local-control-plane/Dockerfile → sandbox-control-plane
Sandbox Mgr:   local-sandbox-manager/Dockerfile → sandbox-manager
Sandbox img:   Dockerfile.sandbox    → open-inspect-sandbox:latest
```

All builds use the repo root as context (unless overridden in compose), so any Dockerfile can COPY from anywhere in the tree.

## Image size rough estimates

| Image | Size |
|-------|------|
| druppie-backend | ~1.2 GB (Chromium + mermaid-cli) |
| druppie-frontend | ~20 MB (nginx + dist) |
| druppie-frontend-dev | ~600 MB (node + node_modules) |
| module-coding | ~1.2 GB (same as backend) |
| module-docker | ~250 MB (Docker CLI) |
| module-{other} | ~150 MB (Python only) |
| sandbox-control-plane | ~400 MB (Node + workspace) |
| sandbox-manager | ~200 MB (Python + Docker CLI) |
| open-inspect-sandbox | ~3.5 GB (everything) |
