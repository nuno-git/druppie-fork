# Druppie API Documentation

## Overview

Druppie provides a REST API for managing AI governance workflows, projects, and agent interactions. The API supports real-time updates via WebSocket and implements role-based access control through Keycloak.

**Base URL**: `http://localhost:8100/api`

**API Version**: 2.0.0

---

## Authentication

### JWT Authentication

Most endpoints require a valid JWT token from Keycloak in the `Authorization` header:

```
Authorization: Bearer <token>
```

### Internal API Key

MCP servers use internal API key authentication for server-to-server calls:

```
X-Internal-API-Key: <internal_api_key>
```

### Authentication Levels

| Level | Description |
|-------|-------------|
| Required | Must provide valid JWT token |
| Optional | Works with or without authentication |
| Admin | Requires admin role |
| Internal | Requires internal API key |

---

## Error Handling

All errors follow a consistent format:

```json
{
  "error_code": "NOT_FOUND",
  "message": "Session not found",
  "details": {
    "resource": "session",
    "id": "123e4567-e89b-12d3-a456-426614174000"
  },
  "timestamp": "2025-01-28T12:00:00Z",
  "request_id": "abc-123"
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| AUTH_REQUIRED | 401 | Authentication required |
| AUTH_INVALID_TOKEN | 401 | Invalid or malformed token |
| AUTH_TOKEN_EXPIRED | 401 | Token has expired |
| FORBIDDEN | 403 | Access denied |
| ROLE_REQUIRED | 403 | Specific role required |
| NOT_FOUND | 404 | Resource not found |
| SESSION_NOT_FOUND | 404 | Session not found |
| PROJECT_NOT_FOUND | 404 | Project not found |
| APPROVAL_NOT_FOUND | 404 | Approval not found |
| VALIDATION_ERROR | 422 | Request validation failed |
| CONFLICT | 409 | Resource conflict |
| APPROVAL_ALREADY_PROCESSED | 409 | Approval already handled |
| LLM_ERROR | 502 | LLM service error |
| MCP_ERROR | 502 | MCP server error |
| INTERNAL_ERROR | 500 | Server error |

---

## Health Check Endpoints

### GET /health

Simple health check.

**Response**: `200 OK`

---

### GET /health/ready

Readiness check including database and agent status.

**Response**:
```json
{
  "status": "ready",
  "database": true,
  "agents": 7
}
```

---

### GET /api/status

Full system status with all dependencies.

**Response**:
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "environment": "development",
  "keycloak": true,
  "database": true,
  "llm": true,
  "gitea": true,
  "agents_count": 7,
  "workflows_count": 3,
  "llm_provider": "deepinfra",
  "llm_model": "Qwen/Qwen3-Next-80B"
}
```

---

## Chat API

### POST /api/chat

Send a message and receive AI response. This is the main entry point for agent interactions.

**Auth**: Optional (creates anonymous session if not authenticated)

**Request**:
```json
{
  "message": "Build me a todo app",
  "session_id": "optional-session-uuid",
  "project_id": "optional-project-uuid",
  "project_name": "optional-project-name",
  "conversation_history": []
}
```

**Response**:
```json
{
  "success": true,
  "type": "response|question|plan|approval_required|error",
  "response": "I'll help you build a todo app...",
  "session_id": "session-uuid",
  "project_id": "project-uuid",
  "workspace_id": "workspace-uuid",
  "status": "completed|paused_approval|paused_question|running",
  "total_usage": {
    "prompt_tokens": 1500,
    "completion_tokens": 500,
    "total_tokens": 2000
  },
  "pending_approvals": [],
  "pending_questions": []
}
```

**Response Types**:
- `response` - Normal agent response
- `question` - HITL question requires user answer
- `plan` - Execution plan for approval
- `approval_required` - MCP tool needs approval
- `error` - Execution error

---

### POST /api/chat/{session_id}/resume

Resume a paused session by providing an answer or approval.

**Auth**: Required

**Request**:
```json
{
  "answer": "yes",
  "approved": true
}
```

**Response**: Same as POST /api/chat

---

### GET /api/chat/{session_id}/status

Get current session status with pending items.

**Auth**: Required

**Response**:
```json
{
  "session_id": "uuid",
  "status": "paused_approval",
  "pending_approvals": [
    {
      "id": "approval-uuid",
      "tool_name": "docker:build",
      "required_roles": ["developer"],
      "status": "pending"
    }
  ],
  "pending_questions": []
}
```

---

### GET /api/chat/{session_id}/events

Retrieve missed WebSocket events for a session.

**Auth**: Required

**Response**:
```json
{
  "events": [
    {
      "type": "agent_started",
      "agent_id": "developer",
      "timestamp": "2025-01-28T12:00:00Z"
    }
  ]
}
```

---

### POST /api/chat/{session_id}/cancel

Cancel an ongoing execution.

**Auth**: Required

**Response**:
```json
{
  "success": true,
  "message": "Session cancelled"
}
```

---

## Sessions API

### GET /api/sessions

List sessions with pagination and filtering.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| page | int | 1 | Page number |
| limit | int | 20 | Items per page (max 100) |
| project_id | uuid | - | Filter by project |
| status | string | - | Filter by status |

**Response**:
```json
{
  "items": [
    {
      "id": "session-uuid",
      "title": "Build todo app",
      "status": "completed",
      "project_id": "project-uuid",
      "project_name": "todo-app",
      "prompt_tokens": 5000,
      "completion_tokens": 2000,
      "total_tokens": 7000,
      "created_at": "2025-01-28T12:00:00Z",
      "updated_at": "2025-01-28T12:05:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 20
}
```

---

### GET /api/sessions/{id}

Get complete session details including execution tree.

**Auth**: Required

**Response**:
```json
{
  "id": "session-uuid",
  "title": "Build todo app",
  "status": "completed",
  "project_id": "project-uuid",
  "project_name": "todo-app",
  "workspace_id": "workspace-uuid",
  "prompt_tokens": 5000,
  "completion_tokens": 2000,
  "total_tokens": 7000,
  "agent_runs": [
    {
      "id": "run-uuid",
      "agent_id": "router",
      "status": "completed",
      "started_at": "2025-01-28T12:00:00Z",
      "completed_at": "2025-01-28T12:00:05Z",
      "prompt_tokens": 500,
      "completion_tokens": 100,
      "llm_calls": [...],
      "tool_calls": [...],
      "approvals": [...],
      "questions": [...]
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": "Build me a todo app",
      "agent_id": null,
      "tool_name": null,
      "created_at": "2025-01-28T12:00:00Z"
    }
  ],
  "events": [...],
  "workflow": {
    "name": "development",
    "status": "completed",
    "current_step": 3,
    "steps": [...]
  }
}
```

---

### DELETE /api/sessions/{id}

Delete a session.

**Auth**: Required (owner or admin)

**Response**: `204 No Content`

---

### GET /api/sessions/{id}/approvals

Get all approvals for a session.

**Auth**: Required

---

### GET /api/sessions/{id}/events

Get session events for debugging.

**Auth**: Required

---

## Approvals API

### GET /api/approvals

List pending approvals for current user based on their roles.

**Auth**: Required

**Response**:
```json
{
  "items": [
    {
      "id": "approval-uuid",
      "session_id": "session-uuid",
      "tool_name": "docker:build",
      "mcp_server": "docker",
      "mcp_tool": "build",
      "required_roles": ["developer"],
      "status": "pending",
      "arguments": {
        "dockerfile": "Dockerfile",
        "tag": "myapp:latest"
      },
      "agent_id": "deployer",
      "approval_type": "mcp_tool",
      "created_at": "2025-01-28T12:00:00Z"
    }
  ],
  "total": 5
}
```

---

### GET /api/approvals/{id}

Get approval details.

**Auth**: Required

**Response**:
```json
{
  "id": "approval-uuid",
  "session_id": "session-uuid",
  "tool_name": "docker:build",
  "mcp_server": "docker",
  "mcp_tool": "build",
  "required_roles": ["developer"],
  "status": "pending",
  "arguments": {
    "dockerfile": "Dockerfile",
    "tag": "myapp:latest"
  },
  "agent_id": "deployer",
  "approval_type": "mcp_tool",
  "created_at": "2025-01-28T12:00:00Z",
  "session": {
    "id": "session-uuid",
    "title": "Build todo app"
  }
}
```

---

### POST /api/approvals/{id}/approve

Approve a pending request. User must have one of the required roles.

**Auth**: Required (role-based)

**Request**:
```json
{
  "comment": "Looks good, approved"
}
```

**Response**:
```json
{
  "success": true,
  "approval_id": "approval-uuid",
  "status": "approved",
  "message": "Approval processed successfully"
}
```

**Error Cases**:
- `403` - User lacks required role
- `409` - Approval already processed
- `502` - Tool execution failed after approval

---

### POST /api/approvals/{id}/reject

Reject a pending request.

**Auth**: Required (role-based)

**Request**:
```json
{
  "reason": "Security concern with this operation"
}
```

**Response**:
```json
{
  "success": true,
  "approval_id": "approval-uuid",
  "status": "rejected"
}
```

---

### GET /api/approvals/session/{session_id}

Get all approvals for a specific session.

**Auth**: Required

---

## Projects API

### GET /api/projects

List user's projects.

**Auth**: Required

**Response**:
```json
{
  "items": [
    {
      "id": "project-uuid",
      "name": "todo-app",
      "description": "A simple todo application",
      "repo_url": "http://gitea:3000/user/todo-app",
      "created_at": "2025-01-28T12:00:00Z",
      "token_usage": {
        "prompt_tokens": 10000,
        "completion_tokens": 5000,
        "total_tokens": 15000
      },
      "session_count": 5,
      "main_build": {
        "id": "build-uuid",
        "status": "running",
        "app_url": "http://localhost:9100",
        "port": 9100
      }
    }
  ],
  "total": 10
}
```

---

### GET /api/projects/{id}

Get project details with builds, sessions, and repository info.

**Auth**: Required

**Response**:
```json
{
  "id": "project-uuid",
  "name": "todo-app",
  "description": "A simple todo application",
  "repo_url": "http://gitea:3000/user/todo-app",
  "created_at": "2025-01-28T12:00:00Z",
  "token_usage": {
    "prompt_tokens": 10000,
    "completion_tokens": 5000,
    "total_tokens": 15000
  },
  "session_count": 5,
  "main_build": {...},
  "preview_builds": [...],
  "app_url": "http://localhost:9100"
}
```

---

### POST /api/projects

Create a new project.

**Auth**: Required

**Request**:
```json
{
  "name": "my-project",
  "description": "Project description"
}
```

**Response**: Project object

---

### PUT /api/projects/{id}

Update project details.

**Auth**: Required (owner or admin)

**Request**:
```json
{
  "name": "new-name",
  "description": "Updated description"
}
```

---

### DELETE /api/projects/{id}

Delete a project.

**Auth**: Required (owner or admin)

---

### GET /api/projects/{id}/sessions

List sessions for a project.

**Auth**: Required

---

### GET /api/projects/{id}/files

Browse project files from Gitea.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| path | string | "" | Directory path |
| branch | string | "main" | Git branch |

**Response**:
```json
{
  "files": [
    {
      "name": "src",
      "path": "src",
      "type": "dir",
      "size": 0
    },
    {
      "name": "package.json",
      "path": "package.json",
      "type": "file",
      "size": 1234,
      "sha": "abc123"
    }
  ]
}
```

---

### GET /api/projects/{id}/file

Get file content from Gitea.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| path | string | File path (required) |
| branch | string | Git branch |

**Response**:
```json
{
  "content": "file content here...",
  "path": "src/main.py",
  "size": 1234,
  "encoding": "utf-8"
}
```

---

### GET /api/projects/{id}/branches

List git branches.

**Auth**: Required

---

### GET /api/projects/{id}/commits

Get recent commits.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| branch | string | "main" | Branch name |
| limit | int | 10 | Number of commits |

---

### GET /api/projects/{id}/builds

List builds for project.

**Auth**: Required

---

### POST /api/projects/{id}/build

Trigger a new build.

**Auth**: Required

**Request**:
```json
{
  "branch": "main"
}
```

---

## MCP API

### GET /api/mcps

List all MCP servers and their tools.

**Auth**: Required

**Response**:
```json
{
  "servers": [
    {
      "id": "coding",
      "name": "Coding MCP",
      "url": "http://mcp-coding:9001",
      "status": "healthy",
      "tools": [
        {
          "id": "coding:read_file",
          "name": "read_file",
          "description": "Read a file from the workspace",
          "requires_approval": false,
          "required_roles": []
        },
        {
          "id": "coding:write_file",
          "name": "write_file",
          "description": "Write content to a file",
          "requires_approval": false,
          "required_roles": []
        }
      ]
    },
    {
      "id": "docker",
      "name": "Docker MCP",
      "url": "http://mcp-docker:9002",
      "status": "healthy",
      "tools": [
        {
          "id": "docker:build",
          "name": "build",
          "description": "Build a Docker image",
          "requires_approval": true,
          "required_roles": ["developer"]
        }
      ]
    }
  ],
  "total_tools": 12
}
```

---

### GET /api/mcps/servers

List MCP servers with health status.

**Auth**: Required

---

### GET /api/mcps/tools

List all tools across all servers.

**Auth**: Required

---

### GET /api/mcps/tools/{tool_id}

Get tool details. Tool ID format: `server:tool_name`

**Auth**: Required

---

### GET /api/mcps/{server_id}

Get MCP server details.

**Auth**: Required

---

## Agents API

### GET /api/agents

List all configured agents.

**Auth**: Required

**Response**:
```json
{
  "items": [
    {
      "id": "router",
      "name": "Router",
      "description": "Classifies user intent and routes to appropriate agent",
      "model": "glm-4",
      "temperature": 0.1,
      "max_tokens": 4096,
      "mcps": ["hitl"],
      "category": "system"
    },
    {
      "id": "developer",
      "name": "Developer",
      "description": "Writes and modifies code",
      "model": "glm-4",
      "temperature": 0.1,
      "max_tokens": 8192,
      "mcps": ["coding", "hitl"],
      "category": "execution"
    }
  ],
  "count": 7
}
```

**Agent Categories**:
- `system` - Router, Planner
- `execution` - Developer, Architect
- `quality` - Reviewer, Tester
- `deployment` - Deployer

---

### GET /api/agents/{agent_id}

Get agent configuration.

**Auth**: Required

---

## Workspace API

### GET /api/workspace

List workspace files for a session.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| session_id | uuid | Session ID (required) |
| path | string | Directory path |
| recursive | bool | Include subdirectories |

**Response**:
```json
{
  "files": [
    {
      "name": "main.py",
      "path": "src/main.py",
      "type": "file",
      "size": 1234
    }
  ],
  "directories": [
    {
      "name": "components",
      "path": "src/components",
      "type": "dir"
    }
  ],
  "workspace_id": "workspace-uuid",
  "base_path": "/workspaces/abc123"
}
```

---

### GET /api/workspace/file

Get file content from workspace.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| session_id | uuid | Session ID (required) |
| path | string | File path (required) |

**Response**:
```json
{
  "content": "file content...",
  "path": "src/main.py",
  "size": 1234,
  "is_binary": false
}
```

---

### GET /api/workspace/download

Download file as attachment.

**Auth**: Required

---

### GET /api/workspace/{workspace_id}

Get workspace by ID.

**Auth**: Required

---

### GET /api/workspaces

List workspaces.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| project_id | uuid | Filter by project |
| limit | int | Max results |

---

## Questions API (HITL)

### GET /api/questions

List pending HITL questions for current user.

**Auth**: Required

**Response**:
```json
{
  "items": [
    {
      "id": "question-uuid",
      "session_id": "session-uuid",
      "agent_id": "architect",
      "question": "Should I use React or Vue for the frontend?",
      "question_type": "choice",
      "choices": ["React", "Vue", "Angular"],
      "status": "pending",
      "created_at": "2025-01-28T12:00:00Z"
    }
  ]
}
```

---

### GET /api/questions/{question_id}

Get question details.

**Auth**: Required

---

### POST /api/questions/{question_id}/answer

Answer a question and resume workflow.

**Auth**: Required

**Request**:
```json
{
  "answer": "React"
}
```

**Response**:
```json
{
  "success": true,
  "question_id": "question-uuid",
  "session_id": "session-uuid",
  "message": "Answer recorded, workflow resumed"
}
```

---

### GET /api/questions/session/{session_id}

Get questions for a session.

**Auth**: Required

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| status | string | Filter: pending, answered, all |

---

### POST /api/questions/internal/create

Create HITL question (internal API for MCP servers).

**Auth**: Internal API Key

**Request**:
```json
{
  "question_id": "uuid",
  "session_id": "session-uuid",
  "agent_id": "architect",
  "question": "Which database should we use?",
  "question_type": "choice",
  "choices": ["PostgreSQL", "MySQL", "MongoDB"]
}
```

---

## Workflows API

### GET /api/workflows

List available workflows.

**Auth**: Optional

**Response**:
```json
{
  "items": [
    {
      "id": "development",
      "name": "Development Workflow",
      "description": "Full development cycle with architect, developer, and deployer",
      "inputs": ["user_request", "project_id"],
      "entry_point": "router"
    }
  ]
}
```

---

### GET /api/workflows/{workflow_id}

Get workflow definition.

**Auth**: Optional

---

### POST /api/workflows/{workflow_id}/run

Run a workflow with inputs.

**Auth**: Required

**Request**:
```json
{
  "inputs": {
    "user_request": "Build a todo app",
    "project_id": "project-uuid"
  }
}
```

---

## Admin API

All admin endpoints require the `admin` role.

### GET /api/admin/tables

List all database tables.

**Response**:
```json
{
  "tables": [
    {
      "name": "sessions",
      "row_count": 150
    },
    {
      "name": "projects",
      "row_count": 25
    }
  ],
  "total_records": 5000
}
```

---

### GET /api/admin/table/{table_name}

Get paginated table data with filtering.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| page | int | 1 | Page number |
| limit | int | 50 | Items per page |
| order_by | string | id | Sort column |
| order_dir | string | desc | asc or desc |
| filter_field | string | - | Field to filter |
| filter_value | string | - | Filter value |

---

### GET /api/admin/table/{table_name}/{record_id}

Get single record with relationships.

---

### GET /api/admin/stats

Database statistics summary.

---

## WebSocket API

### Connection

**General Connection**:
```
ws://localhost:8100/ws
```

**Session-Specific Connection**:
```
ws://localhost:8100/ws/session/{session_id}
```

### Client Messages

**Join Session**:
```json
{
  "type": "join_session",
  "session_id": "session-uuid"
}
```

**Join Approval Rooms**:
```json
{
  "type": "join_approvals",
  "roles": ["admin", "developer"]
}
```

**Ping**:
```json
{
  "type": "ping"
}
```

### Server Events

**Connection Established**:
```json
{
  "type": "connected",
  "message": "Connected to Druppie WebSocket"
}
```

**Session Updates**:
```json
{
  "type": "session_updated",
  "session_id": "uuid",
  "status": "running",
  "data": {...}
}
```

**Agent Lifecycle**:
```json
{
  "type": "agent_started",
  "session_id": "uuid",
  "agent_id": "developer",
  "timestamp": "2025-01-28T12:00:00Z"
}
```

```json
{
  "type": "agent_completed",
  "session_id": "uuid",
  "agent_id": "developer",
  "result": {...},
  "timestamp": "2025-01-28T12:00:05Z"
}
```

**Tool Execution**:
```json
{
  "type": "tool_call",
  "session_id": "uuid",
  "agent_id": "developer",
  "tool_name": "coding:write_file",
  "arguments": {...}
}
```

```json
{
  "type": "tool_result",
  "session_id": "uuid",
  "tool_name": "coding:write_file",
  "success": true,
  "result": {...}
}
```

**Approval Required**:
```json
{
  "type": "approval_required",
  "approval_id": "uuid",
  "session_id": "uuid",
  "tool_name": "docker:build",
  "required_roles": ["developer"],
  "agent_id": "deployer",
  "args": {...}
}
```

**Approval Decision**:
```json
{
  "type": "approval_approved",
  "approval_id": "uuid",
  "session_id": "uuid",
  "approved": true,
  "approver_id": "user-uuid",
  "approver_role": "admin",
  "approver_username": "admin_user"
}
```

**HITL Question**:
```json
{
  "type": "question_pending",
  "question_id": "uuid",
  "session_id": "uuid",
  "question": "Which framework should I use?",
  "options": ["React", "Vue"]
}
```

**Deployment Complete**:
```json
{
  "type": "deployment_complete",
  "session_id": "uuid",
  "url": "http://localhost:9100",
  "container_name": "app-abc123",
  "port": 9100,
  "project_id": "project-uuid"
}
```

### Event Types Summary

| Event Type | Description |
|------------|-------------|
| connected | WebSocket connection established |
| session_updated | Session status changed |
| session_completed | Session finished successfully |
| session_failed | Session failed with error |
| session_paused | Session paused for approval/question |
| workflow_event | Generic workflow event |
| workflow_started | Workflow execution started |
| workflow_completed | Workflow finished |
| agent_started | Agent began execution |
| agent_completed | Agent finished successfully |
| agent_failed | Agent encountered error |
| tool_call | Tool invocation started |
| tool_result | Tool returned result |
| approval_required | MCP tool needs approval |
| approval_approved | Approval granted |
| approval_rejected | Approval denied |
| question_pending | HITL question waiting |
| question_answered | HITL question answered |
| deployment_complete | App deployed successfully |

---

## Rate Limiting

Currently no rate limiting is implemented. Consider implementing if needed for production.

---

## Pagination

List endpoints follow a consistent pagination pattern:

**Request Parameters**:
- `page` - Page number (1-indexed, default: 1)
- `limit` - Items per page (default: 20, max: 100)

**Response Format**:
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "limit": 20
}
```

---

## Common Response Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (successful delete) |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 409 | Conflict |
| 422 | Validation Error |
| 500 | Internal Server Error |
| 502 | External Service Error |

---

## Example Workflows

### 1. Start a Chat Session

```bash
# Send initial message
curl -X POST http://localhost:8100/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Build me a todo app"}'

# Response indicates session_id and status
```

### 2. Handle Approval Request

```bash
# List pending approvals
curl http://localhost:8100/api/approvals \
  -H "Authorization: Bearer $TOKEN"

# Approve specific request
curl -X POST http://localhost:8100/api/approvals/{id}/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Approved"}'
```

### 3. Answer HITL Question

```bash
# List pending questions
curl http://localhost:8100/api/questions \
  -H "Authorization: Bearer $TOKEN"

# Answer question
curl -X POST http://localhost:8100/api/questions/{id}/answer \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answer": "React"}'
```

### 4. WebSocket Connection

```javascript
const ws = new WebSocket('ws://localhost:8100/ws');

ws.onopen = () => {
  // Join session for real-time updates
  ws.send(JSON.stringify({
    type: 'join_session',
    session_id: 'your-session-id'
  }));

  // Join approval rooms based on roles
  ws.send(JSON.stringify({
    type: 'join_approvals',
    roles: ['admin', 'developer']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data.type, data);
};
```

---

## OpenAPI Specification

The full OpenAPI specification is available at:

- Swagger UI: `http://localhost:8100/docs`
- ReDoc: `http://localhost:8100/redoc`
- OpenAPI JSON: `http://localhost:8100/openapi.json`
