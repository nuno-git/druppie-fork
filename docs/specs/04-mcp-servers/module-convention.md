# Module Convention

Authoritative source: `druppie/skills/module-convention/SKILL.md`. This doc summarises and refers to code.

## Directory structure

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml                   # identity + versions list
├── Dockerfile
├── requirements.txt              # shared across versions
├── server.py                     # boilerplate — calls module_router.run_module()
├── db.py                         # optional; only if stateful
├── auth.py                       # optional; only if validates JWT
└── v1/
    ├── __init__.py
    ├── module.py                 # one async method per MCP tool
    ├── tools.py                  # FastMCP @mcp.tool definitions
    ├── schema/                   # optional: SQL migrations
    └── tests/                    # optional: per-version pytest
```

For a breaking change, add `v2/` alongside `v1/` — both can be mounted simultaneously by `server.py`.

## Naming

| Thing | Pattern | Example |
|-------|---------|---------|
| Directory | `module-<slug>` | `module-ocr` |
| Module ID (inside `MODULE.yaml`) | lowercase, hyphens OK | `ocr`, `document-classifier` |
| Version dir | `v<major>` | `v1` |
| Container | `druppie-module-<slug>` | `druppie-module-ocr` |
| Docker service | `module-<slug>` | `module-ocr` |
| Port | 9010–9099 | `9015` |

## MODULE.yaml

```yaml
id: <module-id>
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

Read by `module_router.create_module_app()` and exposed via `/health` for discovery. `registry` module calls this to populate `list_modules`.

## `server.py`

Boilerplate — every module's `server.py` is essentially:

```python
from druppie.mcp_servers.module_router import run_module

if __name__ == "__main__":
    run_module(module_name="<slug>", default_port=<port>)
```

## `v1/module.py`

Business logic. Each public async method is the implementation of one MCP tool.

```python
class OcrModule:
    def __init__(self, data_dir: str = "/data"):
        self.data_dir = Path(data_dir)

    async def extract_text(self, path: str, session_id: UUID, user_id: UUID) -> dict:
        # do work
        # raise on failure; don't return error dicts
        return {"text": "...", "_meta": {"module_id": "ocr", "module_version": "1.0.0"}}
```

Rules:
- Raise exceptions on failure (not `{"error": ...}`).
- Accept standard injected args: `user_id`, `project_id`, `session_id`, `app_id`.
- Return dicts; include `_meta: {module_id, module_version, resource_metrics?}`.

## `v1/tools.py`

Thin wrapper around module.py. Single source of truth for the tool contract.

```python
from fastmcp import FastMCP
from .module import OcrModule

MODULE_ID = "ocr"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "OCR v1",
    version=MODULE_VERSION,
    instructions="Optical character recognition tools."
)
module = OcrModule()

@mcp.tool(
    name="extract_text",
    description="Extract text from an image via Tesseract.",
    meta={"module_id": MODULE_ID, "module_version": MODULE_VERSION, "resource_metrics": {"pages": 1}},
)
async def extract_text(path: str, session_id: UUID, user_id: UUID) -> dict:
    return await module.extract_text(path=path, session_id=session_id, user_id=user_id)
```

- Business args come first (path).
- Standard args next (`session_id`, `user_id` — injected by Druppie at call time).
- `meta` field carries module identity + approximate resource cost.

## Standard arguments

| Arg | Source | When present |
|-----|--------|--------------|
| `user_id` | injected by Druppie from Keycloak token | always (agents + apps) |
| `session_id` | injected by Druppie from context | agents; null for apps |
| `project_id` | injected by Druppie from context | when project is in scope |
| `app_id` | env var inside the sandbox | apps; null for agents |

## Module type

`type` field in `druppie/core/mcp_config.yaml`:

- `core` — agents only (coding, docker, etc.)
- `module` — apps only (via SDK)
- `both` — available to both agent flows and deployed user apps (e.g. OCR)

Druppie filters agent tool lists by type when building the registry for an agent.

## Health endpoints

Every module exposes:
- `GET /health` — aggregate health across all active versions. Returns `{module_id, latest_version, active_versions, status: "ok"}`.
- `GET /v{N}/health` — per-version health.
- `GET /v{N}/mcp` — FastMCP JSON-RPC.
- `GET /mcp` — alias to latest version.

## Adding a new module (checklist)

1. Create `druppie/mcp-servers/module-<name>/` with the files above.
2. Add a service to `docker-compose.yml` with the module's port.
3. Add an entry in `druppie/core/mcp_config.yaml` with `url`, `type`, `inject` rules, `tools` list with approval defaults.
4. Optionally grant existing agents access by editing their `mcps:` list.
5. Restart stack — `ToolRegistry` picks up the new tools at startup.

## Testing

Per-version tests in `v1/tests/` — pytest, fixtures for DB if needed. Run from within the module container or via the module's `requirements-dev.txt`.
