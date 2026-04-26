# Local Sandbox Manager

Path: `background-agents/packages/local-sandbox-manager/`. Stack: Python 3.12, FastAPI, Uvicorn, Docker CLI (Kata optional).

Port: **8000** on `druppie-sandbox-network` only.

## Responsibilities

Spawns, stops, snapshots, and restores sandbox containers. Called by the local control plane — not by Druppie directly.

## Key files

```
src/
├── main.py                 FastAPI app
├── docker_manager.py       container lifecycle (247 lines)
├── config.py               env-driven settings
├── auth.py                 HMAC Bearer token check
├── cache_inspector.py      dep cache analysis
└── snapshot_store.py       snapshot metadata persistence
```

## API surface

All endpoints require `Authorization: Bearer <MODAL_API_SECRET>` HMAC.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/create-sandbox` | Create container, return `{sandbox_id, modal_object_id, status, created_at}` |
| POST | `/api/stop-sandbox` | Stop + remove container |
| POST | `/api/snapshot-sandbox` | `docker commit` → image; persist metadata |
| POST | `/api/restore-sandbox` | `docker run` from snapshot image |

Responses wrapped: `{success: bool, data: {...} | error: string}`.

## `docker_manager.create_sandbox()`

```python
docker run --rm \
  --name {sandbox_id} \
  --network druppie-sandbox-network \
  --security-opt=no-new-privileges \
  --cap-drop=ALL --cap-add=NET_RAW \
  --memory 4g --cpus 2 --pids-limit 8192 \
  --tmpfs /tmp:size=2g \
  -v druppie_sandbox_dep_cache:/cache \
  -e SESSION_CONFIG='{...}' \
  -e CONTROL_PLANE_URL='http://sandbox-control-plane:8787' \
  -e SANDBOX_AUTH_TOKEN='{random}' \
  open-inspect-sandbox:latest
```

Security:
- `no-new-privileges` — blocks setuid/setgid inside.
- All capabilities dropped except `NET_RAW` (for curl/HTTP in sandbox workflows).
- AppArmor + default seccomp (Docker built-ins).
- Non-root user `sandbox` (uid 1000) inside the image.
- Memory/CPU/PID limits enforced.
- `/tmp` as tmpfs auto-wiped.

Resource limits:
- `DOCKER_MEMORY_LIMIT=4g` (overridable via env).
- `DOCKER_CPU_LIMIT=2`.
- `DOCKER_PIDS_LIMIT=8192` (prevents fork bombs).

## Snapshotting

`snapshot_sandbox(sandbox_id, reason, repo_owner, repo_name)`:
1. `docker commit {container} {image_name}` — creates a local image.
2. Persist metadata `{image_id, sandbox_id, session_id, reason, repo, created_at}` to JSON registry (`SNAPSHOT_DIR=/data/snapshots`).
3. Return `{image_id, sandbox_id, session_id, reason}`.

`restore_from_snapshot(snapshot_image_id, sandbox_id?, …)`:
1. Pick image by metadata.
2. Spawn a new container from it (same security hardening).
3. Return sandbox_id + status.

Snapshots keep workspace state across sandbox sessions — useful for incremental coding. Not used by Druppie's current flow (each sandbox is fresh), but the infrastructure is in place.

## `config.py`

Env-driven:
- `SANDBOX_RUNTIME=docker|kata` (kata for Linux+KVM).
- `SANDBOX_IMAGE=open-inspect-sandbox:latest`.
- `SANDBOX_MEMORY_LIMIT`, `SANDBOX_CPU_LIMIT`, `SANDBOX_PIDS_LIMIT`.
- `DOCKER_NETWORK=druppie-sandbox-network`.
- `SANDBOX_CACHE_VOLUME=druppie_sandbox_dep_cache`.
- `SNAPSHOT_DIR=/data/snapshots`.
- `DEFAULT_SANDBOX_TIMEOUT_SECONDS=7200` (2h absolute ceiling).
- `MODAL_API_SECRET` (HMAC for incoming API calls).
- `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_INSTALLATION_ID` for git ops.

## Kata runtime

Enable by `SANDBOX_RUNTIME=kata` (requires host KVM + containerd). Spawns sandboxes as VMs instead of containers — strong isolation but higher overhead. Not the default.

## Cache inspector

`cache_inspector.py` analyses `druppie_sandbox_dep_cache` and exposes:
- List of cached packages per manager (npm, pnpm, bun, uv, pip).
- Size per package.
- Used by Druppie's `/api/cache/packages` to render the CachedDependencies page.

## Dependency on Docker socket

The manager runs with `/var/run/docker.sock` mounted read-write. This is root-equivalent on the host — only deploy this service in trusted environments.
