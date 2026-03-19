# MCP-to-Module Migration — Design Spec

> **Status**: Approved design
> **Date**: 2026-03-19
> **Branch**: `feature/mcp-to-module-migration`
> **Prerequisite**: `docs/module-specification.md`, `docs/modules-research-and-decisions.md`

---

## Overview

Migrate all 7 MCP servers to the module convention defined in `docs/module-specification.md`. Simultaneously refactor the client side (druppie core) to eliminate tool definition duplication by using MCP `tools/list` as the single source of truth. Consolidate the two overlapping MCP client classes (`MCPClient` and `MCPHttp`) into a single clean implementation.

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

| Server | Module ID | Type | Port | Notes |
|--------|-----------|------|------|-------|
| coding | `coding` | `core` | 9001 | Largest server (2000+ lines), has `_internal_*` tools |
| docker | `docker` | `core` | 9002 | |
| hitl | `hitl` | `core` | 9003 | MCP server for ask_question/ask_choice. Note: the HITL *builtin tools* in `builtin_tools.py` route to this server via `tool_executor._execute_hitl_tool()` — the server itself is a real MCP server that gets migrated |
| filesearch | `filesearch` | `core` | 9004 | Currently has no entry in `mcp_config.yaml` — one will be added |
| web | `web` | `core` | 9005 | Currently listed as `bestand-zoeker` in `mcp_config.yaml` — renamed to `web` for consistency with directory name |
| archimate | `archimate` | `core` | 9006 | |
| registry | `registry` | `core` | 9007 | Evolves to live discovery (see Section 5) |

### Naming Clarification: `bestand-zoeker` → `web`

The current `mcp_config.yaml` has an entry called `bestand-zoeker` pointing to `http://mcp-web:9005`. The Docker service is `mcp-web`, the directory is `web/`. The config key is renamed from `bestand-zoeker` to `web` for consistency. All references in agent YAML definitions that use `bestand-zoeker` must be updated to `web`.

### `filesearch` Addition to Config

The `filesearch` server (port 9004) exists as a Docker service and directory but has no entry in `mcp_config.yaml`. An entry will be added. Any tools that `filesearch` exposes will be discovered via `tools/list`.

### Internal Tools (`_internal_*`)

The coding server has `_internal_revert_to_commit` and `_internal_close_pull_request` tools called directly by the backend, not by agents. These get `meta.internal: True` so the `ToolRegistry` filters them from LLM-visible tool lists but they remain callable by the backend.

### MODULE.yaml

Each server gets a minimal manifest:

```yaml
id: coding
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

### server.py — Router

Rewritten per the spec template: reads `MODULE.yaml`, mounts `v1/tools.py` MCP app at `/v1` and `/` (latest), serves `/health` with module metadata. Since all servers start with only v1, the router is simple (no multi-version routing yet).

### v1/tools.py — Single Source of Truth

The `FastMCP` instance moves here with `name`, `version`, `instructions`, and all `@mcp.tool()` decorators. Each tool includes `meta` with `module_id`, `version`, and optionally `pre_validate`, `internal`, and `resource_metrics`.

**Note on `_meta` return pattern:** Adding `_meta` with `module_id`, `module_version`, and `usage` to tool responses is part of the module spec but is **out of scope** for this migration. The `_meta` pattern is for SDK/usage tracking (future work). This migration focuses on structure and discovery.

### v1/module.py — Business Logic

Existing `module.py` files move into `v1/`. No logic changes — just a directory move.

---

## 2. Client-Side Refactor — Eliminating Duplication

### What Gets Removed

- **`druppie/tools/params/*.py`** — all 7 files with hand-written Pydantic parameter models
- **`PARAMS_MODEL_MAP`** in `tool_registry.py` — the 50+ line manual mapping dict
- **Tool descriptions and parameter schemas from `mcp_config.yaml`** — descriptions are dropped entirely, parameter schemas are dropped entirely. Only URLs, `type`, injection rules, and approval config remain.

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

1. Connect via FastMCP Client (`StreamableHttpTransport`)
2. Call `list_tools()` → get tool names, descriptions, JSON schemas, `meta`
3. Filter out tools with `meta.internal: True` from LLM-visible lists (but keep them callable)
4. Cache as `ToolDefinition` objects (with JSON schema instead of Pydantic model)
5. Merge with approval config and injection rules from `mcp_config.yaml`

**Note:** Some tools (like `archimate:list_models`) currently lack validation entirely because they have no `PARAMS_MODEL_MAP` entry. After migration, `tools/list` will provide their JSON schema, so validation will be added where none existed before. This could surface latent issues if agents send arguments that don't match the server-side schema.

### Validation Changes

- `ToolDefinition.validate_arguments()` uses `jsonschema.validate()` against the cached JSON schema instead of `pydantic_model.model_validate()`
- Normalization logic (e.g., `"null"` → `None`) becomes a generic pre-processing step on the raw dict
- **New dependency**: `jsonschema` package added to `druppie/requirements.txt`

### Builtin Tools

`BUILTIN_TOOL_DEFS` in `builtin_tools.py` stays as-is — these are not MCP tools, they run in-process and have no server to discover from.

---

## 3. Client Consolidation

### Current State: Two Overlapping Clients

The codebase has two MCP client implementations, both already using FastMCP Client internally:

| Class | File | Used by | Responsibilities |
|-------|------|---------|-----------------|
| `MCPHttp` | `druppie/execution/mcp_http.py` | `ToolExecutor`, `orchestrator.py`, `mcp_bridge.py`, `workspace.py`, `deployments.py`, `revert_service.py`, `runtime.py` | Clean HTTP client: `call()`, `list_tools()`, result parsing, timeout handling |
| `MCPClient` | `druppie/core/mcp_client.py` | `mcps.py` API routes, `deployment_service.py` | Overlapping client with approval logic, retry logic, error classification, config loading, DB session |

Both import `from fastmcp import Client` and `StreamableHttpTransport`. Neither is "custom JSON-RPC" — both already use FastMCP. The duplication is in the wrapper logic.

### What Changes

**Delete `druppie/core/mcp_client.py`** — the `MCPClient` class is the older, larger implementation (848 lines) that overlaps with `ToolExecutor` + `MCPHttp`. Its unique features:

- Error classification (`classify_error`) → move to `druppie/execution/errors.py` (reusable)
- Approval logic → already handled by `ToolExecutor`
- Retry with exponential backoff → already in `MCPHttp` or add to it
- `to_openai_tools_async()` → replaced by `ToolRegistry` discovering from `tools/list`

**Refactor `druppie/execution/mcp_http.py`** — `MCPHttp` stays as the single MCP client wrapper. Enhanced with:

- Error classification (moved from `MCPClient`)
- Retry with exponential backoff (moved from `MCPClient`)

**Update all consumers of `MCPClient`:**

- `druppie/api/routes/mcps.py` → use `MCPConfig` directly (for config) + `MCPHttp` (for `list_tools()`)
- `druppie/services/deployment_service.py` → use `MCPHttp`

### Connection Lifecycle

The current `MCPHttp.call()` creates a new `async with client:` context per call. This is correct for stateless HTTP — each call opens a connection, sends the request, and closes. No persistent sessions to manage, no stale connection issues.

For `list_tools()` calls during startup/discovery, the same pattern applies: connect, fetch, close. Results are cached in `ToolRegistry`.

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

Generic in `ToolExecutor`:

```
For any tool call:
  1. Validate args (JSON schema from cached tools/list)
  2. Check meta.pre_validate → if set, call that tool on the same server via MCPHttp
     → if validation fails, return error to LLM (skip approval)
  3. Check approval requirements → present to user if needed
  4. Execute via MCPHttp
```

This replaces the hardcoded `_validate_make_design_content()` method in `tool_executor.py` that currently imports `mermaid_validator.py` directly from the coding server directory.

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
  type: core
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
- `druppie/core/mcp_client.py` (overlapping MCPClient — consolidated into MCPHttp)
- Old server directories (`druppie/mcp-servers/coding/`, `docker/`, `hitl/`, `filesearch/`, `web/`, `archimate/`, `registry/`)

### Files Heavily Refactored

- `druppie/core/tool_registry.py` — discovers from `tools/list` instead of YAML + PARAMS_MODEL_MAP
- `druppie/core/mcp_config.yaml` — stripped of descriptions and parameter schemas, gains `type` field, `bestand-zoeker` renamed to `web`, `filesearch` entry added
- `druppie/core/mcp_config.py` — simplified to only parse URLs, types, injection, approval
- `druppie/domain/tool.py` — `ToolDefinition` uses JSON schema instead of Pydantic `params_model`
- `druppie/execution/tool_executor.py` — generic pre-validation via `meta.pre_validate`, removes hardcoded `_validate_make_design_content`
- `druppie/execution/mcp_http.py` — gains error classification and retry logic from deleted `MCPClient`
- `druppie/mcp-servers/module-registry/v1/module.py` — live discovery via FastMCP Client
- `druppie/api/routes/mcps.py` — switch from `MCPClient` to `MCPConfig` + `MCPHttp`
- `druppie/services/deployment_service.py` — switch from `MCPClient` to `MCPHttp`
- Agent YAML definitions referencing `bestand-zoeker` — updated to `web`

### Files Unchanged

- `druppie/agents/builtin_tools.py` — builtin tools stay as-is
- Frontend — unchanged

---

## 8. Verification Criteria

- [ ] All 7 Docker containers start and health checks pass
- [ ] `tools/list` on each server returns correct tool schemas with `meta`
- [ ] Tool calls work end-to-end: injection → pre-validation → approval → execution
- [ ] Pre-validation works for `make_design` (Mermaid syntax check via validate endpoint, no cross-boundary import)
- [ ] Internal tools (`_internal_revert_to_commit`, `_internal_close_pull_request`) are callable by backend but hidden from LLM tool lists
- [ ] Registry server returns live tool metadata from other modules
- [ ] No duplicate tool descriptions remain (grep confirms single source per tool)
- [ ] `mcp_config.yaml` contains no tool descriptions or parameter schemas
- [ ] `druppie/tools/params/` directory is gone
- [ ] `druppie/core/mcp_client.py` is gone (all consumers migrated to `MCPHttp`)
- [ ] `filesearch` has a `mcp_config.yaml` entry
- [ ] `bestand-zoeker` references are gone (renamed to `web`)
- [ ] `jsonschema` dependency added to `druppie/requirements.txt`
- [ ] Existing tests pass (update imports for new paths)

### Suggested Verification Order During Development

1. Migrate one simple server (e.g., `filesearch`) end-to-end — verify directory structure, `MODULE.yaml`, router `server.py`, `v1/tools.py`, Docker build, health check
2. Migrate remaining 6 servers
3. Refactor client side — `ToolRegistry` discovery, `mcp_config.yaml` slimming, `MCPClient` deletion
4. Wire up pre-validation pattern for `make_design`
5. Evolve registry to live discovery
6. Full integration test
