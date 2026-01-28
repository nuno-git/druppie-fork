# API Reference

All endpoints require authentication via Keycloak (Bearer token).

## Base URL

```
http://localhost:8100/api
```

## Sessions

### List Sessions

```
GET /sessions
```

Query params:
- `page` (int, default=1) - Page number
- `limit` (int, default=20) - Items per page
- `status` (string, optional) - Filter by status

Response:
```json
{
  "items": [
    {
      "id": "uuid",
      "title": "Build a todo app",
      "status": "completed",
      "project_id": "uuid | null",
      "token_usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500
      },
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 20
}
```

### Get Session Detail

```
GET /sessions/{session_id}
```

Response:
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": "Build a todo app",
  "status": "completed",
  "token_usage": {
    "prompt_tokens": 6014,
    "completion_tokens": 318,
    "total_tokens": 6332
  },
  "tokens_by_agent": {
    "router": 2000,
    "developer": 4332
  },
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",

  "project": {
    "id": "uuid",
    "name": "todo-app",
    "description": "A simple todo application",
    "git_url": "http://gitea:3000/org/todo-app",
    "status": "active",
    "deployment": {
      "status": "running",
      "app_url": "http://localhost:9100",
      "container_name": "todo-app-main",
      "started_at": "2024-01-01T00:00:00Z"
    }
  },

  "chat": [
    {
      "type": "system_message",
      "content": "Hello! I'm Druppie...",
      "timestamp": "2024-01-01T00:00:00Z"
    },
    {
      "type": "user_message",
      "content": "Build a todo app",
      "timestamp": "2024-01-01T00:00:01Z"
    },
    {
      "type": "agent_run",
      "id": "uuid",
      "agent_id": "router",
      "status": "completed",
      "token_usage": {...},
      "started_at": "...",
      "completed_at": "...",
      "steps": [
        {
          "type": "llm_call",
          "id": "uuid",
          "model": "glm-4",
          "provider": "zai",
          "token_usage": {...},
          "tools_decided": ["hitl:ask_question"]
        },
        {
          "type": "tool_execution",
          "id": "uuid",
          "tool": "coding:write_file",
          "arguments": {"path": "app.py", "content": "..."},
          "status": "executed",
          "approval": null
        }
      ]
    },
    {
      "type": "assistant_message",
      "content": "I've created your todo app...",
      "agent_id": "developer",
      "timestamp": "..."
    }
  ]
}
```

### Delete Session

```
DELETE /sessions/{session_id}
```

Response: `204 No Content`

## Chat

### Send Message

```
POST /chat
```

Request:
```json
{
  "message": "Build a todo app with Flask",
  "session_id": "uuid | null",
  "project_id": "uuid | null"
}
```

Response:
```json
{
  "success": true,
  "session_id": "uuid",
  "message": "I'll help you build a todo app...",
  "status": "completed | paused_approval | paused_hitl",
  "approval_id": "uuid | null",
  "question_id": "uuid | null"
}
```

## Approvals

### List Pending Approvals

```
GET /approvals
```

Returns approvals the current user can act on (based on their roles).

Response:
```json
{
  "items": [
    {
      "id": "uuid",
      "session_id": "uuid",
      "agent_run_id": "uuid",
      "tool": "docker:build",
      "arguments": {
        "image_name": "myapp",
        "dockerfile_path": "./Dockerfile"
      },
      "status": "pending",
      "required_role": "developer",
      "created_at": "..."
    }
  ],
  "total": 5
}
```

### Get Approval Detail

```
GET /approvals/{approval_id}
```

### Approve

```
POST /approvals/{approval_id}/approve
```

Request:
```json
{
  "comment": "Looks good, approved"
}
```

Response:
```json
{
  "success": true,
  "status": "approved",
  "tool_result": {...}
}
```

### Reject

```
POST /approvals/{approval_id}/reject
```

Request:
```json
{
  "reason": "Code needs security review first"
}
```

## HITL Questions

### List Pending Questions

```
GET /questions
```

Response:
```json
{
  "items": [
    {
      "id": "uuid",
      "session_id": "uuid",
      "agent_id": "architect",
      "question": "What database do you prefer?",
      "question_type": "multiple_choice",
      "choices": ["PostgreSQL", "MySQL", "SQLite"],
      "status": "pending",
      "created_at": "..."
    }
  ]
}
```

### Answer Question

```
POST /questions/{question_id}/answer
```

Request:
```json
{
  "answer": "PostgreSQL",
  "selected_choices": [0]
}
```

## Projects

### List Projects

```
GET /projects
```

Response:
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "todo-app",
      "description": "A todo application",
      "repo_url": "http://gitea:3000/org/todo-app",
      "status": "active",
      "token_usage": {
        "total_tokens": 15000,
        "session_count": 3
      },
      "created_at": "..."
    }
  ]
}
```

### Get Project Detail

```
GET /projects/{project_id}
```

Response includes builds and deployments.

### Delete Project

```
DELETE /projects/{project_id}
```

## Deployments (Bridge to Docker MCP)

The deployments API is a **bridge** to the docker MCP. It lets the frontend manage containers that agents have deployed.

**How it works:**
```
Frontend → POST /api/deployments/{id}/stop → Backend → docker MCP: stop → Container stopped
```

### List Running Deployments

```
GET /deployments
```

**Backend:** Queries database for deployment records.

Response:
```json
{
  "items": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "project_name": "todo-app",
      "container_name": "todo-app-main",
      "host_port": 9100,
      "app_url": "http://localhost:9100",
      "status": "running",
      "started_at": "..."
    }
  ]
}
```

### Stop Deployment

```
POST /deployments/{deployment_id}/stop
```

**Backend calls:** `docker:stop`

Response:
```json
{
  "success": true,
  "status": "stopped"
}
```

### Restart Deployment

```
POST /deployments/{deployment_id}/restart
```

**Backend calls:** `docker:stop` then `docker:run`

Response:
```json
{
  "success": true,
  "status": "running",
  "app_url": "http://localhost:9100"
}
```

### Get Deployment Logs

```
GET /deployments/{deployment_id}/logs?tail=100
```

**Backend calls:** `docker:logs`

Query params:
- `tail` (int, default=100) - Number of lines

Response:
```json
{
  "container_name": "todo-app-main",
  "logs": "2024-01-01 10:00:00 Starting server...\n..."
}
```

## Agents

### List Agents

```
GET /agents
```

Response:
```json
{
  "items": [
    {
      "id": "router",
      "name": "Router Agent",
      "description": "Classifies user intent",
      "model": "glm-4",
      "temperature": 0.1,
      "max_tokens": 2048,
      "mcps": []
    },
    {
      "id": "developer",
      "name": "Developer",
      "description": "Writes code",
      "model": "glm-4",
      "temperature": 0.2,
      "mcps": ["coding", "hitl"]
    }
  ]
}
```

## MCP Servers

### List MCP Servers and Tools

```
GET /mcps
```

Response:
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
          "name": "write_file",
          "description": "Write content to a file",
          "requires_approval": false
        },
        {
          "name": "run_command",
          "description": "Run a shell command",
          "requires_approval": true,
          "required_role": "developer"
        }
      ]
    }
  ]
}
```

## Workspace (Bridge to Coding MCP)

The workspace API is a **bridge** to the coding MCP. It lets the frontend browse files that agents have written.

**How it works:**
```
Frontend → GET /api/workspace/files → Backend → coding MCP: list_dir → Files
```

### List Files

```
GET /workspace/files?session_id={session_id}&path={path}
```

Query params:
- `session_id` (required) - Session to get workspace for
- `path` (optional) - Subdirectory to list

**Backend calls:** `coding:list_dir`

Response:
```json
{
  "workspace_id": "uuid",
  "session_id": "uuid",
  "path": "src",
  "files": [
    {"name": "app.py", "path": "src/app.py", "type": "file", "size": 1234}
  ],
  "directories": [
    {"name": "components", "path": "src/components", "type": "directory"}
  ]
}
```

### Get File Content

```
GET /workspace/file?session_id={session_id}&path={path}
```

**Backend calls:** `coding:read_file`

Response:
```json
{
  "path": "src/app.py",
  "content": "from flask import Flask...",
  "size": 1234
}
```

## Health

### Health Check

```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "database": "connected",
  "mcp_servers": {
    "coding": "healthy",
    "docker": "healthy"
  }
}
```

## WebSocket

### Session Updates

```
WS /ws/session/{session_id}
```

Events:
```json
{"type": "agent_started", "agent_id": "developer", "timestamp": "..."}
{"type": "tool_call", "tool": "coding:write_file", "timestamp": "..."}
{"type": "approval_required", "approval_id": "uuid", "tool": "docker:build"}
{"type": "question_asked", "question_id": "uuid", "question": "..."}
{"type": "agent_completed", "agent_id": "developer", "timestamp": "..."}
{"type": "session_completed", "status": "completed"}
```

## Error Responses

All errors follow this format:

```json
{
  "code": "NOT_FOUND",
  "message": "Session not found",
  "details": {
    "resource": "session",
    "id": "uuid"
  },
  "timestamp": "2024-01-01T00:00:00Z",
  "request_id": "uuid"
}
```

Error codes:
- `AUTH_REQUIRED` (401)
- `FORBIDDEN` (403)
- `NOT_FOUND` (404)
- `VALIDATION_ERROR` (422)
- `CONFLICT` (409)
- `INTERNAL_ERROR` (500)
- `EXTERNAL_SERVICE_ERROR` (502)
