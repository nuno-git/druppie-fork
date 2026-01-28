# Folder Structure

This document explains what each folder contains, what we do there, and how they relate.

## Overview

```
cleaner-druppie/
│
├── druppie-backend/         # Python/FastAPI backend (currently named "druppie/")
├── druppie-frontend/        # React/Vite frontend (currently named "frontend/")
├── docs/                    # Documentation (you are here)
├── scripts/                 # Setup and utility scripts
├── iac/                     # Infrastructure as Code (Keycloak, users)
├── setup.sh                 # Main setup script
└── CLAUDE.md                # AI assistant instructions
```

---

## druppie-backend/

The main backend application. This is where all the server-side logic lives.

```
druppie-backend/
│
├── api/                     # HTTP API layer
├── domain/                  # Data shapes (Pydantic schemas) ← NEW
├── repositories/            # Database access layer ← NEW
├── services/                # Business logic layer ← NEW
├── core/                    # Agent execution engine
├── agents/                  # Agent definitions and runtime
├── mcp-servers/             # MCP microservices
├── workflows/               # Workflow definitions
├── llm/                     # LLM providers
├── db/                      # Database layer
├── docker-compose.yml       # Full stack compose
├── Dockerfile               # Backend container
└── requirements.txt         # Python dependencies
```

### api/ - HTTP API Layer

**What it does:** Receives HTTP requests from the frontend, validates input, calls services, returns responses.

**What we do here:**
- Define route handlers (`@router.get`, `@router.post`)
- Validate request data
- Call service methods
- Return responses

**What we DON'T do here:**
- Database queries (that's repositories)
- Permission checks (that's services)
- Complex logic (that's services)

```
api/
├── routes/                  # Endpoint handlers
│   ├── sessions.py          # /api/sessions - List, get, delete sessions
│   ├── chat.py              # /api/chat - Send messages, start conversations
│   ├── approvals.py         # /api/approvals - List, approve, reject
│   ├── questions.py         # /api/questions - HITL question answers
│   ├── projects.py          # /api/projects - Project management
│   ├── workspace.py         # /api/workspace - BRIDGE to coding MCP
│   │                        #   Calls coding MCP tools (list_dir, read_file)
│   │                        #   Frontend uses this to browse files
│   ├── deployments.py       # /api/deployments - BRIDGE to docker MCP
│   │                        #   Calls docker MCP tools (stop, logs)
│   │                        #   Frontend uses this to manage containers
│   ├── agents.py            # /api/agents - List agent configurations
│   ├── mcps.py              # /api/mcps - List MCP servers and tools
│   └── health.py            # /api/health - Health checks
├── deps.py                  # Dependency injection (get_current_user, get_db, get_service)
├── errors.py                # Error handling and response formats
└── schemas.py               # Pydantic models (being moved to domain/)
```

### domain/ - Data Shapes (NEW)

**What it does:** Defines Pydantic models that describe the shape of data in API responses.

**What we do here:**
- Define what a Session looks like
- Define what a ChatItem looks like
- Define what an Approval looks like
- Pure data shapes - no logic

**Why separate from api/schemas.py:**
- One file per entity (easier to find)
- Can be imported by services and repositories
- No duplication

```
domain/
├── __init__.py
├── session.py               # SessionDetail, SessionSummary, ChatItem, AgentRun, etc.
├── project.py               # ProjectDetail, ProjectSummary, BuildInfo
├── deployment.py            # DeploymentInfo, ContainerStatus
├── approval.py              # ApprovalInfo, PendingApproval
├── question.py              # HITLQuestion, QuestionChoice
├── user.py                  # UserInfo, UserRoles
└── common.py                # TokenUsage, FileInfo (shared across entities)
```

### repositories/ - Database Access (NEW)

**What it does:** All database queries. Gets data from database, builds clean response objects.

**What we do here:**
- Write SQLAlchemy queries
- Build response objects from query results
- Handle joins and complex data assembly

**What we DON'T do here:**
- Permission checks (that's services)
- Business logic (that's services)
- HTTP handling (that's routes)

```
repositories/
├── __init__.py
├── base.py                  # BaseRepository with common patterns
├── session_repository.py    # SessionRepository class
│                            #   - get_by_id(session_id)
│                            #   - get_with_chat(session_id) → SessionDetail
│                            #   - list_for_user(user_id) → list[SessionSummary]
│                            #   - create(user_id, title)
│                            #   - update_status(session_id, status)
│
├── project_repository.py    # ProjectRepository class
├── approval_repository.py   # ApprovalRepository class
├── question_repository.py   # QuestionRepository class (HITL)
├── deployment_repository.py # DeploymentRepository class
└── user_repository.py       # UserRepository class
```

### services/ - Business Logic (NEW)

**What it does:** Contains all business rules. Decides what users can do, validates operations.

**What we do here:**
- Check permissions (can user X see session Y?)
- Validate operations (is this action allowed?)
- Orchestrate multiple repository calls
- Apply business rules

**What we DON'T do here:**
- Database queries (that's repositories)
- HTTP handling (that's routes)

```
services/
├── __init__.py
├── session_service.py       # SessionService class
│                            #   - get_detail(session_id, user_id) - checks access
│                            #   - list_for_user(user_id)
│                            #   - delete(session_id, user_id) - checks ownership
│
├── approval_service.py      # ApprovalService class
│                            #   - get_pending_for_user(user_id, roles)
│                            #   - approve(approval_id, user_id) - checks role
│                            #   - reject(approval_id, user_id, reason)
│
├── project_service.py       # ProjectService class
├── question_service.py      # QuestionService class
└── deployment_service.py    # DeploymentService class
```

### core/ - Agent Execution Engine

**What it does:** The heart of Druppie. This is where AI agents run, call tools, and execute workflows.

**What we do here:**
- Orchestrate agent execution
- Manage pausing/resuming workflows
- Call MCP servers
- Handle approvals and HITL questions
- Track execution state

```
core/
├── loop.py                  # Main execution loop
│                            #   - process_message() - starts agent execution
│                            #   - resume_from_approval() - continues after approval
│                            #   - resume_from_question() - continues after HITL answer
│                            #   - Orchestrates: router → planner → workflow steps
│
├── mcp_client.py            # HTTP client for MCP servers
│                            #   - call_tool(server, tool, args) - makes HTTP call
│                            #   - Checks approval rules before executing
│                            #   - Creates approval records when needed
│
├── mcp_config.yaml          # MCP tool definitions
│                            #   - Which tools exist on which server
│                            #   - Which tools need approval
│                            #   - Which role can approve each tool
│
├── execution_context.py     # Runtime state container
│                            #   - session_id, user_id, workspace_id
│                            #   - Tracks LLM calls, tokens, events
│                            #   - Passed to agents and tools
│
├── state.py                 # LangGraph state definitions
├── workspace.py             # Workspace (git) management
│                            #   - Clone repos, create branches
│                            #   - Manage local git sandboxes
│
├── builder.py               # Docker build management
├── gitea.py                 # Gitea API client
├── auth.py                  # Authentication utilities
└── config.py                # Configuration (Settings class)
```

### agents/ - Agent System

**What it does:** Defines agents and how they execute. Agents are the AI "workers" that do tasks.

**What we do here:**
- Define agent configurations (YAML)
- Run agents (LLM calls, tool handling)
- Built-in tools that don't need external servers

```
agents/
├── definitions/             # YAML agent configs
│   ├── router.yaml          # Classifies user intent
│   │                        #   - System prompt, model, temperature
│   │                        #   - No MCP tools (just thinks)
│   │
│   ├── planner.yaml         # Creates execution plans
│   │                        #   - Decides which agents to run
│   │                        #   - Creates workflow steps
│   │
│   ├── architect.yaml       # Designs system structure
│   │                        #   - MCP tools: coding
│   │                        #   - Writes architecture docs
│   │
│   ├── developer.yaml       # Writes code
│   │                        #   - MCP tools: coding
│   │                        #   - Writes actual code files
│   │
│   ├── deployer.yaml        # Deploys apps
│   │                        #   - MCP tools: docker
│   │                        #   - Builds and runs containers
│   │
│   ├── tester.yaml          # Runs tests
│   │                        #   - MCP tools: coding (run_tests)
│   │
│   └── reviewer.yaml        # Reviews code
│                            #   - MCP tools: coding (read_file)
│
├── runtime.py               # Agent execution logic
│                            #   - run() - main agent loop
│                            #   - Sends prompts to LLM
│                            #   - Handles tool calls
│                            #   - Returns when done or paused
│
├── builtin_tools.py         # Built-in tools (no MCP server needed)
│                            #   - hitl_ask_question
│                            #   - hitl_ask_multiple_choice_question
│                            #   - done
│                            #   - execute_agent
│
├── loader.py                # Loads agent definitions from YAML
└── hitl.py                  # Backwards compatibility (imports from builtin_tools)
```

### mcp-servers/ - MCP Microservices

**What it does:** Separate Docker containers that provide tools. Each is a standalone FastMCP server.

**Why separate containers:**
- Isolation (coding server can't affect docker server)
- Different permissions (docker server needs docker socket)
- Can scale independently

```
mcp-servers/
├── coding/                  # File + Git operations (Port 9001)
│   ├── server.py            # FastMCP server implementation
│   │                        #   Tools:
│   │                        #   - read_file(path)
│   │                        #   - write_file(path, content)
│   │                        #   - list_dir(path)
│   │                        #   - run_command(command)
│   │                        #   - commit_and_push(message)
│   │                        #   - run_tests()
│   │
│   ├── Dockerfile
│   └── requirements.txt
│
└── docker/                  # Container operations (Port 9002)
    ├── server.py            # FastMCP server implementation
    │                        #   Tools:
    │                        #   - build(dockerfile_path, image_name)
    │                        #   - run(image_name, port)
    │                        #   - stop(container_name)
    │                        #   - logs(container_name)
    │
    ├── Dockerfile
    └── requirements.txt
```

### workflows/ - Workflow Definitions

**What it does:** Defines multi-step execution plans that can be reused.

```
workflows/
├── definitions/             # YAML workflow configs
│   ├── feature_dev.yaml     # Feature development workflow
│   │                        #   Steps: create_branch → implement → review → commit
│   │
│   ├── deploy.yaml          # Deployment workflow
│   │                        #   Steps: build → run → verify
│   │
│   └── project_setup.yaml   # Project setup workflow
│
└── executor.py              # Workflow execution logic
```

### llm/ - LLM Providers

**What it does:** Abstractions for different LLM providers (Z.AI, DeepInfra, etc.)

```
llm/
├── base.py                  # Abstract interface
│                            #   - chat(messages, tools) → response
│
├── zai.py                   # Z.AI provider (GLM-4)
├── deepinfra.py             # DeepInfra provider
└── mock.py                  # Mock provider (for testing)
```

### db/ - Database Layer

**What it does:** SQLAlchemy models, schema, and CRUD operations.

```
db/
├── models.py                # SQLAlchemy models
│                            #   - Session, AgentRun, Message
│                            #   - Approval, HitlQuestion
│                            #   - Project, Build, Deployment
│                            #   - etc.
│
├── schema.sql               # SQL schema definition
│                            #   - CREATE TABLE statements
│                            #   - Indices, foreign keys
│
├── crud.py                  # CRUD operations (being replaced by repositories)
├── session.py               # DB session management
└── migrations.py            # Database migrations
```

---

## druppie-frontend/

The React frontend application.

```
druppie-frontend/
├── src/
│   ├── pages/               # Page components
│   │   ├── Chat.jsx         # Main chat interface
│   │   ├── Dashboard.jsx    # Overview with stats
│   │   ├── Projects.jsx     # Project list
│   │   ├── ProjectDetail.jsx# Single project view
│   │   ├── Tasks.jsx        # Approval list
│   │   ├── Debug.jsx        # Execution trace viewer
│   │   └── Settings.jsx     # System configuration
│   │
│   ├── components/          # Reusable components
│   │   ├── chat/            # Chat-specific (messages, input)
│   │   └── common/          # Shared (buttons, modals)
│   │
│   ├── services/            # API clients
│   │   ├── api.js           # HTTP client for backend
│   │   ├── websocket.js     # WebSocket for real-time updates
│   │   └── keycloak.js      # Authentication
│   │
│   └── App.jsx              # Main app component
│
├── tests/e2e/               # Playwright end-to-end tests
├── Dockerfile
└── package.json
```

---

## Other Folders

### scripts/

Setup and utility scripts.

```
scripts/
├── setup_keycloak.py        # Configure Keycloak realm and users
├── setup_gitea.py           # Configure Gitea organization
└── run_tests.sh             # Run test suite
```

### iac/

Infrastructure as Code - configuration for external services.

```
iac/
├── realm.yaml               # Keycloak realm config
└── users.yaml               # Test user definitions
```

---

## How Folders Relate

```
User Request (Frontend)
         │
         ▼
┌─────────────────┐
│  api/routes/    │  ← Receives HTTP, calls service
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   services/     │  ← Checks permissions, applies rules
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  repositories/  │  ← Queries database, builds responses
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     db/         │  ← SQLAlchemy models
└─────────────────┘


For agent execution (POST /chat):

┌─────────────────┐
│   api/chat.py   │  ← Receives message
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   core/loop.py  │  ← Main execution loop
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ agents/runtime  │  ← Runs agent (LLM calls)
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Built-in    MCP
Tools       Client
    │         │
    │         ▼
    │    ┌─────────────┐
    │    │ mcp-servers │  ← External tool servers
    │    └─────────────┘
    │
    ▼
Pause for user input (HITL)
or signal done
```

---

## Migration Path

We are migrating from the old flat structure to the new layered structure:

| Old Location | New Location |
|--------------|--------------|
| `api/schemas.py` | `domain/*.py` (split by entity) |
| `db/crud.py` | `repositories/*.py` (one per entity) |
| Business logic in routes | `services/*.py` |
| 776-line route functions | 30-line route + 50-line service + 150-line repository |
| Folder `druppie/` | `druppie-backend/` |
| Folder `frontend/` | `druppie-frontend/` |
