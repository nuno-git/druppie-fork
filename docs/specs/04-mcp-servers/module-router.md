# Module Router

`druppie/mcp-servers/module_router.py` — shared factory used by every MCP server's `server.py`. Removes boilerplate.

## Public API

```python
def create_module_app(
    module_name: str,
    default_port: int,
    module_dir: Path,
) -> Starlette:
    """Build a Starlette app mounting FastMCP versions + health endpoints."""

def run_module(
    module_name: str,
    default_port: int,
) -> None:
    """Convenience for __main__ blocks; reads MCP_PORT env, runs uvicorn."""
```

## Routing layout

For a module with `latest_version: "1.0.0"` and `versions: ["1.0.0"]`:

```
GET  /health              → aggregate health JSON
GET  /v1/health           → v1 health JSON
*    /v1/mcp              → FastMCP JSON-RPC (v1/tools.py)
*    /mcp                 → alias to latest (currently v1)
```

Aggregate `/health` response:
```json
{
  "module_id": "coding",
  "latest_version": "1.0.0",
  "active_versions": ["1.0.0"],
  "status": "ok"
}
```

## How it works

1. `create_module_app()` reads `MODULE.yaml` in `module_dir`.
2. For each version listed in `versions`:
   - Imports `v{N}.tools` (which constructs a `FastMCP` instance and decorates tools).
   - Builds the FastMCP HTTP ASGI app.
   - Mounts it at `/v{N}/mcp`.
   - Mounts a tiny health app at `/v{N}/health`.
3. Aliases `/mcp` to the latest version.
4. Wires a unified aggregate `/health`.
5. Manages FastMCP lifespan for the latest version (so pool connections, DB handles etc. bind at startup).

## Port resolution

`run_module` reads `MCP_PORT` from env. If unset, uses the `default_port` argument. Uvicorn binds to `0.0.0.0:PORT` so the container is reachable from within the `druppie-new-network`.

## Example `server.py` (complete)

```python
# druppie/mcp-servers/module-coding/server.py
from pathlib import Path
from druppie.mcp_servers.module_router import run_module

if __name__ == "__main__":
    run_module(module_name="coding", default_port=9001)
```

## What the router does NOT do

- Does not validate JWTs. If a module needs per-user auth, it adds its own `auth.py` and wraps tools as required.
- Does not inject standard args. That happens in the Druppie backend's `ToolExecutor` before the HTTP call reaches the module.
- Does not authorize approvals. That's enforced by Druppie before tool dispatch, not by the module.
- Does not log structurally. Modules that need structured logs wire their own.
