# Sandbox Image

Image: `open-inspect-sandbox:latest`. Built from `background-agents/packages/local-sandbox-manager/Dockerfile.sandbox` (145 lines).

## Base

`python:3.12-slim-bookworm` (Debian Bookworm + Python 3.12).

## Installed packages

### System
- `git`, `curl`, `build-essential`, `jq`, `unzip`, `openssh-client`.
- Playwright deps: `libatk1.0-0, libcups2, libdrm2, libxkb-common0, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libgbm1, libasound2, libpango-1.0-0, libcairo2, libnss3, libnspr4`.
- Chromium browser (pre-installed so Playwright doesn't have to pull it at runtime).

### Node.js
- Node.js 22 LTS via nodesource.
- Global npm packages: `pnpm`, `bun` (from bun.sh installer).
- Global: `opencode-ai@1.2.22`, `@opencode-ai/plugin@1.2.22`, `zod`.

### Python
- `uv` (package manager).
- `httpx`, `websockets`, `playwright`, `pydantic`, `PyJWT`.

### GitHub CLI
- Official `gh` via apt.

### Playwright
- `playwright install chromium --with-deps`.

### OpenCode CLI
- The TypeScript-based coding agent (v1.2.22). The sandbox entrypoint runs OpenCode with a prompt file.

## Directories

- `/workspace` — the cloned repo (primary working tree).
- `/app/plugins` — OpenCode plugins.
- `/tmp/opencode` — scratch.
- Cache dirs mounted from `druppie_sandbox_dep_cache`:
  - `/cache/npm`, `/cache/pnpm`, `/cache/bun`, `/cache/uv`, `/cache/pip`.
- Relocated browsers: `/opt/playwright-browsers`.
- Relocated package stores: `/home/sandbox/.bun`, `/home/sandbox/.local/share/pnpm`.

## Supply chain hardening

Copied into the image:
- `pip.conf` — HTTPS-only pypi, checksums required.
- `.npmrc` / `.pnpmrc` per-user — HTTPS-only registries.

Goal: even if a package tried to install via HTTP or an unverified mirror, it'd fail.

## Non-root user

```dockerfile
RUN groupadd sandbox --gid 1000 && \
    useradd sandbox --uid 1000 --gid 1000 --home /home/sandbox --shell /bin/bash
USER sandbox
```

Git config:
```
git config --global user.name "Sandbox Agent"
git config --global user.email sandbox@druppie.local
```

## Entrypoint

Copied at image build time:
```
packages/modal-infra/src/sandbox/  →  /app/sandbox/
```

At runtime the container runs `python /app/sandbox/entrypoint.py`, which:
1. Reads `SESSION_CONFIG` env var (JSON).
2. Clones the repo using the provided GitHub App token.
3. Connects to control plane WebSocket.
4. Launches OpenCode with the task prompt.
5. Streams events back over WebSocket.
6. On completion: commits + pushes, emits `completed` event, exits.

## Cache volume strategy

`druppie_sandbox_dep_cache` is shared across ALL sandboxes for all projects. First install of a package is slow; subsequent installs are cache-hits.

Risk: a package poisoned in cache affects future builds. Mitigation: `cache-scanner` service runs OSV vulnerability scans on the cache contents. `docker compose --profile scan-cache run --rm cache-scanner` produces a report to `cache_scan_results` volume.

Nuclear option: `docker compose --profile reset-cache run --rm reset-cache` wipes the cache volume.

## Image size

~3.5 GB. Large because of Chromium + Playwright + Node.js + all npm globals. Trade-off: instant coding-agent startup vs disk space.

## Build command

```bash
docker compose --profile infra up -d sandbox-image-builder
```

This runs to completion (not a long-running service) — it builds the image then exits. Subsequent sandbox spawns use the pre-built image.

On image code changes (`Dockerfile.sandbox` or anything it COPYs), rebuild:
```bash
docker compose --profile infra up -d --build sandbox-image-builder
```
