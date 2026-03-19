# MCP-to-Module Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all MCP servers to the module convention and eliminate tool definition duplication by making MCP `tools/list` the single source of truth.

**Architecture:** Server-side directory restructure (flat → `MODULE.yaml` + `v1/tools.py` + `v1/module.py` + router `server.py`), client-side refactor (ToolRegistry discovers from `tools/list`, JSON schema validation replaces Pydantic models), consolidate two overlapping MCP client classes into one.

**Tech Stack:** Python, FastMCP (server + client), jsonschema, Docker Compose, Starlette, YAML

**Spec:** `docs/superpowers/specs/2026-03-19-mcp-to-module-migration-design.md`

---

## File Structure

### Server-Side (per module, x7)

Each module follows this pattern after migration:

```
druppie/mcp-servers/module-<name>/
├── MODULE.yaml           # 3 fields: id, latest_version, versions
├── Dockerfile            # Unchanged from original
├── requirements.txt      # Add pyyaml dependency
├── server.py             # NEW: router that mounts v1, serves /health
├── v1/
│   ├── __init__.py       # Empty
│   ├── tools.py          # MOVED: @mcp.tool() decorators from old server.py
│   ├── module.py         # MOVED: business logic from old module.py
│   └── <extras>          # MOVED: any extra files (testing_module.py, etc.)
```

### Client-Side Changes

| File | Action |
|------|--------|
| `druppie/tools/params/*.py` (7 files) | DELETE |
| `druppie/core/mcp_client.py` | DELETE |
| `druppie/core/tool_registry.py` | REWRITE — discover from `tools/list` |
| `druppie/core/mcp_config.yaml` | SLIM — remove descriptions/params, add `type` |
| `druppie/core/mcp_config.py` | REFACTOR — simplified parsing |
| `druppie/domain/tool.py` | REFACTOR — JSON schema instead of Pydantic model |
| `druppie/execution/tool_executor.py` | REFACTOR — generic pre-validation |
| `druppie/execution/mcp_http.py` | ENHANCE — add error classification, retry |
| `druppie/execution/__init__.py` | UPDATE — remove MCPHttp/MCPHttpError exports |
| `druppie/api/routes/mcps.py` | REFACTOR — use MCPConfig + MCPHttp |
| `druppie/services/deployment_service.py` | REFACTOR — use MCPHttp |
| `druppie/agents/definitions/router.yaml` | UPDATE — bestand-zoeker → web |
| `docker-compose.yml` | UPDATE — rename services, add hitl |

---

## Phase 1: Pilot Server Migration (filesearch)

Start with the simplest server to prove the pattern works end-to-end.

### Task 1: Create module-filesearch directory structure

**Files:**
- Create: `druppie/mcp-servers/module-filesearch/MODULE.yaml`
- Create: `druppie/mcp-servers/module-filesearch/v1/__init__.py`
- Create: `druppie/mcp-servers/module-filesearch/v1/tools.py`
- Move: `druppie/mcp-servers/filesearch/module.py` → `druppie/mcp-servers/module-filesearch/v1/module.py`
- Create: `druppie/mcp-servers/module-filesearch/server.py`
- Move: `druppie/mcp-servers/filesearch/Dockerfile` → `druppie/mcp-servers/module-filesearch/Dockerfile`
- Move: `druppie/mcp-servers/filesearch/requirements.txt` → `druppie/mcp-servers/module-filesearch/requirements.txt`

- [ ] **Step 1: Create MODULE.yaml**

```yaml
# druppie/mcp-servers/module-filesearch/MODULE.yaml
id: filesearch
latest_version: "1.0.0"
versions:
  - "1.0.0"
```

- [ ] **Step 2: Create v1/__init__.py**

Empty file at `druppie/mcp-servers/module-filesearch/v1/__init__.py`

- [ ] **Step 3: Create v1/tools.py from old server.py**

Extract the FastMCP app and `@mcp.tool()` decorators from `druppie/mcp-servers/filesearch/server.py` (91 lines). The key change: add `meta` to each tool and use `FastMCP(name, version, instructions)`.

```python
"""File Search v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
from fastmcp import FastMCP
from .module import FileSearchModule

MODULE_ID = "filesearch"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "File Search v1",
    version=MODULE_VERSION,
    instructions="""Local file search within a dataset directory.

Use when:
- Searching for text content in local files
- Listing files in a dataset directory
- Reading file content from the dataset

Don't use when:
- You need web search (use web module)
- You need workspace file operations (use coding module)
""",
)

SEARCH_ROOT = os.getenv("SEARCH_ROOT", "/dataset")
module = FileSearchModule(search_root=SEARCH_ROOT)


@mcp.tool(
    name="search_files",
    description="Search for files containing text content matching query.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search_files(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict:
    return module.search_files(
        query=query,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        case_sensitive=case_sensitive,
    )


@mcp.tool(
    name="list_directory",
    description="List files and directories in search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_directory(
    path: str = ".",
    recursive: bool = False,
    show_hidden: bool = False,
) -> dict:
    return module.list_directory(
        path=path,
        recursive=recursive,
        show_hidden=show_hidden,
    )


@mcp.tool(
    name="read_file",
    description="Read file content from search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def read_file(path: str) -> dict:
    return module.read_file(path=path)


@mcp.tool(
    name="get_search_stats",
    description="Get statistics about files in search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_search_stats(path: str = ".") -> dict:
    return module.get_search_stats(path=path)
```

- [ ] **Step 4: Move module.py to v1/module.py**

```bash
cp druppie/mcp-servers/filesearch/module.py druppie/mcp-servers/module-filesearch/v1/module.py
```

No changes needed to module.py content.

- [ ] **Step 5: Create router server.py**

```python
"""File Search MCP Server — Version Router.

Routes requests to the correct version:
  /v1/mcp → v1/tools.py
  /mcp    → latest version (from MODULE.yaml)
  /health → aggregate health
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
logger = logging.getLogger("filesearch-mcp")

# Read MODULE.yaml
MANIFEST_PATH = Path(__file__).parent / "MODULE.yaml"
with open(MANIFEST_PATH) as f:
    manifest = yaml.safe_load(f)

latest_version = manifest["latest_version"]
major_latest = latest_version.split(".")[0]

# Import version-specific MCP apps
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


# Build routes
routes = [
    Route("/health", health, methods=["GET"]),
]
for major, app in version_apps.items():
    routes.append(Mount(f"/v{major}", app=app))

# /mcp → latest version
routes.append(Mount("/", app=version_apps[major_latest]))

app = Starlette(routes=routes)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9004"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```

- [ ] **Step 6: Copy and update Dockerfile**

```bash
cp druppie/mcp-servers/filesearch/Dockerfile druppie/mcp-servers/module-filesearch/Dockerfile
```

No changes needed — Dockerfile already does `COPY . .` and `CMD ["python", "server.py"]`.

- [ ] **Step 7: Copy and update requirements.txt**

```bash
cp druppie/mcp-servers/filesearch/requirements.txt druppie/mcp-servers/module-filesearch/requirements.txt
```

Add `pyyaml` to requirements.txt (needed for MODULE.yaml parsing in server.py):

```
fastmcp>=2.0.0,<3.0.0
uvicorn
pyyaml
```

- [ ] **Step 8: Update docker-compose.yml for filesearch**

In `docker-compose.yml`, change the `mcp-filesearch` service (lines 238-258):

```yaml
  module-filesearch:
    build:
      context: ./druppie/mcp-servers/module-filesearch
      dockerfile: Dockerfile
    container_name: druppie-module-filesearch
    profiles: [infra, dev, prod]
    environment:
      SEARCH_ROOT: /dataset
      MCP_PORT: "9004"
    volumes:
      - druppie_new_dataset:/dataset
    ports:
      - "${MCP_FILESEARCH_PORT:-9004}:9004"
    networks:
      - druppie-new-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9004/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
```

- [ ] **Step 9: Delete old filesearch directory**

```bash
rm -rf druppie/mcp-servers/filesearch/
```

- [ ] **Step 10: Build and verify**

```bash
docker compose --profile infra up -d module-filesearch
docker compose logs module-filesearch | tail -5
curl http://localhost:9004/health
```

Expected health response:
```json
{"status": "healthy", "module_id": "filesearch", "latest_version": "1.0.0", "active_versions": ["1.0.0"]}
```

- [ ] **Step 11: Stop container and commit**

```bash
docker compose --profile infra down
git add -A
git commit -m "feat: migrate filesearch to module convention

- MODULE.yaml with id, latest_version, versions
- v1/tools.py as single source of truth for tool schemas
- v1/module.py business logic (unchanged)
- server.py router with /v1, /mcp, /health
- docker-compose updated: mcp-filesearch → module-filesearch"
```

---

## Phase 2: Migrate Remaining 6 Servers

Apply the same pattern as filesearch. Each task follows the same steps but adapted for the specific server.

### Task 2: Migrate module-web (simple, 107-line server.py)

**Files:**
- Create: `druppie/mcp-servers/module-web/MODULE.yaml`
- Create: `druppie/mcp-servers/module-web/v1/__init__.py`
- Create: `druppie/mcp-servers/module-web/v1/tools.py` (from `web/server.py`)
- Move: `druppie/mcp-servers/web/module.py` → `druppie/mcp-servers/module-web/v1/module.py`
- Create: `druppie/mcp-servers/module-web/server.py` (router)
- Move: `druppie/mcp-servers/web/Dockerfile` → `druppie/mcp-servers/module-web/Dockerfile`
- Move: `druppie/mcp-servers/web/requirements.txt` → `druppie/mcp-servers/module-web/requirements.txt`
- Delete: `druppie/mcp-servers/web/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: web`
- [ ] Port: 9005
- [ ] tools.py: 6 tools (search_files, list_directory, read_file, fetch_url, search_web, get_page_info)
- [ ] instructions: "Local file search and web browsing. Use for fetching web content and searching local datasets."
- [ ] docker-compose: `mcp-web` → `module-web`, container `druppie-module-web`
- [ ] Delete old `druppie/mcp-servers/web/`
- [ ] Build and verify: `curl http://localhost:9005/health`
- [ ] Commit: `feat: migrate web to module convention`

### Task 3: Migrate module-archimate (133-line server.py)

**Files:**
- Create: `druppie/mcp-servers/module-archimate/{MODULE.yaml,server.py,v1/__init__.py,v1/tools.py}`
- Move: `druppie/mcp-servers/archimate/module.py` → `v1/module.py`
- Move: `druppie/mcp-servers/archimate/{Dockerfile,requirements.txt}`
- Move: `druppie/mcp-servers/archimate/models/` → `druppie/mcp-servers/module-archimate/models/`
- Delete: `druppie/mcp-servers/archimate/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: archimate`
- [ ] Port: 9006
- [ ] tools.py: 8 tools (list_models, get_statistics, list_elements, get_element, list_views, get_view, search_model, get_impact)
- [ ] instructions: "Read-only ArchiMate architecture reference. Use for querying elements, relationships, views, and impact analysis."
- [ ] docker-compose: `mcp-archimate` → `module-archimate`, container `druppie-module-archimate`
- [ ] **Important**: volume mount `./druppie/mcp-servers/archimate/models:/models:ro` changes to `./druppie/mcp-servers/module-archimate/models:/models:ro`
- [ ] Build and verify: `curl http://localhost:9006/health`
- [ ] Commit: `feat: migrate archimate to module convention`

### Task 4: Migrate module-hitl (338-line server.py)

**Files:**
- Create: `druppie/mcp-servers/module-hitl/{MODULE.yaml,server.py,v1/__init__.py,v1/tools.py}`
- Move: `druppie/mcp-servers/hitl/module.py` → `v1/module.py`
- Move: `druppie/mcp-servers/hitl/{Dockerfile,requirements.txt}`
- Delete: `druppie/mcp-servers/hitl/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: hitl`
- [ ] Port: 9003
- [ ] tools.py: 3 tools (ask_question, ask_choice, submit_response)
- [ ] instructions: "Human-in-the-loop interaction. Ask users questions and wait for responses."
- [ ] **New docker-compose entry** — HITL currently has no service definition. Add:

```yaml
  module-hitl:
    build:
      context: ./druppie/mcp-servers/module-hitl
      dockerfile: Dockerfile
    container_name: druppie-module-hitl
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9003"
      BACKEND_URL: http://druppie-backend:8000
      INTERNAL_API_KEY: ${INTERNAL_API_KEY:-druppie-internal-secret-key}
      HITL_TIMEOUT: "300"
    ports:
      - "${MCP_HITL_PORT:-9003}:9003"
    networks:
      - druppie-new-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9003/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
```

- [ ] Build and verify: `curl http://localhost:9003/health`
- [ ] Commit: `feat: migrate hitl to module convention`

### Task 5: Migrate module-docker (835-line server.py)

**Files:**
- Create: `druppie/mcp-servers/module-docker/{MODULE.yaml,server.py,v1/__init__.py,v1/tools.py}`
- Move: `druppie/mcp-servers/docker/module.py` → `v1/module.py`
- Move: `druppie/mcp-servers/docker/{Dockerfile,requirements.txt}`
- Delete: `druppie/mcp-servers/docker/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: docker`
- [ ] Port: 9002
- [ ] tools.py: 8 tools (build, run, stop, logs, remove, list_containers, inspect, exec_command)
- [ ] instructions: "Docker container operations. Build images from git repos, run containers with auto-port assignment."
- [ ] docker-compose: `mcp-docker` → `module-docker`, container `druppie-module-docker`
- [ ] Docker socket volume mount stays the same
- [ ] Build and verify: `curl http://localhost:9002/health`
- [ ] Commit: `feat: migrate docker to module convention`

### Task 6: Migrate module-registry (84-line server.py)

**Files:**
- Create: `druppie/mcp-servers/module-registry/{MODULE.yaml,server.py,v1/__init__.py,v1/tools.py}`
- Move: `druppie/mcp-servers/registry/module.py` → `v1/module.py`
- Move: `druppie/mcp-servers/registry/{Dockerfile,requirements.txt}`
- Delete: `druppie/mcp-servers/registry/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: registry`
- [ ] Port: 9007
- [ ] tools.py: 5 tools (list_components, get_agent, get_skill, get_mcp_server, get_tool)
- [ ] instructions: "Druppie platform building block catalog. List and inspect agents, skills, MCP tools, and builtin tools."
- [ ] docker-compose: `mcp-registry` → `module-registry`, container `druppie-module-registry`
- [ ] **Volume mounts** update paths:
  - `./druppie/agents/definitions:/data/agents:ro` (unchanged)
  - `./druppie/core/mcp_config.yaml:/data/mcp_config.yaml:ro` (unchanged)
  - `./druppie/skills:/data/skills:ro` (unchanged)
  - `./druppie/agents/builtin_tools.py:/data/builtin_tools.py:ro` (unchanged)
- [ ] Build and verify: `curl http://localhost:9007/health`
- [ ] Commit: `feat: migrate registry to module convention`

### Task 7: Migrate module-coding (2037-line server.py — largest)

**Files:**
- Create: `druppie/mcp-servers/module-coding/{MODULE.yaml,server.py,v1/__init__.py,v1/tools.py}`
- Move: `druppie/mcp-servers/coding/module.py` → `v1/module.py`
- Move: `druppie/mcp-servers/coding/testing_module.py` → `v1/testing_module.py`
- Move: `druppie/mcp-servers/coding/mermaid_validator.py` → `v1/mermaid_validator.py`
- Move: `druppie/mcp-servers/coding/retry_module.py` → `v1/retry_module.py`
- Move: `druppie/mcp-servers/coding/puppeteer-config.json` → `v1/puppeteer-config.json`
- Move: `druppie/mcp-servers/coding/{Dockerfile,requirements.txt}`
- Delete: `druppie/mcp-servers/coding/`

Follow same steps as Task 1. Key differences:
- [ ] MODULE.yaml: `id: coding`
- [ ] Port: 9001
- [ ] tools.py is the largest — ~15 tools including:
  - read_file, write_file, make_design, batch_write_files, list_dir, delete_file, run_git
  - run_tests, get_test_framework, get_coverage_report, install_test_dependencies, validate_tdd
  - create_pull_request, merge_pull_request
  - _internal_revert_to_commit, _internal_close_pull_request
- [ ] Internal tools get `meta={"internal": True, ...}`
- [ ] make_design gets `meta={"pre_validate": "validate_design", ...}`
- [ ] Add new `validate_design` tool with `meta={"internal": True, ...}` that wraps `validate_mermaid_in_markdown()`
- [ ] instructions: "File operations, git, testing, and pull requests in workspace sandbox."
- [ ] docker-compose: `mcp-coding` → `module-coding`, container `druppie-module-coding`
- [ ] **Import fixes in v1/tools.py**: change `from module import CodingModule` to `from .module import CodingModule`, similarly for testing_module, retry_module, mermaid_validator
- [ ] Build and verify: `curl http://localhost:9001/health`
- [ ] Commit: `feat: migrate coding to module convention`

### Task 8: Verify all 7 servers together

- [ ] **Step 1: Start all services**

```bash
docker compose --profile infra --profile init up -d
```

- [ ] **Step 2: Verify all health checks**

```bash
for port in 9001 9002 9003 9004 9005 9006 9007; do
  echo "Port $port: $(curl -sf http://localhost:$port/health | python3 -m json.tool 2>/dev/null || echo 'FAILED')"
done
```

All 7 should return `{"status": "healthy", "module_id": "...", ...}`.

- [ ] **Step 3: Stop all and commit checkpoint**

```bash
docker compose --profile infra down
git add -A
git commit -m "chore: verify all 7 module servers pass health checks"
```

---

## Phase 3: Config & Agent Updates

### Task 9: Slim mcp_config.yaml and rename bestand-zoeker

**Files:**
- Modify: `druppie/core/mcp_config.yaml`
- Modify: `druppie/agents/definitions/router.yaml`

- [ ] **Step 1: Update mcp_config.yaml**

For each MCP entry:
1. Add `type: core`
2. Update URL hostnames: `mcp-<name>` → `module-<name>`
3. Remove `description` from the top-level server entry
4. Remove `description` and `parameters` from each tool entry (keep only `name`, `requires_approval`, `required_role`)
5. Keep all `inject` rules unchanged
6. Rename `bestand-zoeker` key to `web`
7. Add `filesearch` entry (currently missing):

```yaml
  filesearch:
    url: ${MCP_FILESEARCH_URL:-http://module-filesearch:9004}
    type: core
    tools:
      - name: search_files
        requires_approval: false
      - name: list_directory
        requires_approval: false
      - name: read_file
        requires_approval: false
      - name: get_search_stats
        requires_approval: false
```

- [ ] **Step 2: Update router.yaml**

Change `bestand-zoeker` to `web` at line 75:

```yaml
mcps:
  web:
    - search_files
    - list_directory
    - read_file
    - fetch_url
    - search_web
    - get_page_info
```

- [ ] **Step 3: Commit**

```bash
git add druppie/core/mcp_config.yaml druppie/agents/definitions/router.yaml
git commit -m "refactor: slim mcp_config.yaml, rename bestand-zoeker to web, add filesearch entry

- Remove tool descriptions and parameter schemas (now from tools/list)
- Add type: core to all MCP entries
- Update hostnames: mcp-* → module-*
- Rename bestand-zoeker → web for consistency
- Add missing filesearch entry"
```

---

## Phase 4: Client-Side Refactor

### Task 10: Add jsonschema dependency

**Files:**
- Modify: `druppie/requirements.txt`

- [ ] **Step 1: Add jsonschema**

Add `jsonschema>=4.0.0` to `druppie/requirements.txt`.

- [ ] **Step 2: Commit**

```bash
git add druppie/requirements.txt
git commit -m "chore: add jsonschema dependency for tools/list schema validation"
```

### Task 11: Refactor ToolDefinition to use JSON schema

**Files:**
- Modify: `druppie/domain/tool.py`

- [ ] **Step 1: Read current tool.py**

Read `druppie/domain/tool.py` (440 lines) to understand the full `ToolDefinition` class.

- [ ] **Step 2: Refactor ToolDefinition**

Replace `params_model: Type[BaseModel]` with `json_schema: dict` and `meta: dict`. Update `validate_arguments()` to use `jsonschema.validate()`. Update `to_openai_format()` to use the JSON schema directly. Remove imports of `BaseModel`, `EmptyParams`.

Key changes:
- `params_model` field → `json_schema: dict = {}` and `meta: dict = {}`
- `validate_arguments()` → uses `jsonschema.validate(instance=args, schema=self.json_schema)`
- `to_openai_format()` → uses `self.json_schema` directly for the `parameters` field
- `get_hidden_fields()` → reads from `json_schema["properties"]` instead of `params_model.model_fields`
- Keep normalization logic (e.g., `"null"` → `None`) as generic dict pre-processing

- [ ] **Step 3: Commit**

```bash
git add druppie/domain/tool.py
git commit -m "refactor: ToolDefinition uses JSON schema instead of Pydantic params_model"
```

### Task 12: Refactor ToolRegistry to discover from tools/list

**Files:**
- Modify: `druppie/core/tool_registry.py`

- [ ] **Step 1: Read current tool_registry.py**

Read `druppie/core/tool_registry.py` (386 lines).

- [ ] **Step 2: Rewrite ToolRegistry**

Remove all `from druppie.tools.params.*` imports and the `PARAMS_MODEL_MAP` dict. Replace `_load_all_tools()` with:

1. For builtin tools: keep loading from `BUILTIN_TOOL_DEFS` (unchanged)
2. For MCP tools: call `MCPHttp.list_tools(server)` for each server in config, create `ToolDefinition` objects from the response with `json_schema` and `meta`
3. Filter out tools with `meta.internal == True` from LLM-visible lists (but keep them in the registry for backend use)
4. Merge approval config from `mcp_config.yaml`

Key method changes:
- `_load_all_tools()` → async, calls `list_tools()` per server
- `_ensure_loaded()` → needs to handle async (or use sync initialization with `asyncio.run()`)
- New: `_load_mcp_tools_from_server(server, url)` — connects via FastMCP Client, calls `list_tools()`, returns tool defs
- Remove: all `PARAMS_MODEL_MAP` references

- [ ] **Step 3: Commit**

```bash
git add druppie/core/tool_registry.py
git commit -m "refactor: ToolRegistry discovers tools from MCP tools/list at startup"
```

### Task 13: Delete tools/params directory

**Files:**
- Delete: `druppie/tools/params/__init__.py`
- Delete: `druppie/tools/params/coding.py`
- Delete: `druppie/tools/params/docker.py`
- Delete: `druppie/tools/params/testing.py`
- Delete: `druppie/tools/params/builtin.py`
- Delete: `druppie/tools/params/archimate.py`
- Delete: `druppie/tools/params/registry.py`

- [ ] **Step 1: Delete all param files**

```bash
rm -rf druppie/tools/params/
```

- [ ] **Step 2: Search for any remaining imports**

```bash
grep -r "from druppie.tools.params" druppie/ --include="*.py"
grep -r "from druppie.tools import" druppie/ --include="*.py"
```

Fix any remaining references.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove hand-written Pydantic parameter models (tools/params/)

Replaced by JSON schema validation from MCP tools/list."
```

### Task 14: Consolidate MCPClient into MCPHttp

**Files:**
- Modify: `druppie/execution/mcp_http.py`
- Delete: `druppie/core/mcp_client.py`
- Modify: `druppie/api/routes/mcps.py`
- Modify: `druppie/services/deployment_service.py`
- Modify: `druppie/execution/__init__.py`

- [ ] **Step 1: Move error classification to mcp_http.py**

Copy `MCPErrorType` and `classify_error()` from `druppie/core/mcp_client.py` (lines 34-142) into `druppie/execution/mcp_http.py`. Add retry logic with exponential backoff (from `MCPClient._execute_tool_with_retry`, lines 378-447).

- [ ] **Step 2: Update mcps.py to use MCPConfig + MCPHttp**

In `druppie/api/routes/mcps.py`, replace `from druppie.core.mcp_client import get_mcp_client` with imports from `MCPConfig` and `MCPHttp`. The routes use `MCPClient` for:
- `mcp_client.config` → use `get_mcp_config()` directly
- `mcp_client.get_mcp_url(server)` → use `mcp_config.get_server_url(server)`
- `mcp_client.get_tool_config(server, tool)` → use `mcp_config.get_tool_config(server, tool)`

- [ ] **Step 3: Update deployment_service.py to use MCPHttp**

In `druppie/services/deployment_service.py`, replace `mcp_client.call_tool(...)` with `mcp_http.call(server, tool, args)`.

- [ ] **Step 4: Delete mcp_client.py**

```bash
rm druppie/core/mcp_client.py
```

- [ ] **Step 5: Search for remaining references**

```bash
grep -r "mcp_client\|MCPClient\|get_mcp_client" druppie/ --include="*.py"
```

Fix any remaining references.

- [ ] **Step 6: Update execution/__init__.py**

Remove `MCPClient` from exports if present.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: consolidate MCPClient into MCPHttp

- Move error classification and retry logic to mcp_http.py
- Update mcps.py routes to use MCPConfig + MCPHttp
- Update deployment_service.py to use MCPHttp
- Delete overlapping mcp_client.py"
```

### Task 15: Refactor tool_executor.py for generic pre-validation

**Files:**
- Modify: `druppie/execution/tool_executor.py`

- [ ] **Step 1: Read current tool_executor.py**

Read `druppie/execution/tool_executor.py` (970 lines), focusing on:
- `_validate_make_design_content()` (lines 356-391) — hardcoded cross-boundary import
- The pre-approval validation at lines 492-509

- [ ] **Step 2: Replace hardcoded make_design validation with generic pre-validation**

Remove `_validate_make_design_content()` method entirely. Replace the `if tool_call.tool_name == "make_design"` block with a generic check:

```python
# Generic pre-validation: check if tool has meta.pre_validate
tool_def = registry.get(full_name)
if tool_def and tool_def.meta.get("pre_validate"):
    validate_tool_name = tool_def.meta["pre_validate"]
    # Extract only the args needed for validation from the tool's args
    validate_args = {"content": tool_call.arguments.get("content", "")}
    try:
        result = await self.mcp_http.call(
            tool_def.server, validate_tool_name, validate_args
        )
        if not result.get("valid", True):
            errors = result.get("errors", [])
            error_msg = "PRE-VALIDATION FAILED:\n" + "\n".join(
                f"Line {e['line']} [{e['rule']}]: {e['message']}" for e in errors
            ) + "\n\nFix the errors and try again."
            # Fail the tool call
            self.execution_repo.update_tool_call(
                tool_call.id,
                status=ToolCallStatus.FAILED,
                error=error_msg,
            )
            self.db.commit()
            return ToolCallStatus.FAILED
    except Exception as e:
        logger.warning("pre_validation_exception", error=str(e))
```

- [ ] **Step 3: Commit**

```bash
git add druppie/execution/tool_executor.py
git commit -m "refactor: generic pre-validation via meta.pre_validate

Replaces hardcoded _validate_make_design_content() with generic
pattern that discovers validation tools from meta.pre_validate field."
```

---

## Phase 5: Registry Evolution

### Task 16: Update registry module for live discovery

**Files:**
- Modify: `druppie/mcp-servers/module-registry/v1/module.py`

- [ ] **Step 1: Read current registry module.py**

Read `druppie/mcp-servers/module-registry/v1/module.py`.

- [ ] **Step 2: Add live tools/list discovery**

Update `_load_mcp_config()` to also do live `tools/list` calls. Add caching with TTL (e.g., 60 seconds). The `get_mcp_server()` and `get_tool()` methods should return live tool schemas instead of just what's in the YAML.

```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import time

class RegistryModule:
    def __init__(self, data_dir: str):
        # ... existing init ...
        self._tool_cache: dict[str, dict] = {}
        self._cache_ttl = 60  # seconds
        self._cache_timestamps: dict[str, float] = {}

    async def _get_live_tools(self, server_name: str) -> list[dict]:
        """Fetch tools from a live MCP server via tools/list."""
        now = time.time()
        if server_name in self._tool_cache:
            if now - self._cache_timestamps.get(server_name, 0) < self._cache_ttl:
                return self._tool_cache[server_name]

        url = self._get_server_url(server_name)
        try:
            transport = StreamableHttpTransport(url=f"{url}/mcp")
            async with Client(transport) as client:
                tools = await client.list_tools()
                result = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema if hasattr(t, "inputSchema") else {},
                        "meta": getattr(t, "meta", {}),
                    }
                    for t in tools
                ]
                self._tool_cache[server_name] = result
                self._cache_timestamps[server_name] = now
                return result
        except Exception as e:
            logger.warning(f"Failed to fetch tools from {server_name}: {e}")
            # Fall back to config-based tools
            return self._get_config_tools(server_name)
```

- [ ] **Step 3: Commit**

```bash
git add druppie/mcp-servers/module-registry/v1/module.py
git commit -m "feat: registry module uses live tools/list discovery

Falls back to config-based tools if server is unreachable.
Results cached with 60s TTL."
```

---

## Phase 6: Integration Verification

### Task 17: Full integration test

- [ ] **Step 1: Start full dev environment**

```bash
docker compose --profile dev --profile init up -d --build
```

- [ ] **Step 2: Verify all health checks**

```bash
for port in 9001 9002 9003 9004 9005 9006 9007; do
  echo "Port $port: $(curl -sf http://localhost:$port/health)"
done
```

- [ ] **Step 3: Verify backend starts cleanly**

```bash
docker compose logs -f druppie-backend-dev 2>&1 | head -50
```

Check that ToolRegistry loads successfully (look for `loaded_mcp_tools` and `loaded_builtin_tools` log lines).

- [ ] **Step 4: Grep for duplicate tool descriptions**

```bash
# Should only find descriptions in v1/tools.py files and builtin_tools.py
grep -r "description.*Read file" druppie/ --include="*.py" --include="*.yaml" -l
```

- [ ] **Step 5: Verify no leftover references**

```bash
grep -r "from druppie.tools.params" druppie/ --include="*.py"
grep -r "MCPClient\|get_mcp_client" druppie/ --include="*.py"
grep -r "bestand-zoeker" druppie/ --include="*.yaml" --include="*.py"
grep -r "mcp-servers/coding/" druppie/ --include="*.py" --include="*.yaml" --include="*.yml"
```

All should return no results.

- [ ] **Step 6: Run existing tests**

```bash
cd druppie && pytest -x -v
```

- [ ] **Step 7: Stop and commit**

```bash
docker compose --profile dev down
git add -A
git commit -m "chore: integration verification passes

All 7 module servers healthy, ToolRegistry discovers from tools/list,
no duplicate tool descriptions, no leftover references."
```

### Task 18: Update documentation

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `docs/TECHNICAL.md`

- [ ] **Step 1: Update FEATURES.md**

Add a section about the module convention for MCP servers.

- [ ] **Step 2: Update TECHNICAL.md**

Update the architecture section to reflect:
- `module-<name>/` directory naming
- `v1/tools.py` as single source of truth
- `ToolRegistry` discovers from `tools/list`
- No more `tools/params/` or `mcp_client.py`

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update FEATURES.md and TECHNICAL.md for module convention"
```
