# Druppie Governance Platform - Claude Code Instructions

## Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions, approval workflows, and project management integrated with Gitea.
workflow: always push and commit changes to git!
## Repository Structure

```
cleaner-druppie/
├── druppie/                   # FastAPI backend
│   ├── agents/                # YAML agent definitions
│   │   └── definitions/       # Agent YAML files (router.yaml, developer.yaml, etc.)
│   ├── workflows/             # YAML workflow definitions
│   │   └── definitions/       # Workflow YAML files
│   ├── mcp-servers/           # MCP microservices (Docker containers)
│   │   ├── coding/            # File ops + git (port 9001)
│   │   ├── docker/            # Container ops (port 9002)
│   │   └── hitl/              # Human-in-the-loop (port 9003)
│   ├── core/                  # Main loop, execution context, MCP client
│   │   ├── loop.py            # LangGraph main execution flow
│   │   ├── mcp_client.py      # HTTP client for MCP servers
│   │   └── mcp_config.yaml    # MCP tool definitions & approval rules
│   ├── llm/                   # LLM providers (zai, mock)
│   ├── api/                   # FastAPI routes
│   ├── db/                    # SQLAlchemy models & CRUD
│   ├── docker-compose.yml     # Full stack compose
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                  # React + Vite frontend
│   ├── src/
│   │   ├── pages/             # Dashboard, Chat, Tasks, Projects, Plans
│   │   ├── services/          # API, Keycloak, WebSocket
│   │   └── components/
│   ├── tests/e2e/             # Playwright E2E tests
│   └── Dockerfile
│
├── scripts/                   # Setup scripts
│   ├── setup_keycloak.py      # Keycloak realm/user setup
│   ├── setup_gitea.py         # Gitea organization setup
│   └── run_tests.sh           # Test runner
│
├── iac/                       # Infrastructure as Code
│   ├── realm.yaml             # Keycloak realm config
│   └── users.yaml             # Test user definitions
│
├── setup.sh                   # Main setup script
└── CLAUDE.md                  # This file
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Druppie Backend (FastAPI)                       │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────────┐ │
│  │ Main Loop   │───▶│  MCP Client  │───▶│  HTTP + Bearer Token   │ │
│  │ (LangGraph) │    │(mcp_config)  │    │                        │ │
│  └─────────────┘    └──────────────┘    └────────────────────────┘ │
│         │                                                           │
│         ▼                                                           │
│  ┌─────────────┐   Built-in HITL tools (no separate server)        │
│  │ Agent       │   - hitl_ask_question                             │
│  │ Runtime     │   - hitl_ask_multiple_choice_question             │
│  └─────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
         ┌──────────────────┐    ┌──────────────────┐
         │  Coding MCP      │    │   Docker MCP     │
         │  (FastMCP)       │    │  (FastMCP)       │
         │  Port 9001       │    │  Port 9002       │
         │                  │    │                  │
         │  - Workspace     │    │  - build/run     │
         │  - File ops      │    │  - stop/logs     │
         │  - Git ops       │    │  - Docker socket │
         │  - Auto-commit   │    │                  │
         └──────────────────┘    └──────────────────┘
```

**Key Principle**: Agents can ONLY act through MCP tools. No direct code output.

## Key Components

### 1. Agents (`druppie/agents/definitions/*.yaml`)

```yaml
# Example: druppie/agents/definitions/developer.yaml
name: developer
description: Writes and modifies code
system_prompt: |
  You are a senior developer. You write clean, working code.
  You can ONLY act through MCP tools.
mcps:
  - coding      # Read/write files, git ops
  - docker      # Build, run containers
  - hitl        # Ask user questions
settings:
  model: glm-4
  temperature: 0.1
```

### 2. MCP Servers (Microservices)

MCP servers run as separate Docker containers. Configuration is in `druppie/core/mcp_config.yaml`.

| Server | Port | Tools | Description |
|--------|------|-------|-------------|
| coding | 9001 | read_file, write_file, batch_write_files, list_dir, run_command, run_tests, commit_and_push | File, git, and test operations in workspace |
| docker | 9002 | build, run, stop, logs, list_containers | Container operations |

**NOTE**: HITL (Human-in-the-Loop) is now built into the agent runtime (`druppie/agents/hitl.py`). No separate MCP server is needed. Built-in tools: `hitl_ask_question`, `hitl_ask_multiple_choice_question`.

### 3. MCP Configuration & Layered Approval System (per goal.md)

**Two layers of approval rules:**

1. **mcp_config.yaml** = Global defaults for ALL agents
2. **agent.yaml** = Agent-specific overrides

#### Layer 1: Global Defaults (`druppie/core/mcp_config.yaml`)

```yaml
mcps:
  coding:
    url: ${MCP_CODING_URL:-http://mcp-coding:9001}
    tools:
      - name: write_file
        requires_approval: false  # DEFAULT: no approval
      - name: run_command
        requires_approval: true
        required_role: developer  # Singular, not array

  docker:
    tools:
      - name: build
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
      - name: run
        requires_approval: true
        required_role: developer  # ALWAYS needs developer approval
```

#### Layer 2: Agent Overrides (`druppie/agents/definitions/*.yaml`)

```yaml
# architect.yaml - OVERRIDES write_file to require architect approval
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: architect

# developer.yaml - NO overrides, uses global defaults
# write_file: no approval (default)
# docker:build/run: developer approval (global)
```

#### How It Works

```
Agent calls tool (e.g., coding:write_file)
    │
    ▼
Check agent's approval_overrides for this tool
    │
    ├─► Override exists? → Use override rules
    │
    └─► No override? → Use mcp_config.yaml defaults
```

| Agent | Tool | Override? | Result |
|-------|------|-----------|--------|
| architect | write_file | YES | Needs architect approval |
| developer | write_file | NO | No approval (default) |
| developer | docker:build | NO | Needs developer approval (global) |

### 4. LLM Service (`druppie/llm/`)

- `zai.py` - Z.AI GLM-4.7 provider with retry logic
- `mock.py` - Mock provider for testing
- `base.py` - Abstract interface

### 5. API (`druppie/api/`)

FastAPI endpoints:
- `POST /api/chat` - Main chat interface
- `GET /api/sessions` - List sessions
- `GET /api/approvals` - List pending approvals
- `POST /api/approvals/{id}/approve` - Approve action
- `GET /api/mcps` - List available MCP tools
- `WS /ws/session/{id}` - Real-time updates
- `POST /api/hitl/response` - Submit HITL answers

## Setup & Running

### Full Stack Setup (Recommended)

Uses:
- Frontend: http://localhost:5273
- Backend: http://localhost:8100
- Keycloak: http://localhost:8180
- Gitea: http://localhost:3100

```bash
# Full setup from project root
./setup.sh all

# Or individual steps:
./setup.sh infra      # Start DBs, Keycloak, Gitea
./setup.sh configure  # Configure Keycloak & Gitea
./setup.sh mcp        # Build & start MCP servers
./setup.sh app        # Build & start frontend/backend
```

### Other Commands

```bash
./setup.sh start      # Start all services
./setup.sh stop       # Stop all services
./setup.sh restart    # Restart all services
./setup.sh logs       # View logs (optionally specify service)
./setup.sh status     # Show service status
./setup.sh clean      # Remove all containers and volumes
./setup.sh build      # Build all services
```

## Test Users (Keycloak)

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin (full access) |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |
| juniordev | Junior123! | developer (limited) |

## LLM Configuration

Set in environment or `.env`:

```bash
LLM_PROVIDER=zai          # or 'mock' for testing
ZAI_API_KEY=your_api_key
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
```

## MCP Permission Model

Tools have approval requirements defined in `mcp_config.yaml`:

| Config | Description | Example |
|--------|-------------|---------|
| requires_approval: false | No approval needed | read_file |
| requires_approval: true + roles | Role required | run_command needs [developer] |
| danger_level: high | High-risk operation | run_command, merge_to_main |

When AI requests a tool that `requires_approval: true`:
1. Execution pauses
2. Approval record created in DB
3. Frontend shows approval request
4. User approves (must have required role)
5. Execution resumes

## Development Workflow

### Adding a New Agent

1. Create YAML in `druppie/agents/definitions/`:
```yaml
name: my_agent
description: What it does
system_prompt: |
  Your instructions...
mcps:
  - coding
  - hitl
settings:
  model: glm-4
  temperature: 0.1
```

2. The agent is automatically loaded by the runtime

### Adding a New MCP Tool

1. Add tool function in `druppie/mcp-servers/{server}/server.py`
2. Add tool config in `druppie/core/mcp_config.yaml`
3. Set approval requirements

### Modifying the Frontend

```bash
cd frontend
npm install
npm run dev  # Dev server on port 5173
```

## Key Design Decisions

1. **Agents can only act through MCPs** - No direct LLM output to files
2. **YAML-defined agents** - System prompts and settings in YAML
3. **MCP Microservices** - MCP servers run as separate Docker containers
4. **Permission-based tool access** - Role-based approval workflows via mcp_config.yaml
5. **Human-in-the-loop (HITL)** - Agents can ask questions via Redis pub/sub
6. **Session-based state** - Execution can pause and resume via LangGraph checkpoints

## Troubleshooting

### Slow VM / Keycloak takes long to initialize

**IMPORTANT**: On slow VMs or machines with limited resources, Keycloak can take 30-60 seconds or more to fully initialize. If the frontend login page shows errors or the Keycloak login doesn't appear:

1. **Wait longer** - Keycloak needs time to start up fully
2. Check Keycloak health: `curl http://localhost:8180/health/ready`
3. Wait for "status: UP" before trying to log in
4. The frontend will automatically retry authentication once Keycloak is ready

Don't assume something is broken - just wait and refresh the page after 30+ seconds.

### Backend won't start
```bash
docker logs druppie-new-backend
```

### MCP servers won't start
```bash
# Check individual MCP server logs
docker logs mcp-coding
docker logs mcp-docker
docker logs mcp-hitl
```

### Keycloak issues
```bash
# Check health
curl http://localhost:8180/health/ready

# Reimport realm
python scripts/setup_keycloak.py
```

### Database issues
```bash
# Reset database
./setup.sh clean
./setup.sh all
```

### Check all service status
```bash
./setup.sh status
```

## Key Learnings & Common Issues

### Issue: Session Status Endpoint Using Non-Existent _state_manager
**Symptom**: `/chat/{session_id}/status` crashes with AttributeError
**Cause**: New LangGraph architecture doesn't use _state_manager
**Fix**: Query database directly for session state, approvals, and questions

### Issue: Approval Errors Return success: true
**Symptom**: Frontend shows approval succeeded when MCP execution failed
**Cause**: Exception handler returned `{"success": True}` even on error
**Fix**: Return `{"success": False, "status": "execution_failed"}` on errors

### Issue: Database Connection Leaks in loop.py
**Symptom**: Connection pool exhaustion under load
**Cause**: `next(get_db())` not properly closed on exceptions
**Fix**: Use context manager with comprehensive finally block

### Issue: MCP Tool Errors Not Properly Handled in runtime.py
**Symptom**: Agents don't distinguish tool success from failure
**Cause**: Only checking for "paused" status, not error status
**Fix**: Check `success=False` or `error` field, emit tool_error event

### Issue: Approvals Without Roles Approvable by Anyone
**Symptom**: Security issue - any user can approve if required_roles is empty
**Fix**: Default to `["admin"]` if required_roles is None or empty

### Issue: Router Agent Asking Unnecessary HITL Questions
**Symptom**: Router uses `hitl:ask_question` for simple tasks like "Create a hello.txt file"
**Fix**: Update router.yaml system prompt to be decisive - only ask HITL for truly ambiguous requests
**Key**: Add explicit examples of CLEAR vs AMBIGUOUS requests in the prompt

### Issue: Developer Agent Asking for user_id/workspace_id
**Symptom**: Developer uses `hitl:ask_question` to ask "What is your user ID?"
**Fix**: Update developer.yaml to explain workspace is ALREADY initialized from CONTEXT
**Key**: Pass workspace context via ExecutionContext, inject into tool args automatically

### Issue: `'FunctionTool' object is not callable` Error
**Symptom**: write_file fails when calling commit_and_push internally
**Cause**: Functions decorated with `@mcp.tool()` become FunctionTool objects, not callable
**Fix**: Create separate internal `_do_commit_and_push()` function, keep `commit_and_push` as MCP wrapper
**Pattern**: Always separate internal logic from MCP decorators for functions that call each other

### Issue: Workspace Context Not Reaching MCP Tools
**Symptom**: MCP tools receive placeholder workspace_id instead of actual value
**Fix**: Auto-inject context in `agents/runtime.py` before calling MCP:
```python
if exec_ctx and server == "coding" and "workspace_id" not in tool_args:
    tool_args["workspace_id"] = exec_ctx.workspace_id
```

### Architecture Reminder
- `loop.py` - Keep simple/abstract, orchestrates LangGraph states
- `agents/runtime.py` - Tool-calling loop, injects context
- `core/mcp_client.py` - HTTP client with approval checking
- MCP servers - FastMCP microservices in Docker containers
- Agent definitions - YAML files in `agents/definitions/`

### E2E Testing
Always verify changes with Playwright E2E tests:

```bash
cd frontend
npm run test:e2e  # Full suite (25 tests)
npx playwright test tests/e2e/chat.spec.js:54  # Specific test
```

**Playwright Strict Mode**: When multiple elements match a selector, use:
- `.first()` to get the first match
- `{ exact: true }` for exact text matching
- More specific selectors (role, testid)

Example fix:
```javascript
// Bad - fails if multiple matches
await page.getByText('Deploy to staging').click()

// Good - handles multiple matches
await page.getByText('Deploy to staging').first().click()
await page.getByRole('link', { name: 'Chat', exact: true }).click()
```

**Test Ports**: Full-stack deployment uses:
- Frontend: 5273
- Backend: 8100
- Keycloak: 8180

## Current Agents (7 total)

| Agent | Purpose | Key Tools |
|-------|---------|-----------|
| router | Classifies user intent | hitl |
| planner | Creates execution plans | hitl |
| architect | Designs system architecture | coding, hitl |
| developer | Writes and modifies code | coding, hitl |
| reviewer | Reviews code quality | coding, hitl |
| deployer | Deploys to environments | docker, hitl |
| tester | Runs tests and validates | coding:run_tests, hitl |

## Recent Improvements

### Centralized Configuration (`druppie/core/config.py`)
Single source of truth for all configuration:
- `Settings` class with nested Pydantic models
- Environment variable support with sensible defaults
- Database, Redis, Keycloak, Gitea, LLM, MCP, API settings
- Access via `get_settings()` singleton

```python
from druppie.core.config import get_settings
settings = get_settings()
db_url = settings.database.url
cors_origins = settings.api.cors_origins_list
```

### Standardized API Errors (`druppie/api/errors.py`)
Consistent error responses across all endpoints:
- `ErrorCode` enum with machine-readable codes (AUTH_REQUIRED, NOT_FOUND, etc.)
- `ErrorResponse` model with code, message, details, timestamp, request_id
- Exception classes: `NotFoundError`, `AuthenticationError`, `AuthorizationError`, `ValidationError`
- Registered via `register_exception_handlers(app)`

### Role-Based Authorization Helpers (`druppie/api/deps.py`)
Clean authorization patterns:
- `get_user_roles(user)` - Extract roles from token
- `user_has_role(user, role)` - Check single role (admin bypass)
- `require_role("admin")` - Dependency for route authorization
- `require_any_role(["dev", "admin"])` - Multiple roles
- `check_resource_ownership(user, owner_id)` - Ownership validation

```python
@router.delete("/resource/{id}")
async def delete_resource(
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_role("admin")),  # Admin only
):
    pass
```

### Debug Panel (`/debug/:sessionId`)
Full execution transparency with:
- Event tree showing all agent, tool, and LLM calls
- Timeline with durations
- Expandable details for each event

### Session History
Chat sidebar shows previous conversations with:
- Session previews
- Debug links
- Project associations

### Tool Validation
Validates required arguments before MCP calls:
- Catches missing fields early
- Returns recoverable error for LLM to retry
- Logs validation errors separately

### batch_write_files
Create multiple files with single git commit:
```python
batch_write_files(files={"src/main.py": "...", "package.json": "..."})
```

### run_tests
Auto-detects and runs test frameworks:
- Python: pytest, unittest
- Node.js: jest, mocha, vitest
- Go: go test
- Returns structured pass/fail counts

### Workspace API (`/api/workspace`)
REST API for browsing workspace files:
- `GET /api/workspace` - List files for a session
- `GET /api/workspace/file` - Get file content
- `GET /api/workspace/{id}` - Get workspace details
- Includes path traversal protection

### Project Detail Page (`/projects/:projectId`)
Comprehensive project view with tabs:
- Overview: Project info, repo URL, build/run actions
- Repository: Branch list, recent commits from Gitea
- Conversations: Sessions linked to project
- Settings: Edit project name/description

### Settings Page (`/settings`)
Admin configuration page with:
- User Profile: Current user info and roles
- System Info: Service health status
- MCP Servers: List with health checks
- Configured Agents: Agent list with descriptions

## Frontend Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | / | Overview and stats |
| Chat | /chat | Main agent interaction |
| Projects | /projects | Project list |
| Project Detail | /projects/:id | Comprehensive project view |
| Tasks | /tasks | Pending approvals |
| Plans | /plans | Execution plans |
| Debug | /debug/:id | Execution trace viewer |
| Settings | /settings | System configuration |

## Development Best Practices

### DB Session Management
Use the `db_session()` context manager in loop.py for guaranteed cleanup:
```python
with db_session() as db:
    # Database operations here - always cleaned up
```

### MCP Error Handling
Always check MCP tool results for errors:
```python
result = await mcp_client.call_tool(...)
if result.get("success") is False or "error" in result:
    # Handle error - log, emit event, format for agent
```

### Security: Approval Role Defaults
If a tool approval doesn't specify required_roles, default to admin:
```python
required_roles = approval.required_roles if approval.required_roles else ["admin"]
```

### Context Injection
Only inject fields the MCP tool actually accepts:
- For coding tools: inject `workspace_id`
- For hitl tools: inject `session_id`
- Don't inject project_id, workspace_path, branch to MCP tools

### Database Migrations
Use the migration system in `druppie/db/migrations.py`:
- Add new columns via migration functions
- System tracks applied migrations in `_migrations` table
- Handle "column already exists" errors gracefully
- Migrations run automatically on startup after table creation

### Frontend Components
Key reusable components added:
- `ErrorBoundary.jsx` - Catch React errors with retry UI
- `ConnectionStatus.jsx` - WebSocket status indicator
- `CodeBlock.jsx` - Syntax highlighted code with copy button

### Deep Linking
Chat supports URL parameters for direct navigation:
- `/chat?session=xxx` loads specific session
- URL updates when switching sessions
- Debug page "Back to Chat" preserves session context

### Accessibility
All interactive elements should have:
- `aria-label` for icon-only buttons
- `focus:ring` for visible focus states
- `aria-expanded` for expandable sections

### N+1 Query Prevention
Batch load related data instead of querying per-item:
```python
# In builder.py
builds_by_project = builder.get_builds_for_projects(project_ids)
for project in projects:
    builds = builds_by_project.get(project.id, {"main": None, "previews": []})
```

### Approval Error Types
Distinct error types for frontend handling:
- `workspace_missing`, `mcp_unavailable`, `tool_execution_failed`
- `invalid_arguments`, `session_resume_failed`
- Returns `error_type`, `user_message`, `retryable` in responses

### Pagination Standards
All list endpoints should follow:
- Parameters: `page` (1-indexed, default=1), `limit` (default=20, max=100)
- Response: `{items: [...], total: N, page: N, limit: N}`

### MCP Security
The coding MCP blocks dangerous commands. Key blocked patterns:
- Destructive: `rm -rf /`, `mkfs`, `dd if=`
- Privilege: `sudo`, `su -`
- Permissions: `chmod 777`, `chown` on system dirs
- Reverse shells: `nc -e`, `curl|bash`, `wget|bash`

All MCP servers use Python logging (not print) for production monitoring.

### Security: Dev Mode Protection
The dev mode authentication bypass is protected:
- Cannot be enabled when `ENVIRONMENT=production` or `ENVIRONMENT=prod`
- Logs a warning when enabled in development
- Set `DEV_MODE=true` only in local development

### Security: Credential Warnings
Services log warnings when credentials are not configured:
- `GITEA_ADMIN_PASSWORD` - Required for Gitea operations
- `INTERNAL_API_KEY` - Required for internal MCP→Backend calls

### Logging Best Practices
Always include `exc_info=True` in logger.error calls within exception handlers:
```python
except Exception as e:
    logger.error("operation_failed", error=str(e), exc_info=True)
```

This preserves the full stack trace for debugging.

### Standardized Error Classes
Use the error classes from `druppie/api/errors.py`:
- `NotFoundError("resource", resource_id)` - 404 errors
- `ValidationError("message", field="field_name")` - 422 validation errors
- `ConflictError("message")` - 409 conflicts
- `AuthorizationError("message", required_roles=["admin"])` - 403 forbidden
- `ExternalServiceError("service", "message")` - 502 external service errors

Example usage:
```python
from druppie.api.errors import NotFoundError, ExternalServiceError

if not project:
    raise NotFoundError("project", project_id)

if not result.get("success"):
    raise ExternalServiceError("gitea", f"Failed: {result.get('error')}")
```

### Datetime Best Practices
Use timezone-aware datetime instead of deprecated `datetime.utcnow()`:
```python
from datetime import datetime, timezone

# Bad - deprecated in Python 3.12+
timestamp = datetime.utcnow()

# Good - timezone-aware
timestamp = datetime.now(timezone.utc)
```

### Consistent Logging with structlog
Use `structlog` throughout the codebase, not the `logging` module:
```python
import structlog
logger = structlog.get_logger()

# Use kwargs-style (not f-strings)
logger.info("event_name", key1=value1, key2=value2)
logger.error("error_occurred", error=str(e), exc_info=True)
```

### Safe Array Access
Use `next(iter())` pattern for safe array access:
```python
# Bad - potential IndexError
role = user_roles[0] if user_roles else "user"

# Good - safe and readable
role = next(iter(user_roles), "user")
```

### Input Validation on Request Models
Always add validation to Pydantic request models:
```python
from pydantic import BaseModel, Field
from typing import Literal

class QuestionRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=10000)
    question_type: Literal["text", "choice"] = "text"
    comment: str | None = Field(None, max_length=2000)
```

### WebSocket Memory Management
The ConnectionManager has bounded buffers to prevent memory leaks:
- `MAX_MISSED_EVENTS_PER_SESSION = 100` - Oldest events dropped when full
- `cleanup_stale_sessions()` - Call periodically to remove orphaned data
- `get_stats()` - Monitor connection and buffer statistics

### Configuration Without Hardcoded Credentials
Never hardcode default passwords in config. Use empty defaults and warn:
```python
admin_password: str = Field(
    default="",  # No default value!
    description="Admin password (required)",
)

@property
def is_configured(self) -> bool:
    return bool(self.admin_password)
```
