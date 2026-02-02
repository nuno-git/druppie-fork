# MCP Servers

This document describes the MCP (Model Context Protocol) servers in Druppie, the tools they expose, how the backend communicates with them, how approval rules work, and how context injection operates.

## Overview

Druppie uses two MCP server containers that run as standalone HTTP microservices. Each server is built with the [FastMCP](https://github.com/jlowin/fastmcp) framework and exposes tools that agents can call. The backend communicates with these servers over HTTP using the FastMCP client library.

| Server | Port | Docker Service | Description |
|---|---|---|---|
| **Coding** | 9001 | `mcp-coding` | File operations and git within workspace sandbox |
| **Docker** | 9002 | `mcp-docker` | Docker container build, run, and management |

Both servers expose:
- A health endpoint at `GET /health`
- MCP tool endpoints at `/mcp` (FastMCP HTTP transport)

---

## Coding MCP Server (Port 9001)

**Source:** `druppie/mcp-servers/coding/server.py`

The Coding server provides file I/O and git operations within sandboxed workspaces. Each workspace is tied to a session and backed by a Gitea repository.

### Tools

#### `read_file`
Read a file from the workspace.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | File path relative to workspace root |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID for workspace path |
| `user_id` | string | no | User ID for workspace path |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** File content, path, and size. Handles binary files and enforces a 10MB size limit.

---

#### `write_file`
Write a file to the workspace. Does NOT commit or push -- use `commit_and_push` separately.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | File path relative to workspace root |
| `content` | string | yes | File content to write |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval (global default):** Not required
**Approval (business_analyst override):** Required, role `business_analyst`
**Approval (architect override):** Required, role `architect`
**Returns:** Written path and file size. Creates parent directories automatically.

---

#### `batch_write_files`
Write multiple files to the workspace in a single operation. Does NOT commit or push.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `files` | object | yes | Map of file path to content |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** List of files created, count, and any errors for partial failures.

---

#### `list_dir`
List directory contents in the workspace.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Directory path (use `.` for root) |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `recursive` | boolean | no | Whether to list recursively |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** Lists of files and directories with names, paths, types, and sizes. Excludes `.git`, `__pycache__`, and `node_modules`.

---

#### `delete_file`
Delete a file from the workspace. Auto-commits by default.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | File path to delete |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `auto_commit` | boolean | no | Whether to auto-commit (default: true) |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** Deleted file path and commit status.

---

#### `commit_and_push`
Stage all changes, commit with a message, and push to Gitea.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `message` | string | yes | Git commit message |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** Success status, whether changes were committed, whether push succeeded. Pushes to the current branch tracked by the workspace.

---

#### `create_branch`
Create a new git branch and switch to it. If the branch already exists, switches to it.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `branch_name` | string | yes | Name of the branch (e.g., `feature/add-login`) |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** Branch name and whether it was newly created or switched to an existing one. Persists branch state to disk.

---

#### `merge_to_main`
Merge the current feature branch to main via direct git merge (no PR).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Required, role `architect`
**Returns:** Name of the merged branch.

---

#### `create_pull_request`
Create a pull request from the current branch to main on Gitea.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | PR title |
| `body` | string | no | PR description |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** PR number, PR URL, HTML URL, head and base branch names.

---

#### `merge_pull_request`
Merge a pull request on Gitea and optionally delete the source branch.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `pr_number` | integer | yes | PR number to merge |
| `delete_branch` | boolean | no | Delete source branch after merge (default: true) |
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Required, role `developer`
**Returns:** Merge status, PR number, whether branch was deleted. Updates local workspace to main after merge.

---

#### `get_git_status`
Get the current git status of the workspace.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | no | Session ID (auto-injected) |
| `workspace_id` | string | no | Legacy workspace ID |
| `project_id` | string | no | Project ID |
| `user_id` | string | no | User ID |
| `repo_name` | string | no | Gitea repository name (auto-injected) |
| `repo_owner` | string | no | Gitea repository owner (auto-injected) |

**Approval:** Not required
**Returns:** Current branch name, list of changed files with statuses, and whether there are uncommitted changes.

---

### Workspace Management

The Coding server maintains an in-memory workspace registry. Each workspace is tied to a session and has:
- A filesystem path under `/workspaces/{user_id}/{project_id}/{session_id}`
- A git repository (cloned from Gitea or initialized fresh)
- A tracked current branch (persisted to `.druppie_state.json`)

Workspaces are auto-created on first tool call using the injected `session_id`. If `repo_name` and `repo_owner` are provided (via injection), the workspace clones from Gitea on initialization.

### Path Security

All file paths are resolved relative to the workspace root. Path traversal attempts (e.g., `../../etc/passwd`) are blocked by `resolve_path()`, which ensures the resolved path stays within the workspace directory.

---

## Docker MCP Server (Port 9002)

**Source:** `druppie/mcp-servers/docker/server.py`

The Docker server handles container lifecycle: building images from git repos, running containers, and managing deployments. It is fully standalone -- it clones from git directly rather than depending on the Coding server's workspace.

### Tools

#### `build`
Build a Docker image by cloning a git repository.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `image_name` | string | yes | Name for the built image (e.g., `myapp:latest`) |
| `git_url` | string | no | Full git URL to clone |
| `repo_name` | string | no | Gitea repo name (auto-injected) |
| `repo_owner` | string | no | Gitea repo owner (auto-injected) |
| `branch` | string | no | Git branch (default: `main`) -- NOT auto-injected |
| `session_id` | string | no | Session ID (auto-injected) |
| `project_id` | string | no | Project ID |
| `dockerfile` | string | no | Dockerfile name (default: `Dockerfile`) |
| `build_args` | object | no | Docker build arguments |

**Approval:** Required, role `developer`
**Returns:** Image name and build log. Clones to a temp directory, builds, then cleans up.

---

#### `run`
Run a Docker container with ownership tracking labels.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `image_name` | string | yes | Docker image to run |
| `container_name` | string | yes | Name for the container |
| `container_port` | integer | yes | Container port (from Dockerfile EXPOSE) |
| `session_id` | string | no | Session ID (auto-injected) |
| `project_id` | string | no | Project ID (auto-injected, added as label) |
| `user_id` | string | no | User ID (auto-injected, added as label) |
| `git_url` | string | no | Source git URL (added as label) |
| `branch` | string | no | Branch used for build (added as label) |
| `port` | integer | no | Host port (auto-assigned from 9100-9199 if omitted) |
| `port_mapping` | string | no | Full port mapping (e.g., `8080:3000`) |
| `env_vars` | object | no | Environment variables |
| `volumes` | array | no | Volume mounts (`host:container`) |
| `command` | string | no | Override command |

**Approval:** Required, role `developer`
**Returns:** Container name, container ID, host port, access URL, and labels. Automatically removes existing containers with the same name. Adds ownership labels (`druppie.project_id`, `druppie.session_id`, `druppie.user_id`, `druppie.git_url`, `druppie.branch`).

---

#### `stop`
Stop a running container.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `container_name` | string | yes | Name of container to stop |
| `remove` | boolean | no | Whether to remove after stopping (default: true) |

**Approval:** Not required
**Returns:** Stopped container name and whether it was removed.

---

#### `logs`
Get container logs.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `container_name` | string | yes | Name of container |
| `tail` | integer | no | Number of lines to show (default: 100) |
| `follow` | boolean | no | Not supported in MCP (always false) |

**Approval:** Not required
**Returns:** Container name and combined stdout/stderr log output.

---

#### `remove`
Remove a container.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `container_name` | string | yes | Name of container to remove |
| `force` | boolean | no | Force remove running container (default: false) |

**Approval:** Required, role `developer`
**Returns:** Removed container name.

---

#### `list_containers`
List Docker containers with optional filtering by ownership labels.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `all` | boolean | no | Include stopped containers (default: false) |
| `project_id` | string | no | Filter by `druppie.project_id` label |
| `session_id` | string | no | Filter by `druppie.session_id` label |
| `user_id` | string | no | Filter by `druppie.user_id` label |

**Approval:** Not required
**Returns:** List of containers with ID, name, image, status, ports, and Druppie labels.

---

#### `inspect`
Inspect a container's details.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `container_name` | string | yes | Name of container to inspect |

**Approval:** Not required
**Returns:** Container ID, name, image, status, creation time, port mappings, and Druppie labels.

---

#### `exec_command`
Execute a command inside a running container.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `container_name` | string | yes | Name of container |
| `command` | string | yes | Command to execute |
| `workdir` | string | no | Working directory inside container |

**Approval:** Required, role `developer`
**Returns:** stdout, stderr, and return code. Times out after 60 seconds.

---

### Port Management

The Docker server manages host port allocation:
- Port range: 9100-9199 (configurable via `PORT_RANGE_START` / `PORT_RANGE_END`)
- Ports are auto-assigned from the range when not explicitly specified
- The server checks both Docker's currently bound ports and an internal tracking set
- If a requested port is busy, an alternative is auto-selected

### Container Labels

Every container created through `docker:run` gets ownership labels:
- `druppie.project_id` -- which project the container belongs to
- `druppie.session_id` -- which session created it
- `druppie.user_id` -- which user owns it
- `druppie.git_url` -- source git repository
- `druppie.branch` -- git branch used for the build

These labels enable filtering via `list_containers` and provide audit trails.

---

## MCP Configuration (`mcp_config.yaml`)

**Source:** `druppie/core/mcp_config.yaml`
**Loader:** `druppie/core/mcp_config.py`

The configuration file defines all MCP servers, their URLs, tool definitions, approval rules, and injection rules.

### Structure

```yaml
mcps:
  <server_name>:
    url: ${ENV_VAR:-default_url}
    description: "Human-readable description"
    inject:
      <param_name>:
        from: <context_path>
        hidden: true/false
        tools: [tool1, tool2]  # optional, applies to all if omitted
    tools:
      - name: <tool_name>
        description: "What the tool does"
        requires_approval: true/false
        required_role: <role_name>  # only if requires_approval: true
        parameters:
          type: object
          properties:
            <param_name>:
              type: <type>
              description: "..."
          required:
            - <param_name>
```

### Environment Variable Substitution

URLs support environment variable substitution with defaults:
- `${MCP_CODING_URL:-http://mcp-coding:9001}` -- uses env var or falls back to default
- `${VAR}` -- uses env var or empty string

### Approval Rules

The approval system has two layers:

**Layer 1: Global defaults** (in `mcp_config.yaml`)
```yaml
tools:
  - name: build
    requires_approval: true
    required_role: developer
```

**Layer 2: Agent overrides** (in agent YAML files)
```yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

Resolution order:
1. Check the agent's `approval_overrides` for a matching `server:tool` key
2. Fall back to the global `requires_approval` / `required_role` in `mcp_config.yaml`

### Approval Summary

| Server | Tool | Global Default | Agent Overrides |
|---|---|---|---|
| coding | read_file | No approval | -- |
| coding | write_file | No approval | business_analyst: requires `business_analyst` role; architect: requires `architect` role |
| coding | batch_write_files | No approval | -- |
| coding | list_dir | No approval | -- |
| coding | delete_file | No approval | -- |
| coding | commit_and_push | No approval | -- |
| coding | create_branch | No approval | -- |
| coding | merge_to_main | Requires `architect` | -- |
| coding | create_pull_request | No approval | -- |
| coding | merge_pull_request | Requires `developer` | -- |
| coding | get_git_status | No approval | -- |
| docker | build | Requires `developer` | -- |
| docker | run | Requires `developer` | -- |
| docker | stop | No approval | -- |
| docker | logs | No approval | -- |
| docker | remove | Requires `developer` | -- |
| docker | list_containers | No approval | -- |
| docker | inspect | No approval | -- |
| docker | exec_command | Requires `developer` | -- |

---

## Context Injection

**Source:** `druppie/core/mcp_config.py` (class `MCPConfig`, method `get_injection_rules`)

Context injection automatically populates tool arguments from the session/project context so that the LLM does not need to know or provide values like `session_id`, `repo_name`, or `repo_owner`.

### How It Works

1. **Declaration**: Injection rules are declared in `mcp_config.yaml` under each server's `inject` section.
2. **Hidden parameters**: Parameters marked `hidden: true` are stripped from the tool schema that the LLM sees. The LLM never knows these parameters exist.
3. **Injection at execution time**: When the `ToolExecutor` runs a tool, it resolves injection rules and adds the hidden parameter values from the current session context.
4. **Tool filtering**: Rules can specify a `tools` list to restrict injection to specific tools. If `tools` is omitted, the rule applies to all tools on that server.

### Injection Rules -- Coding Server

| Parameter | Context Path | Hidden | Applies To |
|---|---|---|---|
| `session_id` | `session.id` | yes | All tools |
| `repo_name` | `project.repo_name` | yes | read_file, write_file, batch_write_files, list_dir, delete_file, create_branch, commit_and_push, get_git_status, create_pull_request, merge_pull_request |
| `repo_owner` | `project.repo_owner` | yes | read_file, write_file, batch_write_files, list_dir, delete_file, create_branch, commit_and_push, get_git_status, create_pull_request, merge_pull_request |

### Injection Rules -- Docker Server

| Parameter | Context Path | Hidden | Applies To |
|---|---|---|---|
| `session_id` | `session.id` | yes | build, run |
| `repo_name` | `project.repo_name` | yes | build |
| `repo_owner` | `project.repo_owner` | yes | build |
| `user_id` | `session.user_id` | yes | run |
| `project_id` | `session.project_id` | yes | run |

### Context Path Resolution

The `from` field in an injection rule is a dotted path that gets resolved against the execution context:

- `session.id` -- the current session's UUID
- `session.user_id` -- the user who owns the session
- `session.project_id` -- the project linked to the session
- `project.repo_name` -- the Gitea repository name for the project
- `project.repo_owner` -- the Gitea repository owner

### Effect on LLM-Visible Schemas

When the runtime builds the tool list for the LLM, it calls `MCPConfig.get_all_tools_for_agent()` with `filter_hidden=True`. This:

1. Reads the injection rules for each server
2. Identifies hidden parameters per tool
3. Removes those parameters from the JSON Schema `properties` and `required` arrays
4. Returns the filtered schemas to the LLM

The LLM only sees parameters it should actually provide (like `path`, `content`, `branch_name`, etc.), while infrastructure parameters (`session_id`, `repo_name`, `repo_owner`) are invisible and auto-injected.

---

## Backend-to-MCP Communication

**Source:** `druppie/execution/mcp_http.py`

The backend communicates with MCP servers through the `MCPHttp` class, which wraps the FastMCP client library.

### Architecture

```
Agent Runtime (runtime.py)
    |
    v
ToolExecutor (tool_executor.py)
    |
    +--> Builtin tools: executed locally (builtin_tools.py)
    +--> HITL tools: create Question record, pause agent
    +--> MCP tools: dispatched via MCPHttp
            |
            v
        MCPHttp (mcp_http.py)
            |
            v
        FastMCP Client (StreamableHttpTransport)
            |
            v (HTTP)
        MCP Server Container (FastMCP HTTP app)
```

### Communication Details

1. **Transport**: HTTP via `StreamableHttpTransport` from the FastMCP library
2. **URL format**: `http://<host>:<port>/mcp` (the `/mcp` suffix is required by FastMCP)
3. **Client caching**: `MCPHttp` caches FastMCP `Client` instances per server
4. **Timeout**: 60 seconds per call (configurable)
5. **Response parsing**: FastMCP returns a list of content items. The first item's `.text` field is parsed as JSON. Falls back to wrapping in a `{"success": true, "content": ...}` dict if JSON parsing fails.

### Error Handling

The `MCPClient` class (`druppie/core/mcp_client.py`) classifies errors into four categories:

| Type | Retryable | Recoverable | Examples |
|---|---|---|---|
| `transient` | yes | no | Connection refused, timeout, 502/503/504 |
| `permission` | no | no | 401, 403, forbidden |
| `validation` | no | yes (by LLM) | Missing required arg, invalid value |
| `fatal` | no | no | Tool not found, 400, bad request |

Transient errors are retried up to 3 times with exponential backoff (1s, 2s, 4s delays).

---

## Health Checks

Both servers expose a health endpoint:

- **Coding**: `GET http://mcp-coding:9001/health` returns `{"status": "healthy", "service": "coding-mcp"}`
- **Docker**: `GET http://mcp-docker:9002/health` returns `{"status": "healthy", "service": "docker-mcp"}`

These are used by the infrastructure setup scripts to verify server readiness.
