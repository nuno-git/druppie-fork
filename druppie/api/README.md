# API Layer

The API layer defines FastAPI routes, dependency injection, and error handling. Routes are intentionally thin -- they validate input, call a service, and return the result.

## Architecture

```
HTTP Request
    |
    v
  FastAPI Router  (api/routes/*.py)
    |
    |--> Depends(get_current_user)       # auth from deps.py
    |--> Depends(get_session_service)     # service injection from deps.py
    |
    v
  Service Layer  (services/*.py)
```

## Files

### `main.py`
FastAPI application factory. Sets up:
- CORS middleware (origins from environment config).
- All route routers mounted under `/api` prefix.
- Health check endpoint at `/api/health`.

### `deps.py`
**Dependency injection wiring** -- the most architecturally important file. Contains factory functions that wire the clean architecture layers:

**Repository factories** (inject DB session):
```python
def get_session_repository(db = Depends(get_db)) -> SessionRepository
def get_approval_repository(db = Depends(get_db)) -> ApprovalRepository
def get_project_repository(db = Depends(get_db)) -> ProjectRepository
def get_question_repository(db = Depends(get_db)) -> QuestionRepository
def get_execution_repository(db = Depends(get_db)) -> ExecutionRepository
```

**Service factories** (inject repositories):
```python
def get_session_service(session_repo = Depends(...)) -> SessionService
def get_approval_service(approval_repo = Depends(...)) -> ApprovalService
def get_question_service(question_repo, session_repo = Depends(...)) -> QuestionService
def get_project_service(project_repo = Depends(...)) -> ProjectService
def get_workflow_service(orchestrator = Depends(...)) -> WorkflowService
```

**Auth functions**:
- `get_current_user(authorization)` -- validates JWT token via Keycloak, syncs user to database on every request. Returns user dict or raises 401.
- `get_optional_user(authorization)` -- same but returns None instead of 401.
- `verify_internal_api_key(header)` -- validates internal API key for MCP server callbacks.

**Role-based authorization**:
- `get_user_roles(user)` -- extracts roles from token.
- `require_role(role)` / `require_any_role(roles)` -- FastAPI dependencies that raise 403 if the user lacks the required role.
- `require_admin(user)` -- shorthand for requiring admin role.
- `check_resource_ownership(user, resource_user_id)` -- checks ownership or admin access.

### `errors.py`
Custom exception classes that map to HTTP status codes:
- `NotFoundError(resource_type, resource_id)` -- maps to 404.
- `ValidationError(message, field)` -- maps to 422.
- `ForbiddenError(message)` -- maps to 403.

These are raised by routes and services, caught by FastAPI exception handlers registered in `main.py`.

### `schemas.py`
Request/response schemas for API endpoints. Pydantic models for request bodies (e.g., `ChatRequest`, `ApprovalAction`). Response models typically come from the domain layer directly.

## Routes (`routes/` subdirectory)

### `routes/__init__.py`
Empty init file. Routes are registered in `main.py`.

### `routes/sessions.py`
Session management endpoints:
- `GET /api/sessions` -- list user's sessions.
- `GET /api/sessions/{id}` -- get session detail with full timeline.
- `DELETE /api/sessions/{id}` -- delete a session.

### `routes/chat.py`
Chat/message processing endpoints:
- `POST /api/chat` -- send a user message. Creates or continues a session. Triggers the orchestrator pipeline (router -> planner -> agents).
- This is the main entry point for the agent workflow.

### `routes/approvals.py`
Approval workflow endpoints:
- `GET /api/approvals/pending` -- list pending approvals for current user.
- `GET /api/approvals/{id}` -- get approval detail.
- `POST /api/approvals/{id}/approve` -- approve a tool execution. Resumes the paused workflow.
- `POST /api/approvals/{id}/reject` -- reject with reason.

### `routes/questions.py`
HITL question endpoints:
- `GET /api/questions/pending` -- list pending questions for a session.
- `GET /api/questions/{id}` -- get question detail.
- `POST /api/questions/{id}/answer` -- submit an answer. Resumes the paused workflow.

### `routes/projects.py`
Project CRUD endpoints:
- `GET /api/projects` -- list user's projects.
- `GET /api/projects/{id}` -- get project detail.
- `POST /api/projects` -- create a new project.

### `routes/deployments.py`
Deployment management endpoints:
- `GET /api/deployments` -- list active deployments.
- `GET /api/deployments/{project_id}` -- get deployment status.
- `POST /api/deployments/{project_id}/stop` -- stop a running container.

### `routes/agents.py`
Agent definition endpoints:
- `GET /api/agents` -- list available agent definitions (loaded from YAML).
- `GET /api/agents/{id}` -- get agent definition detail.

### `routes/mcps.py`
MCP server and tool management:
- `GET /api/mcps` -- list MCP servers with tools (role-filtered).
- `GET /api/mcps/servers` -- list servers with health status.
- `GET /api/mcps/tools` -- flat list of all tools.
- `GET /api/mcps/tools/{id}` -- get specific tool details.
- `GET /api/mcps/{server_id}` -- get server details with tools.

### `routes/mcp_bridge.py`
Direct MCP tool testing bridge (bypasses agent workflow):
- `GET /api/mcp/servers` -- list MCP servers.
- `GET /api/mcp/servers/{server}/tools` -- list tools from a server (merges config + live).
- `POST /api/mcp/call` -- call an MCP tool directly. For testing only.

### `routes/workspace.py`
Workspace file browsing via Coding MCP:
- `GET /api/workspace/files` -- list files in a session's workspace.
- `GET /api/workspace/file` -- get file content.

## Layer Connections

- **Depends on**: `druppie.services` (business logic), `druppie.domain` (response models), `druppie.core.auth` (authentication), `druppie.db` (session factory), `druppie.execution` (orchestrator via deps).
- **Depended on by**: Nothing (top of the call stack).

## Conventions

1. Routes are thin: validate input, call service, return result.
2. All routes require authentication via `Depends(get_current_user)` unless explicitly optional.
3. Authorization is enforced in services, not routes.
4. Response models are domain models from `druppie/domain/`.
5. Dependency injection is defined in `deps.py`, not inline in route files.
6. Route files use the `router = APIRouter()` pattern and are mounted in `main.py`.
