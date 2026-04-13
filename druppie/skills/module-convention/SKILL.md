---
name: module-convention
description: Druppie module convention for creating new MCP modules — directory structure, file templates, naming, MODULE.yaml, server.py routing, tools.py contract, Dockerfile, docker-compose service, and mcp_config.yaml entry
---
# Druppie Module Convention

This skill contains the complete convention and templates for creating new Druppie MCP modules.
For the full specification see `docs/module-specification.md`.

---

## 1. Module Definition

A Druppie module is a containerized MCP server that:
- Exposes tools via MCP protocol (JSON-RPC over HTTP)
- Has a `MODULE.yaml` manifest
- Follows versioned directory pattern: `server.py` (router) + `vN/module.py` (business logic)
- Manages own data storage independently (own database or stateless)
- Supports multiple major versions via path routing (`/v1/mcp`, `/v2/mcp`)

### What a Module Is NOT
- Not a Python library imported into applications
- Not a free-form microservice (must follow MCP tool protocol)
- Not a pipeline/orchestrator — if it mainly calls other modules, it belongs in the application layer
- Not a thin wrapper around a single utility function — use a builtin tool instead

---

## 2. Directory Structure

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml              # Identity + version listing
├── Dockerfile               # One container serves all versions
├── requirements.txt         # Combined dependencies
├── server.py                # Routes /v1/mcp, /v2/mcp, /mcp → latest, /health
├── db.py                    # Shared DB connection (only if stateful)
├── auth.py                  # Shared Keycloak JWT validation
├── v1/
│   ├── __init__.py
│   ├── module.py            # v1 public API: one method per MCP tool
│   ├── tools.py             # v1 FastMCP tool definitions (single source of truth)
│   ├── schema/              # SQL migrations (only if stateful)
│   │   ├── 001_initial.sql
│   │   └── current.sql
│   └── tests/
│       └── test_module.py
└── tests/
    └── test_routing.py      # Cross-version routing tests
```

> **Stateless modules** (e.g., wrapping an external API) omit `db.py`, `auth.py`, and `schema/` directories.

---

## 3. Naming Convention

| Item | Pattern | Example |
|------|---------|---------|
| Directory | `module-<name>` | `module-ocr` |
| Module ID | `<name>` (lowercase, hyphens OK) | `ocr`, `document-classifier` |
| Version directory | `v<major>` | `v1`, `v2` |
| Container name | `druppie-module-<name>` | `druppie-module-ocr` |
| Docker Compose service | `module-<name>` | `module-ocr` |
| Port | 9010-9099 (9001-9009 reserved for core) | `9010` |
| DB container (if needed) | `druppie-module-<name>-db` | `druppie-module-ocr-db` |
| DB name (if needed) | `module_<name>` | `module_ocr` |

---

## 4. MODULE.yaml Template

Minimal — only 3 fields. Everything else is defined in code via FastMCP.

```yaml
id: <module-id>                    # Unique module identifier
latest_version: "1.0.0"           # Version served at /mcp
versions:
  - "1.0.0"                       # Served at /v1/mcp
```

---

## 5. Module Code Contract

### vN/module.py — Business Logic

Entry point for the version's business logic. One public async method per MCP tool.
MUST NOT depend on FastMCP, Starlette, or HTTP frameworks.

```python
"""<Module Name> Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imported by v1/tools.py for MCP exposure.
"""

import logging
from typing import Any

logger = logging.getLogger("<module-id>-mcp.v1")


class <ModuleName>Module:
    """v1 business logic for <description>."""

    def __init__(self, config_param: str = "default"):
        self.config_param = config_param

    async def tool_name(
        self,
        required_param: str,
        optional_param: str = "default",
        user_id: str = "",
        project_id: str = "",
        session_id: str = "",
        app_id: str = "",
    ) -> dict[str, Any]:
        """Execute tool operation."""
        result = self._internal_processing(required_param)
        return {
            "field1": result["value"],
            "field2": result["score"],
        }
```

**Rules:**
- One public async method per MCP tool
- Method names match tool names in `vN/tools.py`
- Raise exceptions on failure (don't return error dicts)
- No `SELECT *` — always select explicit columns

### vN/tools.py — MCP Tool Definitions

Thin wrapper around module.py methods as MCP tools. Single source of truth for tool contract.

```python
"""<Module Name> v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema → @mcp.tool()
- Version, resource metrics → @mcp.tool(meta={...})
- Agent guidance → FastMCP(instructions=...)
"""

import os
import time
from fastmcp import FastMCP
from .module import <ModuleName>Module

MODULE_ID = "<module-id>"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "<Module Name> v1",
    version=MODULE_VERSION,
    instructions="""<Description of what this module does and when to use it.>

Use when:
- <scenario 1>
- <scenario 2>

Don't use when:
- <scenario where this module is not appropriate>
""",
)

module = <ModuleName>Module(
    config_param=os.getenv("CONFIG_PARAM", "default"),
)


@mcp.tool(
    name="tool_name",
    description="Tool description — this is what agents and SDK users see.",
    meta={
        "module_id": MODULE_ID,
        "version": MODULE_VERSION,
        "resource_metrics": {
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def tool_name(
    required_param: str,
    optional_param: str = "default",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.tool_name(
        required_param=required_param,
        optional_param=optional_param,
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": MODULE_ID,
            "module_version": MODULE_VERSION,
            "usage": {
                "cost_cents": 0.0,
                "resources": {"processing_ms": elapsed_ms},
            },
        },
    }
```

**Two kinds of arguments:**
- **Business args** (from caller): `image_url`, `language`, etc.
- **Standard args** (injected by core): `user_id`, `project_id`, `session_id`, `app_id`

### server.py — Root Router

Routes requests to the correct version. Provides `/health` endpoint.

```python
"""<Module Name> MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /mcp    → latest version
"""

import logging
import os
from pathlib import Path

import yaml
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("<module-id>-mcp")

MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

from v1.tools import mcp as v1_mcp

version_apps = {
    "1": v1_mcp.http_app(),
}


async def health(request):
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "latest_version": latest_version,
        "active_versions": manifest["versions"],
    })


async def version_health(request):
    major = request.path_params["major"]
    if major not in version_apps:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "version": f"v{major}",
    })


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v{major}/health", version_health, methods=["GET"]),
]
for major, app in version_apps.items():
    routes.append(Mount(f"/v{major}", app=app))
routes.append(Mount("/", app=version_apps[major_latest]))

app = Starlette(routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```

**Routing:**
| Path | Routes to |
|------|-----------|
| `/v1/mcp` | `v1/tools.py` |
| `/v1/health` | v1 health check |
| `/mcp` | Latest version |
| `/health` | Aggregate health |

---

## 6. Dockerfile Template

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MCP_PORT=9010

EXPOSE 9010

HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=30s \
    CMD curl -f http://localhost:9010/health || exit 1

CMD ["python", "server.py"]
```

---

## 7. Docker Compose Service Template

### Stateful module (with database):

```yaml
  module-<name>-db:
    image: postgres:16-alpine
    container_name: druppie-module-<name>-db
    profiles: [infra, dev, prod]
    environment:
      POSTGRES_DB: module_<name>
      POSTGRES_USER: module_<name>
      POSTGRES_PASSWORD: ${MODULE_<NAME>_DB_PASSWORD:-module_<name>_dev}
    volumes:
      - module-<name>-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U module_<name>"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - druppie-new-network

  module-<name>:
    build:
      context: ./druppie/mcp-servers/module-<name>
      dockerfile: Dockerfile
    container_name: druppie-module-<name>
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9010"
      MODULE_DB_URL: postgresql://module_<name>:${MODULE_<NAME>_DB_PASSWORD:-module_<name>_dev}@module-<name>-db:5432/module_<name>
    ports:
      - "${MODULE_<NAME>_PORT:-9010}:9010"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9010/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    networks:
      - druppie-new-network
    depends_on:
      module-<name>-db:
        condition: service_healthy
```

### Stateless module (no database):

```yaml
  module-<name>:
    build:
      context: ./druppie/mcp-servers/module-<name>
      dockerfile: Dockerfile
    container_name: druppie-module-<name>
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9010"
    ports:
      - "${MODULE_<NAME>_PORT:-9010}:9010"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9010/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    networks:
      - druppie-new-network
```

---

## 8. mcp_config.yaml Entry Template

```yaml
  <module-id>:
    url: ${MCP_<MODULE>_URL:-http://module-<name>:9010}
    type: module                               # core | module | both
    description: "Module description"
    inject:
      session_id:
        from: session.id
        hidden: true
      user_id:
        from: session.user_id
        hidden: true
      project_id:
        from: project.id
        hidden: true
    tools:
      - name: tool_name
        description: "Tool description"
        requires_approval: false
        parameters:
          type: object
          properties:
            required_param:
              type: string
              description: "Description"
          required: [required_param]
```

**MCP types:**
- `core` = agents only (coding, docker, etc.)
- `module` = apps only (via SDK)
- `both` = agents + apps (OCR, classifier, etc.)

**How to decide:**
- Only makes sense during agent sessions → `core`
- Only used by generated apps → `module`
- Used by both agents and apps → `both`

---

## 9. Standard Module Arguments

Every `module` or `both` type MCP call includes:

| Argument | Type | Core (agent) | App (SDK) |
|----------|------|-------------|-----------|
| `user_id` | UUID | Injected by core | From Keycloak token |
| `project_id` | UUID/null | Injected, null for general_chat | From env var |
| `session_id` | UUID/null | Injected | Must be null |
| `app_id` | UUID/null | Must be null | From env var |

---

## 10. Database Rules (Stateful Modules Only)

- One database per module: `module_<name>`
- Shared across all major versions
- **Additive-only changes**: add columns (with defaults), add tables, add indexes
- **Never destructive**: no DROP, RENAME, or ALTER TYPE
- Every new column has a DEFAULT
- No `SELECT *` — explicit columns only

---

## 11. Checklist: Creating a New Module

1. Decide: stateful or stateless?
2. Check registry for overlap: `registry_search_modules(<capability>)`
3. Pick next available port in 9010-9099 range (check `registry_list_modules()`)
4. Create directory: `druppie/mcp-servers/module-<name>/`
5. Create files: `MODULE.yaml`, `server.py`, `requirements.txt`, `Dockerfile`
6. Create `v1/`: `__init__.py`, `module.py`, `tools.py`
7. If stateful: add `db.py`, `v1/schema/001_initial.sql`, `v1/schema/current.sql`
8. Add docker-compose service to `docker-compose.yml`
9. Add entry to `druppie/core/mcp_config.yaml`
10. Test: `/health` returns healthy, `/v1/mcp` responds to MCP calls
