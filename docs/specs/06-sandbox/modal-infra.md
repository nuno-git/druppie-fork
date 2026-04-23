# Modal Infra

Path: `background-agents/packages/modal-infra/`. Stack: Python 3.12, Modal Labs, Pydantic, httpx, websockets.

Used only in production (where the CF Workers control plane is active). Druppie's local dev path uses `local-sandbox-manager` instead.

## App definition

`src/app.py`:
```python
import modal
app = modal.App("open-inspect")

function_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi", "httpx", "websockets", "pydantic", "PyJWT"
)

secrets = [
    modal.Secret.from_name("llm-api-keys"),
    modal.Secret.from_name("github-app"),
    modal.Secret.from_name("internal-api"),
]
```

## Deployment

```bash
modal deploy deploy.py
```

`deploy.py` imports `src/__init__.py` which imports every module, registering `@app.function`s. The CLAUDE.md for `background-agents/` says **never deploy `src/app.py` directly** — it only defines the app; functions are registered via the package import.

## Key functions (`src/functions.py`)

Decorated with `@app.function(secrets=secrets, image=function_image, ...)`:

- `create_sandbox(session_id, repo_owner, repo_name, control_plane_url, sandbox_auth_token, ...)` — creates a Modal Sandbox, returns `{sandbox_id, status, created_at}`.
- `warm_sandbox(repo_owner, repo_name, control_plane_url)` — pre-warms for faster startup (clones repo ahead of time).
- `get_latest_snapshot(repo_owner, repo_name)` — returns snapshot metadata.
- `list_snapshots(repo_owner, repo_name, limit)` — snapshot history.
- `register_repository(repo_owner, repo_name, default_branch, setup_commands, build_commands)` — registers a repo for scheduled image builds.

## Web endpoints

Exposed via Modal's `@fastapi_endpoint`:
```
https://{workspace}--open-inspect-api-create-sandbox.modal.run
https://{workspace}--open-inspect-api-health.modal.run
https://{workspace}--open-inspect-web-api.modal.run
```

These are what the CF Workers control plane calls to spawn sandboxes.

## Sandbox lifecycle

`src/sandbox/manager.py:SandboxManager`:

```
PENDING → SPAWNING → CONNECTING → WARMING → SYNCING → READY
       → RUNNING → [SNAPSHOTTING] → STOPPED or FAILED
```

Transitions driven by:
- Sandbox entrypoint (`src/sandbox/entrypoint.py`) reports status back over WebSocket.
- Control plane decisions (`lifecycle/decisions.ts`) — when to snapshot, warm, restore.

## Image building

`src/images/base.py` — constructs the sandbox image via Modal's Python API. Include a `CACHE_BUSTER` string to force rebuild when infrastructure changes (e.g. `"v24-add-playwright"`).

Scheduled image builds: `src/scheduler/image_builder.py` runs on cron, rebuilds images for registered repos so warm-starts are always current with the latest dependencies.

## Bridge

`src/sandbox/bridge.py` (~77KB) — WebSocket bridge inside the sandbox, tunnels:
- LLM requests from OpenCode agent → control plane LLM proxy.
- Tool call events → control plane.
- Status updates → control plane.

This is the code that runs inside the Modal sandbox — the sandbox-side client for the control plane's WebSocket server.

## GitHub App tokens

`src/auth/github_app.py` generates installation tokens on demand for git operations. Same shared GitHub App config as Druppie's `update_core_builder` uses (see `05-agents/definitions/update_core_builder.md`).

## Registry

`src/registry/store.py` persists snapshot metadata to a Modal Volume. Keyed by `{repo_owner}/{repo_name}` — latest snapshot and history.

## Why Modal

- Zero-op autoscaling: spawn as many sandboxes as needed.
- Isolated per-invocation environments.
- Python-native SDK (matches the sandbox-side language).
- GPU support if needed for future agents.

## When Druppie will use this

When Druppie is deployed behind a public domain with the CF Workers control plane, the Modal path activates. For now, `docker compose` + `local-sandbox-manager` is the only path exercised.
