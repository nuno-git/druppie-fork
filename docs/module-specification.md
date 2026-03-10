# Druppie Module Specification — Technical Contract

> **Status**: Specification (ready for team review)
> **Date**: 2026-03-10 (versioning redesign), original 2026-02-24
> **Prerequisite**: Read `docs/modules.md` for the design research and approach selection
> **Approach**: SDK + MCP Hybrid with Shared DB + API Gateway (Approaches C+E from design doc)

---

## Table of Contents

1. [Module Definition](#1-module-definition)
2. [File Structure & Contract](#2-file-structure--contract)
3. [MODULE.yaml & Version Manifests](#3-moduleyaml--version-manifests)
4. [Module Code Contract](#4-module-code-contract)
5. [Version System](#5-version-system)
6. [Database Schema & Migrations](#6-database-schema--migrations)
7. [Module Registry](#7-module-registry)
8. [Druppie SDK](#8-druppie-sdk)
9. [API Gateway](#9-api-gateway)
10. [Module Lifecycle](#10-module-lifecycle)
11. [Complete Example: OCR Module v1.0→v2.0](#11-complete-example-ocr-module)

---

## 1. Module Definition

A **Druppie module** is a containerized MCP server that:

1. Exposes tools via the MCP protocol (JSON-RPC over HTTP)
2. Has a `MODULE.yaml` manifest declaring its identity and active versions
3. Follows the versioned directory pattern: `server.py` (root router) + `vN/module.py` (business logic per major version)
4. Can access the shared Druppie PostgreSQL database (via schema isolation)
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
├── v1/
│   ├── manifest.yaml        # v1 version metadata + tool schemas
│   ├── module.py            # v1 business logic (fully independent)
│   ├── tools.py             # v1 @mcp.tool() definitions
│   ├── schema/
│   │   ├── 001_initial.sql  # First migration
│   │   └── current.sql      # Full schema snapshot (for fresh installs)
│   └── tests/
│       └── test_module.py   # v1-specific tests
├── v2/
│   ├── manifest.yaml        # v2 version metadata + tool schemas
│   ├── module.py            # v2 business logic (fully independent)
│   ├── tools.py             # v2 @mcp.tool() definitions
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
| Root `MODULE.yaml` | Module identity (id, name, author, description), list of active versions, latest version pointer | N/A — one file |
| Root `server.py` | HTTP entrypoint, path-based routing to version dirs, DB connection setup, config loading | Yes — infrastructure only |
| Root `Dockerfile` | Container definition, installs all deps | Yes |
| Root `requirements.txt` | Union of all version dependencies | Yes |
| `vN/manifest.yaml` | Version number, tool schemas (input/output JSON Schema), per-tool metadata | No — owned by version |
| `vN/module.py` | All business logic for this version | No — owned by version |
| `vN/tools.py` | MCP tool definitions delegating to module.py | No — owned by version |
| `vN/schema/` | SQL migration files for this version's DB changes | No — owned by version |
| `vN/tests/` | Tests for this version's contract | No — owned by version |
| Root `tests/` | Cross-version tests (routing, coexistence) | N/A |

### Sharing Rule

Infrastructure code (DB connection, config loading, logging, server setup) lives at the root and is shared. **Business logic is never shared** — each version owns its full implementation, even if some lines are identical across versions. If a bug exists in shared logic, fix it independently in each version directory.

### Naming Convention

| Item | Pattern | Example |
|------|---------|---------|
| Directory | `module-<name>` | `module-ocr` |
| Module ID | `<name>` (lowercase, hyphens OK) | `ocr`, `document-classifier` |
| Version directory | `v<major>` | `v1`, `v2` |
| Container name | `druppie-module-<name>` | `druppie-module-ocr` |
| Docker Compose service | `module-<name>` | `module-ocr` |
| Port | 9010-9099 (9001-9009 reserved for core MCP servers) | `9010` |
| DB schema | `module_<name>` (underscores, no hyphens) | `module_ocr` |
| DB role | `druppie_module_<name>` | `druppie_module_ocr` |

---

## 3. MODULE.yaml & Version Manifests

Module metadata is split across two levels: a root `MODULE.yaml` for identity and version listing, and per-version `manifest.yaml` files that own the tool schemas.

### Root MODULE.yaml

The root manifest is small. It identifies the module and lists which major versions are active:

```yaml
# =============================================================================
# MODULE.yaml — Root Module Manifest
# =============================================================================

# --- Identity ---
id: ocr                                    # Unique module identifier (required)
name: OCR Module                           # Human-readable name (required)
description: "Extract text from images and documents (PDF, JPG, PNG)"
author: druppie-team
license: MIT
repository: https://gitea.local/druppie/module-ocr

# --- Versions ---
latest_version: "2.0.0"                   # The version served at /mcp (required)
versions:                                  # All active major versions (required)
  - "1.0.0"                               # Served at /v1/mcp
  - "2.0.0"                               # Served at /v2/mcp

# --- Infrastructure ---
infrastructure:
  port: 9010
  health_endpoint: /health
  info_endpoint: /module/info
  db_schema: module_ocr                    # null if module doesn't need DB access

# --- Metadata ---
metadata:
  category: document-processing
  tags: [ocr, text-extraction, pdf, image]
  icon: document-text

# --- Agent Metadata (for LLM discovery and comprehension) ---
agent_metadata:
  summary: "Extracts text from images and documents using OCR"
  when_to_use:
    - "User needs text extracted from PDF, JPG, or PNG files"
    - "Application processes scanned or photographed documents"
  when_not_to_use:
    - "Document is already digital text (use direct file reading instead)"
    - "Only file metadata is needed, not content"
  related_modules:
    - module: classifier
      pattern: "OCR output → classifier input for document categorization"
```

### Per-Version manifest.yaml

Each version directory has its own `manifest.yaml` that defines the version's tool schemas. This file is the **contract** for that version:

```yaml
# v1/manifest.yaml
version: "1.2.0"                           # Current minor.patch within this major
tools:
  - name: extract_text
    description: "Extract text from an image or document"
    requires_approval: false
    required_role: null
    input_schema:
      type: object
      properties:
        image_url:
          type: string
          description: "URL or path to the image"
        language:
          type: string
          description: "OCR language hint (default: auto-detect)"
          default: "auto"
      required: [image_url]
    output_schema:
      type: object
      properties:
        text: { type: string }
        confidence: { type: number }
      required: [text, confidence]
    usage_examples:
      - description: "Extract Dutch text from a scanned invoice"
        input: { image_url: "invoice.png", language: "nl" }
        output: { text: "Factuurnummer: 1234...", confidence: 0.95 }
```

```yaml
# v2/manifest.yaml
version: "2.0.0"
tools:
  - name: extract_text
    description: "Extract text from a document using URL, path, or base64 data"
    requires_approval: false
    required_role: null
    input_schema:
      type: object
      properties:
        source:
          type: string
          description: "URL, file path, or base64 data of the document"
        language:
          type: string
          description: "OCR language hint (default: auto-detect)"
          default: "auto"
        output_format:
          type: string
          enum: ["plain", "markdown", "html"]
          description: "Output text format"
          default: "plain"
      required: [source]
    output_schema:
      type: object
      properties:
        document:
          type: object
          properties:
            text: { type: string }
            format: { type: string }
            language: { type: string }
        confidence: { type: number }
        pages:
          type: array
          items:
            type: object
            properties:
              page_number: { type: integer }
              text: { type: string }
      required: [document, confidence]
    usage_examples:
      - description: "Extract Dutch text from a scanned invoice"
        input: { source: "invoice.png", language: "nl" }
        output: { document: { text: "Factuurnummer: 1234...", format: "plain", language: "nl" }, confidence: 0.95 }
```

### What Each Section Controls

| Section | Read by | Purpose |
|---------|---------|---------|
| Root Identity | Registry, admin UI | Discovery and documentation |
| Root Versions | `server.py`, registry | Which major versions are active, which is latest |
| Root Infrastructure | Docker Compose, health checks | Deployment configuration |
| Root Agent Metadata | Agent system prompts, registry | Module discovery and selection by AI agents |
| Per-version Tools | `vN/tools.py`, SDK, agent YAML | Tool schema definition for this version |
| Per-version Examples | Agents, SDK docs | Concrete usage patterns per version |

---

## 4. Module Code Contract

### vN/module.py — Business Logic (Per-Version)

Each version directory contains its own `module.py` with ALL business logic for that version. It MUST NOT depend on FastMCP, Starlette, or any HTTP framework.

```python
"""<Module Name> Module v1 — Business Logic.

This file contains the pure business logic for v1 of the module.
It is imported by v1/tools.py for MCP tool exposure.
It can be tested independently without HTTP infrastructure.
"""

import logging
from typing import Any

logger = logging.getLogger("<module-id>-mcp.v1")


class <ModuleName>Module:
    """v1 business logic for <description>.

    All public methods correspond 1:1 to MCP tools defined in tools.py.
    Method signatures match this version's manifest.yaml schemas.
    """

    def __init__(self, config_param: str = "default"):
        """Initialize with configuration from environment variables."""
        self.config_param = config_param

    async def tool_name(
        self,
        required_param: str,
        optional_param: str = "default",
    ) -> dict[str, Any]:
        """Execute tool operation.

        Returns:
            Dict matching the output_schema in this version's manifest.yaml
        """
        result = self._internal_processing(required_param)
        return {
            "field1": result["value"],
            "field2": result["score"],
        }
```

**Rules**:
- One public async method per MCP tool
- Method names match tool names in `vN/manifest.yaml`
- Parameter names match this version's `input_schema`
- Return dicts match this version's `output_schema`
- Raise exceptions on failure (don't return error dicts — let server.py handle formatting)
- No `SELECT *` in database queries — always select explicit columns so new columns from other versions don't break this version

### vN/tools.py — MCP Tool Definitions (Per-Version)

Each version directory contains its own `tools.py` that wraps module methods as MCP tools:

```python
"""<Module Name> v1 — MCP Tool Definitions.

Wraps v1/module.py business logic as MCP tools via FastMCP.
"""

import os
from fastmcp import FastMCP
from .module import <ModuleName>Module

mcp = FastMCP("<Module Name> v1")

module = <ModuleName>Module(
    config_param=os.getenv("CONFIG_PARAM", "default"),
)


@mcp.tool()
async def tool_name(
    required_param: str,
    optional_param: str = "default",
) -> dict:
    """Tool description matching manifest.yaml."""
    return await module.tool_name(
        required_param=required_param,
        optional_param=optional_param,
    )
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
    return JSONResponse({
        "status": "healthy",
        "service": f"module-{manifest['id']}",
        "latest_version": latest_version,
        "active_versions": manifest["versions"],
    })


async def module_info(request):
    return JSONResponse({
        "module_id": manifest["id"],
        "latest_version": latest_version,
        "versions": manifest["versions"],
    })


# Build routes: /v1/mcp, /v2/mcp, /mcp → latest
routes = [
    Route("/health", health, methods=["GET"]),
    Route("/module/info", module_info, methods=["GET"]),
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
| `/v2/mcp` | `v2/tools.py` |
| `/mcp` | Latest version (from `MODULE.yaml` `latest_version`) |
| `/health` | Health check (lists all active versions) |
| `/module/info` | Module metadata |

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
  module-<name>:
    build:
      context: ./druppie/mcp-servers/module-<name>
      dockerfile: Dockerfile
    container_name: druppie-module-<name>
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9010"
      CONFIG_PARAM: ${MODULE_<NAME>_CONFIG:-default}
      # If module needs DB access:
      MODULE_DB_URL: postgresql://druppie_module_<name>:${MODULE_<NAME>_DB_PASSWORD}@druppie-db:5432/druppie
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
      druppie-db:
        condition: service_healthy
```

### mcp_config.yaml Entry Template

```yaml
  <module-id>:
    url: ${MCP_<MODULE>_URL:-http://module-<name>:9010}
    description: "Module description from MODULE.yaml"
    inject:
      session_id:
        from: session.id
        hidden: true
      user_id:
        from: session.user_id
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
4. Write `v2/manifest.yaml` with new tool schemas
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

## 6. Database Schema & Migrations

### Schema Isolation

Modules that need persistent storage get their own PostgreSQL schema with controlled access:

```sql
-- Create module schema
CREATE SCHEMA module_ocr;

-- Create dedicated role
CREATE ROLE druppie_module_ocr LOGIN PASSWORD 'generated-password';

-- Full access to own schema
GRANT ALL ON SCHEMA module_ocr TO druppie_module_ocr;
ALTER DEFAULT PRIVILEGES IN SCHEMA module_ocr
    GRANT ALL ON TABLES TO druppie_module_ocr;

-- Read-only access to shared Druppie tables
GRANT USAGE ON SCHEMA public TO druppie_module_ocr;
GRANT SELECT ON public.sessions TO druppie_module_ocr;
GRANT SELECT ON public.projects TO druppie_module_ocr;
GRANT SELECT ON public.users TO druppie_module_ocr;

-- Set default search path
ALTER ROLE druppie_module_ocr SET search_path TO module_ocr, public;
```

### Database Rules for Versioned Modules

Since multiple major versions run simultaneously against the same database schema, strict rules apply:

1. **One PostgreSQL schema per module** — `module_<name>` (e.g., `module_ocr`)
2. **Shared across all major versions** — v1 and v2 read/write the same schema
3. **Additive-only changes** — add columns (with defaults), add tables, add indexes
4. **Never destructive** — no `DROP`, `RENAME`, or `ALTER TYPE` while any version uses the affected object
5. **Every new column has a `DEFAULT`** — older version code can INSERT without specifying it
6. **No `SELECT *`** — version code selects explicit columns so new columns don't break it

### Why Additive-Only

Both v1 and v2 run simultaneously against the same database schema. If v2 drops a column that v1 uses, v1 breaks. Additive-only guarantees that older versions keep working regardless of what newer versions add.

### Migration Files

Each version directory has a `schema/` folder with numbered SQL migration files:

```
v1/schema/
├── 001_initial.sql                # CREATE TABLE module_ocr.extractions (...)
├── 002_add_output_format.sql      # ALTER TABLE ... ADD COLUMN output_format VARCHAR DEFAULT 'plain'
└── current.sql                    # Full schema snapshot (for fresh installs)
```

```
v2/schema/
├── 001_add_pages_table.sql        # CREATE TABLE module_ocr.extraction_pages (...)
├── 002_add_source_column.sql      # ALTER TABLE ... ADD COLUMN source VARCHAR DEFAULT ''
└── current.sql                    # Full schema = v1 final state + v2 additions
```

### Migration Tracking

A tracking table records which migrations have been applied:

```sql
CREATE TABLE module_<name>._migrations (
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
  modules                    — Installed module instances
  module_versions            — Every active major version of a module
  module_tool_schemas        — Tool schemas per version (JSON Schema as Text)
  application_module_bindings — Which app uses which module major version
"""

from uuid import uuid4
from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text,
    Boolean, Float, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import Base, utcnow


class Module(Base):
    """An installed Druppie module."""
    __tablename__ = "modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    author = Column(String(255))
    category = Column(String(100))
    latest_version = Column(String(20), nullable=False)
    container_url = Column(String(500), nullable=False)
    container_port = Column(Integer, default=9010)
    status = Column(String(20), default="active")   # active, disabled
    is_core = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions = relationship("ModuleVersion", back_populates="module", cascade="all, delete-orphan")
    bindings = relationship("ApplicationModuleBinding", back_populates="module", cascade="all, delete-orphan")


class ModuleVersion(Base):
    """An active major version of a module (e.g., v1 at 1.2.0, v2 at 2.0.0)."""
    __tablename__ = "module_versions"
    __table_args__ = (UniqueConstraint("module_id", "major_version", name="uq_module_major_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    major_version = Column(Integer, nullable=False)          # 1, 2, etc.
    current_version = Column(String(20), nullable=False)     # "1.2.0", "2.0.0"
    route_path = Column(String(20), nullable=False)          # "/v1", "/v2"
    release_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    module = relationship("Module", back_populates="versions")
    tool_schemas = relationship("ModuleToolSchema", back_populates="module_version", cascade="all, delete-orphan")


class ModuleToolSchema(Base):
    """Tool input/output schema at a specific major version.

    Stores JSON Schema as Text (not JSONB) — read-only, never queried by sub-field.
    """
    __tablename__ = "module_tool_schemas"
    __table_args__ = (
        UniqueConstraint("module_version_id", "tool_name", name="uq_version_tool"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_version_id = Column(UUID(as_uuid=True), ForeignKey("module_versions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    description = Column(Text)
    input_schema_json = Column(Text, nullable=False)
    output_schema_json = Column(Text, nullable=False)
    requires_approval = Column(Boolean, default=False)
    required_role = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    module_version = relationship("ModuleVersion", back_populates="tool_schemas")


class ApplicationModuleBinding(Base):
    """Tracks which application uses which module major version."""
    __tablename__ = "application_module_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "module_id", name="uq_project_module"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    major_version = Column(Integer, nullable=False)          # 1 or 2
    last_called_at = Column(DateTime(timezone=True))
    total_calls = Column(Integer, default=0)
    total_cost_cents = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    module = relationship("Module", back_populates="bindings")
```

### Registry Service

The registry reads `MODULE.yaml` and per-version `manifest.yaml` files and populates the database:

```python
# druppie/services/module_registry_service.py

class ModuleRegistryService:
    """Manages module registration, version tracking, and discovery."""

    async def register_module(self, module_path: str) -> Module:
        """Register a module from its directory.

        1. Parse root MODULE.yaml (identity, version list)
        2. Parse each vN/manifest.yaml (tool schemas)
        3. Create/update Module record
        4. Create ModuleVersion records for each major version
        5. Create ModuleToolSchema records for each tool per version
        """
        ...

    async def get_module(self, module_id: str) -> ModuleDetail:
        """Get module with all versions and tool schemas."""
        ...

    async def list_modules(self, category: str = None) -> list[ModuleSummary]:
        """List all installed modules (Summary pattern)."""
        ...

    async def bind_application(
        self, project_id: UUID, module_id: str, major_version: int
    ) -> ApplicationModuleBinding:
        """Bind an application to a specific module major version."""
        ...

    async def get_binding(
        self, project_id: UUID, module_id: str
    ) -> ApplicationModuleBinding | None:
        """Get which major version an application is bound to."""
        ...
```

---

## 8. Druppie SDK

The SDK is a lightweight Python package (~50KB) included in every Druppie-generated application. It handles module calls, authentication, version routing, cost tracking, and retries.

### Package Structure

```
druppie-sdk/
├── druppie_sdk/
│   ├── __init__.py          # DruppieClient, DruppieAuth, health_router
│   ├── client.py            # Main client with module calling
│   ├── auth.py              # OBO token exchange with Keycloak
│   ├── health.py            # Standard /health endpoint for generated apps
│   └── py.typed             # PEP 561 marker
├── pyproject.toml
└── README.md
```

### Core Client

```python
# druppie_sdk/client.py

class DruppieClient:
    """Main SDK client for Druppie-generated applications.

    Zero-config: reads DRUPPIE_* environment variables automatically.
    Firebase pattern: auto-discovery.
    Stripe pattern: thin client, remote logic, idempotency.

    Usage:
        druppie = DruppieClient()
        text = await druppie.modules.call("ocr", "extract_text", {"source": "img.png"})
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        session_token: str | None = None,
        module_versions: dict[str, str] | None = None,
    ):
        self.gateway_url = gateway_url or os.environ.get(
            "DRUPPIE_GATEWAY_URL", "http://druppie-gateway:8000"
        )
        self.session_token = session_token or os.environ.get("DRUPPIE_SESSION_TOKEN")
        self.module_versions = module_versions or {}  # e.g., {"ocr": "v1", "classifier": "v2"}
        self.modules = ModuleClient(self)
        self.costs = CostTracker()
        self._auth = DruppieAuth()

    @property
    def ocr(self) -> OCRAccessor:
        """Typed OCR module accessor."""
        return OCRAccessor(self)

    @property
    def classifier(self) -> ClassifierAccessor:
        """Typed classifier module accessor."""
        return ClassifierAccessor(self)


class ModuleClient:
    """Generic module caller — calls any module by name."""

    def __init__(self, client: DruppieClient):
        self._client = client

    async def call(
        self,
        module: str,
        tool: str,
        args: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        """Call an MCP module tool.

        Handles: path-based version routing, OBO auth, retries, cost tracking.
        """
        headers = {"Content-Type": "application/json"}

        # Auth
        if self._client.session_token:
            token = await self._client._auth.get_token(self._client.session_token)
            headers["Authorization"] = f"Bearer {token}"

        # Idempotency
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Build URL with version path
        # e.g., {"ocr": "v1"} → /api/modules/ocr/v1/call
        # No version specified → /api/modules/ocr/call (gateway routes to latest)
        pinned = self._client.module_versions.get(module)
        if pinned:
            url = f"{self._client.gateway_url}/api/modules/{module}/{pinned}/call"
        else:
            url = f"{self._client.gateway_url}/api/modules/{module}/call"

        # Make request with retry
        result = await self._request_with_retry(url, tool, args, headers)

        # Track costs
        if result.get("cost_cents"):
            self._client.costs.record(module, tool, result["cost_cents"])

        return result

    async def _request_with_retry(self, url, tool, args, headers, max_retries=3):
        """Exponential backoff with jitter (AWS SDK pattern)."""
        import random, asyncio, httpx

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    response = await http.post(
                        url,
                        json={"tool": tool, "arguments": args},
                        headers=headers,
                    )
                    if response.status_code == 200:
                        return response.json()
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        return {"success": False, "error": response.text}
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

            if attempt < max_retries:
                delay = min(2 ** attempt + random.random(), 20)
                await asyncio.sleep(delay)

        return {"success": False, "error": "Max retries exceeded"}


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

### OBO Authentication

```python
# druppie_sdk/auth.py

class DruppieAuth:
    """OBO token exchange with Keycloak (RFC 8693).

    Exchanges the user's Keycloak token for a module-scoped token.
    Keycloak 26.2+ supports Standard Token Exchange natively.
    """

    def __init__(self):
        self.keycloak_url = os.environ.get("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
        self.realm = os.environ.get("KEYCLOAK_REALM", "druppie")
        self.client_id = os.environ.get("DRUPPIE_CLIENT_ID", "druppie-sdk")
        self.client_secret = os.environ.get("DRUPPIE_CLIENT_SECRET")
        self._token: str | None = None
        self._token_expiry: float = 0

    @property
    def token_endpoint(self) -> str:
        return f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"

    async def exchange_token(self, user_token: str) -> str:
        """Exchange user token for module-scoped OBO token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_endpoint, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": "druppie-modules",
            })
            data = response.json()
            self._token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 300) - 30
            return self._token

    async def get_token(self, user_token: str) -> str:
        """Get valid token, auto-refreshing if expired."""
        if self._token and time.time() < self._token_expiry:
            return self._token
        return await self.exchange_token(user_token)
```

---

## 9. API Gateway

The gateway is a lightweight FastAPI service that sits between applications and module servers. It handles routing, authentication, rate limiting, and cost tracking in one place. Version routing is path-based.

### Option: Extend the Existing Backend

Instead of a separate gateway, add `/api/modules/` routes to the existing Druppie backend:

```python
# druppie/api/routes/modules.py

from fastapi import APIRouter, Request, Depends
from druppie.services.module_registry_service import ModuleRegistryService
from druppie.execution.mcp_http import MCPHttp

router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.post("/{module_id}/call")
@router.post("/{module_id}/{version}/call")
async def call_module(
    module_id: str,
    request: Request,
    version: str | None = None,
    registry: ModuleRegistryService = Depends(),
    mcp: MCPHttp = Depends(),
):
    """Route a module call through the gateway.

    Path-based version routing:
      POST /api/modules/ocr/call        → forwards to module at /mcp (latest)
      POST /api/modules/ocr/v1/call     → forwards to module at /v1/mcp
      POST /api/modules/ocr/v2/call     → forwards to module at /v2/mcp
    """
    body = await request.json()
    tool = body["tool"]
    args = body["arguments"]

    # Get module info
    module = await registry.get_module(module_id)
    if not module:
        return {"error": f"Module '{module_id}' not found"}, 404

    # Build MCP endpoint path based on version
    if version:
        mcp_path = f"/{version}/mcp"
    else:
        mcp_path = "/mcp"  # Routes to latest at the module server

    # Forward to module MCP server
    result = await mcp.call(
        server=module_id,
        tool=tool,
        args=args,
        path=mcp_path,
    )

    # Record usage
    user_id = request.state.user_id  # From auth middleware
    await registry.record_usage(
        user_id=user_id,
        module_id=module_id,
        tool=tool,
        major_version=int(version[1:]) if version else None,
        cost_cents=result.get("cost_cents", 0),
    )

    return result


@router.get("/{module_id}/info")
async def module_info(module_id: str, registry: ModuleRegistryService = Depends()):
    """Get module metadata including active versions and tools."""
    return await registry.get_module(module_id)


@router.get("/")
async def list_modules(category: str = None, registry: ModuleRegistryService = Depends()):
    """List all available modules."""
    return await registry.list_modules(category=category)
```

---

## 10. Module Lifecycle

### From Proposal to Running

```
0. ACCEPT      Module proposal evaluated against acceptance criteria
                AR validates: reuse, genericity, no overlap, ownership
                (See "Module Acceptance" in modules.md)

1. DEVELOP     Create module directory with v1/ subdirectory:
                v1/module.py, v1/tools.py, v1/manifest.yaml, v1/schema/
                Root: MODULE.yaml, server.py, Dockerfile, requirements.txt
                Test locally: python server.py (no Docker needed)

2. REGISTER    Add docker-compose service + mcp_config.yaml entry
                Run: ModuleRegistryService.register_module("path/to/module")
                → Creates Module, ModuleVersion, ModuleToolSchema records

3. DEPLOY      docker compose --profile dev up -d module-<name>
                Container starts, health check passes

4. CONFIGURE   Agent YAML files updated to include module tools
                Injection rules added to mcp_config.yaml

5. AVAILABLE   Module tools appear in agent tool lists
                SDK can call module via gateway at /v1/mcp or /mcp
```

### Updating a Module

**Non-breaking update (MINOR/PATCH)** — changes within `vN/`:
1. Update `vN/module.py`, `vN/tools.py`
2. Add migration file to `vN/schema/` if DB changes needed (additive-only, with defaults)
3. Bump version in `vN/manifest.yaml`
4. Update `vN/tests/`
5. Rebuild and restart container
6. Run `register_module()` to update registry
7. All applications continue working — no changes needed

**Breaking update (MAJOR)** — create new `vN+1/` directory:
1. Create `vN+1/` directory
2. Copy `vN/` contents as starting point
3. Make breaking changes in `vN+1/module.py`, `vN+1/tools.py`
4. Write `vN+1/manifest.yaml` with new tool schemas
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
├── v1/
│   ├── manifest.yaml
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
name: OCR Module
description: "Extract text from images and documents"
author: druppie-team
latest_version: "1.0.0"
versions:
  - "1.0.0"
infrastructure:
  port: 9010
  db_schema: module_ocr
```

**v1/manifest.yaml**:
```yaml
version: "1.0.0"
tools:
  - name: extract_text
    description: "Extract text from an image or document"
    requires_approval: false
    input_schema:
      type: object
      properties:
        image_url: { type: string }
        language: { type: string, default: "auto" }
      required: [image_url]
    output_schema:
      type: object
      properties:
        text: { type: string }
        confidence: { type: number }
      required: [text, confidence]
```

**v1/module.py**:
```python
class OCRModule:
    async def extract_text(self, image_url: str, language: str = "auto") -> dict:
        result = self._run_ocr(image_url, language)
        return {"text": result["text"], "confidence": result["confidence"]}
```

**v1/schema/001_initial.sql**:
```sql
CREATE TABLE module_ocr.extractions (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
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

**v1/manifest.yaml**: Bump version to `"1.1.0"`, add `output_format` to input_schema.

**v1/module.py**: Add `output_format` parameter with default `"plain"`.

**v1/schema/002_add_output_format.sql**:
```sql
ALTER TABLE module_ocr.extractions
    ADD COLUMN output_format VARCHAR(20) DEFAULT 'plain';
```

**Existing SDK callers**: No changes needed. `output_format` defaults to `"plain"`.

### v1.2.0 — Add `bounding_boxes` to response (non-breaking, in-place update)

Changes happen inside `v1/` — no new directory.

**v1/manifest.yaml**: Bump version to `"1.2.0"`, add `bounding_boxes` to output_schema.

**v1/module.py**: Include `bounding_boxes` in return dict.

**Existing SDK callers**: No changes needed. Extra field is ignored or used optionally.

### v2.0.0 — Rename `image_url`→`source`, restructure response (BREAKING)

A new `v2/` directory is created. `v1/` is untouched.

**New folder structure**:
```
druppie/mcp-servers/module-ocr/
├── MODULE.yaml              # Updated: latest_version: "2.0.0", versions: ["1.0.0", "2.0.0"]
├── server.py                # Updated: imports and mounts v2/tools.py at /v2
├── v1/                      # UNTOUCHED — still serves at /v1/mcp
│   ├── manifest.yaml        # Still at 1.2.0
│   ├── module.py
│   ├── tools.py
│   ├── schema/
│   │   ├── 001_initial.sql
│   │   ├── 002_add_output_format.sql
│   │   └── current.sql
│   └── tests/
├── v2/                      # NEW — serves at /v2/mcp
│   ├── manifest.yaml        # version: "2.0.0", new tool schemas
│   ├── module.py            # Breaking changes: source param, nested response
│   ├── tools.py
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
    async def extract_text(self, source: str, language: str = "auto", output_format: str = "plain") -> dict:
        result = self._run_ocr(source, language)
        return {
            "document": {"text": result["text"], "format": output_format, "language": result["detected_language"]},
            "confidence": result["confidence"],
            "pages": [{"page_number": 1, "text": result["text"]}],
        }
```

**v2/schema/001_add_source_column.sql** (additive — v1 still works):
```sql
ALTER TABLE module_ocr.extractions
    ADD COLUMN source VARCHAR(500) DEFAULT '';
```

**v2/schema/002_add_pages_table.sql**:
```sql
CREATE TABLE module_ocr.extraction_pages (
    id UUID PRIMARY KEY,
    extraction_id UUID NOT NULL REFERENCES module_ocr.extractions(id),
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
- [PostgreSQL Schemas Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [Crunchy Data: PostgreSQL Multi-Tenancy](https://www.crunchydata.com/blog/designing-your-postgres-database-for-multi-tenancy)
