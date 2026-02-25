# Druppie Module Specification — Technical Contract

> **Status**: Specification (ready for team review)
> **Date**: 2026-02-24
> **Prerequisite**: Read `docs/modules.md` for the design research and approach selection
> **Approach**: SDK + MCP Hybrid with Shared DB + API Gateway (Approaches C+E from design doc)

---

## Table of Contents

1. [Module Definition](#1-module-definition)
2. [File Structure & Contract](#2-file-structure--contract)
3. [MODULE.yaml Manifest](#3-moduleyaml-manifest)
4. [Module Code Contract](#4-module-code-contract)
5. [Version System](#5-version-system)
6. [Backwards Compatibility Layer](#6-backwards-compatibility-layer)
7. [Module Registry](#7-module-registry)
8. [Druppie SDK](#8-druppie-sdk)
9. [API Gateway](#9-api-gateway)
10. [Database Schema Isolation](#10-database-schema-isolation)
11. [Module Lifecycle](#11-module-lifecycle)
12. [Complete Example: OCR Module v1.0→v2.0](#12-complete-example-ocr-module)

---

## 1. Module Definition

A **Druppie module** is a containerized MCP server that:

1. Exposes tools via the MCP protocol (JSON-RPC over HTTP)
2. Has a `MODULE.yaml` manifest declaring its identity, version, tool schemas, and compatibility
3. Follows the `module.py` (business logic) + `server.py` (HTTP transport) separation
4. Can access the shared Druppie PostgreSQL database (via schema isolation)
5. Is callable by both Druppie agents (during build-time) and generated applications (at runtime via SDK)
6. Supports versioned tool schemas with backwards-compatible transformations

### What a Module Is NOT

- Not a Python library imported into applications (that's Approach B — rejected)
- Not a free-form microservice (must follow the MCP tool protocol)
- Not a standalone application (modules are building blocks, not end products)
- Not a pipeline or orchestrator — if it mainly calls other modules, it belongs in the application layer or as a skill
- Not a thin wrapper around a single utility function — if it has no own state or heavy dependencies, use a builtin tool instead

---

## 2. File Structure & Contract

Every module lives in `druppie/mcp-servers/module-<name>/` and MUST contain these files:

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml              # Manifest: identity, version, tool schemas
├── module.py                # Business logic (no HTTP dependencies)
├── server.py                # FastMCP server with @mcp.tool() decorators
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container definition
├── version_transformers.py  # Version compatibility transformers (if version > 1.0.0)
└── migrations/              # Version migration guides (if breaking changes exist)
    └── MIGRATION_v1_to_v2.md
```

### Naming Convention

| Item | Pattern | Example |
|------|---------|---------|
| Directory | `module-<name>` | `module-ocr` |
| Module ID | `<name>` (lowercase, hyphens OK) | `ocr`, `document-classifier` |
| Container name | `druppie-module-<name>` | `druppie-module-ocr` |
| Docker Compose service | `module-<name>` | `module-ocr` |
| Port | 9010-9099 (9001-9009 reserved for core MCP servers) | `9010` |
| DB schema | `module_<name>` (underscores, no hyphens) | `module_ocr` |
| DB role | `druppie_module_<name>` | `druppie_module_ocr` |

---

## 3. MODULE.yaml Manifest

The manifest is the **single source of truth** for a module's identity, capabilities, and version history. It is read by: the module server, the registry, the SDK, and CI/CD.

### Full Specification

```yaml
# =============================================================================
# MODULE.yaml — Module Manifest Specification
# =============================================================================

# --- Identity ---
id: ocr                                    # Unique module identifier (required)
name: OCR Module                           # Human-readable name (required)
description: "Extract text from images and documents (PDF, JPG, PNG)"
author: druppie-team
license: MIT
repository: https://gitea.local/druppie/module-ocr

# --- Versioning ---
version: "2.0.0"                           # Current module version, semver (required)
min_compatible_version: "2.0.0"            # Oldest wire-compatible version (required)

supported_versions:                        # Versions the server can serve via transformers
  - "2.0.0"                                # Current (no transform needed)
  - "1.2.0"                                # Supported via transformer
  - "1.1.0"                                # Supported via transformer

version_sunset_dates:                      # When old versions stop being served
  "1.1.0": "2026-06-01"
  "1.2.0": "2026-09-01"

# --- Tools ---
tools:
  - name: extract_text                     # Tool name (stable identifier, never changes)
    description: "Extract text from an image or document"
    tool_version: "2.0.0"                  # Per-tool version (can differ from module version)
    requires_approval: false
    required_role: null                     # Or "developer", "architect", etc.

    input_schema:                           # Current JSON Schema for input args
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

    output_schema:                          # Current JSON Schema for output
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
              bounding_boxes:
                type: array
                items:
                  type: object
                  properties:
                    text: { type: string }
                    x: { type: number }
                    y: { type: number }
                    width: { type: number }
                    height: { type: number }
                    confidence: { type: number }
      required: [document, confidence]

    schema_history:                         # Previous schemas (for version transformers)
      "1.0.0":
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

      "1.1.0":
        input_schema:
          type: object
          properties:
            image_url: { type: string }
            language: { type: string, default: "auto" }
            output_format: { type: string, enum: ["plain", "markdown", "html"], default: "plain" }
          required: [image_url]
        output_schema:
          type: object
          properties:
            text: { type: string }
            confidence: { type: number }
          required: [text, confidence]

      "1.2.0":
        input_schema:
          type: object
          properties:
            image_url: { type: string }
            language: { type: string, default: "auto" }
            output_format: { type: string, enum: ["plain", "markdown", "html"], default: "plain" }
          required: [image_url]
        output_schema:
          type: object
          properties:
            text: { type: string }
            confidence: { type: number }
            bounding_boxes: { type: array }
          required: [text, confidence]

    deprecations:                           # Active deprecation notices
      - parameter: "image_url"
        deprecated_in: "2.0.0"
        removed_in: null
        replacement: "source"
        message: "Use 'source' instead of 'image_url'. Will stop being accepted in v3.0.0."

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
  usage_examples:
    - description: "Extract Dutch text from a scanned invoice"
      input: { source: "invoice.png", language: "nl" }
      output: { document: { text: "Factuurnummer: 1234..." }, confidence: 0.95 }
  related_modules:
    - module: classifier
      pattern: "OCR output → classifier input for document categorization"
```

### What Each Section Controls

| Section | Read by | Purpose |
|---------|---------|---------|
| Identity | Registry, admin UI | Discovery and documentation |
| Versioning | Server middleware, SDK, registry | Version negotiation and compatibility |
| Tools | mcp_config.yaml sync, agent YAML, SDK codegen | Tool schema definition |
| schema_history | Version transformers | Request/response transformation between versions |
| deprecations | SDK deprecation tracker, response headers | Developer warnings |
| Infrastructure | Docker Compose, health checks | Deployment configuration |
| Agent Metadata | Agent system prompts, registry | Module discovery and selection by AI agents |

---

## 4. Module Code Contract

### module.py — Business Logic

The module class contains ALL business logic. It MUST NOT depend on FastMCP, Starlette, or any HTTP framework.

```python
"""<Module Name> Module — Business Logic.

This file contains the pure business logic for the module.
It is imported by server.py for HTTP exposure.
It can be tested independently without HTTP infrastructure.
"""

import logging
from typing import Any

logger = logging.getLogger("<module-id>-mcp")


class <ModuleName>Module:
    """Business logic for <description>.

    All public methods correspond 1:1 to MCP tools defined in server.py.
    Method signatures use the CURRENT version's parameter names.
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

        Args:
            required_param: Description
            optional_param: Description

        Returns:
            Dict matching the output_schema in MODULE.yaml
        """
        try:
            # Business logic here
            result = self._internal_processing(required_param)

            return {
                "field1": result["value"],
                "field2": result["score"],
            }
        except Exception as e:
            logger.error("tool_name failed: %s", str(e))
            raise  # Let server.py handle error formatting
```

**Rules**:
- One public async method per MCP tool
- Method names match tool names in MODULE.yaml
- Parameter names match the CURRENT version's input_schema
- Return dicts match the CURRENT version's output_schema
- Raise exceptions on failure (don't return error dicts — let server.py handle formatting)
- Use `logging` for structured logs

### server.py — HTTP Transport

The server file wraps module methods as MCP tools using FastMCP.

```python
"""<Module Name> MCP Server.

HTTP transport layer for <module-id> module.
Wraps module.py business logic as MCP tools via FastMCP.
Adds version negotiation middleware if module has multiple versions.
"""

import logging
import os
from pathlib import Path

from fastmcp import FastMCP

from module import <ModuleName>Module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("<module-id>-mcp")

# Initialize FastMCP server
mcp = FastMCP("<Module Name> MCP Server")

# Initialize business logic from environment config
module = <ModuleName>Module(
    config_param=os.getenv("CONFIG_PARAM", "default"),
)


@mcp.tool()
async def tool_name(
    required_param: str,
    optional_param: str = "default",
) -> dict:
    """Tool description matching MODULE.yaml.

    Args:
        required_param: Description
        optional_param: Description
    """
    return await module.tool_name(
        required_param=required_param,
        optional_param=optional_param,
    )


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    # Health endpoint (required by MODULE.yaml infrastructure.health_endpoint)
    async def health(request):
        return JSONResponse({
            "status": "healthy",
            "service": "module-<module-id>",
            "version": "<current-version>",
        })

    # Module info endpoint (serves MODULE.yaml metadata)
    MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"

    async def module_info(request):
        import yaml
        with open(MANIFEST_PATH) as f:
            manifest = yaml.safe_load(f)
        return JSONResponse({
            "module_id": manifest["id"],
            "version": manifest["version"],
            "supported_versions": manifest.get("supported_versions", []),
            "tools": [t["name"] for t in manifest.get("tools", [])],
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(1, Route("/module/info", module_info, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
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

# Copy module code
COPY MODULE.yaml .
COPY module.py .
COPY server.py .
COPY version_transformers.py .

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

### Semantic Versioning Rules

Modules use **SemVer 2.0.0** with Druppie-specific interpretations:

| Change Type | Version Bump | Examples |
|------------|-------------|---------|
| **MAJOR** | Breaking change | Rename parameter, change response structure, remove tool |
| **MINOR** | Backwards-compatible addition | New optional parameter, new field in response, new tool |
| **PATCH** | Bug fix / internal improvement | Fix calculation error, improve performance |

### What Constitutes a Breaking Change

Based on research from Stripe, Google AIP-180, and Zalando API guidelines:

**Breaking (requires MAJOR bump)**:
- Removing a tool, parameter, or response field
- Renaming a tool, parameter, or response field
- Changing a field's type (e.g., `string` → `integer`)
- Changing field semantics (e.g., UTC → local time)
- Making an optional input parameter required
- Making a required output field optional/nullable
- Removing an enum value from an input parameter
- Changing a tool's description significantly (breaks LLM callers)

**Non-breaking (MINOR bump)**:
- Adding a new tool
- Adding a new optional input parameter (with default)
- Adding a new field to response output
- Adding a new enum value to an input parameter
- Relaxing validation (e.g., increasing max length)

**Internal (PATCH bump)**:
- Bug fixes that don't change the API contract
- Performance improvements
- Logging changes
- Dependency updates

### Version Negotiation Protocol

When an application calls a module, the version is negotiated via HTTP headers:

**Request** (client specifies expected version):
```
POST /mcp HTTP/1.1
Druppie-Module-Version: 1.2.0
Authorization: Bearer <obo_token>

{"jsonrpc": "2.0", "method": "tools/call", "params": {...}, "id": "1"}
```

**Response** (server reports actual version + transformation info):
```
HTTP/1.1 200 OK
Druppie-Module-Version: 2.0.0
Druppie-Requested-Version: 1.2.0
Druppie-Min-Compatible-Version: 2.0.0
Druppie-Version-Sunset: 2026-09-01
Druppie-Deprecations: image_url -> source (Use 'source' parameter instead)
```

**Version resolution order** (server-side):
1. `Druppie-Module-Version` header (explicit per-request)
2. Application's pinned version (from `application_module_bindings` table)
3. Default to current version (no transformation)

**Error: unsupported version (HTTP 410 Gone)**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "Version 0.9.0 is no longer supported",
    "data": {
      "supported_versions": ["2.0.0", "1.2.0", "1.1.0"],
      "migration_guide_url": "https://docs.druppie.local/modules/ocr/migration/v1-to-v2"
    }
  }
}
```

### Application Version Pinning

The SDK pins applications to module versions:

```python
# Application is pinned to specific module versions
druppie = DruppieClient(
    module_versions={
        "ocr": "1.2.0",           # Pin OCR to v1.2.0
        "classifier": "1.0.0",    # Pin classifier to v1.0.0
    }
)

# SDK sends Druppie-Module-Version: 1.2.0 on every OCR call
# Server transforms v2.0.0 responses back to v1.2.0 format
result = await druppie.ocr.extract("invoice.png")
# result has v1.2.0 shape: {"text": "...", "confidence": 0.95, "bounding_boxes": [...]}
```

---

## 6. Backwards Compatibility Layer

Inspired by Stripe's version change modules. Each breaking change between adjacent versions is encoded as a discrete, testable, composable **VersionTransformer**.

### Architecture

```
Request:  v1.0.0 args → T(1.0→1.1) → T(1.1→1.2) → T(1.2→2.0) → v2.0.0 args
                                                                      ↓
                                                               [tool executes]
                                                                      ↓
Response: v2.0.0 result → T(2.0→1.2) → T(1.2→1.1) → T(1.1→1.0) → v1.0.0 result
```

### Base Classes

File: `druppie/mcp-servers/_shared/version_transformer.py`

```python
"""Version transformation chain for Druppie module servers.

Inspired by Stripe's API versioning (stripe.com/blog/api-versioning).
Each transformer handles the delta between two adjacent versions.
Transformers are composed into a chain that translates across version gaps.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TransformResult:
    """Result of a version transformation."""
    data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    deprecations: list[dict[str, Any]] = field(default_factory=list)


class VersionTransformer(ABC):
    """Handles the delta between two adjacent versions for one tool.

    Naming convention: Transform_<tool>_v<from>_to_v<to>
    Example: Transform_extract_text_v1_2_0_to_v2_0_0
    """

    @property
    @abstractmethod
    def from_version(self) -> str:
        """The older version."""
        ...

    @property
    @abstractmethod
    def to_version(self) -> str:
        """The newer version."""
        ...

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """The tool this transformer applies to."""
        ...

    @abstractmethod
    def transform_request_up(self, args: dict[str, Any]) -> TransformResult:
        """Transform request args: old format → new format."""
        ...

    @abstractmethod
    def transform_response_down(self, result: dict[str, Any]) -> TransformResult:
        """Transform response: new format → old format."""
        ...


class TransformChain:
    """Ordered chain of transformers between two versions.

    Builds the shortest path between any two supported versions
    and applies transformers in sequence.
    """

    def __init__(self):
        self._transformers: dict[tuple[str, str, str], VersionTransformer] = {}
        self._version_order: dict[str, list[str]] = {}

    def register(self, transformer: VersionTransformer) -> None:
        key = (transformer.tool_name, transformer.from_version, transformer.to_version)
        self._transformers[key] = transformer

        tool = transformer.tool_name
        if tool not in self._version_order:
            self._version_order[tool] = []
        for v in [transformer.from_version, transformer.to_version]:
            if v not in self._version_order[tool]:
                self._version_order[tool].append(v)
        self._version_order[tool].sort(
            key=lambda v: tuple(int(x) for x in v.split("."))
        )

    def transform_request(
        self, tool_name: str, from_version: str, to_version: str, args: dict
    ) -> TransformResult:
        """Transform request args from client version to server version."""
        chain = self._get_ascending_chain(tool_name, from_version, to_version)
        current = TransformResult(data=dict(args))
        for transformer in chain:
            step = transformer.transform_request_up(current.data)
            current = TransformResult(
                data=step.data,
                warnings=current.warnings + step.warnings,
                deprecations=current.deprecations + step.deprecations,
            )
        return current

    def transform_response(
        self, tool_name: str, server_version: str, client_version: str, result: dict
    ) -> TransformResult:
        """Transform response from server version down to client version."""
        chain = self._get_descending_chain(tool_name, server_version, client_version)
        current = TransformResult(data=dict(result))
        for transformer in chain:
            step = transformer.transform_response_down(current.data)
            current = TransformResult(
                data=step.data,
                warnings=current.warnings + step.warnings,
                deprecations=current.deprecations + step.deprecations,
            )
        return current

    def _get_ascending_chain(self, tool: str, from_v: str, to_v: str) -> list:
        versions = self._version_order.get(tool, [])
        from_idx, to_idx = versions.index(from_v), versions.index(to_v)
        chain = []
        for i in range(from_idx, to_idx):
            key = (tool, versions[i], versions[i + 1])
            chain.append(self._transformers[key])
        return chain

    def _get_descending_chain(self, tool: str, from_v: str, to_v: str) -> list:
        versions = self._version_order.get(tool, [])
        from_idx, to_idx = versions.index(from_v), versions.index(to_v)
        chain = []
        for i in range(from_idx, to_idx, -1):
            key = (tool, versions[i - 1], versions[i])
            chain.append(self._transformers[key])
        return chain
```

### Concrete Example: OCR Transformers

File: `druppie/mcp-servers/module-ocr/version_transformers.py`

```python
"""OCR module version transformers.

Version timeline:
  v1.0.0: extract_text(image_url, language) → {text, confidence}
  v1.1.0: + optional output_format parameter
  v1.2.0: + bounding_boxes in response
  v2.0.0: image_url→source, flat response→nested document structure
"""

from _shared.version_transformer import VersionTransformer, TransformResult, TransformChain


class Transform_extract_text_v1_0_0_to_v1_1_0(VersionTransformer):
    """Added output_format parameter (non-breaking)."""
    from_version = "1.0.0"
    to_version = "1.1.0"
    tool_name = "extract_text"

    def transform_request_up(self, args):
        result = dict(args)
        result.setdefault("output_format", "plain")
        return TransformResult(data=result)

    def transform_response_down(self, result):
        return TransformResult(data=result)  # Response unchanged


class Transform_extract_text_v1_1_0_to_v1_2_0(VersionTransformer):
    """Added bounding_boxes to response (non-breaking)."""
    from_version = "1.1.0"
    to_version = "1.2.0"
    tool_name = "extract_text"

    def transform_request_up(self, args):
        return TransformResult(data=args)  # Input unchanged

    def transform_response_down(self, result):
        cleaned = dict(result)
        cleaned.pop("bounding_boxes", None)  # Strip for v1.1.0 clients
        return TransformResult(data=cleaned)


class Transform_extract_text_v1_2_0_to_v2_0_0(VersionTransformer):
    """BREAKING: image_url→source, flat→nested response."""
    from_version = "1.2.0"
    to_version = "2.0.0"
    tool_name = "extract_text"

    def transform_request_up(self, args):
        result = dict(args)
        deprecations = []
        if "image_url" in result:
            result["source"] = result.pop("image_url")
            deprecations.append({
                "parameter": "image_url",
                "replacement": "source",
                "message": "Use 'source' instead. 'image_url' stops working in v3.0.0.",
            })
        return TransformResult(data=result, deprecations=deprecations)

    def transform_response_down(self, result):
        """Convert nested v2.0 response back to flat v1.2 format."""
        document = result.get("document", {})
        pages = result.get("pages", [])
        all_boxes = []
        for page in pages:
            all_boxes.extend(page.get("bounding_boxes", []))

        flat = {
            "text": document.get("text", ""),
            "confidence": result.get("confidence", 0.0),
        }
        if all_boxes:
            flat["bounding_boxes"] = all_boxes
        return TransformResult(data=flat)


def build_ocr_transform_chain() -> TransformChain:
    """Build at server startup. Used for every version-negotiated request."""
    chain = TransformChain()
    chain.register(Transform_extract_text_v1_0_0_to_v1_1_0())
    chain.register(Transform_extract_text_v1_1_0_to_v1_2_0())
    chain.register(Transform_extract_text_v1_2_0_to_v2_0_0())
    return chain
```

---

## 7. Module Registry

### Database Tables

File: `druppie/db/models/module_registry.py`

```python
"""Module registry database models.

Tables:
  modules                    — Installed module instances
  module_versions            — Every published version of a module
  module_tool_schemas        — Tool schemas per version (JSON Schema as Text)
  application_module_bindings — Which app uses which module version
  module_deprecation_notices — Active deprecation notices
"""

from uuid import uuid4
from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text,
    Boolean, Float, UniqueConstraint, Index,
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
    current_version = Column(String(20), nullable=False)
    min_compatible_version = Column(String(20), nullable=False)
    container_url = Column(String(500), nullable=False)
    container_port = Column(Integer, default=9010)
    status = Column(String(20), default="active")   # active, disabled, deprecated
    is_core = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions = relationship("ModuleVersion", back_populates="module", cascade="all, delete-orphan")
    bindings = relationship("ApplicationModuleBinding", back_populates="module", cascade="all, delete-orphan")


class ModuleVersion(Base):
    """A published version of a module."""
    __tablename__ = "module_versions"
    __table_args__ = (UniqueConstraint("module_id", "version", name="uq_module_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    version = Column(String(20), nullable=False)
    release_notes = Column(Text)
    is_breaking = Column(Boolean, default=False)
    status = Column(String(20), default="supported")  # supported, deprecated, sunset
    sunset_date = Column(DateTime(timezone=True))
    has_transformers = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    module = relationship("Module", back_populates="versions")
    tool_schemas = relationship("ModuleToolSchema", back_populates="module_version", cascade="all, delete-orphan")


class ModuleToolSchema(Base):
    """Tool input/output schema at a specific version.

    Stores JSON Schema as Text (not JSONB) — read-only, never queried by sub-field.
    """
    __tablename__ = "module_tool_schemas"
    __table_args__ = (
        UniqueConstraint("module_version_id", "tool_name", name="uq_version_tool"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_version_id = Column(UUID(as_uuid=True), ForeignKey("module_versions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    tool_version = Column(String(20), nullable=False)
    description = Column(Text)
    input_schema_json = Column(Text, nullable=False)
    output_schema_json = Column(Text, nullable=False)
    requires_approval = Column(Boolean, default=False)
    required_role = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    module_version = relationship("ModuleVersion", back_populates="tool_schemas")


class ApplicationModuleBinding(Base):
    """Tracks which application is pinned to which module version."""
    __tablename__ = "application_module_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "module_id", name="uq_project_module"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    pinned_version = Column(String(20), nullable=False)
    auto_upgrade_minor = Column(Boolean, default=True)
    auto_upgrade_major = Column(Boolean, default=False)
    last_called_at = Column(DateTime(timezone=True))
    total_calls = Column(Integer, default=0)
    total_cost_cents = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    module = relationship("Module", back_populates="bindings")


class ModuleDeprecationNotice(Base):
    """Active deprecation notices for tools/parameters."""
    __tablename__ = "module_deprecation_notices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    scope = Column(String(20), nullable=False)       # "parameter", "tool", "module"
    tool_name = Column(String(100))
    parameter_name = Column(String(100))
    deprecated_in_version = Column(String(20), nullable=False)
    removed_in_version = Column(String(20))
    replacement = Column(String(255))
    message = Column(Text, nullable=False)
    sunset_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)
```

### Registry Service

The registry reads `MODULE.yaml` files and populates the database:

```python
# druppie/services/module_registry_service.py

class ModuleRegistryService:
    """Manages module registration, version tracking, and discovery."""

    async def register_module(self, manifest_path: str) -> Module:
        """Register a module from its MODULE.yaml manifest.

        1. Parse MODULE.yaml
        2. Create/update Module record
        3. Create ModuleVersion records for each supported_version
        4. Create ModuleToolSchema records for each tool at each version
        5. Create ModuleDeprecationNotice records
        """
        ...

    async def get_module(self, module_id: str) -> ModuleDetail:
        """Get module with all versions and tool schemas."""
        ...

    async def list_modules(self, category: str = None) -> list[ModuleSummary]:
        """List all installed modules (Summary pattern)."""
        ...

    async def bind_application(
        self, project_id: UUID, module_id: str, version: str
    ) -> ApplicationModuleBinding:
        """Pin an application to a specific module version."""
        ...

    async def get_binding(
        self, project_id: UUID, module_id: str
    ) -> ApplicationModuleBinding | None:
        """Get the version an application is pinned to."""
        ...

    async def check_impact(self, module_id: str, version: str) -> dict:
        """Before sunsetting a version, check which apps still use it."""
        ...
```

---

## 8. Druppie SDK

The SDK is a lightweight Python package (~50KB) included in every Druppie-generated application. It handles module calls, authentication, versioning, cost tracking, and deprecation warnings.

### Package Structure

```
druppie-sdk/
├── druppie_sdk/
│   ├── __init__.py          # DruppieClient, DruppieAuth, health_router
│   ├── client.py            # Main client with module calling
│   ├── auth.py              # OBO token exchange with Keycloak
│   ├── deprecation.py       # Deprecation tracking and warnings
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
        self.module_versions = module_versions or {}  # Pin per-module versions
        self.modules = ModuleClient(self)
        self.costs = CostTracker()
        self._deprecations = DeprecationTracker()
        self._auth = DruppieAuth()

    @property
    def ocr(self) -> OCRAccessor:
        """Typed OCR module accessor."""
        return OCRAccessor(self)

    @property
    def classifier(self) -> ClassifierAccessor:
        """Typed classifier module accessor."""
        return ClassifierAccessor(self)

    def deprecation_report(self) -> list[dict]:
        """Get all deprecation notices from this session."""
        return self._deprecations.report()


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

        Handles: version pinning, OBO auth, retries, cost tracking, deprecation warnings.
        """
        headers = {"Content-Type": "application/json"}

        # Version pinning
        pinned = self._client.module_versions.get(module)
        if pinned:
            headers["Druppie-Module-Version"] = pinned

        # Auth
        if self._client.session_token:
            token = await self._client._auth.get_token(self._client.session_token)
            headers["Authorization"] = f"Bearer {token}"

        # Idempotency
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Make request with retry
        result = await self._request_with_retry(module, tool, args, headers)

        # Track costs
        if result.get("cost_cents"):
            self._client.costs.record(module, tool, result["cost_cents"])

        # Process deprecation warnings from response headers
        if hasattr(result, "_response_headers"):
            self._client._deprecations.process_response_headers(
                module, tool, result["_response_headers"]
            )

        return result

    async def _request_with_retry(self, module, tool, args, headers, max_retries=3):
        """Exponential backoff with jitter (AWS SDK pattern)."""
        import random, asyncio, httpx

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    response = await http.post(
                        f"{self._client.gateway_url}/api/modules/{module}/call",
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

The gateway is a lightweight FastAPI service that sits between applications and module servers. It handles routing, authentication, rate limiting, and cost tracking in one place.

### Option: Extend the Existing Backend

Instead of a separate gateway, add `/api/modules/` routes to the existing Druppie backend:

```python
# druppie/api/routes/modules.py

from fastapi import APIRouter, Request, Depends
from druppie.services.module_registry_service import ModuleRegistryService
from druppie.execution.mcp_http import MCPHttp

router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.post("/{module_id}/call")
async def call_module(
    module_id: str,
    request: Request,
    registry: ModuleRegistryService = Depends(),
    mcp: MCPHttp = Depends(),
):
    """Route a module call through the gateway.

    1. Validate OBO token and extract user identity
    2. Resolve module URL from registry
    3. Apply version negotiation (pin or header)
    4. Forward to module MCP server
    5. Record cost and usage
    """
    body = await request.json()
    tool = body["tool"]
    args = body["arguments"]

    # Get module info
    module = await registry.get_module(module_id)
    if not module:
        return {"error": f"Module '{module_id}' not found"}, 404

    # Version negotiation
    requested_version = request.headers.get("Druppie-Module-Version")

    # Forward to module MCP server
    result = await mcp.call(
        server=module_id,
        tool=tool,
        args=args,
        headers={"Druppie-Module-Version": requested_version} if requested_version else {},
    )

    # Record usage
    user_id = request.state.user_id  # From auth middleware
    await registry.record_usage(
        user_id=user_id,
        module_id=module_id,
        tool=tool,
        cost_cents=result.get("cost_cents", 0),
    )

    return result


@router.get("/{module_id}/info")
async def module_info(module_id: str, registry: ModuleRegistryService = Depends()):
    """Get module metadata including supported versions and tools."""
    return await registry.get_module(module_id)


@router.get("/")
async def list_modules(category: str = None, registry: ModuleRegistryService = Depends()):
    """List all available modules."""
    return await registry.list_modules(category=category)
```

---

## 10. Database Schema Isolation

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

Module's own tables:

```sql
-- In module_ocr schema
CREATE TABLE module_ocr.extraction_jobs (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,          -- FK to public.sessions (read-only)
    user_id UUID NOT NULL,             -- From OBO token
    source VARCHAR(500) NOT NULL,
    language VARCHAR(10) DEFAULT 'auto',
    extracted_text TEXT,
    confidence FLOAT,
    cost_cents FLOAT DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 11. Module Lifecycle

### From Proposal to Running

```
0. ACCEPT      Module proposal evaluated against acceptance criteria
                AR validates: reuse, genericity, no overlap, ownership
                (See "Module Acceptance" in modules.md)

1. DEVELOP     Write module.py, server.py, MODULE.yaml, Dockerfile
                Test locally: python server.py (no Docker needed)

2. REGISTER    Add docker-compose service + mcp_config.yaml entry
                Run: ModuleRegistryService.register_module("MODULE.yaml")
                → Creates Module, ModuleVersion, ModuleToolSchema records

3. DEPLOY      docker compose --profile dev up -d module-<name>
                Container starts, health check passes

4. CONFIGURE   Agent YAML files updated to include module tools
                Injection rules added to mcp_config.yaml

5. AVAILABLE   Module tools appear in agent tool lists
                SDK can call module via gateway
```

### Updating a Module

**Non-breaking update (MINOR/PATCH)**:
1. Update module.py, server.py
2. Bump version in MODULE.yaml
3. Rebuild and restart container
4. Run `register_module()` to update registry
5. All applications continue working — no changes needed

**Breaking update (MAJOR)**:
1. Update module.py, server.py with new interface
2. Add version transformer for old→new translation
3. Add old version to `schema_history` in MODULE.yaml
4. Add old version to `supported_versions` with sunset date
5. Write migration guide in `migrations/`
6. Bump major version in MODULE.yaml
7. Rebuild and restart container
8. Run `register_module()` to update registry
9. Applications pinned to old version continue working via transformers
10. SDK logs deprecation warnings for old-version callers
11. After sunset date, old version returns HTTP 410

### Deprecation Timeline

```
Day 0:    v2.0.0 released. v1.2.0 and v1.1.0 added to supported_versions.
          Transformers serve old clients transparently.
          SDK warns: "You're using v1.2.0. Please upgrade to v2.0.0."

Month 3:  v1.1.0 sunset date reached.
          Server returns HTTP 410 for v1.1.0 requests.
          v1.1.0 removed from supported_versions.

Month 6:  v1.2.0 sunset date reached.
          Server returns HTTP 410 for v1.2.0 requests.
          All v1.x support ends.
          Transformers can be removed from codebase.
```

---

## 12. Complete Example: OCR Module

### v1.0.0 — Initial Release

**MODULE.yaml**:
```yaml
id: ocr
name: OCR Module
version: "1.0.0"
min_compatible_version: "1.0.0"
supported_versions: ["1.0.0"]
tools:
  - name: extract_text
    tool_version: "1.0.0"
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
infrastructure:
  port: 9010
```

**module.py**:
```python
class OCRModule:
    async def extract_text(self, image_url: str, language: str = "auto") -> dict:
        result = self._run_ocr(image_url, language)
        return {"text": result["text"], "confidence": result["confidence"]}
```

**SDK usage**:
```python
druppie = DruppieClient()
result = await druppie.ocr.extract("invoice.png")
# {"text": "Invoice #1234...", "confidence": 0.95}
```

### v1.1.0 — Add `output_format` (non-breaking)

**MODULE.yaml changes**: Add `output_format` to input_schema, add `"1.0.0"` to schema_history.

**module.py changes**: Add `output_format` parameter with default `"plain"`.

**version_transformers.py**: First transformer (defaults `output_format` for v1.0 clients).

**Existing SDK callers**: No changes needed. `output_format` defaults to `"plain"`.

### v1.2.0 — Add `bounding_boxes` to response (non-breaking)

**MODULE.yaml changes**: Add `bounding_boxes` to output_schema, add `"1.1.0"` to schema_history.

**module.py changes**: Include `bounding_boxes` in return dict.

**version_transformers.py**: Second transformer (strips `bounding_boxes` for v1.1 clients).

**Existing SDK callers**: No changes needed. Extra field is ignored or used optionally.

### v2.0.0 — Rename `image_url`→`source`, restructure response (BREAKING)

**MODULE.yaml changes**:
```yaml
version: "2.0.0"
min_compatible_version: "2.0.0"
supported_versions: ["2.0.0", "1.2.0", "1.1.0"]
version_sunset_dates:
  "1.1.0": "2026-06-01"
  "1.2.0": "2026-09-01"
```

**module.py changes**:
```python
class OCRModule:
    async def extract_text(self, source: str, language: str = "auto", output_format: str = "plain") -> dict:
        result = self._run_ocr(source, language)
        return {
            "document": {"text": result["text"], "format": output_format, "language": result["detected_language"]},
            "confidence": result["confidence"],
            "pages": [{"page_number": 1, "text": result["text"], "bounding_boxes": result.get("bounding_boxes", [])}],
        }
```

**version_transformers.py**: Third transformer (renames `image_url`→`source`, flattens nested response).

**SDK callers pinned to v1.2.0**:
```python
# This STILL WORKS — server transforms v2.0 response back to v1.2 format
druppie = DruppieClient(module_versions={"ocr": "1.2.0"})
result = await druppie.ocr.extract("invoice.png")
# {"text": "...", "confidence": 0.95, "bounding_boxes": [...]}
# SDK logs: WARNING: module 'ocr', parameter 'image_url' is deprecated. Use 'source'.
```

**SDK callers upgrading to v2.0.0**:
```python
druppie = DruppieClient(module_versions={"ocr": "2.0.0"})
result = await druppie.ocr.extract("invoice.png")
# {"document": {"text": "...", "format": "plain", "language": "nl"}, "confidence": 0.95, "pages": [...]}
```

---

## Sources

### Versioning Strategy Research
- [Stripe: APIs as infrastructure — future-proofing with versioning](https://stripe.com/blog/api-versioning)
- [Stripe API Versioning Reference](https://docs.stripe.com/api/versioning)
- [Kubernetes Deprecation Policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)
- [AWS SDK Locking API Versions](https://docs.aws.amazon.com/sdk-for-javascript/v2/developer-guide/locking-api-versions.html)
- [AWS Lambda Versioning](https://docs.aws.amazon.com/lambda/latest/dg/configuration-versions.html)

### Backwards Compatibility
- [Google AIP-180: Backwards Compatibility](https://google.aip.dev/180)
- [Zalando RESTful API Guidelines — Compatibility](https://github.com/zalando/restful-api-guidelines/blob/main/chapters/compatibility.adoc)
- [GraphQL Schema Design — Evolution Without Versioning](https://graphql.org/learn/schema-design/)

### MCP Protocol
- [MCP Versioning Specification](https://modelcontextprotocol.io/specification/versioning)
- [MCP Tool Versioning Discussion (#1915)](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1915)
- [The Weak Point in MCP — API Versioning](https://nordicapis.com/the-weak-point-in-mcp-nobodys-talking-about-api-versioning/)

### Authentication
- [Keycloak Standard Token Exchange (RFC 8693)](https://www.keycloak.org/2025/05/standard-token-exchange-kc-26-2)

### Database Patterns
- [PostgreSQL Schemas Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [Crunchy Data: PostgreSQL Multi-Tenancy](https://www.crunchydata.com/blog/designing-your-postgres-database-for-multi-tenancy)
