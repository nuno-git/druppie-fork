# Druppie -- Master Overview

Everything you need to understand the entire system in one document.

---

## Table of Contents

1. [What is Druppie](#1-what-is-druppie)
2. [Architecture at a Glance](#2-architecture-at-a-glance)
3. [How a User Request Flows](#3-how-a-user-request-flows)
4. [The Agent System](#4-the-agent-system)
5. [Builtin Tools](#5-builtin-tools)
6. [MCP Servers](#6-mcp-servers)
7. [The Approval System](#7-the-approval-system)
8. [HITL (Human-in-the-Loop)](#8-hitl-human-in-the-loop)
9. [Infrastructure](#9-infrastructure)
10. [Database Schema](#10-database-schema)
11. [Frontend](#11-frontend)
12. [Development Setup](#12-development-setup)
13. [Key Design Decisions](#13-key-design-decisions)

---

## 1. What is Druppie

Druppie is a **governance platform for AI agents**. It lets users describe what
they want built ("Build me a todo app"), then orchestrates a pipeline of
specialized AI agents that design, implement, deploy, and summarize the result --
all within a governed environment where every consequential action (writing files,
building Docker images, deploying containers) flows through MCP (Model Context
Protocol) tool servers with configurable approval gates.

Key properties:

- **Agents can only act through MCP tools.** They never produce raw file output.
  Every file write, git push, and Docker build goes through a tracked tool call.
- **Approval workflows.** Dangerous operations (Docker build/run, merging PRs)
  require human approval from a user with the right role before execution proceeds.
- **Human-in-the-loop (HITL).** Agents can pause and ask users questions (free-form
  or multiple-choice) then resume when the answer arrives.
- **Full audit trail.** Every LLM call, every tool invocation, every approval
  decision is stored in the database with foreign-key linkage.

---

## 2. Architecture at a Glance

```
                           +-------------------+
                           |    Frontend        |
                           |  React / Vite      |
                           |  port 5273         |
                           +--------+----------+
                                    |
                              HTTP
                                    |
                           +--------v----------+
                           |    Backend API     |
                           |  FastAPI           |
                           |  port 8100         |
                           +--------+----------+
                                    |
                 +------------------+------------------+
                 |                  |                   |
        +--------v------+  +-------v-------+  +-------v--------+
        |   Services    |  | Orchestrator  |  |  Agent Runtime |
        | (business     |  | (coordinates  |  |  (LLM loop,    |
        |  logic)       |  |  agent runs)  |  |   tool calls)  |
        +--------+------+  +-------+-------+  +-------+--------+
                 |                  |                   |
        +--------v------+          |           +-------v--------+
        | Repositories  |          |           | Tool Executor  |
        | (data access) |          |           | (builtin +     |
        +--------+------+          |           |  MCP dispatch) |
                 |                  |           +---+--------+---+
        +--------v------+          |               |        |
        |  PostgreSQL   |          |          +----v---+ +--v-------+
        |  port 5533    |          |          | MCP    | | MCP      |
        +---------------+          |          | Coding | | Docker   |
                                   |          | :9001  | | :9002    |
                           +-------v-------+  +--------+ +----------+
                           |   Keycloak    |
                           |   (auth)      |       +----------+
                           |   port 8180   |       |  Gitea   |
                           +---------------+       |  (git)   |
                                                   | port 3100|
                                                   +----------+
```

### Layer Responsibilities

| Layer           | Location                  | Responsibility                                     |
|-----------------|---------------------------|-----------------------------------------------------|
| API Routes      | `druppie/api/routes/`     | Thin HTTP layer, delegates to services              |
| Services        | `druppie/services/`       | Business logic, coordinates repositories            |
| Repositories    | `druppie/repositories/`   | Data access, returns domain models                  |
| Domain Models   | `druppie/domain/`         | Pydantic models (Summary/Detail pattern)            |
| DB Models       | `druppie/db/models/`      | SQLAlchemy ORM models                               |
| Orchestrator    | `druppie/execution/`      | Coordinates agent runs in sequence                  |
| Agent Runtime   | `druppie/agents/`         | YAML-driven LLM tool-calling loop                   |
| Tool Executor   | `druppie/execution/`      | Routes tool calls to builtin handlers or MCP servers|
| MCP Servers     | `druppie/mcp-servers/`    | Coding (port 9001) and Docker (port 9002)           |

Data flow for reads:

```
Repository --> Domain Model --> Service --> API Route --> JSON Response
```

---

## 3. How a User Request Flows

Concrete example: a user types **"Build me a todo app"** in the chat.

```
User: "Build me a todo app"
  |
  v
[1] POST /api/chat  -->  Orchestrator.process_message()
  |
  |-- Creates Session
  |-- Saves user message to timeline
  |-- Creates two PENDING agent runs: router (seq 0), planner (seq 1)
  |-- Calls execute_pending_runs()
  |
  v
[2] ROUTER (seq 0)
  |  LLM analyzes the message
  |  Calls set_intent(intent="create_project", project_name="todo-app")
  |    --> Creates Project record + Gitea repository
  |    --> Updates planner's prompt with intent + project context
  |  Calls done(summary="Creating new project: todo-app")
  |
  v
[3] PLANNER (seq 1)
  |  Reads the intent from its prompt: "create_project"
  |  Calls make_plan(steps=[
  |    {agent: "business_analyst", prompt: "Gather requirements for todo app..."},
  |    {agent: "architect",        prompt: "Design architecture for todo app..."},
  |    {agent: "developer",        prompt: "Implement todo app..."},
  |    {agent: "deployer",         prompt: "Build and deploy todo app..."},
  |    {agent: "summarizer",       prompt: "Summarize what was accomplished..."},
  |  ])
  |    --> Creates 5 new PENDING agent runs (seq 2-6)
  |  Calls done(summary="Plan created with 5 steps")
  |
  v
[4] BUSINESS_ANALYST (seq 2)
  |  Asks user 2-3 clarifying questions via hitl_ask_question
  |    --> Execution PAUSES, status = PAUSED_HITL
  |    --> User answers in the UI
  |    --> Orchestrator.resume_after_answer() resumes the agent
  |  Writes functional_design.md via coding:write_file
  |    --> Requires approval (business_analyst role) --> PAUSES
  |    --> Approved by user --> Orchestrator.resume_after_approval()
  |  Calls done(summary="Agent business_analyst: Gathered requirements...")
  |
  v
[5] ARCHITECT (seq 3)
  |  Reads functional_design.md
  |  Writes architecture.md via coding:write_file
  |    --> Requires approval (architect role) --> PAUSES, then approved
  |  Calls done(summary="Agent architect: Designed todo app architecture...")
  |
  v
[6] DEVELOPER (seq 4)
  |  Reads architecture.md
  |  Creates files: index.html, styles.css, app.js, Dockerfile
  |    via coding:batch_write_files (no approval needed for developer)
  |  Calls coding:commit_and_push
  |  Calls done(summary="Agent developer: Implemented on main, pushed 4 files")
  |
  v
[7] DEPLOYER (seq 5)
  |  Calls docker:build  --> Requires developer approval --> PAUSES, approved
  |  Calls docker:run    --> Requires developer approval --> PAUSES, approved
  |  Checks docker:logs to verify
  |  Calls done(summary="Agent deployer: Deployed at http://localhost:9101...")
  |
  v
[8] SUMMARIZER (seq 6)
  |  Reads all previous agent summaries
  |  Calls create_message with a friendly summary for the user
  |  Calls done(summary="Agent summarizer: Posted completion summary.")
  |
  v
Session status = COMPLETED
User sees: "Your todo app is running at http://localhost:9101"
```

### Two Kinds of Pause

| Pause Type       | Trigger                          | Resume Method                    | Agent Run Status |
|------------------|----------------------------------|----------------------------------|------------------|
| **HITL**         | Agent calls `hitl_ask_question`  | User answers in UI               | `PAUSED_HITL`    |
| **Approval**     | MCP tool needs approval          | User with correct role approves  | `PAUSED_TOOL`    |

When either pause resolves, the orchestrator calls `resume_after_answer()` or
`resume_after_approval()`, which re-enters the agent's LLM loop from where it
left off.

---

## 4. The Agent System

### How Agents Are Defined

Each agent is a **YAML file** in `druppie/agents/definitions/`. The YAML
specifies the agent's system prompt, which MCP tools it can access, its LLM
settings, and any approval overrides.

Example structure of an agent YAML:

```yaml
id: developer
name: Developer Agent
description: Writes and modifies code in git-managed workspaces

system_prompt: |
  You are a Senior Developer Agent...
  [COMMON_INSTRUCTIONS]      # Replaced with _common.md contents
  [TOOL_DESCRIPTIONS_PLACEHOLDER]  # Replaced with MCP tool docs

mcps:                         # Which MCP tools this agent can use
  coding:
    - read_file
    - write_file
    - batch_write_files
    - commit_and_push
    - create_branch
    - create_pull_request
    - merge_pull_request

extra_builtin_tools: []       # Additional builtins beyond the defaults

approval_overrides:           # Override global approval rules for this agent
  "coding:write_file":
    requires_approval: true
    required_role: architect

model: glm-4
temperature: 0.1
max_tokens: 163840
max_iterations: 100
```

### How Agents Are Loaded and Run

1. `Agent.__init__("developer", db=session)` loads and caches the YAML as an
   `AgentDefinition` Pydantic model.
2. `agent.run(prompt, session_id, agent_run_id)` enters the **tool-calling
   loop**:
   - Builds system prompt (injects `_common.md`, tool descriptions)
   - Calls the LLM with messages + available tools
   - For each tool call in the LLM response:
     - Creates a `ToolCall` DB record
     - Routes to `ToolExecutor.execute(tool_call_id)`
     - Handles result status: completed, waiting_approval, waiting_answer
   - Loop continues until the agent calls `done` or hits `max_iterations`
3. `agent.continue_run(session_id, agent_run_id)` reconstructs state from DB
   and re-enters the loop (used after pause/resume).

### All 9 Agents

| Agent              | Role                     | MCP Access         | Special Builtin Tools | Approval Overrides |
|--------------------|--------------------------|--------------------|-----------------------|--------------------|
| **router**         | Classifies user intent   | None               | `set_intent`          | None               |
| **planner**        | Creates execution plan   | None               | `make_plan`           | None               |
| **business_analyst**| Gathers requirements    | coding (r/w/list)  | --                    | write_file needs BA role |
| **architect**      | Designs architecture     | coding (r/w/list)  | --                    | write_file needs architect role |
| **developer**      | Writes code              | coding (full)      | --                    | None (uses global defaults) |
| **deployer**       | Docker build + deploy    | docker + coding (r)| --                    | None (uses global defaults) |
| **reviewer**       | Reviews code quality     | coding (r/w/list)  | --                    | None               |
| **tester**         | Runs tests               | coding (r/list)    | --                    | None               |
| **summarizer**     | Creates user summary     | None               | `create_message`      | None               |

### Agent Communication via Summary Relay

Agents do not talk to each other directly. Instead, each agent's `done(summary)`
output is accumulated and injected into the next agent's prompt as
`PREVIOUS AGENT SUMMARY:`. This is how the deployer learns the branch name
from the developer, and how the summarizer knows what happened across the
entire pipeline.

The shared instructions in `_common.md` enforce the format:

```
Agent architect: Designed counter app, wrote architecture.md.
Agent developer: Implemented on branch feature/add-counter, pushed 3 files.
Agent deployer: Built and deployed at http://localhost:9101 (container: counter-preview).
```

---

## 5. Builtin Tools

Builtin tools are handled directly by the backend (no MCP server needed).
Every agent gets the **default three**; some agents get additional ones.

### Default Tools (all agents)

| Tool                              | Purpose                                          |
|-----------------------------------|--------------------------------------------------|
| `done`                            | Signal task completion. The `summary` argument is the ONLY way to pass info to the next agent. Must be specific (URLs, branch names, file paths). |
| `hitl_ask_question`               | Ask the user a free-form text question. Pauses execution until answered. |
| `hitl_ask_multiple_choice_question`| Ask the user to pick from predefined options. Supports an optional "Other" free-text option. |

### Agent-Specific Builtins

| Tool              | Used By   | Purpose                                          |
|-------------------|-----------|--------------------------------------------------|
| `set_intent`      | router    | Declares session intent (`create_project`, `update_project`, `general_chat`). Creates Project + Gitea repo for new projects. Updates planner's prompt with context. |
| `make_plan`       | planner   | Creates an execution plan as an ordered list of `{agent_id, prompt}` steps. Each step becomes a PENDING agent run in the database. |
| `create_message`  | summarizer| Posts a visible message in the chat timeline for the user. |

---

## 6. MCP Servers

MCP (Model Context Protocol) servers are HTTP microservices that expose tools
agents can call. Druppie has two:

### Coding MCP -- port 9001

Manages file operations within git-managed workspaces. Each session gets an
isolated workspace directory with the project's Gitea repository cloned.

| Tool                  | Description                                      | Approval |
|-----------------------|--------------------------------------------------|----------|
| `read_file`           | Read a file from the workspace                   | No       |
| `write_file`          | Write a file to the workspace                    | No*      |
| `batch_write_files`   | Write multiple files at once                     | No*      |
| `list_dir`            | List directory contents                          | No       |
| `delete_file`         | Delete a file                                    | No       |
| `create_branch`       | Create and switch to a git branch                | No       |
| `commit_and_push`     | Stage, commit, and push all changes to Gitea     | No       |
| `get_git_status`      | Current branch, changed files, unpushed commits  | No       |
| `create_pull_request` | Create a PR from current branch to main          | No       |
| `merge_pull_request`  | Merge a PR and delete source branch              | Yes (developer) |
| `merge_to_main`       | Direct merge to main (no PR)                     | Yes (architect) |

*\*write_file and batch_write_files have no approval by default, but specific
agents override this (architect requires architect role, business_analyst
requires BA role).*

### Docker MCP -- port 9002

Manages Docker container lifecycle. Connects to the host Docker daemon via
the Docker socket.

| Tool              | Description                                      | Approval |
|-------------------|--------------------------------------------------|----------|
| `build`           | Build image by cloning from Gitea                | Yes (developer) |
| `run`             | Run container (host port auto-assigned 9100-9199)| Yes (developer) |
| `stop`            | Stop a running container                         | No       |
| `logs`            | Get container logs                               | No       |
| `remove`          | Remove a container                               | Yes (developer) |
| `list_containers` | List containers with label filtering             | No       |
| `inspect`         | Inspect container details                        | No       |
| `exec_command`    | Execute command inside a running container        | Yes (developer) |

### Declarative Argument Injection

The MCP config (`druppie/core/mcp_config.yaml`) defines **injection rules**
that automatically inject context values into tool arguments at execution time.
Parameters marked `hidden: true` are removed from the LLM-visible tool schema
so the LLM never sees or fills them.

```yaml
inject:
  session_id:
    from: session.id
    hidden: true         # LLM never sees this parameter
  repo_name:
    from: project.repo_name
    hidden: true
    tools: [read_file, write_file, ...]  # Only inject into these tools
```

This means agents never have to worry about passing `session_id`, `repo_name`,
or `repo_owner` -- the system injects them automatically.

---

## 7. The Approval System

### How It Works

1. Agent calls an MCP tool (e.g., `docker:build`)
2. `ToolExecutor.execute()` checks `MCPConfig` for approval requirements
3. If approval is required:
   - Creates an `Approval` record (status: `pending`, required_role: `developer`)
   - Sets `ToolCall` status to `waiting_approval`
   - Agent run pauses (`PAUSED_TOOL`)
4. User with the required role sees the pending approval in the UI
5. User approves (or rejects)
6. `Orchestrator.resume_after_approval()`:
   - Executes the tool via MCP
   - Reconstructs agent state from DB
   - Continues the agent's LLM loop

### Layered Approval Rules

Approval requirements are configured in two layers:

**Layer 1: Global defaults** in `mcp_config.yaml`

```yaml
tools:
  - name: write_file
    requires_approval: false    # Global default: no approval
  - name: build
    requires_approval: true     # Global default: always needs approval
    required_role: developer
```

**Layer 2: Per-agent overrides** in agent YAML files

```yaml
# architect.yaml
approval_overrides:
  "coding:write_file":
    requires_approval: true     # Override: architect must approve
    required_role: architect
```

The agent-level override wins. This means `write_file` needs no approval when
the developer calls it, but needs architect approval when the architect agent
calls it.

### Roles

| Role        | Can Approve                                        |
|-------------|----------------------------------------------------|
| `admin`     | Everything                                         |
| `architect` | Architecture documents (write_file for architect)  |
| `developer` | Docker build, Docker run, merge PRs                |

---

## 8. HITL (Human-in-the-Loop)

### How It Works

1. Agent calls `hitl_ask_question` or `hitl_ask_multiple_choice_question`
2. `ToolExecutor` creates a `Question` record in the database
   - Links to session, agent_run, and tool_call
   - Status: `pending`
3. Agent run pauses (`PAUSED_HITL`)
4. Frontend polls for pending questions and displays them in the chat
5. User types an answer
6. `POST /api/questions/{id}/answer` saves the answer
7. `Orchestrator.resume_after_answer()`:
   - Saves answer as the tool call result in DB
   - Reconstructs agent messages from DB (answer automatically included)
   - Continues the LLM loop

### Question Types

| Type               | Agent Calls                              | User Experience               |
|--------------------|------------------------------------------|-------------------------------|
| Free-form text     | `hitl_ask_question(question="...")`      | Text input field              |
| Multiple choice    | `hitl_ask_multiple_choice_question(question="...", choices=["A","B","C"])` | Radio buttons + optional "Other" |

### When Agents Ask Questions

- **business_analyst**: Asks 2-3 clarifying questions about features, users, preferences
- **router**: May ask for clarification on ambiguous requests (rare)
- **developer** (review task): Shows preview URL and asks if changes look good

---

## 9. Infrastructure

All infrastructure runs in Docker via `docker-compose.yml`.

```
+-------------------+     +-------------------+     +-------------------+
|   Keycloak        |     |   Gitea           |     |   PostgreSQL      |
|   (Auth / SSO)    |     |   (Git hosting)   |     |   (Main DB)       |
|   port 8180       |     |   port 3100       |     |   port 5533       |
+-------------------+     +-------------------+     +-------------------+

+-------------------+     +-------------------+     +-------------------+
|   Keycloak DB     |     |   Gitea DB        |     |   Adminer         |
|   (PostgreSQL)    |     |   (PostgreSQL)    |     |   (DB admin UI)   |
|   internal only   |     |   internal only   |     |   port 8081       |
+-------------------+     +-------------------+     +-------------------+

+-------------------+     +-------------------+
|   MCP Coding      |     |   MCP Docker      |
|   port 9001       |     |   port 9002       |
+-------------------+     +-------------------+
```

### Component Details

| Component      | Image / Tech            | Port  | Purpose                                    |
|----------------|-------------------------|-------|--------------------------------------------|
| **Keycloak**   | keycloak:24.0           | 8180  | Authentication, SSO, role management. Realm: `druppie` |
| **Gitea**      | gitea:1.21              | 3100  | Git repository hosting. Each project gets a repo. |
| **PostgreSQL** | postgres:15-alpine      | 5533  | Main application database (sessions, runs, approvals, etc.) |
| **Adminer**    | adminer:latest          | 8081  | Database admin web UI                      |
| **MCP Coding** | Custom Python/FastAPI   | 9001  | File operations + git in sandboxed workspaces |
| **MCP Docker** | Custom Python/FastAPI   | 9002  | Docker build/run/stop/logs via Docker socket |
| **Backend**    | Custom Python/FastAPI   | 8100  | Main API (runs locally in dev mode)        |
| **Frontend**   | Custom React/Vite       | 5273  | Web UI (runs locally in dev mode)          |

### Test Users (pre-configured in Keycloak)

| User        | Password        | Roles                    |
|-------------|-----------------|--------------------------|
| `admin`     | `Admin123!`     | admin                    |
| `architect` | `Architect123!` | architect, developer     |
| `seniordev` | `Developer123!` | developer                |

---

## 10. Database Schema

PostgreSQL with 11 tables. All models in `druppie/db/models/`.

```
+------------------+       +------------------+       +------------------+
|     users        |       |   user_roles     |       |  user_tokens     |
|------------------|       |------------------|       |------------------|
| id (PK, UUID)    |<------| user_id (FK)     |       | id (PK, UUID)    |
| username         |       | role (PK)        |       | user_id (FK)     |
| email            |       +------------------+       | service          |
| display_name     |                                  | access_token     |
| created_at       |                                  | refresh_token    |
| updated_at       |                                  | expires_at       |
+------------------+                                  +------------------+
        |
        | owner_id
        v
+------------------+       +------------------+
|    projects      |       |    sessions      |
|------------------|       |------------------|
| id (PK, UUID)    |<------| project_id (FK)  |
| name             |       | id (PK, UUID)    |
| description      |       | user_id (FK)     |
| repo_name        |       | title            |
| repo_owner       |       | status           |
| repo_url         |       | intent           |
| clone_url        |       | branch_name      |
| owner_id (FK)    |       | prompt_tokens    |
| status           |       | completion_tokens|
| created_at       |       | total_tokens     |
| updated_at       |       | created_at       |
+------------------+       | updated_at       |
                           +------------------+
                                   |
              +--------------------+--------------------+
              |                    |                     |
              v                    v                     v
+------------------+  +------------------+  +------------------+
|    messages      |  |   agent_runs     |  |   approvals      |
|------------------|  |------------------|  |------------------|
| id (PK, UUID)    |  | id (PK, UUID)    |  | id (PK, UUID)    |
| session_id (FK)  |  | session_id (FK)  |  | session_id (FK)  |
| role             |  | agent_id         |  | agent_run_id (FK)|
| content          |  | status           |  | tool_call_id (FK)|
| sequence_number  |  | planned_prompt   |  | approval_type    |
| created_at       |  | sequence_number  |  | mcp_server       |
+------------------+  | created_at       |  | tool_name        |
                      | updated_at       |  | title            |
                      +------------------+  | description      |
                              |             | required_role    |
              +---------------+-------+     | status           |
              |                       |     | resolved_by (FK) |
              v                       v     | arguments (JSON) |
+------------------+  +------------------+  | agent_state(JSON)|
|   llm_calls      |  |   tool_calls     |  | created_at       |
|------------------|  |------------------|  +------------------+
| id (PK, UUID)    |  | id (PK, UUID)    |
| session_id (FK)  |  | session_id (FK)  |  +------------------+
| agent_run_id(FK) |  | agent_run_id(FK) |  |   questions      |
| provider         |  | llm_call_id (FK) |  |------------------|
| model            |  | mcp_server       |  | id (PK, UUID)    |
| request_messages |  | tool_name        |  | session_id (FK)  |
| response_content |  | arguments (JSON) |  | agent_run_id(FK) |
| response_tool_   |  | result           |  | tool_call_id(FK) |
|   calls          |  | error_message    |  | agent_id         |
| prompt_tokens    |  | status           |  | question         |
| completion_tokens|  | tool_call_index  |  | question_type    |
| duration_ms      |  | created_at       |  | choices (JSON)   |
| created_at       |  +------------------+  | selected_indices |
+------------------+                        | status           |
                                            | answer           |
                                            | agent_state(JSON)|
                                            | created_at       |
                                            +------------------+
```

### Table Purposes

| Table          | Records                                                    |
|----------------|------------------------------------------------------------|
| `users`        | Users synced from Keycloak                                 |
| `user_roles`   | Role assignments (admin, architect, developer)             |
| `user_tokens`  | OBO tokens for external services (Gitea)                   |
| `projects`     | Projects with Gitea repository links                       |
| `sessions`     | Conversation sessions, tracks intent and status            |
| `messages`     | User/system messages in the chat timeline                  |
| `agent_runs`   | Each agent execution (router, planner, developer, etc.)    |
| `llm_calls`    | Every LLM API call with request/response/token counts      |
| `tool_calls`   | Every tool invocation with arguments and results           |
| `approvals`    | Approval requests for tool calls that need human sign-off  |
| `questions`    | HITL questions from agents to users                        |

### Key Relationships

- A **session** belongs to a **user** and optionally a **project**
- An **agent_run** belongs to a **session**
- An **llm_call** belongs to an **agent_run**
- A **tool_call** belongs to an **agent_run** and an **llm_call**
- An **approval** links to a **tool_call** (and by extension to the agent_run and session)
- A **question** links to a **tool_call** (and by extension to the agent_run and session)

---

## 11. Frontend

React + Vite application with Keycloak SSO integration.

### Pages

| Page              | File                    | Purpose                                          |
|-------------------|-------------------------|--------------------------------------------------|
| Chat              | `Chat.jsx`              | Main interaction -- send messages, see agent progress, answer questions, approve tools |
| Sessions          | `Dashboard.jsx`         | List of past sessions with status and token usage |
| Approvals         | `Tasks.jsx`             | Pending approval requests with approve/reject    |
| Projects          | `Projects.jsx`          | Browse all projects, see repos and deployments   |
| Project Detail    | `ProjectDetail.jsx`     | Single project view with sessions and deployments|
| Settings          | `Settings.jsx`          | User settings                                    |
| Database Admin    | `AdminDatabase.jsx`     | Admin view of database tables                    |
| Debug Trace       | `Debug.jsx`             | Execution trace viewer for a session             |

**Debug pages** (accessible via Debug dropdown in nav, used for raw API testing):

| Page              | File                    | Purpose                                          |
|-------------------|-------------------------|--------------------------------------------------|
| Debug Chat        | `DebugChat.jsx`         | Raw API debug interface for chat endpoints       |
| Debug Approvals   | `DebugApprovals.jsx`    | Raw API debug interface for approvals            |
| Debug Projects    | `DebugProjects.jsx`     | Raw API debug interface for projects/deployments |
| Debug MCP         | `DebugMCP.jsx`          | Raw API debug interface for MCP servers/tools    |

### Services

| File              | Purpose                                                    |
|-------------------|------------------------------------------------------------|
| `api.js`          | HTTP client for all backend API calls                      |
| `keycloak.js`     | Keycloak initialization, token management, role checking   |

### Updates

The frontend uses polling (via TanStack React Query `refetchInterval`) to detect
state changes. Real-time WebSocket push is a future improvement (see ROADMAP.md C2).

---

## 12. Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Docker and Docker Compose

### Quick Start

```bash
# Start everything (infra in Docker, backend + frontend locally with hot reload)
./setup_dev.sh

# Or start components individually
./setup_dev.sh infra      # Start databases, Keycloak, Gitea, MCP servers
./setup_dev.sh backend    # Start backend on port 8100 (hot reload)
./setup_dev.sh frontend   # Start frontend on port 5273 (HMR)

# Management
./setup_dev.sh stop       # Stop everything
./setup_dev.sh status     # Check what is running
./setup_dev.sh logs       # Show infrastructure logs
```

### Environment Variables

Required in `.env`:

```bash
LLM_PROVIDER=zai          # or: deepinfra, mock, auto
ZAI_API_KEY=your_key       # Required if using zai provider
GITEA_TOKEN=your_token     # For Gitea API access
```

### Running Tests

```bash
# Backend
cd druppie && pytest
cd druppie && ruff check .    # Linting
cd druppie && black .         # Formatting

# Frontend
cd frontend && npm test
cd frontend && npm run lint
cd frontend && npm run test:e2e   # Playwright end-to-end tests
```

### Access Points

| Service       | URL                           |
|---------------|-------------------------------|
| Frontend      | http://localhost:5273          |
| Backend API   | http://localhost:8100          |
| API Docs      | http://localhost:8100/docs     |
| Keycloak      | http://localhost:8180          |
| Gitea         | http://localhost:3100          |
| Adminer       | http://localhost:8081          |
| MCP Coding    | http://localhost:9001          |
| MCP Docker    | http://localhost:9002          |

---

## 13. Key Design Decisions

### 1. No Database Migrations

SQLAlchemy models are the source of truth. When the schema changes, reset the
database:

```bash
./setup.sh clean && ./setup.sh all
```

This keeps development fast and eliminates migration conflicts. The trade-off
is acceptable because the platform is in active development and no production
data needs to be preserved yet.

### 2. No JSON/JSONB for Structured Data

All structured data is normalized into proper relational tables. For example,
agent run results are stored in `tool_calls` and `llm_calls` tables with
proper foreign keys -- not as JSON blobs on the `agent_runs` table. The only
uses of JSON columns are for genuinely dynamic data: tool `arguments`, LLM
`request_messages`, and `agent_state` for pause/resume serialization.

### 3. Agents Only Act Through MCP Tools

Agents never produce raw file output. Every file write goes through
`coding:write_file`, every Docker operation goes through `docker:build`/`run`.
This ensures:

- Full audit trail of every action
- Approval gates can be inserted at any point
- Tool arguments are stored in the database for debugging
- Operations are sandboxed within workspace directories

### 4. Clean Architecture Layers

Strict separation: Route -> Service -> Repository -> Database. No layer
skips another. Routes are thin (validate input, call service, return response).
Services contain business logic. Repositories handle SQL and return domain
models.

### 5. Summary/Detail Domain Model Pattern

Domain models come in pairs:
- `SessionSummary` -- lightweight, used in list endpoints
- `SessionDetail` -- full data, used in single-item endpoints

All domain models are Pydantic, exported through `druppie/domain/__init__.py`.

### 6. YAML-Driven Agent Definitions

Agent behavior is configured in YAML, not code. Adding a new agent means
creating a new YAML file. The system prompt, tool access, approval overrides,
and LLM settings are all declarative. Shared instructions go in `_common.md`
and are injected via the `[COMMON_INSTRUCTIONS]` placeholder.

### 7. Intentionally Dumb Orchestrator

The orchestrator (`execution/orchestrator.py`) is deliberately simple. It
creates agent runs and executes them in sequence. All intelligence lives in:
- **set_intent** (builtin tool): creates projects, Gitea repos, updates prompts
- **make_plan** (builtin tool): creates the execution plan
- **Agent LLM loop**: decides which tools to call and when

This keeps the orchestrator easy to understand and debug.

### 8. Layered Approval System

Global defaults in `mcp_config.yaml` + per-agent overrides in agent YAML.
This means `write_file` can be safe by default (no approval) but require
approval when called by the architect agent. The deployer does not need to
override anything because `docker:build` and `docker:run` already require
developer approval globally.

---

## File Reference

Key files to read when exploring the codebase:

| What                       | File                                          |
|----------------------------|-----------------------------------------------|
| API entry point            | `druppie/api/main.py`                         |
| Orchestrator               | `druppie/execution/orchestrator.py`           |
| Agent runtime (LLM loop)  | `druppie/agents/runtime.py`                   |
| Builtin tool definitions   | `druppie/agents/builtin_tools.py`             |
| Tool executor              | `druppie/execution/tool_executor.py`          |
| MCP configuration          | `druppie/core/mcp_config.yaml`                |
| Agent YAML definitions     | `druppie/agents/definitions/*.yaml`           |
| Common agent instructions  | `druppie/agents/definitions/_common.md`       |
| Domain models              | `druppie/domain/__init__.py`                  |
| Database models            | `druppie/db/models/__init__.py`               |
| Repositories               | `druppie/repositories/__init__.py`            |
| Services                   | `druppie/services/__init__.py`                |
| Docker Compose             | `druppie/docker-compose.yml`                  |
| Dev setup script           | `setup_dev.sh`                                |
