# MCP-to-Module Migration — Design Spec

> **Status**: Approved design
> **Date**: 2026-03-19
> **Branch**: `feature/mcp-to-module-migration`
> **Prerequisite**: `docs/module-specification.md`, `docs/modules-research-and-decisions.md`

---

## Overview

Migrate all 7 MCP servers (coding, docker, hitl, filesearch, web, archimate, registry) to the module convention defined in `docs/module-specification.md`. Simultaneously refactor the client side (druppie core) to eliminate tool definition duplication by using MCP `tools/list` as the single source of truth, and replace the custom `MCPHttp` client with FastMCP Client.

**Scope**: One branch, one PR, all 7 servers + client-side refactor. No hybrid state.

---

## 1. Server-Side Restructure

### Directory Change

Each server moves from flat structure to versioned module convention:

**Before:**
```
druppie/mcp-servers/coding/
├── server.py          # FastMCP app + tools + health
├── module.py          # Business logic
├── testing_module.py
├── mermaid_validator.py
└── retry_module.py
```

**After:**
```
druppie/mcp-servers/module-coding/
├── MODULE.yaml            # id, latest_version, versions
├── Dockerfile
├── requirements.txt
├── server.py              # Router: mounts v1 at /v1, /mcp → latest, /health
├── v1/
│   ├── __init__.py
│   ├── tools.py           # FastMCP app with @mcp.tool() — SINGLE SOURCE OF TRUTH
│   ├── module.py          # Business logic (CodingModule)
│   ├── testing_module.py
│   ├── mermaid_validator.py
│   └── retry_module.py
└── tests/
```

### All 7 Servers

| Server | Module ID | Type | Port |
|--------|-----------|------|------|
| coding | `coding` | `core` | 9001 |
| docker | `docker` | `core` | 9002 |
| hitl | `hitl` | `core` | 9003 |
| filesearch | `filesearch` | `core` | 9004 |
| web | `web` | `core` | 9005 |
| archimate | `archimate` | `core` | 9006 |
| registry | `registry` | `core` | 9007 |

### MODULE.yaml

Each server gets a minimal manifest:

```yaml
id: coding
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

### server.py — Router

Rewritten per the spec template: reads `MODULE.yaml`, mounts `v1/tools.py` MCP app at `/v1` and `/` (latest), serves `/health` with module metadata.

### v1/tools.py — Single Source of Truth

The `FastMCP` instance moves here with `name`, `version`, `instructions`, and all `@mcp.tool()` decorators. Each tool includes `meta` with `module_id`, `version`, and optionally `pre_validate` and `resource_metrics`.

### v1/module.py — Business Logic

Existing `module.py` files move into `v1/`. No logic changes — just a directory move.

---

## 2. Client-Side Refactor — Eliminating Duplication

### What Gets Removed

- **`druppie/tools/params/*.py`** — all 7 files with hand-written Pydantic parameter models
- **`PARAMS_MODEL_MAP`** in `tool_registry.py` — the 50+ line manual mapping dict
- **Tool descriptions and parameter schemas from `mcp_config.yaml`** — only URLs, `type`, injection rules, and approval config remain

### What `mcp_config.yaml` Shrinks To

```yaml
coding:
  url: ${MCP_CODING_URL:-http://module-coding:9001}
  type: core
  inject:
    session_id:
      from: session.id
      hidden: true
      tools: [read_file, write_file, make_design, batch_write_files, list_dir, delete_file, run_git, create_pull_request, merge_pull_request]
    project_id:
      from: project.id
      hidden: true
    repo_name:
      from: project.repo_name
      hidden: true
      tools: [read_file, write_file, make_design, batch_write_files, list_dir, delete_file, run_git, create_pull_request, merge_pull_request]
    repo_owner:
      from: project.repo_owner
      hidden: true
      tools: [read_file, write_file, make_design, batch_write_files, list_dir, delete_file, run_git, create_pull_request, merge_pull_request]
  tools:
    - name: read_file
      requires_approval: false
    - name: write_file
      requires_approval: false
    - name: make_design
      requires_approval: false
    - name: merge_pull_request
      requires_approval: true
      required_role: developer
    # ... etc — name + approval only, no descriptions or parameters
```

### How `ToolRegistry` Changes

At startup (or lazy first use), for each server in `mcp_config.yaml`:

1. Connect via FastMCP Client
2. Call `list_tools()` → get tool names, descriptions, JSON schemas, `meta`
3. Cache as `ToolDefinition` objects (with JSON schema instead of Pydantic model)
4. Merge with approval config and injection rules from `mcp_config.yaml`

### Validation Changes

- `ToolDefinition.validate_arguments()` uses `jsonschema.validate()` against the cached JSON schema instead of `pydantic_model.model_validate()`
- Normalization logic (e.g., `"null"` → `None`) becomes a generic pre-processing step on the raw dict

### Builtin Tools

`BUILTIN_TOOL_DEFS` in `builtin_tools.py` stays as-is — these are not MCP tools, they run in-process and have no server to discover from.

---

## 3. FastMCP Client Replacement

### What Gets Replaced

`druppie/core/mcp_client.py` (custom `MCPHttp` class with hand-rolled JSON-RPC) is replaced by FastMCP Client — the same `fastmcp` library already used for servers.

```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

transport = StreamableHttpTransport(url="http://module-coding:9001/v1/mcp")
async with Client(transport) as client:
    tools = await client.list_tools()
    result = await client.call_tool("read_file", {"path": "main.py"})
```

### DruppieToolExecutor Wrapper

A new wrapper replaces the current MCPHttp usage:

```python
class DruppieToolExecutor:
    """Wraps FastMCP Client with Druppie-specific features.

    1. Argument injection (session_id, project_id, etc. from mcp_config.yaml rules)
    2. Pre-validation (calls tool's validate endpoint if meta.pre_validate is set)
    3. Approval checking (existing flow, unchanged)
    4. Execution via FastMCP Client
    """
```

### Connection Lifecycle

- On first use per server, create a FastMCP Client session via `StreamableHttpTransport`
- Cache the session (reuse across tool calls to the same server)
- `list_tools()` called once per session and cached in `ToolRegistry`

### What Stays the Same

- Injection logic (reads `inject` rules from `mcp_config.yaml`, adds hidden params before sending)
- Approval flow (checks `requires_approval`, `required_role`, presents to user)
- The overall tool execution flow: validate → inject → pre-validate → approve → execute → record

---

## 4. Pre-Validation Endpoints

### Pattern

Modules can expose validation tools that the core calls before the approval gate. Discovered automatically via `meta.pre_validate` in `tools/list`.

### Server Side

```python
# module-coding/v1/tools.py

@mcp.tool(
    name="make_design",
    description="Write a design document with Mermaid syntax validation.",
    meta={
        "module_id": "coding",
        "version": "1.0.0",
        "pre_validate": "validate_design",
    },
)
async def make_design(path: str, content: str, ...) -> dict:
    ...

@mcp.tool(
    name="validate_design",
    description="Validate Mermaid syntax in design content. Returns errors if any.",
    meta={
        "module_id": "coding",
        "version": "1.0.0",
        "internal": True,  # hidden from LLM tool lists
    },
)
async def validate_design(content: str) -> dict:
    errors = validate_mermaid_in_markdown(content)
    if errors:
        return {"valid": False, "errors": [{"line": e.line_number, "rule": e.rule, "message": e.message} for e in errors]}
    return {"valid": True}
```

### Client Side

Generic in `DruppieToolExecutor`:

```
For any tool call:
  1. Validate args (JSON schema from cached tools/list)
  2. Check meta.pre_validate → if set, call that tool on the same server
     → if validation fails, return error to LLM (skip approval)
  3. Check approval requirements → present to user if needed
  4. Execute via FastMCP Client
```

### Key Properties

- No hardcoded `if tool_name == "make_design"` in core — fully generic
- No cross-boundary imports of server code
- `internal: True` in meta means core filters the tool out of LLM-visible tool lists
- Any module can add pre-validation for any tool without core changes

---

## 5. Registry Module Evolution

### Current State

Reads `mcp_config.yaml` and parses `builtin_tools.py` with AST to serve tool metadata statically.

### New State

Live discovery layer that queries other modules via FastMCP Client:

```python
# module-registry/v1/module.py

class RegistryModule:
    async def get_mcp_server(self, server_name: str) -> dict:
        """Query the actual module via MCP tools/list."""
        url = self._resolve_url(server_name)
        transport = StreamableHttpTransport(url=f"{url}/mcp")
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {
                "server_name": server_name,
                "tools": [{"name": t.name, "description": t.description, ...} for t in tools],
            }
```

### What Changes

- Tool schemas come from live `list_tools()` calls instead of re-parsing YAML
- Results cached with TTL to avoid hammering other modules on every query
- Agent definitions and skills still loaded from files (no MCP equivalent)
- Builtin tools still loaded from `builtin_tools.py`

### What Stays

- Same tools: `list_components`, `get_agent`, `get_skill`, `get_mcp_server`, `get_tool`
- Same purpose: single discovery point for agents

---

## 6. Docker Compose & Infrastructure

### Service Renames

| Old Service | New Service | Container Name | Port |
|-------------|-------------|----------------|------|
| `mcp-coding` | `module-coding` | `druppie-module-coding` | 9001 |
| `mcp-docker` | `module-docker` | `druppie-module-docker` | 9002 |
| `mcp-hitl` | `module-hitl` | `druppie-module-hitl` | 9003 |
| `mcp-filesearch` | `module-filesearch` | `druppie-module-filesearch` | 9004 |
| `mcp-web` | `module-web` | `druppie-module-web` | 9005 |
| `mcp-archimate` | `module-archimate` | `druppie-module-archimate` | 9006 |
| `mcp-registry` | `module-registry` | `druppie-module-registry` | 9007 |

### Docker Compose Changes

```yaml
module-coding:
  build:
    context: ./druppie/mcp-servers/module-coding
  container_name: druppie-module-coding
  # ports, healthcheck, volumes, env vars stay the same
```

### URL Updates in mcp_config.yaml

```yaml
coding:
  url: ${MCP_CODING_URL:-http://module-coding:9001}
```

### Ports and Health Checks

Unchanged. Same ports, same `/health` endpoint pattern.

---

## 7. What Gets Deleted

### Files Deleted

- `druppie/tools/params/coding.py`
- `druppie/tools/params/docker.py`
- `druppie/tools/params/testing.py`
- `druppie/tools/params/builtin.py`
- `druppie/tools/params/archimate.py`
- `druppie/tools/params/registry.py`
- `druppie/tools/params/__init__.py`
- `druppie/core/mcp_client.py` (custom MCPHttp)
- Old server directories (`druppie/mcp-servers/coding/`, `docker/`, `hitl/`, `filesearch/`, `web/`, `archimate/`, `registry/`)

### Files Heavily Refactored

- `druppie/core/tool_registry.py` — discovers from `tools/list` instead of YAML + PARAMS_MODEL_MAP
- `druppie/core/mcp_config.yaml` — stripped of descriptions and parameter schemas, gains `type` field
- `druppie/core/mcp_config.py` — simplified to only parse URLs, types, injection, approval
- `druppie/domain/tool.py` — `ToolDefinition` uses JSON schema instead of Pydantic `params_model`
- `druppie/execution/tool_executor.py` — uses FastMCP Client, generic pre-validation, removes hardcoded make_design check
- `druppie/mcp-servers/module-registry/v1/module.py` — live discovery via FastMCP Client

### Files Unchanged

- `druppie/agents/builtin_tools.py` — builtin tools stay as-is
- `druppie/agents/definitions/*.yaml` — agent definitions unchanged
- Frontend — unchanged

---

## 8. Verification Criteria

- [ ] All 7 Docker containers start and health checks pass
- [ ] `tools/list` on each server returns correct tool schemas with meta
- [ ] Tool calls work end-to-end: injection → pre-validation → approval → execution
- [ ] Pre-validation works for `make_design` (Mermaid syntax check via validate endpoint)
- [ ] Registry server returns live tool metadata from other modules
- [ ] No duplicate tool descriptions remain (grep confirms single source per tool)
- [ ] `mcp_config.yaml` contains no tool descriptions or parameter schemas
- [ ] `druppie/tools/params/` directory is gone
- [ ] `druppie/core/mcp_client.py` is gone
- [ ] Existing tests pass (update as needed for new paths/imports)
