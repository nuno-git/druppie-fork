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

## What Gets Logged in a Session

A session contains EVERYTHING that happened:

```
Session
├── Messages (user input, assistant responses)
├── Agent Runs (each agent that executed)
│   ├── Raw LLM Requests (full prompt sent to LLM)
│   ├── Raw LLM Responses (exactly what LLM returned)
│   ├── Tool Calls (what tools were invoked)
│   │   ├── Arguments (what was passed)
│   │   ├── Results (what was returned)
│   │   └── Errors (if failed)
│   ├── Approvals (if tool needed approval)
│   └── HITL Questions (if agent asked user something)
├── Workflow (if multi-step plan)
│   └── Steps (each step and its status)
└── Events (timeline of everything)
```

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
