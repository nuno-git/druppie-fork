# Druppie Architecture

This document explains how all the parts of Druppie fit together.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DRUPPIE-FRONTEND (React)                             │
│                            localhost:5273                                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │  Chat   │  │Projects │  │Approvals│  │  Debug  │  │Settings │           │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘           │
└───────┼────────────┼────────────┼────────────┼────────────┼─────────────────┘
        │            │            │            │            │
        └────────────┴────────────┴────────────┴────────────┘
                                  │
                                  ▼ HTTP + WebSocket
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DRUPPIE-BACKEND (FastAPI)                            │
│                           localhost:8100                                     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         API LAYER                                     │  │
│  │  Routes: /sessions, /approvals, /projects, /chat, /questions         │  │
│  │  Thin handlers that receive HTTP requests and call services          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                       SERVICE LAYER (NEW)                             │  │
│  │  Business logic: permissions, validation, orchestration              │  │
│  │  SessionService, ApprovalService, ProjectService                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     REPOSITORY LAYER (NEW)                            │  │
│  │  Database access: clean queries, builds response objects             │  │
│  │  SessionRepository, ApprovalRepository, ProjectRepository            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         CORE LAYER                                    │  │
│  │  Agent execution engine - where AI agents run                        │  │
│  │                                                                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │  │
│  │  │  Main Loop  │  │ MCP Client  │  │   Agents    │                  │  │
│  │  │  (loop.py)  │  │  (HTTP)     │  │  (runtime)  │                  │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │  │
│  │         │                │                │                          │  │
│  │         └────────────────┴────────────────┘                          │  │
│  │                          │                                            │  │
│  │  Built-in Tools:                                                     │  │
│  │  • hitl_ask_question (pause for user input)                          │  │
│  │  • hitl_ask_multiple_choice_question (choices + other option)        │  │
│  │  • done (signal task completion)                                     │  │
│  │  • execute_agent (delegate to another agent)                         │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ HTTP calls to MCP servers
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
           ┌───────────────┐             ┌───────────────┐
           │  MCP CODING   │             │  MCP DOCKER   │
           │  Port 9001    │             │  Port 9002    │
           │               │             │               │
           │  - read_file  │             │  - build      │
           │  - write_file │             │  - run        │
           │  - run_command│             │  - stop       │
           │  - git ops    │             │  - logs       │
           │  - run_tests  │             │               │
           └───────┬───────┘             └───────┬───────┘
                   │                             │
                   ▼                             ▼
           ┌───────────────┐             ┌───────────────┐
           │  Workspace    │             │ Docker Daemon │
           │  (git repos)  │             │ (containers)  │
           └───────────────┘             └───────────────┘
```

## Two Types of Tools

### 1. Built-in Tools (Part of Agent Runtime)

These are handled directly by the agent runtime - no external HTTP call needed:

| Tool | What It Does |
|------|--------------|
| `hitl_ask_question` | Pauses execution, asks user a free-form question, resumes with answer |
| `hitl_ask_multiple_choice_question` | Pauses execution, shows choices (with optional "Other"), resumes with selection |
| `done` | Signals the agent is finished, returns summary |
| `execute_agent` | Calls another agent to perform a sub-task |

### 2. MCP Tools (External Microservices)

These require HTTP calls to separate MCP server containers:

| Server | Tool | What It Does |
|--------|------|--------------|
| coding | `read_file` | Read file content |
| coding | `write_file` | Write/create a file |
| coding | `run_command` | Execute shell command |
| coding | `commit_and_push` | Git commit and push |
| coding | `run_tests` | Auto-detect and run tests |
| docker | `build` | Build Docker image |
| docker | `run` | Run container |
| docker | `stop` | Stop container |
| docker | `logs` | Get container logs |

## Session Structure

A session contains EVERYTHING in one unified timeline:

```
Session
│
├── GENERAL INFO
│   ├── id, user_id, title, status
│   ├── token_usage: { prompt_tokens, completion_tokens, total_tokens }
│   ├── tokens_by_agent: { router: 1000, developer: 5000, ... }
│   ├── created_at, updated_at
│   │
│   └── project (full details if linked, null otherwise)
│       ├── id, name, description
│       ├── git_url (Gitea repo URL)
│       ├── status (active/archived)
│       └── deployment (if deployed)
│           ├── status (running/stopped)
│           ├── app_url (http://localhost:9100)
│           ├── container_name
│           └── started_at
│
└── CHAT (single chronological timeline - NO separate events/messages arrays)
    │
    ├── { type: "system_message", content: "Hello! I'm Druppie...", timestamp }
    │
    ├── { type: "user_message", content: "Build a todo app", timestamp }
    │
    ├── { type: "agent_run", agent_id: "router", status: "completed",
    │     token_usage: {...},
    │     steps: [
    │       { type: "llm_call", model: "glm-4", provider: "zai", ... },
    │       { type: "tool_execution", tool: "coding:write_file",
    │         arguments: {...}, status: "executed",
    │         approval: { status: "approved", resolved_by: "..." } }  ← EMBEDDED
    │       { type: "hitl_question", question: "...", answer: "..." } ← EMBEDDED
    │     ]
    │   }
    │
    ├── { type: "assistant_message", content: "I'll create...", agent_id: "router" }
    │
    ├── { type: "user_message", content: "Now add auth", timestamp }
    │
    └── ... continues in order
```

**Key design decisions:**

| Decision | Why |
|----------|-----|
| One `chat` array, no separate `events` | Events IS the chat - no duplication |
| Approvals embedded in tool_execution | No need to match approval to tool call |
| HITL questions embedded in agent_run | No need for separate lookup |
| Full project info included | Frontend doesn't need separate API call |
| Steps inside agent_run | Shows exactly what happened in order |

## How a Message Flows

### User sends "Build a todo app"

```
1. FRONTEND
   User types message, clicks send
   POST /api/chat { message: "Build a todo app" }

2. API ROUTE
   Receives request, validates, calls service

3. SERVICE
   Creates session, calls core loop

4. CORE LOOP (loop.py)

   ┌─────────────────────────────────────────────────┐
   │ Run Router Agent                                │
   │ • Sends prompt to LLM                           │
   │ • LLM returns: {action: "create_project", ...}  │
   │ • Logs: raw request, raw response               │
   └─────────────────────────────────────────────────┘
                         │
                         ▼
   ┌─────────────────────────────────────────────────┐
   │ Run Planner Agent                               │
   │ • Sends prompt to LLM                           │
   │ • LLM returns workflow: [architect, developer]  │
   │ • Logs: raw request, raw response               │
   └─────────────────────────────────────────────────┘
                         │
                         ▼
   ┌─────────────────────────────────────────────────┐
   │ Execute Workflow Step 1: Architect              │
   │ • LLM decides to call coding:write_file         │
   │ • MCP Client checks: needs approval? YES        │
   │ • Creates approval record, PAUSES               │
   │ • Logs: LLM call, tool call, approval created   │
   └─────────────────────────────────────────────────┘
                         │
                         ▼
                   [PAUSED - waiting for approval]
                         │
                         ▼
   ┌─────────────────────────────────────────────────┐
   │ User Approves                                   │
   │ POST /api/approvals/{id}/approve                │
   └─────────────────────────────────────────────────┘
                         │
                         ▼
   ┌─────────────────────────────────────────────────┐
   │ Resume from Approval                            │
   │ • Executes the tool                             │
   │ • Restores agent state                          │
   │ • Agent continues with tool result              │
   │ • Agent calls done() when finished              │
   └─────────────────────────────────────────────────┘
                         │
                         ▼
   ┌─────────────────────────────────────────────────┐
   │ Execute Workflow Step 2: Developer              │
   │ • Same pattern...                               │
   └─────────────────────────────────────────────────┘
```

## The New Layers (Refactoring)

We are adding Repository and Service layers to organize the code:

### Current (Problems)

```python
# routes/sessions.py - 776 lines!
# Does: HTTP handling + permissions + queries + formatting

@router.get("/{session_id}")
async def get_session(session_id, db):
    session = db.query(Session).filter_by(id=session_id).first()
    # Check permissions here
    # Query agent_runs here
    # Query approvals here
    # Build complex response here
    # ... 500 more lines
```

### New (Clean)

```python
# routes/sessions.py - ~30 lines
# Only does: HTTP handling
@router.get("/{session_id}")
async def get_session(session_id, service: SessionService):
    return service.get_detail(session_id)


# services/session_service.py - ~50 lines
# Only does: permissions + business rules
class SessionService:
    def get_detail(self, session_id, user_id):
        session = self.repo.get(session_id)
        if not self._can_access(session, user_id):
            raise AuthorizationError()
        return self.repo.get_with_chat(session_id)


# repositories/session_repository.py - ~150 lines
# Only does: database queries
class SessionRepository:
    def get_with_chat(self, session_id):
        # All query logic in ONE place
        ...
```

## API Bridge Architecture

The backend acts as a **bridge** between the frontend and MCP servers. This keeps MCP servers as the single source of truth for all operations.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                        │
│                                                                              │
│   User actions:                                                             │
│   • Browse files in a project                                               │
│   • Stop a running container                                                │
│   • View container logs                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ REST API
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                         │
│                                                                              │
│   API Bridge Routes:                                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │  /api/workspace/files    → calls coding MCP: list_dir              │  │
│   │  /api/workspace/file     → calls coding MCP: read_file             │  │
│   │  /api/deployments/stop   → calls docker MCP: stop                  │  │
│   │  /api/deployments/logs   → calls docker MCP: logs                  │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                         Uses: core/mcp_client.py                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTP (MCP protocol)
                    ┌───────────────┴───────────────┐
                    │                               │
           ┌────────▼────────┐             ┌────────▼────────┐
           │   CODING MCP    │             │   DOCKER MCP    │
           │   Port 9001     │             │   Port 9002     │
           │                 │             │                 │
           │ • list_dir      │             │ • stop          │
           │ • read_file     │             │ • logs          │
           │ • write_file    │             │ • build         │
           │ • run_command   │             │ • run           │
           └────────┬────────┘             └────────┬────────┘
                    │                               │
                    ▼                               ▼
           ┌─────────────────┐             ┌─────────────────┐
           │   Filesystem    │             │  Docker Daemon  │
           │   (workspace)   │             │  (containers)   │
           └─────────────────┘             └─────────────────┘
```

### Two Paths to MCP - Same Tools, Different Entry Points

| Who | Entry Point | Flow |
|-----|-------------|------|
| **Agents** | Core loop | Agent → MCP Client → MCP Server |
| **Users** | REST API | Frontend → Backend Bridge → MCP Client → MCP Server |

**Why this design?**

1. **Single source of truth** - MCP servers own all file and container operations
2. **Kubernetes friendly** - No shared volumes between containers needed
3. **Security** - Only MCP servers need dangerous permissions (docker.sock, filesystem)
4. **Consistency** - Same tools used by agents and users
5. **Reuses existing code** - Backend already has MCP client, just adds bridge routes

### Bridge Routes (to be implemented)

**Workspace Bridge** (files created by agents):
```
GET  /api/workspace/files?session_id=X&path=Y  → coding:list_dir
GET  /api/workspace/file?session_id=X&path=Y   → coding:read_file
```

**Deployment Bridge** (containers):
```
GET  /api/deployments                          → list from database + docker:list
POST /api/deployments/{id}/stop                → docker:stop
POST /api/deployments/{id}/restart             → docker:stop + docker:run
GET  /api/deployments/{id}/logs                → docker:logs
```

## Key Files

| File | What It Does |
|------|--------------|
| `core/loop.py` | Main execution loop - orchestrates agent runs, handles pausing/resuming |
| `core/mcp_client.py` | HTTP client for MCP servers, checks approval rules |
| `core/mcp_config.yaml` | Defines MCP tools and which need approval |
| `agents/runtime.py` | Runs individual agents (LLM loop, tool calling) |
| `agents/builtin_tools.py` | Built-in tools (hitl, done, execute_agent) |
| `agents/definitions/*.yaml` | Agent configurations (prompts, models, allowed tools) |
| `mcp-servers/coding/server.py` | Coding MCP implementation |
| `mcp-servers/docker/server.py` | Docker MCP implementation |
| `db/models.py` | SQLAlchemy database models |
| `db/schema.sql` | Database schema |
