# Druppie Governance Platform - Claude Code Instructions

## Overview

Druppie is a governance platform for AI agents with MCP (Model Context Protocol) tool permissions, approval workflows, and project management integrated with Gitea.

## Architecture

```
User Request -> Router (LLM) -> Intent Analysis -> Planner (LLM) -> Execution Plan
                                                        |
                                                        v
                                              PlanExecutionEngine
                                                   /        \
                                           Workflows    AgentRuntime
                                                        (parallel tasks)
```

### Core Architecture Components (druppie/)

- **Router** (`router/router.py`): LangChain-based intent analysis, classifies user requests
- **Planner** (`planner/planner.py`): Creates execution plans using LLM
- **PlanExecutionEngine** (`plan_execution_engine.py`): Routes plans to WorkflowEngine or AgentRuntime
- **AgentRuntime** (`agents/runtime.py`): Parallel execution of autonomous agents
- **WorkflowEngine** (`workflows/engine.py`): Executes predefined workflow steps
- **MCPClient** (`mcp/client.py`): Invokes MCP tools
- **MCPRegistry** (`mcp/registry.py`): Loads MCP server definitions from YAML

### Infrastructure Components

- **Backend** (`/backend`): Flask API with Keycloak auth, SQLAlchemy ORM
- **Frontend** (`/frontend`): Vite + React with Keycloak OIDC
- **Keycloak**: Identity provider with role-based access control
- **Gitea**: Git server for project repositories
- **Docker-in-Docker**: Building and running user projects

## Setup & Running

```bash
# Full setup (first time)
./setup.sh all

# Start all services
docker compose up -d

# Rebuild backend after changes
docker compose build druppie-backend && docker compose up -d druppie-backend

# Rebuild frontend after changes
docker compose build druppie-frontend && docker compose up -d druppie-frontend

# View logs
docker compose logs -f druppie-backend
```

## Test Users (Keycloak)

| Username | Password | Roles |
|----------|----------|-------|
| admin | Admin123! | admin (full access) |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |
| infra | Infra123! | infra-engineer |

## API Endpoints

### Authentication
All endpoints (except `/health`) require Bearer token from Keycloak.

### Core Endpoints

```bash
# Get auth token
curl -X POST "http://localhost:8080/realms/druppie/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=druppie-frontend&username=admin&password=Admin123!"

# Chat (create project/ask questions)
POST /api/chat
{
  "message": "Create a todo app with Flask"
}

# List projects
GET /api/projects

# Get project details
GET /api/projects/<project_id>

# Build project
POST /api/projects/<project_id>/build

# Run project
POST /api/projects/<project_id>/run
```

## LLM Integration

The system uses Z.AI GLM API (OpenAI-compatible). Configure in `.env`:

```bash
LLM_PROVIDER=zai
ZAI_API_KEY=your_api_key
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
```

### LLM Router Flow

1. User sends message via `/api/chat`
2. Router analyzes intent (create_project, update_project, general_chat)
3. If action needed, creates Plan with Tasks
4. Tasks execute MCP tools (generate_app, docker.build, docker.run)
5. Results returned with project URLs

## Key Files

### Backend

- `app.py` - Flask routes and WebSocket handlers
- `druppie/llm_service.py` - LLM integration, router prompts, code generation
- `druppie/plans.py` - Plan/Task management, chat processing
- `druppie/project.py` - Project service, Gitea integration
- `druppie/builder.py` - Docker build/run service
- `druppie/mcp_registry.py` - MCP tool registry and permissions
- `druppie/auth.py` - Keycloak JWT authentication

### Frontend

- `src/pages/Chat.jsx` - Main chat interface
- `src/pages/Projects.jsx` - Project listing and management
- `src/context/AuthContext.jsx` - Keycloak authentication

### Configuration

- `iac/users.yaml` - Users, roles, MCP permissions, approval workflows
- `docker-compose.yml` - All services configuration
- `.env` - Environment variables (API keys, passwords)

## Development Workflow

1. **Making Backend Changes**:
   ```bash
   # Edit files in /backend
   docker compose build druppie-backend
   docker compose up -d druppie-backend
   docker compose logs -f druppie-backend
   ```

2. **Making Frontend Changes**:
   ```bash
   # Edit files in /frontend
   docker compose build druppie-frontend
   docker compose up -d druppie-frontend
   ```

3. **Testing the Chat API**:
   ```python
   import requests

   # Get token
   token_resp = requests.post(
       'http://localhost:8080/realms/druppie/protocol/openid-connect/token',
       data={
           'grant_type': 'password',
           'client_id': 'druppie-frontend',
           'username': 'admin',
           'password': 'Admin123!',
       }
   )
   token = token_resp.json()['access_token']

   # Create project
   resp = requests.post(
       'http://localhost:8000/api/chat',
       json={'message': 'Create a Flask todo app'},
       headers={'Authorization': f'Bearer {token}'}
   )
   print(resp.json())
   ```

## MCP Tool Permissions

Tools are controlled by role-based permissions defined in `iac/users.yaml`:

- **Auto-approve**: `filesystem.read`, `git.status`, `git.log`
- **User-approve**: `filesystem.write`, `shell.run`, `git.commit`
- **Role-approve**: `git.push`, `docker.build`, `docker.run`, `docker.deploy`

## Debugging

```bash
# Check all services
docker compose ps

# Backend logs
docker compose logs -f druppie-backend

# Keycloak logs
docker compose logs -f keycloak

# Gitea logs
docker compose logs -f gitea

# Check Gitea repos
curl -u gitea_admin:GiteaAdmin123 http://localhost:3000/api/v1/orgs/druppie/repos
```

## Common Issues

1. **"Invalid user credentials"**: Run `python3 scripts/setup_keycloak.py` to reset passwords
2. **"git: command not found"**: Rebuild backend (`docker compose build druppie-backend`)
3. **Gitea repo not created**: Check backend logs for API errors
4. **Frontend auth issues**: Clear browser storage, check Keycloak client config

## E2E Testing with Playwright (Standard)

**IMPORTANT**: Always use Playwright MCP tools for end-to-end testing. Do NOT use curl or bash commands for testing the UI or API interactions.

### Testing Workflow

1. **Navigate to the app**:
   ```
   Use: mcp__plugin_playwright_playwright__browser_navigate
   URL: http://localhost:5173
   ```

2. **Take a snapshot to see the page state**:
   ```
   Use: mcp__plugin_playwright_playwright__browser_snapshot
   ```

3. **Login via Keycloak**:
   - Navigate to login page
   - Fill username/password fields using browser_type or browser_fill_form
   - Click login button

4. **Test chat functionality**:
   - Navigate to Chat page
   - Type a message in the chat input
   - Submit and verify the response appears
   - Check the Debug panel for LLM calls (router_agent, planning_agent)

5. **Verify UI state**:
   - Use browser_snapshot to get the current page state
   - Check for expected elements, text, and data

### Test Users for Playwright

| Username | Password | Use Case |
|----------|----------|----------|
| admin | Admin123! | Full access testing |
| architect | Architect123! | Role-based testing |
| seniordev | Developer123! | Limited permissions |

### Example: Test Chat with Router and Planner

1. Navigate to `http://localhost:5173`
2. Login as admin
3. Go to Chat page
4. Send message: "Create a simple counter app"
5. Verify:
   - Router Agent appears in Debug panel
   - Planning Agent appears in Debug panel
   - Execution plan is shown
   - Response is generated

## Git Workflow for Claude

- Always commit and push changes after making modifications
- Use descriptive commit messages
- Group related changes into single commits
