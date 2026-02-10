# Technical Architecture

This document describes how the Druppie platform is built: its components, data flow, runtime behavior, and infrastructure.

---

## 1. Architecture Overview

Druppie is a full-stack platform composed of the following services:

| Service | Technology | Port | Purpose |
|---------|-----------|------|---------|
| Backend | Python / FastAPI | 8100 | API server, orchestration, agent runtime |
| Frontend | React / Vite | 5273 | Web UI for chat, approvals, projects |
| Database | PostgreSQL 15 | 5533 | Primary data store |
| Auth | Keycloak 24.0 | 8180 | JWT authentication, role management |
| Git | Gitea 1.21 | 3100 | Repository hosting for agent-created code |
| MCP Coding | Python / FastMCP | 9001 | File operations, git operations |
| MCP Docker | Python / FastMCP | 9002 | Container build, run, manage |
| MCP File Search | Python / FastMCP | 9004 | Local file search within datasets |
| MCP Web | Python / FastMCP | 9005 | Web browsing, URL fetching, web search |
| Adminer | PHP | 8081 | Database admin UI |

All services run in Docker containers on a shared bridge network (`druppie-new-network`). The backend communicates with MCP servers over HTTP using internal container hostnames.

---

## 2. Backend (Python / FastAPI)

### 2.1 Layered Architecture

The backend follows a strict layered architecture with unidirectional data flow:

```
Repository  -->  Domain Model  -->  Service  -->  API Route
(DB access)      (Pydantic)        (logic)       (HTTP)
```

Each layer has a single responsibility:

- **API Routes** (`druppie/api/routes/`): Thin HTTP layer. Receives requests, delegates to services, returns domain models. Route modules: `chat`, `sessions`, `approvals`, `questions`, `projects`, `deployments`, `workspace`, `agents`, `mcps`, `mcp_bridge`.
- **Services** (`druppie/services/`): Business logic. Orchestrates repository calls, enforces rules. Modules: `session_service`, `approval_service`, `question_service`, `project_service`, `workflow_service`, `deployment_service`.
- **Repositories** (`druppie/repositories/`): Data access. Queries SQLAlchemy models, returns domain models. Modules: `session_repository`, `approval_repository`, `question_repository`, `project_repository`, `execution_repository`, `user_repository`.
- **Domain Models** (`druppie/domain/`): Pydantic models that define the API contract. All exports go through `druppie/domain/__init__.py`.

### 2.2 Domain Model Naming Convention

Domain models use a Summary/Detail pattern:

- **Summary** models are lightweight, used in list endpoints (e.g., `SessionSummary`, `ProjectSummary`, `ApprovalSummary`).
- **Detail** models contain full data, used in single-item endpoints (e.g., `SessionDetail`, `ProjectDetail`, `AgentRunDetail`).

Key domain modules:

| Module | Models |
|--------|--------|
| `session.py` | `SessionSummary`, `SessionDetail`, `Message`, `TimelineEntry` |
| `agent_run.py` | `AgentRunSummary`, `AgentRunDetail`, `LLMCallDetail`, `ToolCallDetail` |
| `approval.py` | `ApprovalSummary`, `ApprovalDetail`, `PendingApprovalList` |
| `project.py` | `ProjectSummary`, `ProjectDetail`, `DeploymentInfo` |
| `question.py` | `QuestionDetail`, `QuestionChoice`, `PendingQuestionList` |
| `common.py` | `SessionStatus`, `AgentRunStatus`, `ToolCallStatus`, `ApprovalStatus`, `QuestionStatus` (enums) |
| `user.py` | `UserInfo` |
| `agent_definition.py` | `AgentDefinition`, `ApprovalOverride` |

### 2.3 Dependency Injection

Dependencies are wired in `druppie/api/deps.py`. Repositories and services are injected into route handlers via FastAPI's dependency injection system. Authentication is handled by a Keycloak JWT validator (`druppie/core/auth.py`).

### 2.4 Application Startup

`druppie/api/main.py` creates the FastAPI app via `create_app()`. It:

1. Loads settings from environment variables via `druppie/core/config.py`.
2. Registers CORS middleware (origins from `CORS_ORIGINS` env var).
3. Registers standardized error handlers.
4. Mounts all route modules under `/api`.
5. Exposes health endpoints: `/health`, `/health/ready`, `/api/status`.

The `/api/status` endpoint checks liveness of all dependent services (Keycloak, database, LLM provider, Gitea) and reports the active LLM provider and model.

### 2.5 Directory Structure

```
druppie/
  api/
    main.py              # App factory, CORS, health endpoints
    deps.py              # Dependency injection
    errors.py            # Standardized error handlers
    routes/
      chat.py            # POST /api/chat - message processing
      sessions.py        # Session CRUD
      approvals.py       # Approval management
      questions.py       # HITL question management
      projects.py        # Project CRUD
      deployments.py     # Deployment management
      workspace.py       # Workspace file access
      agents.py          # Agent listing
      mcps.py            # MCP server status
      mcp_bridge.py      # Direct MCP tool invocation
  services/
    session_service.py
    approval_service.py
    question_service.py
    project_service.py
    workflow_service.py
    deployment_service.py
  repositories/
    session_repository.py
    approval_repository.py
    question_repository.py
    project_repository.py
    execution_repository.py
    user_repository.py
  domain/
    __init__.py          # Central exports for all domain models
    common.py            # Shared enums, base types
    tool.py              # ToolDefinition with Pydantic schema generation
    session.py
    agent_run.py
    approval.py
    project.py
    question.py
    user.py
    agent_definition.py
  tools/
    params/
      builtin.py         # Pydantic models for builtin tool params
      coding.py          # Pydantic models for coding MCP tool params
      docker.py          # Pydantic models for docker MCP tool params
  db/models/
    base.py              # SQLAlchemy base, mixins
    user.py
    project.py
    session.py
    agent_run.py
    message.py
    tool_call.py
    llm_call.py
    approval.py
    question.py
  execution/
    orchestrator.py      # Main entry point: process_message()
    tool_executor.py     # Routes tool calls to MCP or builtins
    mcp_http.py          # HTTP client for MCP servers
  agents/
    runtime.py           # Agent loop, prompt construction
    builtin_tools.py     # Built-in tool definitions and execution
    definitions/         # YAML agent configs (see Section 8)
      _common.md         # Shared instructions injected via placeholder
  llm/
    service.py           # LLMService singleton, provider factory
    base.py              # BaseLLM interface, LLMResponse model
    litellm_provider.py  # Unified LiteLLM implementation (all providers)
  core/
    config.py            # Settings from env vars
    auth.py              # Keycloak JWT validation
    gitea.py             # Gitea API client
    mcp_client.py        # MCP tool fetching
    mcp_config.yaml      # MCP server + tool + approval definitions
    tool_registry.py     # Unified tool registry with Pydantic models
  mcp-servers/
    coding/              # Port 9001
    docker/              # Port 9002
    filesearch/          # Port 9004
    web/                 # Port 9005
```

---

## 3. Frontend (React / Vite)

### 3.1 Technology Stack

| Library | Version | Purpose |
|---------|---------|---------|
| React | 18.2 | UI framework |
| Vite | 5.x | Build tool, dev server |
| Tailwind CSS | 3.4 | Utility-first CSS |
| Zustand | 4.4 | State management |
| TanStack React Query | 5.17 | Server state, data fetching |
| Keycloak-js | 23.x | Authentication |
| React Router DOM | 6.21 | Client-side routing |
| React Markdown | 10.1 | Markdown rendering in chat |
| Lucide React | 0.303 | Icon library |
| Prism.js | 1.30 | Syntax highlighting |

### 3.2 Pages

| Page | File | Purpose |
|------|------|---------|
| Dashboard | `Dashboard.jsx` | Overview, service status |
| Chat | `Chat.jsx` | Main agent interaction |
| Tasks | `Tasks.jsx` | Approval management |
| Projects | `Projects.jsx` | Project listing |
| Project Detail | `ProjectDetail.jsx` | Single project view with deployments |
| Plans | `Plans.jsx` | Execution plan viewer |
| Settings | `Settings.jsx` | User preferences |
| Admin Database | `AdminDatabase.jsx` | Database inspection |
| Debug | `Debug.jsx`, `DebugChat.jsx`, `DebugApprovals.jsx`, `DebugMCP.jsx`, `DebugProjects.jsx` | Development debugging tools |

### 3.3 Real-time Updates

The frontend uses polling for real-time updates:

- **Active sessions**: 500ms polling interval for chat messages and agent status.
- **Approvals**: 1-second polling interval for pending approval/question lists.

### 3.4 API Client

`frontend/src/services/api.js` is a fetch-based HTTP client. All requests include a Bearer token from Keycloak for authentication. The base URL defaults to `http://localhost:8100` (configurable via `VITE_API_URL`).

### 3.5 Testing

- **Unit tests**: Vitest (`npm test`)
- **End-to-end tests**: Playwright (`npm run test:e2e`)

---

## 4. Database (PostgreSQL / SQLAlchemy)

### 4.1 Design Principles

- **No migrations**: Models are updated directly. The database is reset with `docker compose --profile reset-hard up` (full wipe) or `docker compose --profile reset-db up` (soft reset, keeps users).
- **No JSON/JSONB columns**: All data is normalized into proper relational tables. (excep raw API requests for debugging for now. Might be other things too, needs to be checked and updated)
- **No legacy/fallback code**: Clean architecture only.

### 4.2 Tables

SQLAlchemy ORM models live in `druppie/db/models/`. The schema:

| Table | Description |
|-------|-------------|
| `User` | Platform users (synced from Keycloak) |
| `UserRole` | User role assignments (admin, architect, developer) |
| `UserToken` | User API tokens |
| `Project` | Projects with Gitea repo references |
| `Session` | Chat sessions tied to a user and optionally a project |
| `AgentRun` | Individual agent execution records within a session |
| `Message` | Conversation messages (user and assistant) in the timeline |
| `ToolCall` | Tool invocations by agents, linked to LLM calls |
| `LlmCall` | LLM API call records (request, response, tokens, timing) |
| `Approval` | Tool approval requests requiring human authorization |
| `Question` | HITL questions requiring user answers |

### 4.3 Key Relationships

At the **database level**, `messages` and `agent_runs` are separate tables that both reference `sessions` via foreign key:

```
Session
  |-- belongs to --> User
  |-- belongs to --> Project (optional)
  |-- has many --> Message (user/assistant/system messages)
  |-- has many --> AgentRun (ordered by sequence_number)

AgentRun
  |-- has many --> LlmCall (ordered by created_at)
  |-- has many --> ToolCall
  |-- has many --> Message (scoped to this run via agent_run_id)

LlmCall
  |-- has many --> ToolCall (linked by llm_call_id)

ToolCall
  |-- has one --> Approval (if requires_approval)
  |-- has one --> Question (if HITL tool)
```

At the **domain level**, `SessionDetail` does not expose messages and agent runs as separate collections. Instead, the repository assembles a unified **timeline** -- a single chronologically sorted list of `TimelineEntry` objects. Each entry is either a `Message` or an `AgentRunDetail`:

```
SessionDetail
  |-- timeline: list[TimelineEntry]
        |
        |-- TimelineEntry (type: "message")
        |     |-- Message (role, content, timestamp)
        |
        |-- TimelineEntry (type: "agent_run")
              |-- AgentRunDetail
                    |-- llm_calls: list[LLMCallDetail]
                          |-- tool_calls: list[ToolCallDetail]
                                |-- approval: ApprovalSummary (optional)
                                |-- question_id: UUID (optional)
```

This timeline is what the frontend renders -- messages and agent runs interleaved in the order they occurred.

### 4.4 Connection

PostgreSQL 15 on port 5533 (mapped from container port 5432). Connection string: `postgresql://druppie:druppie_secret@druppie-db:5432/druppie` (within Docker network).

---

## 5. LLM Providers

### 5.1 Architecture

The LLM layer (`druppie/llm/`) uses LiteLLM as a unified interface to all providers:

```
BaseLLM (abstract)
  |-- ChatLiteLLM  (unified provider via LiteLLM SDK)
```

`LLMService` is a global singleton (in `druppie/llm/service.py`) that manages provider selection and lazy initialization. All agents share the same LLM instance.

LiteLLM provides standardized tool calling across 100+ providers, eliminating the need for custom parsing code.

### 5.2 Provider Selection

Controlled by the `LLM_PROVIDER` environment variable:

| Value | Behavior |
|-------|----------|
| `zai` | Use Z.AI with `ZAI_API_KEY` |
| `deepinfra` | Use DeepInfra with `DEEPINFRA_API_KEY` |

### 5.3 Provider Details

Both providers are OpenAI-compatible and use the same unified code path via LiteLLM. They use the `openai/` prefix internally with custom `api_base` URLs.

**Z.AI (GLM)**
- Model: `glm-4.7` (default, configurable via `ZAI_MODEL`)
- Base URL: `https://api.z.ai/api/coding/paas/v4`
- Display name: `zai/glm-4.7`

**DeepInfra (Qwen)**
- Model: `Qwen/Qwen3-32B` (default, configurable via `DEEPINFRA_MODEL`)
- Base URL: `https://api.deepinfra.com/v1/openai`
- Display name: `deepinfra/Qwen/Qwen3-32B`

### 5.4 Response Parsing

LiteLLM handles all response parsing and tool call extraction automatically. The `LLMResponse` model normalizes responses into a consistent format with content, tool calls, and token usage.

---

## 6. MCP Servers

MCP (Model Context Protocol) servers are HTTP microservices built with the FastMCP framework. Each exposes a `/health` endpoint and tool endpoints.

### 6.1 Configuration

MCP servers, their tools, and approval requirements are defined in `druppie/core/mcp_config.yaml`. This is the single source of truth for:

- Server URLs (with environment variable substitution)
- Tool names, descriptions, and parameter schemas
- Approval requirements per tool (which role can approve)
- Parameter injection rules (what context values get auto-injected)

### 6.2 Coding Server (port 9001)

File and git operations within workspace sandboxes.

| Tool | Approval | Description |
|------|----------|-------------|
| `read_file` | None | Read file from workspace |
| `write_file` | None (overridable per agent) | Write file to workspace |
| `batch_write_files` | None (overridable per agent) | Write multiple files at once |
| `list_dir` | None | List directory contents |
| `delete_file` | None | Delete file from workspace |
| `create_branch` | None | Create/switch git branch |
| `commit_and_push` | None | Commit and push to Gitea |
| `get_git_status` | None | Git status of workspace |
| `create_pull_request` | None | Create PR on Gitea |
| `merge_pull_request` | Developer | Merge PR and delete branch |
| `merge_to_main` | Architect | Direct merge to main branch |

### 6.3 Docker Server (port 9002)

Container lifecycle management.

| Tool | Approval | Description |
|------|----------|-------------|
| `build` | Developer | Build image by cloning from git |
| `run` | Developer | Run container (auto-assigns host port from 9100-9199) |
| `stop` | None | Stop container |
| `logs` | None | Get container logs |
| `remove` | Developer | Remove container |
| `list_containers` | None | List containers with label filtering |
| `inspect` | None | Inspect container details |
| `exec_command` | Developer | Execute command in container |

### 6.4 Web / Bestand-Zoeker Server (port 9005)

Web browsing and local file search within datasets.

| Tool | Approval | Description |
|------|----------|-------------|
| `search_files` | None | Text search in local files |
| `list_directory` | None | List files in dataset |
| `read_file` | None | Read file from dataset |
| `fetch_url` | None | Fetch content from URL |
| `search_web` | None | Web search |
| `get_page_info` | None | Get web page metadata |

### 6.5 File Search Server (port 9004)

Local file search capability over mounted dataset volumes.

### 6.6 Declarative Parameter Injection

MCP tools can have parameters auto-injected from the session/project context. Injected parameters are marked `hidden: true` and are removed from the LLM-visible tool schema. This prevents the LLM from needing to know internal IDs.

Example from `mcp_config.yaml`:

```yaml
inject:
  session_id:
    from: session.id
    hidden: true
  repo_name:
    from: project.repo_name
    hidden: true
    tools: [read_file, write_file, list_dir, ...]
```

### 6.7 Layered Approval System

Approvals have two layers:

1. **Global defaults** in `mcp_config.yaml`: define the default approval requirement for each tool.
2. **Per-agent overrides** in agent YAML files via `approval_overrides`: agents can tighten or loosen requirements.

Example override in an agent YAML:

```yaml
approval_overrides:
  coding:write_file:
    requires_approval: true
    required_role: architect
```

---

## 7. Infrastructure (Docker Compose)

### 7.1 Services

All services are defined in `docker-compose.yml` (at the repository root):

```
druppie-db          PostgreSQL 15     :5533   Main database
keycloak-db         PostgreSQL 15     -       Keycloak database (internal)
keycloak            Keycloak 24.0     :8180   Authentication
gitea-db            PostgreSQL 15     -       Gitea database (internal)
gitea               Gitea 1.21        :3100   Git hosting
druppie-backend     FastAPI           :8100   Backend API
druppie-frontend    Vite/React        :5273   Frontend
mcp-coding          FastMCP           :9001   File/git operations
mcp-docker          FastMCP           :9002   Docker operations
mcp-filesearch      FastMCP           :9004   File search
mcp-web             FastMCP           :9005   Web browsing
adminer             Adminer           :8081   DB admin UI
```

### 7.2 Network

All containers share a single bridge network: `druppie-new-network`. Internal communication uses container hostnames (e.g., `druppie-db`, `keycloak`, `gitea`, `mcp-coding`).

### 7.3 Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `druppie_new_postgres` | PostgreSQL data | Main database persistence |
| `druppie_new_keycloak_postgres` | Keycloak PostgreSQL | Auth database persistence |
| `druppie_new_gitea_postgres` | Gitea PostgreSQL | Git database persistence |
| `druppie_new_gitea` | Gitea data | Repository storage |
| `druppie_new_workspace` | `/app/workspace` (backend), `/workspaces` (MCP) | Shared workspace for agent file operations |
| Docker socket | `/var/run/docker.sock` | Allows backend and MCP Docker to manage containers |

### 7.4 Health Checks

Every service has a Docker health check. Services with dependencies use `condition: service_healthy` to enforce startup order:

```
druppie-db  <-- keycloak (via keycloak-db)
            <-- gitea (via gitea-db)
            <-- druppie-backend
                   <-- druppie-frontend
                   <-- mcp-coding (depends on gitea)
```

### 7.5 Development Setup

The setup uses Docker Compose with profiles:

```bash
# First time setup (initialize Keycloak and Gitea)
cp .env.example .env          # Copy and edit environment variables
docker compose --profile init up -d

# Development mode (hot reload enabled)
docker compose --profile dev up -d

# Production mode
docker compose --profile prod up -d

# Infrastructure only (DBs, Keycloak, Gitea, MCPs)
docker compose --profile infra up -d

# Stop all services
docker compose --profile dev --profile prod --profile infra down

# Check status
docker compose ps
```

### 7.6 Database Reset

Two reset options are available:

```bash
# Soft reset: drops application tables (projects, sessions, etc.), keeps users
docker compose --profile reset-db up

# Hard reset: wipes all volumes, restarts everything fresh
docker compose --profile reset-hard up
```

The soft reset is useful during development when you want to clear session/project data without re-running Keycloak/Gitea setup. The hard reset is a full wipe that requires re-initialization.

### 7.7 Profiles

| Profile | Purpose |
|---------|---------|
| `infra` | Infrastructure only (DBs, Keycloak, Gitea, MCP servers) |
| `dev` | Development mode with hot reload (backend via uvicorn --reload, frontend via Vite HMR) |
| `prod` | Production mode (static builds) |
| `init` | One-time Keycloak and Gitea setup (creates realm, users, OAuth apps) |
| `reset-db` | Soft reset: drops application tables, keeps users |
| `reset-hard` | Hard reset: wipes all volumes, reinitializes everything |

### 7.8 Cross-Platform Support

The Docker Compose setup works on Windows, macOS, and Linux. Shell scripts use LF line endings (enforced via `.gitattributes`) and Dockerfiles include `sed` commands to strip any CRLF characters that may be introduced on Windows.

---

## 8. Agent System

### 8.1 Agent Definitions

Nine agents are defined as YAML files in `druppie/agents/definitions/`:

| Agent | Role | Builtin Tools | MCP Access |
|-------|------|---------------|------------|
| `router` | Classifies user intent, selects project | `set_intent` | None |
| `planner` | Creates execution plan (which agents to run) | `make_plan` | None |
| `business_analyst` | Gathers requirements from user | Default | None (HITL only) |
| `architect` | Designs system architecture, writes specs | Default | `coding` |
| `developer` | Writes code, commits, creates PRs | Default | `coding` |
| `reviewer` | Reviews code quality | Default | `coding` |
| `tester` | Writes and runs tests | Default | `coding`, `docker` |
| `deployer` | Builds and deploys containers | Default | `coding`, `docker` |
| `summarizer` | Creates conversation summary message | `create_message` | None |

Default builtin tools (all agents): `done`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`.

Each YAML file specifies:

```yaml
name: developer
system_prompt: |
  You are a senior developer...
  [COMMON_INSTRUCTIONS]
model: null              # Uses global LLM (per-agent selection not yet active)
temperature: 0.7
max_tokens: 8192
max_iterations: 10
mcps:
  - coding
builtin_tools:
  - done
  - hitl_ask_question
  - hitl_ask_multiple_choice_question
extra_builtin_tools: []
approval_overrides: {}
```

### 8.2 Shared Instructions

`druppie/agents/definitions/_common.md` contains instructions shared across all agents (summary relay format, `done()` output format, workspace state context). The `[COMMON_INSTRUCTIONS]` placeholder in an agent's system prompt is replaced with this content at runtime.

**Note:** Currently only 4 agents include the `[COMMON_INSTRUCTIONS]` placeholder (deployer, architect, business_analyst, planner). The developer, reviewer, tester, and router agents do not, which can lead to inconsistent agent communication -- see BACKLOG.md.

### 8.3 Agent Runtime Loop

The agent runtime (`druppie/agents/runtime.py`) implements a tool-calling loop:

```
1. Build system prompt (inject common instructions + tool descriptions)
2. Build user prompt (inject project context)
3. Call LLM with messages + tool definitions
4. Parse response for tool calls
5. For each tool call:
   a. Create ToolCall record in DB
   b. Execute via ToolExecutor
   c. If waiting_approval -> pause agent, return
   d. If waiting_answer -> pause agent, return
   e. If "done" tool -> agent complete, return
   f. Otherwise -> add result to messages, loop to step 3
6. If max_iterations reached -> raise AgentMaxIterationsError
```

If the LLM responds without tool calls, the runtime sends a correction message and retries. Agents can only interact through tool calls -- they cannot produce raw text output.

**Note:** Tool information is currently sent to the LLM twice per request: as human-readable text in the system prompt (step 1) and as structured OpenAI function schemas in the API `tools` parameter (step 3). The system prompt text carries extra context the schema cannot (e.g., approval requirements), but tool name, description, and parameters are fully duplicated, wasting tokens on every call -- see BACKLOG.md.

### 8.4 Summary Relay Mechanism

When an agent calls the `done()` builtin tool, the platform automatically collects summaries from all previously completed agents in the session and forwards them to the next pending agent. This is the only mechanism for inter-agent context passing.

**Implementation:** `druppie/agents/builtin_tools.py` (lines 628-684)

The relay works in two phases:

**Phase 1 -- Accumulate (lines 628-659):**

1. Query all completed `AgentRun` records for the current session via `execution_repo.get_completed_runs(session_id)`, ordered by `completed_at`.
2. For each completed run, call `execution_repo.get_done_summary_for_run(run_id)` which looks up the `ToolCall` record where `tool_name='done'` and `status='completed'`, then extracts the `summary` field from the result JSON.
3. Extract only lines matching the `"Agent <role>: ..."` pattern from each summary. This avoids duplication -- since each stored summary already contains the accumulated context that agent received, copying the full text would repeat everything.
4. Deduplicate: track seen lines and skip duplicates across runs.
5. Combine the current agent's own new lines (those not already in the previous set) with the accumulated previous lines.

**Phase 2 -- Inject (lines 669-684):**

1. Query the next pending agent run via `execution_repo.get_next_pending(session_id)`.
2. If a next run exists, prepend the accumulated summary to its `planned_prompt` in the database:

```python
new_prompt = (
    f"PREVIOUS AGENT SUMMARY:\n{accumulated_summary}\n\n---\n\n"
    + next_run.planned_prompt
)
execution_repo.update_planned_prompt(next_run.id, new_prompt)
```

**Storage:** Summaries are persisted as `ToolCall` result JSON. The repository method `get_done_summary_for_run()` (`execution_repository.py:149-175`) queries for the `done` tool call and parses the summary from the stored JSON result.

**Scope:** Accumulation is per-session and never resets. Every completed agent run in the session contributes to the chain, regardless of planner re-evaluations or workflow phase transitions. A new session starts with no accumulated summaries.

### 8.5 Tool Registry

`druppie/core/tool_registry.py` is the single source of truth for all tool definitions. It combines:
- **MCP tools** fetched from MCP servers with Pydantic parameter models
- **Builtin tools** (done, make_plan, hitl_ask_question, etc.)

Each tool is represented by a `ToolDefinition` (`druppie/domain/tool.py`) which contains:
- Tool metadata (name, description, server)
- A Pydantic model class for type-safe parameters
- Approval requirements

**Pydantic Parameter Models** (`druppie/tools/params/`):
```
params/
  builtin.py   # DoneParams, MakePlanParams, HitlAskQuestionParams, ...
  coding.py    # ReadFileParams, WriteFileParams, CommitAndPushParams, ...
  docker.py    # BuildImageParams, StartContainerParams, ...
```

**OpenAI Strict Mode**: Tool schemas follow OpenAI strict mode requirements:
- `strict: true` on all function definitions
- `additionalProperties: false` on all object schemas
- All properties in `required` array
- Optional fields use `anyOf: [{type}, {type: null}]` pattern with `default: null`

**Usage in Agent Runtime**:
```python
registry = get_tool_registry()

# Get tools for an agent based on its MCP permissions
tools = registry.get_tools_for_agent(
    agent_mcps=["coding", "docker"],
    builtin_tool_names=["done", "hitl_ask_question"],
)

# Convert to OpenAI format for LLM
openai_tools = registry.to_openai_format(tools)
```

### 8.6 Tool Executor

`druppie/execution/tool_executor.py` is the single entry point for all tool execution:

```
ToolExecutor.execute(tool_call_id)
  |
  |-- Validate arguments against Tool Registry schema
  |-- Builtin HITL tool? --> Create Question record, status = waiting_answer
  |-- Builtin other?     --> Execute directly, status = completed
  |-- MCP tool needs approval? --> Create Approval record, status = waiting_approval
  |-- MCP tool?           --> Call MCP server via HTTP, status = completed/failed
```

**Argument Validation**: Before executing any tool, the executor validates arguments against the Pydantic schema from the Tool Registry. Invalid arguments result in a clear error message returned to the LLM, allowing it to retry with correct arguments.

The `ToolCall` database record is the source of truth. `Question` and `Approval` records link back to it via `tool_call_id`.

### 8.7 Orchestrator

`druppie/execution/orchestrator.py` is the main entry point for processing user messages. The flow:

```
process_message(message, user_id)
  |
  |-- 1. Create or get session
  |-- 2. Build conversation history (if continuing)
  |-- 3. Save user message to timeline
  |-- 4. Inject user's project list into router prompt
  |-- 5. Create Router (seq 0) + Planner (seq 1) as PENDING
  |-- 6. Execute all pending runs:
  |       |-- Router runs -> calls set_intent()
  |       |     set_intent creates project + Gitea repo if needed,
  |       |     updates planner prompt with intent context
  |       |-- Planner runs -> calls make_plan()
  |       |     make_plan creates PENDING agent runs (e.g., architect, developer, deployer)
  |       |-- Remaining agents execute in sequence_number order
  |-- 7. If any agent pauses (approval/question), execution stops
  |-- 8. On resume (after approval/answer), agent continues from DB state
```

Key resume methods:

- `resume_after_approval()`: Executes the approved tool, then continues the paused agent.
- `resume_after_answer()`: Saves the answer to the tool call result, then continues the paused agent.

Both methods reconstruct agent state from the database (LLM call history, tool call results) so the agent can continue where it left off.

### 8.8 Pause and Resume

When an agent encounters a tool that requires approval or a HITL question:

1. The `ToolExecutor` creates an `Approval` or `Question` record.
2. The agent run is marked `PAUSED_TOOL` or `PAUSED_HITL`.
3. The orchestrator stops executing further agents.
4. The frontend polls for pending approvals/questions and presents them to the user.
5. When the user responds, the API calls the orchestrator's resume method.
6. The orchestrator reconstructs the agent's message history from `LlmCall` and `ToolCall` records.
7. The agent loop continues from the iteration where it paused.

---

## 9. Configuration

### 9.1 Environment Variables

Required in `.env`:

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | LLM provider selection (`zai`, `deepinfra`) |
| `ZAI_API_KEY` | Z.AI API key (if using zai) |
| `DEEPINFRA_API_KEY` | DeepInfra API key (if using deepinfra) |
| `GITEA_TOKEN` | Gitea API token |

Optional:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ZAI_MODEL` | `glm-4.7` | Z.AI model name |
| `ZAI_BASE_URL` | `https://api.z.ai/api/coding/paas/v4` | Z.AI API base URL |
| `DEEPINFRA_MODEL` | `Qwen/Qwen3-32B` | DeepInfra model name |
| `DEEPINFRA_BASE_URL` | `https://api.deepinfra.com/v1/openai` | DeepInfra API base URL |
| `CORS_ORIGINS` | `http://localhost:5273,http://localhost:5173` | Allowed CORS origins |
| `VITE_API_URL` | `http://localhost:8100` | Frontend API base URL |
| `VITE_KEYCLOAK_URL` | `http://localhost:8180` | Frontend Keycloak URL |

### 9.2 Configuration Files

| File | Purpose |
|------|---------|
| `druppie/core/mcp_config.yaml` | MCP server URLs, tool schemas, approval rules, parameter injection |
| `druppie/agents/definitions/*.yaml` | Agent definitions (prompt, tools, model config) |
| `druppie/agents/definitions/_common.md` | Shared prompt instructions for all agents |
| `docker-compose.yml` | Infrastructure service definitions (at repository root) |
| `.env` | Environment variable overrides |
| `.env.example` | Documented template for environment variables |

