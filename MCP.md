# Druppie MCP Servers Documentation

## Overview

Druppie uses the Model Context Protocol (MCP) to provide tools for AI agents. Three MCP servers run as Docker containers, each providing specialized capabilities.

| Server | Port | Purpose |
|--------|------|---------|
| Coding | 9001 | File operations, git, tests |
| Docker | 9002 | Container lifecycle |
| HITL | 9003 | Human-in-the-loop questions |

**Framework**: FastMCP with HTTP transport

---

## Table of Contents

1. [Coding MCP](#coding-mcp)
2. [Docker MCP](#docker-mcp)
3. [HITL MCP](#hitl-mcp)
4. [Configuration](#configuration)
5. [Backend Integration](#backend-integration)
6. [Security](#security)

---

## Coding MCP

**Port**: 9001

**Location**: `druppie/mcp-servers/coding/`

Provides file operations, git commands, and test automation.

### Tools

#### register_workspace

Register a pre-initialized workspace with the MCP server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Unique workspace identifier |
| workspace_path | string | Yes | Filesystem path |
| project_id | string | No | Associated project |
| branch | string | No | Git branch |
| user_id | string | No | Owner user ID |
| session_id | string | No | Associated session |

**Approval**: Not required

---

#### initialize_workspace

Create a new workspace, clone repo, and create feature branch.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| user_id | string | Yes | Owner user ID |
| session_id | string | Yes | Session ID |
| project_id | string | No | Existing project ID |
| project_name | string | No | New project name |

**Approval**: Not required

**Returns**: `{ workspace_id, workspace_path, project_id, branch, repo_name }`

---

#### read_file

Read file content from workspace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| path | string | Yes | Relative file path |

**Approval**: Not required

**Limits**: Max 10MB file size

---

#### write_file

Write content to a file with optional auto-commit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| path | string | Yes | Relative file path |
| content | string | Yes | File content |
| auto_commit | boolean | No | Auto-commit (default: true) |
| commit_message | string | No | Custom commit message |

**Approval**: Not required (can be overridden by agent)

---

#### batch_write_files

Create multiple files in a single git commit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| files | object | Yes | `{ "path": "content", ... }` |
| commit_message | string | No | Custom commit message |

**Approval**: Not required (can be overridden by agent)

---

#### list_dir

List files and directories.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| path | string | No | Directory path (default: ".") |
| recursive | boolean | No | Include subdirectories |

**Approval**: Not required

**Skips**: `__pycache__`, `node_modules`, `.git`

---

#### delete_file

Delete a file from workspace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| path | string | Yes | File path to delete |
| auto_commit | boolean | No | Auto-commit deletion |

**Approval**: Not required

---

#### run_command

Execute a shell command in workspace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| command | string | Yes | Shell command |
| timeout | integer | No | Timeout seconds (default: 60) |

**Approval**: Required (developer role)

**Security**: Command blocklist enforced (see [Security](#security))

---

#### run_tests

Auto-detect and run test framework.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| test_command | string | No | Custom test command |
| timeout | integer | No | Timeout seconds (default: 120) |

**Approval**: Not required

**Auto-Detection**:
- Node.js: jest, mocha, vitest, ava, npm test
- Python: pytest
- Go: go test
- Rust: cargo test
- Ruby: rspec, minitest
- Java: maven, gradle

---

#### commit_and_push

Commit all changes and push to Gitea.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| message | string | Yes | Commit message |

**Approval**: Not required

---

#### create_branch

Create and checkout a new git branch.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| branch_name | string | Yes | New branch name |

**Approval**: Not required

---

#### merge_to_main

Merge feature branch to main.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |

**Approval**: Required (architect role)

---

#### get_git_status

Get current git status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |

**Approval**: Not required

**Returns**: `{ branch, modified_files, untracked_files }`

---

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| WORKSPACE_ROOT | /workspaces | Base directory |
| GITEA_URL | http://gitea:3000 | Gitea server |
| GITEA_ORG | druppie | Gitea organization |
| GITEA_TOKEN | - | API token for repo creation |
| GITEA_USER | - | Git username |
| GITEA_PASSWORD | - | Git password |
| MCP_PORT | 9001 | Server port |

---

## Docker MCP

**Port**: 9002

**Location**: `druppie/mcp-servers/docker/`

Provides Docker container lifecycle management.

### Tools

#### register_workspace

Register workspace for Docker operations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| workspace_id | string | Yes | Workspace identifier |
| workspace_path | string | Yes | Filesystem path |
| project_id | string | No | Project ID |
| branch | string | No | Git branch |

**Approval**: Not required

---

#### build

Build a Docker image.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| image_name | string | Yes | Image name/tag |
| workspace_id | string | No | Workspace ID (or workspace_path) |
| workspace_path | string | No | Direct path |
| dockerfile | string | No | Dockerfile name (default: "Dockerfile") |
| build_args | object | No | Build arguments |

**Approval**: Required (developer role)

**Timeout**: 10 minutes

---

#### run

Run a Docker container.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| image_name | string | Yes | Image to run |
| container_name | string | Yes | Container name |
| port | integer | No | Host port (auto-assigned if busy) |
| container_port | integer | No | Container port (default: 3000) |
| port_mapping | string | No | Custom mapping "host:container" |
| env_vars | object | No | Environment variables |
| volumes | array | No | Volume mounts |
| command | string | No | Override command |

**Approval**: Required (developer role)

**Port Range**: 9100-9199 (auto-assigned if requested port busy)

---

#### stop

Stop a running container.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| container_name | string | Yes | Container name |
| remove | boolean | No | Remove after stop (default: true) |

**Approval**: Not required

---

#### logs

Get container logs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| container_name | string | Yes | Container name |
| tail | integer | No | Lines to return (default: 100) |
| follow | boolean | No | Stream logs (always false) |

**Approval**: Not required

---

#### remove

Remove a container.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| container_name | string | Yes | Container name |
| force | boolean | No | Force removal |

**Approval**: Required (developer role)

---

#### list_containers

List running containers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| all | boolean | No | Include stopped containers |

**Approval**: Not required

**Returns**: Array of `{ id, name, image, status, ports }`

---

#### inspect

Get detailed container information.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| container_name | string | Yes | Container name |

**Approval**: Not required

**Returns**: Config, State, NetworkSettings, etc.

---

#### exec_command

Execute command in running container.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| container_name | string | Yes | Container name |
| command | string | Yes | Command to execute |
| workdir | string | No | Working directory |

**Approval**: Required (developer role)

---

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| WORKSPACE_ROOT | /workspaces | For path resolution |
| DOCKER_NETWORK | druppie-new-network | Container network |
| PORT_RANGE_START | 9100 | Port range minimum |
| PORT_RANGE_END | 9199 | Port range maximum |
| MCP_PORT | 9002 | Server port |

---

## HITL MCP

**Port**: 9003

**Location**: `druppie/mcp-servers/hitl/`

Provides human-in-the-loop question capabilities.

### Tools

#### ask_question

Ask a free-form text question.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | string | Yes | Session ID |
| question | string | Yes | Question text |
| context | string | No | Additional context |
| agent_id | string | No | Asking agent |

**Approval**: Not required

**Blocks**: Until user responds (timeout: 300s)

---

#### ask_choice

Ask a multiple-choice question.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session_id | string | Yes | Session ID |
| question | string | Yes | Question text |
| choices | array | Yes | List of choices |
| allow_other | boolean | No | Allow custom input (default: true) |
| context | string | No | Additional context |
| agent_id | string | No | Asking agent |

**Approval**: Not required

**Blocks**: Until user responds (timeout: 300s)

---

#### submit_response

Submit user response (internal use).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| request_id | string | Yes | Question request ID |
| answer | string | Yes | User's answer |
| selected | string | No | Selected choice |

**Approval**: Not required

---

### Communication Flow

1. Agent calls `ask_question` or `ask_choice`
2. HITL MCP persists question to backend database
3. Publishes to Redis channel `hitl:{session_id}`
4. Blocks on Redis list `hitl:response:{request_id}`
5. Frontend receives WebSocket event
6. User answers via UI
7. Backend calls `submit_response`
8. Response pushed to Redis list
9. Agent unblocks and continues

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_URL | redis://redis:6379/0 | Redis connection |
| BACKEND_URL | http://druppie-backend:8000 | Backend API |
| INTERNAL_API_KEY | druppie-internal-key | API authentication |
| HITL_TIMEOUT | 300 | Response timeout (seconds) |
| MCP_PORT | 9003 | Server port |

---

## Configuration

### MCP Config (`druppie/core/mcp_config.yaml`)

Global tool configuration with approval requirements.

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    tools:
      - name: read_file
        description: Read a file from the workspace
        requires_approval: false

      - name: write_file
        description: Write content to a file
        requires_approval: false

      - name: run_command
        description: Execute a shell command
        requires_approval: true
        required_role: developer
        danger_level: medium

  docker:
    url: ${MCP_DOCKER_URL:-http://mcp-docker:9002}
    tools:
      - name: build
        description: Build a Docker image
        requires_approval: true
        required_role: developer

      - name: run
        description: Run a Docker container
        requires_approval: true
        required_role: developer

  hitl:
    url: ${MCP_HITL_URL:-http://mcp-hitl:9003}
    tools:
      - name: ask_question
        description: Ask user a question
        requires_approval: false
```

### Agent Overrides

Agents can override global defaults in their YAML definitions.

```yaml
# druppie/agents/definitions/architect.yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect
```

### Resolution Order

1. Check agent's `approval_overrides["{server}:{tool}"]`
2. Fall back to `mcp_config.yaml` global defaults
3. Default: `requires_approval: false`

---

## Backend Integration

### MCP Client (`druppie/core/mcp_client.py`)

The backend communicates with MCP servers via HTTP.

**Transport**: FastMCP `StreamableHttpTransport`

**URL Pattern**: `http://mcp-{server}:{port}/mcp`

### Error Handling

Errors are classified and may be retried:

| Type | Retryable | Examples |
|------|-----------|----------|
| Transient | Yes | Connection refused, timeout, DNS, 502/503/504 |
| Permission | No | 403, unauthorized, approval required |
| Validation | No | Missing fields, invalid format |
| Fatal | No | Invalid argument, tool not found, 400/404 |

**Retry Strategy**: Exponential backoff (1s, 2s, 4s)

### Approval Flow

1. Agent calls tool
2. MCP client checks `requires_approval()`
3. If required, creates approval record with `agent_state`
4. Broadcasts via WebSocket to role rooms
5. Returns `{ status: "paused", approval_id: "..." }`
6. User approves in UI
7. Backend calls `execute_approved_tool()`
8. Agent resumes

### Built-in HITL

HITL tools can also be handled internally by the backend without the external MCP server:

- `hitl_ask_question` - Creates HitlQuestion database record
- `hitl_ask_multiple_choice_question` - Creates record with choices

Located in `druppie/agents/hitl.py`.

---

## Security

### Command Blocklist (Coding MCP)

The following patterns are blocked in `run_command`:

**Destructive Commands**:
- `rm -rf /`, `rm -rf /*`
- `mkfs`, `dd if=`
- `fdisk`, `parted`

**Privilege Escalation**:
- `sudo`
- `su -`, `su root`

**Permission Changes**:
- `chmod 777`, `chmod -R 777`
- `chown` on system directories

**System Commands**:
- `shutdown`, `reboot`
- `init 0-6`
- `systemctl stop/disable/mask` for ssh/network

**Reverse Shells**:
- `nc -e`
- `bash -i >&`
- `curl | bash`, `wget | bash`

**File Access**:
- `/etc/passwd`, `/etc/shadow`, `/etc/sudoers` overwrites
- `/dev/sd*` writes

### Path Security

- `resolve_path()` prevents directory traversal
- Paths must stay within workspace boundary
- Absolute paths validated against workspace root

### File Size Limits

- Read: 10MB maximum
- No explicit write limit

### Docker Socket

Docker MCP requires the Docker socket mount:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

### Internal API Key

HITL MCP authenticates to backend with `X-Internal-API-Key` header.

---

## Docker Configuration

### Coding MCP Dockerfile

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y git curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN mkdir -p /workspaces
ENV WORKSPACE_ROOT=/workspaces
ENV MCP_PORT=9001
EXPOSE 9001
CMD ["python", "server.py"]
```

### Docker MCP Dockerfile

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y curl
RUN curl -fsSL https://get.docker.com | sh
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV MCP_PORT=9002
ENV DOCKER_NETWORK=druppie-new-network
EXPOSE 9002
CMD ["python", "server.py"]
```

### HITL MCP Dockerfile

```dockerfile
FROM python:3.11-slim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV MCP_PORT=9003
ENV REDIS_URL=redis://redis:6379/0
ENV HITL_TIMEOUT=300
EXPOSE 9003
CMD ["python", "server.py"]
```

---

## Health Checks

Each server exposes a `/health` endpoint:

**Coding/Docker**:
```json
{ "status": "healthy", "service": "coding-mcp" }
```

**HITL**:
```json
{
  "status": "healthy|degraded",
  "service": "hitl-mcp",
  "redis": "connected|disconnected"
}
```

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    druppie-new-network                       │
│                                                              │
│  ┌──────────────┐     ┌──────────────┐    ┌──────────────┐ │
│  │ mcp-coding   │     │ mcp-docker   │    │  mcp-hitl    │ │
│  │   :9001      │     │   :9002      │    │   :9003      │ │
│  └──────────────┘     └──────────────┘    └──────────────┘ │
│         │                    │                   │          │
│         │                    │                   │          │
│         └────────────────────┼───────────────────┘          │
│                              │                              │
│                    ┌─────────▼─────────┐                    │
│                    │ druppie-backend   │                    │
│                    │     :8000         │                    │
│                    └───────────────────┘                    │
│                              │                              │
│         ┌────────────────────┼────────────────────┐        │
│         │                    │                    │        │
│  ┌──────▼──────┐     ┌───────▼───────┐    ┌──────▼──────┐ │
│  │    gitea    │     │   postgres    │    │    redis    │ │
│  │    :3000    │     │    :5432      │    │    :6379    │ │
│  └─────────────┘     └───────────────┘    └─────────────┘ │
│                                                              │
│  Docker Socket: /var/run/docker.sock (shared by mcp-docker) │
└─────────────────────────────────────────────────────────────┘
```

---

## Workspace Management

### Path Structure

```
/workspaces/
└── {user_id}/
    └── {project_id}/
        └── {session_id}/
            ├── .git/
            ├── src/
            ├── package.json
            └── ...
```

### Workspace Registry

Each MCP server maintains an in-memory registry:

```python
workspaces = {
    "workspace_id": {
        "path": "/workspaces/user/project/session",
        "project_id": "...",
        "branch": "feature-abc123",
        "repo_name": "project-name",
        "user_id": "...",
        "session_id": "..."
    }
}
```

### Auto-Commit Behavior

Write operations (`write_file`, `batch_write_files`, `delete_file`) automatically:
1. Stage changes with `git add`
2. Commit with auto-generated message
3. Push to Gitea (if configured)

Disable with `auto_commit: false`.
