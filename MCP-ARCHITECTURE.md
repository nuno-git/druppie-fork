# MCP Architecture in Druppie

## Overview

Druppie uses a microservice architecture where MCP (Model Context Protocol) servers provide tools to AI agents. MCPs communicate via HTTP using the FastMCP framework.

## Components

### 1. MCP Servers (Microservices)

MCP servers are standalone Docker containers that expose tools via HTTP API.

**Existing MCPs:**

- **mcp-coding** (port 9001)
  - File operations: read_file, write_file, delete_file, list_dir
  - Git operations: commit_and_push, create_branch, merge_to_main, get_git_status
  - Test execution: run_tests (with auto-detection of test frameworks)
  - Shell commands: run_command (with security blocklist)
  - Workspace: register_workspace, initialize_workspace

- **mcp-docker** (port 9002)
  - Container lifecycle: build, run, stop, remove
  - Container inspection: logs, inspect, list_containers
  - Container operations: exec_command
  - Workspace: register_workspace

- **hitl** (builtin)
  - Human-in-the-loop tools built directly into backend
  - ask_question, ask_choice, progress, notify
  - No external server - implements `_execute_builtin_tool()` in MCPClient

- **bestand-zoeker** (port 9005)
  - Local file search: search_files, list_directory, read_file, get_search_stats
  - Web browsing: search_web, get_page_info

### 2. MCP Configuration

**File:** `druppie/core/mcp_config.yaml`

Defines:
- MCP server URLs (with environment variable support)
- Tool descriptions and parameters
- Approval requirements per tool
- Required roles for approval

**Example configuration:**
```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    description: "File operations and git within workspace sandbox"
    tools:
      - name: write_file
        description: "Write file to workspace (auto-commits)"
        requires_approval: false
      - name: run_command
        description: "Execute shell command in workspace"
        requires_approval: true
        required_role: developer
```

### 3. MCP Client

**File:** `druppie/core/mcp_client.py`

The `MCPClient` class handles:
- Loading configuration from `mcp_config.yaml`
- Managing FastMCP client connections to MCP servers
- Checking tool approval requirements
- Executing tools with retry logic for transient errors
- Recording tool calls in database
- Emitting events via WebSocket

**Key methods:**
- `call_tool()` - Execute tool with approval checking
- `requires_approval()` - Check if tool needs approval (layered system)
- `_execute_tool_with_retry()` - Retry transient errors with exponential backoff
- `to_openai_tools_async()` - Convert tools to OpenAI format for LLM

### 4. Agent Integration

Agents specify which MCPs/tools they can use in their YAML definition:

**File:** `druppie/agents/definitions/developer.yaml`
```yaml
# MCP tools this agent can use
mcps:
  coding:
    - read_file
    - write_file
    - batch_write_files
    - commit_and_push
    - list_dir
    - delete_file
    - run_command
  hitl:
    - progress
  bestand-zoeker:
    - search_files
    - search_web
```

### 5. Execution Flow

```
1. Agent receives task from user
2. LLM generates tool call request
3. Backend checks tool via MCPClient:
   - Loads tool config from mcp_config.yaml
   - Checks if tool requires approval
   - If approval needed: pause and create approval record
   - If no approval: proceed
4. MCPClient makes HTTP request to MCP server
5. MCP server executes tool (e.g., write_file)
6. Result returned to MCPClient
7. Result passed back to agent/LLM
8. Agent continues to next step
```

### 6. Layered Approval System

Per `goal.md`, the approval system has two layers:

**Layer 1: Agent-Specific Overrides** (optional)
- Agents can override global defaults in their YAML
- Example: architect agent may require architect approval for write_file

**Layer 2: Global Defaults** (mcp_config.yaml)
- Fallback for agents without overrides
- Defines baseline approval requirements

**Decision Logic:**
```
1. Check agent's approval_overrides (if agent_definition provided)
2. If override exists: use it
3. Else: use global default from mcp_config.yaml
```

**Example in agent YAML:**
```yaml
approval_overrides:
  coding:write_file:
    requires_approval: true
    required_role: architect
```

## MCP Server Structure

Each MCP server follows this structure:

```
mcp-servers/
├── coding/
│   ├── Dockerfile          # Container definition
│   ├── module.py          # Business logic (CodingModule class)
│   ├── server.py          # FastMCP server wrapper
│   ├── requirements.txt    # Python dependencies
│   └── (other files)
├── docker/
│   └── (same structure)
└── web/
    └── (same structure)
```

**Key files:**

- **module.py**: Contains the actual business logic
  - All tool implementations
  - Security checks (command blocklist)
  - Workspace management
  - Error handling

- **server.py**: FastMCP wrapper
  - Creates FastMCP instance
  - Decorates module functions with `@mcp.tool()`
  - Starts HTTP server with uvicorn

- **Dockerfile**: Container configuration
  - Installs dependencies
  - Exposes MCP port
  - Sets environment variables
  - Health check endpoint

## Security Features

### Command Blocklist
The coding MCP includes a blocklist of dangerous commands:
- File system destruction: `rm -rf /`, `mkfs`, `dd`, `fdisk`
- Privilege escalation: `sudo`, `su -`, `chmod 777`
- System control: `shutdown`, `reboot`, `init`
- Network backdoors: bash fork bombs, reverse shells
- File system injection: redirects to `/etc/passwd`, `/etc/sudoers`

### Path Traversal Protection
All file operations use `resolve_path()` to ensure:
- Paths are relative to workspace root
- No `../` escapes to parent directories
- Absolute paths are validated against workspace

### Timeout Protection
Shell commands and test execution have configurable timeouts (default 60s for commands, 120s for tests)

## Error Classification

MCPClient classifies errors into four types:

1. **Transient** (retryable)
   - Connection errors, timeouts, service unavailable
   - Auto-retry up to 3 times with exponential backoff

2. **Permission** (not retryable)
   - 401, 403 errors, approval required
   - Don't retry - requires user action

3. **Validation** (recoverable)
   - Missing required fields, invalid argument format
   - LLM can fix and retry

4. **Fatal** (not retryable)
   - Tool not found, invalid parameters
   - Won't succeed on retry

## Docker Compose Integration

MCP servers are defined in `docker-compose.yml`:

```yaml
mcp-coding:
  build: ./mcp-servers/coding
  ports: ["9001:9001"]
  volumes:
    - druppie_new_workspace:/workspaces
  depends_on:
    gitea: { condition: service_healthy }

mcp-docker:
  build: ./mcp-servers/docker
  ports: ["9002:9002"]
  volumes:
    - druppie_new_workspace:/workspaces
    - /var/run/docker.sock:/var/run/docker.sock
```

All MCPs share:
- `druppie_new_network` for internal communication
- `druppie_new_workspace` volume for workspace files

## Environment Variables

MCP servers use these environment variables:

**Coding MCP:**
- `WORKSPACE_ROOT`: Base path for workspaces (default: `/workspaces`)
- `MCP_PORT`: HTTP server port (default: `9001`)
- `GITEA_INTERNAL_URL`: Internal Gitea URL
- `GITEA_ORG`: Gitea organization name
- `GITEA_TOKEN`: Gitea API token
- `GITEA_USER`: Git push username
- `GITEA_PASSWORD`: Git push password

**Docker MCP:**
- `WORKSPACE_ROOT`: Base path for workspaces
- `MCP_PORT`: HTTP server port (default: `9002`)
- `DOCKER_NETWORK`: Docker network for containers
- `PORT_RANGE_START`: Start of port allocation range
- `PORT_RANGE_END`: End of port allocation range

**Backend (MCP Client):**
- `USE_MCP_MICROSERVICES`: Enable MCP microservices (`true`/`false`)
- `MCP_CODING_URL`: Coding MCP URL
- `MCP_DOCKER_URL`: Docker MCP URL
- `MCP_FILESEARCH_URL`: File search MCP URL

## Tool Result Caching

When an MCP tool requires approval:
1. Tool call pauses, approval record created
2. After user approves, tool executes
3. Result is stored in `context.completed_tool_results`
4. If agent re-runs and calls same tool, cached result returned
5. Prevents duplicate execution after approval

## Event Tracking

All tool calls emit events:
- Tool call started/completed events
- Tool error events
- Approval requested events
- WebSocket broadcast to frontend
- Database persistence in `tool_calls` table

## Adding a New MCP

To add a new MCP server:

1. Create directory in `mcp-servers/your-mcp/`
2. Add Dockerfile, module.py, server.py, requirements.txt
3. Define tools in `mcp_config.yaml`
4. Add service to `docker-compose.yml`
5. Configure agents to use new MCP tools
6. Update backend environment variables

See `MCP-BUILDER.md` for detailed template.
