# Druppie Module Specification — Technical Contract

> **Status**: Specification (ready for team review)
> **Date**: 2026-03-10 (versioning redesign), original 2026-02-24
> **Prerequisite**: Read `docs/modules.md` for the design research and approach selection
> **Approach**: SDK + MCP Hybrid with direct module access (Approach C from design doc, without shared DB or gateway proxy from E)

---

## Table of Contents

1. [Module Definition](#1-module-definition)
2. [File Structure & Contract](#2-file-structure--contract)
3. [MODULE.yaml & MCP as Source of Truth](#3-moduleyaml--mcp-as-source-of-truth)
4. [Module Code Contract](#4-module-code-contract)
5. [Version System](#5-version-system)
6. [Database & Storage](#6-database--storage)
7. [Module Registry](#7-module-registry)
8. [Druppie SDK](#8-druppie-sdk)
9. [Backend API for Modules](#9-backend-api-for-modules)
10. [Module Lifecycle](#10-module-lifecycle)
11. [Complete Example: OCR Module v1.0→v2.0](#11-complete-example-ocr-module)

---

## 1. Module Definition

A **Druppie module** is a containerized MCP server that:

1. Exposes tools via the MCP protocol (JSON-RPC over HTTP)
2. Has a `MODULE.yaml` manifest declaring its identity and active versions
3. Follows the versioned directory pattern: `server.py` (root router) + `vN/module.py` (business logic per major version)
4. Manages its own data storage independently (own database or stateless). Receives Druppie context (user, session, project) through injected MCP parameters — never by querying Druppie's database directly
5. Is callable by both Druppie agents (during build-time) and generated applications (at runtime via SDK)
6. Supports multiple major versions running simultaneously via path-based routing (`/v1/mcp`, `/v2/mcp`)

### What a Module Is NOT

- Not a Python library imported into applications (that's Approach B — rejected)
- Not a free-form microservice (must follow the MCP tool protocol)
- Not a standalone application (modules are building blocks, not end products)
- Not a pipeline or orchestrator — if it mainly calls other modules, it belongs in the application layer or as a skill
- Not a thin wrapper around a single utility function — if it has no own state or heavy dependencies, use a builtin tool instead

---

## 2. File Structure & Contract

Every module lives in `druppie/mcp-servers/module-<name>/` with versioned subdirectories per major version:

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml              # Identity + version listing (root-level only)
├── Dockerfile               # One container serves all versions
├── requirements.txt         # Combined dependencies for all versions
├── server.py                # Entrypoint: routes /v1/mcp, /v2/mcp, /mcp → latest
├── db.py                    # Shared DB connection (if module needs a database)
├── auth.py                  # Shared Keycloak JWT validation
├── v1/
│   ├── __init__.py
│   ├── module.py            # v1 public API: one method per MCP tool
│   ├── tools.py             # v1 FastMCP tool definitions (name, description, schema, meta)
│   ├── ...                  # Any internal modules (parsers, pipelines, models, etc.)
│   ├── schema/
│   │   ├── 001_initial.sql  # First migration
│   │   └── current.sql      # Full schema snapshot (for fresh installs)
│   └── tests/
│       └── test_module.py   # v1-specific tests
├── v2/
│   ├── __init__.py
│   ├── module.py            # v2 public API: one method per MCP tool
│   ├── tools.py             # v2 FastMCP tool definitions (name, description, schema, meta)
│   ├── ...                  # Any internal modules
│   ├── schema/
│   │   ├── 001_add_pages_table.sql
│   │   ├── 002_add_source_column.sql
│   │   └── current.sql      # Full schema = v1 final + v2 additions
│   └── tests/
│       └── test_module.py   # v2-specific tests
└── tests/
    └── test_routing.py      # Cross-version routing tests
```

### What Lives Where

| Location | Contains | Shared? |
|----------|----------|---------|
| Root `MODULE.yaml` | Module ID, list of active versions, latest version pointer | N/A — one file |
| Root `server.py` | HTTP entrypoint, path-based routing to version dirs, config loading | Yes — infrastructure only |
| Root `db.py` | Database connection pool to the module's own database (if needed) | Yes — infrastructure only |
| Root `auth.py` | Keycloak JWT validation middleware | Yes — infrastructure only |
| Root `Dockerfile` | Container definition, installs all deps | Yes |
| Root `requirements.txt` | Union of all version dependencies | Yes |
| `vN/module.py` | Public API for this version (one method per tool). Imports from sibling files for complex modules | No — owned by version |
| `vN/tools.py` | FastMCP tool definitions: name, description, input schema, `meta` (version, resource_metrics) — the **single source of truth** for the tool contract | No — owned by version |
| `vN/schema/` | SQL migration files for this version's DB changes | No — owned by version |
| `vN/tests/` | Tests for this version's contract | No — owned by version |
| Root `tests/` | Cross-version tests (routing, coexistence) | N/A |

### Sharing Rule

Infrastructure code lives at the root and is shared across all versions: `server.py` (routing), `db.py` (database connection pool), `auth.py` (JWT validation). **Business logic is never shared** — each version owns its full implementation in `vN/`, even if some code is identical across versions. If a bug exists in shared infrastructure, it is fixed once at the root. If a bug exists in business logic, fix it independently in each version directory.

### Naming Convention

| Item | Pattern | Example |
|------|---------|---------|
| Directory | `module-<name>` | `module-ocr` |
| Module ID | `<name>` (lowercase, hyphens OK) | `ocr`, `document-classifier` |
| Version directory | `v<major>` | `v1`, `v2` |
| Container name | `druppie-module-<name>` | `druppie-module-ocr` |
| Docker Compose service | `module-<name>` | `module-ocr` |
| Port | 9010-9099 (9001-9009 reserved for core MCP servers) | `9010` |
| DB container (if needed) | `druppie-module-<name>-db` | `druppie-module-ocr-db` |
| DB name (if needed) | `module_<name>` | `module_ocr` |

---

## 3. MODULE.yaml & MCP as Source of Truth

### Design Principle: Define Once

Module metadata lives in exactly one place — no duplication between YAML files and code.

- **MODULE.yaml** contains only what the MCP protocol cannot provide: module ID and version routing
- **Everything else** — name, description, tool schemas, agent guidance, resource metrics — is defined in the FastMCP server code (`vN/tools.py`) and discoverable via the MCP protocol (`initialize`, `tools/list`)

### MODULE.yaml

The only YAML file in the module. Minimal — just version routing:

```yaml
id: ocr                                    # Unique module identifier (required)
latest_version: "2.0.0"                   # The version served at /mcp (required)
versions:                                  # All active major versions (required)
  - "1.0.0"                               # Served at /v1/mcp
  - "2.0.0"                               # Served at /v2/mcp
```

That's it. Three fields. Read by `server.py` for routing and by the registry for version tracking.

### What Comes From the MCP Server Instead

Everything else is defined in code via FastMCP and exposed through the MCP protocol:

| What | Where it's defined | How it's discovered |
|------|-------------------|-------------------|
| Server name | `FastMCP("OCR Module v1")` | MCP `initialize` → `serverInfo.name` |
| Server version | `FastMCP(..., version="1.2.0")` | MCP `initialize` → `serverInfo.version` |
| Agent guidance | `FastMCP(..., instructions="...")` | MCP `initialize` → `instructions` |
| Tool name, description, input schema | `@mcp.tool(name=..., description=...)` | MCP `tools/list` |
| Tool version, resource metrics | `@mcp.tool(meta={...})` | MCP `tools/list` → `meta` |
| Approval rules, required roles | `mcp_config.yaml` | Druppie-specific, not in MCP |

---

## 4. Module Code Contract

### vN/module.py — Public API (Per-Version)

`module.py` is the **entry point** to the version's business logic — not necessarily the entire codebase. It exposes one public method per MCP tool, and `tools.py` only imports from `module.py`.

For simple modules, all logic can live in `module.py`. For complex modules (document pipelines, ML models, multiple processing stages), `module.py` imports from sibling files:

```
v1/
├── module.py          # Public API — tools.py imports from here
├── tools.py           # FastMCP definitions
├── parser.py          # Internal: document parsing logic
├── pipeline.py        # Internal: processing pipeline
├── models/
│   └── classifier.py  # Internal: ML model wrapper
├── schema/
└── tests/
```

`module.py` and anything it imports MUST NOT depend on FastMCP, Starlette, or any HTTP framework — so it can be tested independently.

```python
"""<Module Name> Module v1 — Public API.

Entry point for v1 business logic. One public method per MCP tool.
Imported by v1/tools.py for MCP exposure.
Can import from sibling files for complex logic.
"""

import logging
from typing import Any

logger = logging.getLogger("<module-id>-mcp.v1")


class <ModuleName>Module:
    """v1 business logic for <description>.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    """

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

**Rules**:
- One public async method per MCP tool, receiving all arguments (business + standard)
- Method names match tool names in `vN/tools.py`
- Raise exceptions on failure (don't return error dicts — let tools.py handle formatting)
- No `SELECT *` in database queries — always select explicit columns so new columns from other versions don't break this version

### vN/tools.py — MCP Tool Definitions (Per-Version)

Each version directory contains its own `tools.py` that wraps module methods as MCP tools. `tools.py` is a thin layer with two responsibilities:

1. **Pass all arguments** to `module.py` (business args + standard args)
2. **Usage reporting**: measure timing, wrap the result with `_meta`

Every MCP tool receives two kinds of arguments. `tools.py` passes all of them to `module.py` — the module uses what it needs and ignores the rest:

| Type | Examples | Who provides them | Purpose |
|------|----------|-------------------|---------|
| **Business args** | `image_url`, `language` | The caller (agent prompt or app code) | What the tool actually does |
| **Standard args** | `user_id`, `project_id`, `session_id`, `app_id` | Core injects them (agents), SDK passes them (apps) | Governance: who called, from where |

```python
"""<Module Name> v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
This file is the SINGLE SOURCE OF TRUTH for the tool contract:
- Tool name, description, input schema → via @mcp.tool() decorator
- Version, resource metrics → via @mcp.tool(meta={...})
- Agent guidance → via FastMCP(instructions=...)
All discoverable by MCP clients via initialize + tools/list.
"""

import os
import time
from fastmcp import FastMCP
from .module import <ModuleName>Module

MODULE_ID = "<module-id>"
MODULE_VERSION = "1.2.0"

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

### server.py — Root Router

The root `server.py` is the entrypoint. It mounts each version's MCP app at its path and handles routing:

```python
"""<Module Name> MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /v2/mcp → v2/tools.py
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

# Read MODULE.yaml for version info
MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

# Import version-specific MCP apps
from v1.tools import mcp as v1_mcp
from v2.tools import mcp as v2_mcp

version_apps = {
    "1": v1_mcp.http_app(),
    "2": v2_mcp.http_app(),
}


async def health(request):
    """Aggregate health: reports status of all active versions."""
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "latest_version": latest_version,
        "active_versions": manifest["versions"],
    })


async def version_health(request):
    """Per-version health check."""
    major = request.path_params["major"]
    if major not in version_apps:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({
        "status": "healthy",
        "module_id": manifest["id"],
        "version": f"v{major}",
    })


# Build routes: /v1/mcp, /v1/health, /v2/mcp, /v2/health, /mcp → latest
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v{major}/health", version_health, methods=["GET"]),
]
for major, app in version_apps.items():
    routes.append(Mount(f"/v{major}", app=app))

# /mcp → latest version
routes.append(Mount("/", app=version_apps[major_latest]))

app = Starlette(routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```

### Routing Summary

| Request path | Routes to |
|-------------|-----------|
| `/v1/mcp` | `v1/tools.py` |
| `/v1/health` | v1 health check |
| `/v2/mcp` | `v2/tools.py` |
| `/v2/health` | v2 health check |
| `/mcp` | Latest version (from `MODULE.yaml` `latest_version`) |
| `/health` | Aggregate health (all versions) |

### db.py — Shared Database Connection (Optional)

Modules that need a database define the connection at the root level. All versions share the same connection pool and the same database:

```python
"""<Module Name> — Shared Database Connection.

Provides a connection pool to the module's OWN database.
This is NOT Druppie's database — it's a separate PostgreSQL instance
owned by this module (see docker-compose service module-<name>-db).

All versions (v1, v2, ...) share this connection and the same database.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

MODULE_DB_URL = os.getenv("MODULE_DB_URL")

if MODULE_DB_URL:
    engine = create_async_engine(MODULE_DB_URL, pool_size=5, max_overflow=10)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
else:
    engine = None
    SessionLocal = None
```

Version code imports it:

```python
# v1/module.py
from db import SessionLocal

class OCRModule:
    async def extract_text(self, image_url: str, ...) -> dict:
        async with SessionLocal() as session:
            # Query the module's own database
            ...
```

### auth.py — Shared JWT Validation

All versions share the same Keycloak JWT validation logic:

```python
"""<Module Name> — Shared Keycloak JWT Validation.

Validates incoming Keycloak tokens. Modules validate tokens themselves
(no gateway proxy). The token proves user identity; context (project_id,
app_id, session_id) comes via standard MCP tool arguments.
"""

import os
from jose import jwt, JWTError
from jose.backends import RSAKey
import httpx

KEYCLOAK_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

_jwks_cache = None

async def _get_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        async with httpx.AsyncClient() as client:
            response = await client.get(JWKS_URL)
            _jwks_cache = response.json()
    return _jwks_cache

async def validate_token(token: str) -> dict:
    """Validate Keycloak JWT and extract user identity.

    Returns: {"user_id": "uuid", "username": "...", "roles": [...]}
    Raises: JWTError if token is invalid.
    """
    jwks = await _get_jwks()
    payload = jwt.decode(
        token,
        jwks,
        algorithms=["RS256"],
        issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
    )
    return {
        "user_id": payload["sub"],
        "username": payload.get("preferred_username"),
        "roles": payload.get("realm_access", {}).get("roles", []),
    }
```

### Dockerfile Template

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies (customize per module)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all module code (root + version dirs)
COPY . .

ENV MCP_PORT=9010

EXPOSE 9010

HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=30s \
    CMD curl -f http://localhost:9010/health || exit 1

CMD ["python", "server.py"]
```

### Docker Compose Service Template

```yaml
  # Module's own database (only if module needs persistent storage)
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
      CONFIG_PARAM: ${MODULE_<NAME>_CONFIG:-default}
      # Module's own database (not Druppie's):
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

> **Note**: Stateless modules (e.g., a module that wraps an external API) don't need a database container at all — omit the `module-<name>-db` service and the `MODULE_DB_URL` environment variable.

### mcp_config.yaml Entry Template

```yaml
  <module-id>:
    url: ${MCP_<MODULE>_URL:-http://module-<name>:9010}
    type: module                               # "module" = available to agents AND apps via SDK
    description: "Module description from MODULE.yaml"
    inject:                                    # Core-only injection (for agent calls)
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

> **MCP types**: `core` = agents only (coding, docker, etc.), `module` = agents + apps (OCR, classifier, etc.). Apps connect directly to modules via the SDK. See `docs/plans/2026-03-11-auth-governance-design.md` for details.

---

## 5. Version System

### Core Principle

Each major version is an independent, self-contained codebase. No translation between versions, no shared business logic. `v1/` always contains the latest 1.x.y code; `v2/` always contains the latest 2.x.y code. Minor and patch bumps update code in-place within their major version directory.

### Semantic Versioning Rules

Modules use **SemVer 2.0.0** with Druppie-specific interpretations:

| Change Type | Version Bump | What Happens |
|------------|-------------|-------------|
| **MAJOR** | New `vN+1/` directory | Create new version directory, copy from previous, make breaking changes |
| **MINOR** | Update in-place in `vN/` | New optional parameter (with default), new response field, new tool |
| **PATCH** | Update in-place in `vN/` | Bug fix, performance improvement, dependency update |

### What Constitutes a Breaking Change

Based on research from Stripe, Google AIP-180, and Zalando API guidelines:

**Breaking (requires new major version directory)**:
- Removing a tool, parameter, or response field
- Renaming a tool, parameter, or response field
- Changing a field's type (e.g., `string` → `integer`)
- Changing field semantics (e.g., UTC → local time)
- Making an optional input parameter required
- Making a required output field optional/nullable
- Removing an enum value from an input parameter
- Changing a tool's description significantly (breaks LLM callers)

**Non-breaking (minor bump, in-place in `vN/`)**:
- Adding a new tool
- Adding a new optional input parameter (with default)
- Adding a new field to response output
- Adding a new enum value to an input parameter
- Relaxing validation (e.g., increasing max length)

**Internal (patch bump, in-place in `vN/`)**:
- Bug fixes that don't change the API contract
- Performance improvements
- Logging changes
- Dependency updates

### Major Version Bump Procedure

When going from v1 to v2:

1. Create `v2/` directory
2. Copy `v1/` contents as starting point
3. Make breaking changes in `v2/module.py`, `v2/tools.py`
4. Update version and meta in `v2/tools.py` (FastMCP constructor + `@mcp.tool(meta={...})`)
5. Write `v2/schema/` migrations for any DB additions (additive-only)
6. Write `v2/tests/`
7. Update root `MODULE.yaml`: add `"2.0.0"` to `versions`, set `latest_version: "2.0.0"`
8. Update root `server.py` to import and mount `v2/tools.py`
9. `v1/` is untouched — still serves its clients at `/v1/mcp`

### No Transformers

Each version runs its own code independently. There is no translation layer between versions. A v1 client calls `/v1/mcp` and gets a v1 response from `v1/module.py`. A v2 client calls `/v2/mcp` and gets a v2 response from `v2/module.py`.

### No Sunset / End of Life

All versions stay running indefinitely. There is no sunset mechanism, no deprecation dates, no 410 Gone responses. If a version exists in `MODULE.yaml`, it is served.

### Application Version Selection

The SDK selects which major version to call via the path:

```python
# Application calls v1 endpoint
druppie = DruppieClient(
    module_versions={
        "ocr": "v1",              # Calls /v1/mcp
        "classifier": "v2",      # Calls /v2/mcp
    }
)

result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v1/mcp

# Or call latest (default — hits /mcp which routes to latest)
druppie = DruppieClient()
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp
```

---

## 6. Database & Storage

### Design Principle: Module-Owned Storage

Each module manages its own data storage independently. Modules **never** connect to Druppie's PostgreSQL database. Instead:

- **Stateful modules** get their own database container (PostgreSQL, SQLite, or whatever fits)
- **Stateless modules** don't need any database at all
- **Druppie context** (user_id, session_id, project_id) is received through injected MCP parameters, not by querying Druppie's tables
- **Cost tracking** is the caller's responsibility (core or SDK reports to Druppie backend), not the module's

### Why Not Shared DB?

Sharing Druppie's PostgreSQL (even with schema isolation) creates hidden coupling:

| Problem | Impact |
|---------|--------|
| **Schema coupling** | Module does `SELECT * FROM public.sessions` → Druppie renames a column → module breaks |
| **Not portable** | Can't develop, test, or run a module without a copy of Druppie's schema |
| **Not self-contained** | Contradicts the core module principle of independence |
| **Reset fragility** | Druppie's "reset DB" workflow can break modules that read from `public.*` |
| **Permission complexity** | PostgreSQL role/grant management adds operational overhead |

### What Modules Need (and How They Get It)

| Need | How | Example |
|------|-----|---------|
| Know which user called | Injected MCP parameter `user_id` | Already in `mcp_config.yaml` inject rules |
| Know which session | Injected MCP parameter `session_id` | Already in `mcp_config.yaml` inject rules |
| Project context | Passed as tool argument | `project_id` in tool input schema |
| Persistent state | Module's own database | `module-ocr-db` PostgreSQL container |
| Cost tracking | Caller (core/SDK) records usage | SDK reports to Druppie backend after each call |

### Database Rules for Versioned Modules

Since multiple major versions of a module run simultaneously against the module's own database, strict rules apply:

1. **One database per module** — `module_<name>` (e.g., `module_ocr`)
2. **Shared across all major versions of that module** — v1 and v2 read/write the same database
3. **Additive-only changes** — add columns (with defaults), add tables, add indexes
4. **Never destructive** — no `DROP`, `RENAME`, or `ALTER TYPE` while any version uses the affected object
5. **Every new column has a `DEFAULT`** — older version code can INSERT without specifying it
6. **No `SELECT *`** — version code selects explicit columns so new columns don't break it

### Why Additive-Only

Both v1 and v2 run simultaneously against the same module database. If v2 drops a column that v1 uses, v1 breaks. Additive-only guarantees that older versions keep working regardless of what newer versions add.

### Migration Files

Each version directory has a `schema/` folder with numbered SQL migration files:

```
v1/schema/
├── 001_initial.sql                # CREATE TABLE extractions (...)
├── 002_add_output_format.sql      # ALTER TABLE ... ADD COLUMN output_format VARCHAR DEFAULT 'plain'
└── current.sql                    # Full schema snapshot (for fresh installs)
```

```
v2/schema/
├── 001_add_pages_table.sql        # CREATE TABLE extraction_pages (...)
├── 002_add_source_column.sql      # ALTER TABLE ... ADD COLUMN source VARCHAR DEFAULT ''
└── current.sql                    # Full schema = v1 final state + v2 additions
```

### Migration Tracking

A tracking table records which migrations have been applied:

```sql
CREATE TABLE _migrations (
    id SERIAL PRIMARY KEY,
    version_dir VARCHAR NOT NULL,     -- 'v1' or 'v2'
    filename VARCHAR NOT NULL,        -- '001_initial.sql'
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(version_dir, filename)
);
```

### Fresh Install vs. Upgrade

| Scenario | What runs |
|----------|-----------|
| Fresh install | `v1/schema/current.sql` then `v2/schema/current.sql` |
| Upgrade v1 (1.0 → 1.2) | Unapplied `v1/schema/00N_*.sql` files in order |
| Add v2 to existing v1 | All `v2/schema/00N_*.sql` files in order |

Migrations always run in order: all v1 migrations first, then v2 migrations. v2's schema builds on v1's final state.

---

## 7. Module Registry

### Database Tables

File: `druppie/db/models/module_registry.py`

```python
"""Module registry database models.

Tables:
  modules              — Installed module instances (identity + container location)
  module_versions      — Every active major version of a module
  module_tool_schemas  — Cached tool schemas per version (from MCP tools/list)

Design principle: the registry caches what MCP tells us. Module identity
(name, description) comes from the MCP `initialize` response. Tool schemas
come from `tools/list`. The registry stores these for offline discovery
and UI display — the MCP server is always the source of truth.
"""

from uuid import uuid4
from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import Base, utcnow


class Module(Base):
    """An installed Druppie module.

    Only stores operational data: where is it, what version is latest,
    is it active. Display fields (name, description) are cached from
    the MCP `initialize` response and refreshed on registration.
    """
    __tablename__ = "modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(String(100), unique=True, nullable=False)  # matches MODULE.yaml id
    display_name = Column(String(255))           # cached from MCP initialize response
    description = Column(Text)                   # cached from MCP initialize response
    latest_version = Column(String(20), nullable=False)
    container_url = Column(String(500), nullable=False)
    status = Column(String(20), default="active")  # active, disabled
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions = relationship("ModuleVersion", back_populates="module", cascade="all, delete-orphan")


class ModuleVersion(Base):
    """An active major version of a module (e.g., v1 at 1.2.0, v2 at 2.0.0).

    Route path is derived: major_version=1 → /v1/mcp. No need to store it.
    """
    __tablename__ = "module_versions"
    __table_args__ = (UniqueConstraint("module_id", "major_version", name="uq_module_major_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    major_version = Column(Integer, nullable=False)          # 1, 2, etc.
    current_version = Column(String(20), nullable=False)     # "1.2.0", "2.0.0"
    instructions = Column(Text)                              # cached from MCP initialize
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    module = relationship("Module", back_populates="versions")
    tool_schemas = relationship("ModuleToolSchema", back_populates="module_version", cascade="all, delete-orphan")


class ModuleToolSchema(Base):
    """Cached tool schema from MCP tools/list response.

    Stores the input schema and meta (including resource_metrics) as Text.
    Refreshed on module registration. The MCP server is the source of truth —
    this is a cache for discovery UI and offline reference.

    Approval rules and role requirements live in mcp_config.yaml, not here.
    """
    __tablename__ = "module_tool_schemas"
    __table_args__ = (
        UniqueConstraint("module_version_id", "tool_name", name="uq_version_tool"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_version_id = Column(UUID(as_uuid=True), ForeignKey("module_versions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    description = Column(Text)                   # cached from tools/list
    input_schema_json = Column(Text, nullable=False)  # cached from tools/list
    meta_json = Column(Text)                     # cached from tools/list meta (resource_metrics, etc.)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    module_version = relationship("ModuleVersion", back_populates="tool_schemas")
```

### Registry Service

The registry reads `MODULE.yaml` for version info and queries the live MCP server for tool schemas and metadata. It acts as a **cache** — the MCP server is always the source of truth.

```python
# druppie/services/module_registry_service.py

class ModuleRegistryService:
    """Manages module registration, version tracking, and discovery."""

    async def register_module(self, module_path: str) -> Module:
        """Register or refresh a module from its directory.

        1. Parse root MODULE.yaml (id, version list, latest_version)
        2. For each version, call MCP initialize → cache name, description, instructions
        3. For each version, call MCP tools/list → cache tool schemas + meta
        4. Create/update Module, ModuleVersion, ModuleToolSchema records
        """
        ...

    async def refresh_module(self, module_id: str) -> Module:
        """Re-query MCP server and update cached schemas/metadata."""
        ...

    async def get_module(self, module_id: str) -> ModuleDetail:
        """Get module with all versions and tool schemas."""
        ...

    async def list_modules(self) -> list[ModuleSummary]:
        """List all installed modules (Summary pattern)."""
        ...
```

---

## 8. Druppie SDK

The SDK is a lightweight Python package included in every Druppie-generated application. It is an **MCP client** that connects directly to module MCP servers (no gateway proxy). It handles authentication, standard argument injection, usage reporting, version routing, and retries.

> For the full auth, governance, and usage tracking design, see `docs/plans/2026-03-11-auth-governance-design.md`.

### Location

The SDK lives in the Druppie monorepo at `druppie/sdk/`. It is a pip-installable Python package.

```
druppie/sdk/
├── druppie_sdk/
│   ├── __init__.py          # DruppieClient, DruppieAuth
│   ├── client.py            # Main client — MCP client wrapper
│   ├── auth.py              # Keycloak JWT validation + app role checking
│   ├── usage.py             # Usage reporting to Druppie backend
│   ├── health.py            # Standard /health endpoint for generated apps
│   └── py.typed             # PEP 561 marker
├── pyproject.toml
└── README.md
```

### How apps get the SDK

Every Druppie-generated project starts from a **project template** (see [Project Template](#project-template) below) that already has the SDK installed. The builder agent doesn't install it — it just `from druppie_sdk import DruppieClient` in the code it writes.

In Docker (deploy time), the SDK is copied from the Druppie repo and installed:

```dockerfile
COPY druppie/sdk/ /tmp/druppie-sdk/
RUN pip install /tmp/druppie-sdk/
```

### Project Template

Every new Druppie project starts from a template at `druppie/templates/project/`. This is copied into the project's repo at creation time, before the builder agent starts writing code.

```
druppie/templates/project/
├── requirements.txt          # druppie-sdk already listed
├── druppie.config.yaml       # Module connections, app identity (populated at deploy)
├── Dockerfile                # SDK install baked in
└── app/
    └── main.py               # Skeleton with DruppieClient initialized
```

**What the template provides:**
- SDK pre-installed as a dependency — builder agent just imports it
- `druppie.config.yaml` — module URLs and app identity, populated at deploy time
- Standard Dockerfile — SDK install, health endpoint, env vars
- Skeleton `main.py` — `DruppieClient` initialized, ready for the agent to add routes

**What the builder agent does:**
- Writes application code that imports from `druppie_sdk`
- Adds routes, business logic, frontend
- Does NOT need to know how the SDK is installed or configured

> **Python only for now.** The project template and SDK are Python. Non-Python app support may be added later.

### Core Client

```python
# druppie_sdk/client.py

class DruppieClient:
    """MCP client for Druppie-generated applications.

    Connects directly to module MCP servers (no gateway proxy).
    Zero-config: reads DRUPPIE_* environment variables automatically.

    Usage:
        druppie = DruppieClient()
        result = await druppie.modules.call("ocr", "extract_text", {"source": "img.png"})
    """

    def __init__(
        self,
        druppie_url: str | None = None,
        module_versions: dict[str, str] | None = None,
    ):
        # Druppie backend URL (for usage reporting + app role checks)
        self.druppie_url = druppie_url or os.environ.get(
            "DRUPPIE_URL", "http://druppie-backend:8000"
        )
        # App identity (set at deploy time)
        self.app_id = os.environ.get("DRUPPIE_APP_ID")
        self.project_id = os.environ.get("DRUPPIE_PROJECT_ID")
        # Auth token (Keycloak JWT or short-lived sandbox token)
        self._token = os.environ.get("DRUPPIE_MODULE_TOKEN")

        self.module_versions = module_versions or {}
        self.modules = ModuleClient(self)
        self.auth = AppAuth(self)
        self._usage = UsageReporter(self)

    @property
    def ocr(self) -> OCRAccessor:
        return OCRAccessor(self)

    @property
    def classifier(self) -> ClassifierAccessor:
        return ClassifierAccessor(self)


class ModuleClient:
    """MCP client that calls module servers directly."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def call(
        self,
        module: str,
        tool: str,
        args: dict,
    ) -> dict:
        """Call a module MCP tool directly.

        1. Resolves module URL from config/registry
        2. Adds standard arguments (user_id, project_id, app_id)
        3. Makes MCP tool call (official protocol)
        4. Extracts _meta.usage and reports to Druppie backend
        5. Returns the business result (without _meta)
        """
        # Add standard arguments
        user_id = self._get_user_id_from_token()
        args = {
            **args,
            "user_id": user_id,
            "project_id": self._client.project_id or "",
            "app_id": self._client.app_id or "",
            "session_id": "",  # Always empty for app calls
        }

        # Build MCP endpoint URL with version routing
        module_url = self._resolve_module_url(module)
        pinned = self._client.module_versions.get(module)
        if pinned:
            url = f"{module_url}/{pinned}/mcp"
        else:
            url = f"{module_url}/mcp"

        # Make MCP tool call with retry
        started_at = time.time()
        result = await self._mcp_call_with_retry(url, tool, args)
        duration_ms = int((time.time() - started_at) * 1000)

        # Extract and report usage
        meta = result.pop("_meta", {})
        if meta.get("usage"):
            await self._client._usage.report(
                module_id=meta.get("module_id", module),
                module_version=meta.get("module_version"),
                tool_name=tool,
                user_id=user_id,
                cost_cents=meta["usage"].get("cost_cents", 0.0),
                resources=meta["usage"].get("resources"),
                success=True,
                duration_ms=duration_ms,
            )

        return result
```

### Authentication & App Access Control

```python
# druppie_sdk/auth.py

class AppAuth:
    """App-level authentication and role-based access control.

    Authentication: Keycloak JWT (validated by modules themselves).
    Authorization: App-specific roles managed in Druppie backend.
    """

    def __init__(self, client: DruppieClient):
        self._client = client

    async def get_user_roles(self, user_token: str | None = None) -> list[str]:
        """Get the current user's roles for this app.

        Calls Druppie backend: GET /api/applications/{app_id}/users/{user_id}/roles
        Returns: ["editor", "admin"] or [] if no access.
        """
        token = user_token or self._client._token
        user_id = self._extract_user_id(token)
        async with httpx.AsyncClient() as http:
            response = await http.get(
                f"{self._client.druppie_url}/api/applications/{self._client.app_id}/users/{user_id}/roles",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 200:
                return response.json().get("roles", [])
            return []

    async def require_role(self, role: str, user_token: str | None = None):
        """Raise 403 if user doesn't have the required role."""
        roles = await self.get_user_roles(user_token)
        if role not in roles:
            raise PermissionError(f"Role '{role}' required")
```

### Usage Reporting

```python
# druppie_sdk/usage.py

class UsageReporter:
    """Reports module usage to Druppie backend asynchronously."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def report(
        self,
        module_id: str,
        module_version: str | None,
        tool_name: str,
        user_id: str,
        cost_cents: float,
        resources: dict | None,
        success: bool,
        duration_ms: int,
    ):
        """POST usage record to Druppie backend.

        Fire-and-forget: failures are logged but don't affect the caller.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                await http.post(
                    f"{self._client.druppie_url}/api/usage",
                    json={
                        "user_id": user_id,
                        "app_id": self._client.app_id,
                        "project_id": self._client.project_id,
                        "session_id": None,
                        "module_id": module_id,
                        "module_version": module_version,
                        "tool_name": tool_name,
                        "cost_cents": cost_cents,
                        "resources": json.dumps(resources) if resources else None,
                        "success": success,
                        "duration_ms": duration_ms,
                    },
                    headers={"Authorization": f"Bearer {self._client._token}"},
                )
        except Exception:
            logger.warning(f"Failed to report usage for {module_id}:{tool_name}")
```

### Typed Module Accessors

```python
class OCRAccessor:
    """Typed convenience accessor for OCR module."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def extract(self, source: str, language: str = "auto", output_format: str = "plain") -> dict:
        return await self._client.modules.call("ocr", "extract_text", {
            "source": source, "language": language, "output_format": output_format,
        })


class ClassifierAccessor:
    """Typed convenience accessor for classifier module."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def classify(self, text: str, categories: list[str]) -> dict:
        return await self._client.modules.call("classifier", "classify_document", {
            "content": text, "categories": categories,
        })
```

---

## 9. Backend API for Modules

Apps connect directly to module MCP servers (no gateway proxy). The Druppie backend provides supporting API routes for usage reporting, module discovery, and app access control.

### Routes on the existing Druppie backend

```python
# druppie/api/routes/modules.py

router = APIRouter(prefix="/api/modules", tags=["modules"])

@router.get("/")
async def list_modules(category: str = None):
    """List all available modules (for discovery)."""
    ...

@router.get("/{module_id}/info")
async def module_info(module_id: str):
    """Get module metadata including active versions and tools."""
    ...
```

```python
# druppie/api/routes/usage.py

router = APIRouter(prefix="/api/usage", tags=["usage"])

@router.post("/")
async def record_usage(payload: UsageRecord, user: dict = Depends(get_current_user)):
    """Record a module usage event (called by SDK after each module call)."""
    ...

@router.get("/")
async def get_usage(
    module_id: str = None, app_id: str = None, user_id: str = None,
    period: str = "month",
):
    """Query usage analytics with filters."""
    ...
```

```python
# druppie/api/routes/applications.py

router = APIRouter(prefix="/api/applications", tags=["applications"])

@router.get("/{app_id}/users/{user_id}/roles")
async def get_user_roles(app_id: str, user_id: str):
    """Get a user's roles for an app (called by SDK for access control)."""
    ...

@router.post("/{app_id}/roles")
async def create_role(app_id: str, role: RoleCreate):
    """Create a role for an app (called by app owner via frontend)."""
    ...

@router.post("/{app_id}/users/{user_id}/roles")
async def assign_role(app_id: str, user_id: str, role_assignment: RoleAssignment):
    """Assign a role to a user for an app."""
    ...
```

---

## 10. Module Lifecycle

### From Proposal to Running

```
0. ACCEPT      Module proposal evaluated against acceptance criteria
                AR validates: reuse, genericity, no overlap, ownership
                (See "Module Acceptance" in modules.md)

1. DEVELOP     Create module directory with v1/ subdirectory:
                v1/module.py, v1/tools.py, v1/schema/
                Root: MODULE.yaml, server.py, db.py, auth.py, Dockerfile, requirements.txt
                Test locally: python server.py (no Docker needed)

2. REGISTER    Add docker-compose service + mcp_config.yaml entry
                Run: ModuleRegistryService.register_module("path/to/module")
                → Creates Module, ModuleVersion, ModuleToolSchema records

3. DEPLOY      docker compose --profile dev up -d module-<name>
                Container starts, health check passes

4. CONFIGURE   Agent YAML files updated to include module tools
                Injection rules added to mcp_config.yaml

5. AVAILABLE   Module tools appear in agent tool lists
                SDK can call module directly at /v1/mcp or /mcp
```

### Updating a Module

**Non-breaking update (MINOR/PATCH)** — changes within `vN/`:
1. Update `vN/module.py`, `vN/tools.py`
2. Bump version in `vN/tools.py` (FastMCP constructor + tool meta)
3. Add migration file to `vN/schema/` if DB changes needed (additive-only, with defaults)
4. Update `vN/tests/`
5. Rebuild and restart container
6. Run `register_module()` to update registry (re-reads from MCP `tools/list`)
7. All applications continue working — no changes needed

**Breaking update (MAJOR)** — create new `vN+1/` directory:
1. Create `vN+1/` directory
2. Copy `vN/` contents as starting point
3. Make breaking changes in `vN+1/module.py`, `vN+1/tools.py`
4. Update version and meta in `vN+1/tools.py`
5. Write `vN+1/schema/` migrations for any DB additions (additive-only)
6. Write `vN+1/tests/`
7. Update root `MODULE.yaml`: add new version to `versions`, update `latest_version`
8. Update root `server.py` to import and mount `vN+1/tools.py`
9. Rebuild and restart container
10. Run `register_module()` to update registry
11. `vN/` is untouched — all existing clients at `/vN/mcp` continue working

---

## 11. Complete Example: OCR Module

### v1.0.0 — Initial Release

**Folder structure**:
```
druppie/mcp-servers/module-ocr/
├── MODULE.yaml
├── Dockerfile
├── requirements.txt
├── server.py
├── db.py
├── auth.py
├── v1/
│   ├── module.py
│   ├── tools.py
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   └── current.sql
│   └── tests/
│       └── test_module.py
└── tests/
    └── test_routing.py
```

**MODULE.yaml**:
```yaml
id: ocr
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

**v1/tools.py** (single source of truth for the tool contract):
```python
from fastmcp import FastMCP
from .module import OCRModule

mcp = FastMCP(
    "OCR Module v1",
    version="1.0.0",
    instructions="Extract text from images and documents (PDF, JPG, PNG). Use when processing scanned or photographed documents.",
)

module = OCRModule()

@mcp.tool(
    name="extract_text",
    description="Extract text from an image or document",
    meta={
        "module_id": "ocr",
        "version": "1.0.0",
        "resource_metrics": {
            "bytes_processed": {"type": "integer", "unit": "bytes"},
            "processing_ms": {"type": "integer", "unit": "milliseconds"},
        },
    },
)
async def extract_text(
    image_url: str,
    language: str = "auto",
    user_id: str = "",
    project_id: str = "",
    session_id: str = "",
    app_id: str = "",
) -> dict:
    start = time.time()
    result = await module.extract_text(
        image_url=image_url, language=language,
        user_id=user_id, project_id=project_id,
        session_id=session_id, app_id=app_id,
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        **result,
        "_meta": {
            "module_id": "ocr",
            "module_version": "1.0.0",
            "usage": {"cost_cents": 0.0, "resources": {"bytes_processed": 0, "processing_ms": elapsed_ms}},
        },
    }
```

**v1/module.py**:
```python
class OCRModule:
    async def extract_text(self, image_url: str, language: str = "auto",
                           user_id: str = "", project_id: str = "",
                           session_id: str = "", app_id: str = "") -> dict:
        result = self._run_ocr(image_url, language)
        await self._save_extraction(session_id, image_url, result)
        return {"text": result["text"], "confidence": result["confidence"]}
```

**v1/schema/001_initial.sql** (runs against module's own database, not Druppie's):
```sql
CREATE TABLE extractions (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,     -- Passed via standard MCP argument
    image_url VARCHAR(500) NOT NULL,
    language VARCHAR(10) DEFAULT 'auto',
    extracted_text TEXT,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**SDK usage**:
```python
druppie = DruppieClient()
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp (latest = v1)
# {"text": "Invoice #1234...", "confidence": 0.95}
```

### v1.1.0 — Add `output_format` (non-breaking, in-place update)

Changes happen inside `v1/` — no new directory.

**v1/tools.py**: Bump version to `"1.1.0"` in FastMCP constructor and tool meta. Add `output_format` parameter to `@mcp.tool()`.

**v1/module.py**: Add `output_format` parameter with default `"plain"`.

**v1/schema/002_add_output_format.sql**:
```sql
ALTER TABLE extractions
    ADD COLUMN output_format VARCHAR(20) DEFAULT 'plain';
```

**Existing SDK callers**: No changes needed. `output_format` defaults to `"plain"`.

### v1.2.0 — Add `bounding_boxes` to response (non-breaking, in-place update)

Changes happen inside `v1/` — no new directory.

**v1/tools.py**: Bump version to `"1.2.0"` in FastMCP constructor and tool meta.

**v1/module.py**: Include `bounding_boxes` in return dict.

**Existing SDK callers**: No changes needed. Extra field is ignored or used optionally.

### v2.0.0 — Rename `image_url`→`source`, restructure response (BREAKING)

A new `v2/` directory is created. `v1/` is untouched.

**New folder structure**:
```
druppie/mcp-servers/module-ocr/
├── MODULE.yaml              # Updated: latest_version: "2.0.0", versions: ["1.0.0", "2.0.0"]
├── server.py                # Updated: imports and mounts v2/tools.py at /v2
├── db.py                    # Shared DB connection (both versions use same database)
├── auth.py                  # Shared JWT validation
├── v1/                      # UNTOUCHED — still serves at /v1/mcp
│   ├── module.py
│   ├── tools.py             # Still at 1.2.0 (version in FastMCP constructor)
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   ├── 002_add_output_format.sql
│   │   └── current.sql
│   └── tests/
├── v2/                      # NEW — serves at /v2/mcp
│   ├── module.py            # Breaking changes: source param, nested response
│   ├── tools.py             # version="2.0.0", new tool schemas in @mcp.tool()
│   ├── schema/
│   │   ├── 001_add_source_column.sql
│   │   ├── 002_add_pages_table.sql
│   │   └── current.sql
│   └── tests/
└── tests/
```

**MODULE.yaml changes**:
```yaml
latest_version: "2.0.0"
versions:
  - "1.0.0"
  - "2.0.0"
```

**v2/module.py**:
```python
class OCRModule:
    async def extract_text(self, source: str, language: str = "auto", output_format: str = "plain",
                           user_id: str = "", project_id: str = "",
                           session_id: str = "", app_id: str = "") -> dict:
        result = self._run_ocr(source, language)
        await self._save_extraction(session_id, source, result)
        return {
            "document": {"text": result["text"], "format": output_format, "language": result["detected_language"]},
            "confidence": result["confidence"],
            "pages": [{"page_number": 1, "text": result["text"]}],
        }
```

**v2/schema/001_add_source_column.sql** (additive — v1 still works):
```sql
ALTER TABLE extractions
    ADD COLUMN source VARCHAR(500) DEFAULT '';
```

**v2/schema/002_add_pages_table.sql**:
```sql
CREATE TABLE extraction_pages (
    id UUID PRIMARY KEY,
    extraction_id UUID NOT NULL REFERENCES extractions(id),
    page_number INTEGER NOT NULL,
    text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**SDK callers using v1**:
```python
# Still works — v1 code is untouched, running at /v1/mcp
druppie = DruppieClient(module_versions={"ocr": "v1"})
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v1/mcp
# {"text": "...", "confidence": 0.95, "bounding_boxes": [...]}
```

**SDK callers using v2**:
```python
druppie = DruppieClient(module_versions={"ocr": "v2"})
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/v2/mcp
# {"document": {"text": "...", "format": "plain", "language": "nl"}, "confidence": 0.95, "pages": [...]}
```

**SDK callers using latest (default)**:
```python
druppie = DruppieClient()  # No version pinning
result = await druppie.ocr.extract("invoice.png")
# SDK calls: POST http://module-ocr:9010/mcp → routes to v2 (latest)
```

---

## Sources

### Versioning & Compatibility
- [Stripe: APIs as infrastructure — future-proofing with versioning](https://stripe.com/blog/api-versioning)
- [Google AIP-180: Backwards Compatibility](https://google.aip.dev/180)
- [Zalando RESTful API Guidelines — Compatibility](https://github.com/zalando/restful-api-guidelines/blob/main/chapters/compatibility.adoc)
- [Kubernetes Deprecation Policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)

### MCP Protocol
- [MCP Versioning Specification](https://modelcontextprotocol.io/specification/versioning)
- [MCP Tool Versioning Discussion (#1915)](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1915)

### Authentication
- [Keycloak Standard Token Exchange (RFC 8693)](https://www.keycloak.org/2025/05/standard-token-exchange-kc-26-2)

### Database Patterns
- [12-Factor App: Backing Services](https://12factor.net/backing-services) — treat databases as attached resources per service
