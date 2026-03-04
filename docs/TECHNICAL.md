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
| Sandbox Control Plane | Node.js | 8787 | Sandbox session/event management, coordinates sandbox lifecycle |
| Sandbox Manager | Node.js | 8000 | Creates/manages sandbox Docker containers, enforces resource limits |
| Sandbox Image Builder | Docker | — | One-shot build producing `open-inspect-sandbox:latest` image |
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
- **Services** (`druppie/services/`): Business logic. Orchestrates repository calls, enforces rules. Modules: `session_service`, `approval_service`, `question_service`, `project_service`, `workflow_service`, `deployment_service`, `revert_service`.
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
| `skill.py` | `SkillSummary`, `SkillDetail` |
| `tool.py` | `ToolDefinition`, `ToolDefinitionSummary`, `ToolType` |

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
      sandbox.py         # Sandbox session registration, events proxy, completion webhook
  services/
    session_service.py
    approval_service.py
    question_service.py
    project_service.py
    workflow_service.py
    deployment_service.py
    revert_service.py
  repositories/
    session_repository.py
    approval_repository.py
    question_repository.py
    project_repository.py
    execution_repository.py
    user_repository.py
    sandbox_session_repository.py
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
  sandbox-config/
    opencode-config.json   # OpenCode default agent + permissions
    agents/
      druppie-builder.md   # Sandbox coding agent prompt
      druppie-tester.md    # Sandbox testing agent prompt
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
    sandbox_session.py   # Sandbox session ownership mapping
  execution/
    orchestrator.py      # Main entry point: process_message()
    tool_executor.py     # Routes tool calls to MCP or builtins
    mcp_http.py          # HTTP client for MCP servers
  agents/
    runtime.py           # Agent facade (public API)
    loop.py              # Core LLM ↔ tool-calling loop
    definition_loader.py # Loads YAML definitions, resolves placeholders
    message_history.py   # Reconstructs agent state from DB for resume
    prompt_builder.py    # Builds system/user prompts with context
    builtin_tools.py     # Built-in tool definitions and execution
    definitions/         # YAML agent configs (see Section 8)
      system_prompts/    # Composable system prompts (see Section 8.2)
  skills/
    code-review/SKILL.md # Code review skill definition
    git-workflow/SKILL.md# Git workflow skill definition
  services/
    skill_service.py     # Loads and resolves skill definitions
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
| `LlmRetry` | Audit trail for LLM retry attempts (error type, delay) |
| `ToolCallNormalization` | Audit trail for argument normalization (original → normalized values) |
| `SandboxSession` | Maps sandbox control plane session IDs to Druppie users for ownership verification |

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

### 5.5 LLM Profiles

Agents reference shared **LLM profiles** defined in `druppie/agents/definitions/llm_profiles.yaml`. Each profile is an ordered list of `{provider, model}` pairs:

```yaml
profiles:
  standard:
    - provider: zai
      model: glm-4.7
    - provider: azure_foundry
      model: GPT-5-MINI
  cheap:
    - provider: azure_foundry
      model: GPT-5-MINI
    - provider: zai
      model: glm-4.7
    - provider: deepinfra
      model: Qwen/Qwen3-32B
```

Agent YAMLs reference a profile by name:
```yaml
llm_profile: standard   # or "cheap" for router/summarizer
temperature: 0.2
```

The **model resolver** (`druppie/llm/resolver.py`) determines which provider/model to use through a 3-step resolution:

1. **Override** — `LLM_FORCE_PROVIDER` / `LLM_FORCE_MODEL` env vars force ALL agents to a single provider (useful for testing/debugging).
2. **Profile** — Filter the profile's provider list by API key availability. First available entry becomes primary, second becomes fallback. The global `LLM_PROVIDER` env var is appended to the chain as last-resort if not already present.
3. **Global default** — If no profile is set, falls back to `LLM_PROVIDER` env var.

**Runtime fallback** (`druppie/llm/fallback.py`): When a profile has multiple available providers, `FallbackLLM` wraps primary + fallback. Any `LLMError` from the primary triggers fallback — including `AuthenticationError`. This is correct for cross-provider fallback: if provider A's auth key is invalid, provider B (a completely different service) may work fine.

```
AgentLoop._call_llm() retry loop (3 attempts, exponential backoff)
  └─ FallbackLLM.achat()
       ├─ primary ChatLiteLLM.achat() (litellm internal retries: num_retries=3)
       │   └─ any LLMError after all litellm retries
       └─ fallback ChatLiteLLM.achat() (litellm internal retries: num_retries=3)
```

All resolution decisions are logged as structured `model_resolved` events, and the `/api/status` endpoint exposes loaded profiles and their provider chains.

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
| `execute_coding_task` | None | Execute coding task in isolated sandbox |
| `revert_to_commit` | None (internal) | Hard reset + force push to a target commit |
| `close_pull_request` | None (internal) | Close a PR on Gitea without merging |

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
sandbox-control-plane  Node.js        :8787   Sandbox session/event management
sandbox-manager     Node.js           :8000   Sandbox container lifecycle
sandbox-image-builder  Docker         -       Builds open-inspect-sandbox:latest image
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
| `sandbox_data` | `/data` (control plane) | Sandbox session data (SQLite) |
| `sandbox_snapshots` | `/data/snapshots` (manager) | Sandbox container snapshots |
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

| Agent | Role | Builtin Tools | MCP Access | Skills |
|-------|------|---------------|------------|--------|
| `router` | Classifies user intent, selects project | `set_intent` | None | — |
| `planner` | Creates execution plan (which agents to run) | `make_plan` | None | — |
| `business_analyst` | Gathers requirements from user | Default | None (HITL only) | — |
| `architect` | Designs system architecture, writes specs | Default | `coding` | — |
| `developer` | Writes code, commits, creates PRs | `invoke_skill`, `execute_coding_task` | `coding` | `code-review`, `git-workflow` |
| `reviewer` | Reviews code quality | Default | `coding` | — |
| `tester` | Writes and runs tests | `execute_coding_task` | `coding`, `docker` | — |
| `deployer` | Builds and deploys containers | Default | `coding`, `docker` | — |
| `summarizer` | Creates conversation summary message | `create_message` | None | — |

Default builtin tools (all agents): `done`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`. Optional extra builtins: `execute_coding_task` (sandbox delegation, used by Developer/Tester).

Each YAML file specifies:

```yaml
name: developer
system_prompt: |
  You are a senior developer...
system_prompts:           # Composable system prompts (see 8.2)
  - summary_relay
  - done_tool_format
  - workspace_state
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

### 8.2 System Prompts

Reusable prompt instructions live as YAML files in `druppie/agents/definitions/system_prompts/`. Each file has a `name` (matching the filename) and a `prompt` field containing the text to inject.

Available system prompts:

| System Prompt | Purpose |
|----------|---------|
| `summary_relay` | How to read previous agent summaries and format your own via `done()` |
| `done_tool_format` | Mandatory `done()` output format rules |
| `workspace_state` | Shared workspace and git branch rules |

Agents declare which system prompts to include via the `system_prompts` list in their YAML definition. At runtime, the agent's `_build_system_prompt()` method loads each system prompt and appends it (in order) after the agent's own `system_prompt` text, before tool instructions are added.

Agents without a `system_prompts` list (or with an empty list) receive no system prompts. Currently, 5 agents include all 3 system prompts: architect, business_analyst, deployer, developer, and planner. The router, summarizer, reviewer, and tester agents do not include system prompts.

### 8.3 Agent Runtime Architecture

The agent runtime is split into focused modules:

| Module | Class | Purpose |
|--------|-------|---------|
| `runtime.py` | `Agent` | Public facade — coordinates loader, prompt builder, and loop |
| `loop.py` | `AgentLoop` | Core LLM ↔ tool-calling loop, skill tool enrichment |
| `definition_loader.py` | `AgentDefinitionLoader` | Loads YAML definitions and system prompts |
| `message_history.py` | `reconstruct_from_db()` | Rebuilds agent message history from DB for resume |
| `prompt_builder.py` | `PromptBuilder` | Builds system/user prompts with context injection |

The core loop (`AgentLoop.run()`):

```
1. Build system prompt (append declared system prompts + tool descriptions)
2. Build user prompt (inject project context)
3. Call LLM with messages + tool definitions
4. Parse response for tool calls
5. For each tool call:
   a. Normalize arguments (e.g., "null" → None) with audit trail
   b. Create ToolCall record in DB
   c. Execute via ToolExecutor
   d. If waiting_approval -> pause agent, return
   e. If waiting_answer -> pause agent, return
   f. If "done" tool -> agent complete, return
   g. If failed + break_on_failure -> stop batch, let LLM retry
   h. Otherwise -> add result to messages, loop to step 3
6. If max_iterations reached -> raise AgentMaxIterationsError
```

If the LLM responds without tool calls, the runtime sends a correction message and retries. Agents can only interact through tool calls -- they cannot produce raw text output.

**Argument normalization:** Before executing a tool call, the loop normalizes common LLM mistakes (e.g., `"null"` string → `None`, `"true"` → `true`). Each normalization is recorded in the `tool_call_normalizations` table for debugging.

**Break-on-failure:** When a tool call fails, the loop stops processing remaining tool calls from the same LLM response and feeds the error back to the LLM so it can retry with corrected arguments. This prevents cascading failures from bad tool call batches.

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

**Skill-based access control:** When a tool call comes from an agent with active skills, the executor also checks whether the tool is allowed by any of the agent's skills (via `_is_tool_allowed_via_skill()`). This extends the agent's tool access beyond its static YAML `mcps` configuration.

### 8.7 Skills System

Skills are reusable prompt/instruction packages stored as Markdown files in `druppie/skills/<skill-name>/SKILL.md`. Each skill has YAML frontmatter (`name`, `description`, `allowed-tools`) and a Markdown body with instructions.

**Architecture:**
- **`druppie/services/skill_service.py`** — `SkillService` loads skills from the filesystem, parses YAML frontmatter, and returns `SkillDetail` domain objects.
- **`druppie/domain/skill.py`** — `SkillSummary` and `SkillDetail` Pydantic models.
- **`druppie/agents/builtin_tools.py`** — `invoke_skill` builtin tool definition and handler.
- **`druppie/agents/loop.py`** — `_prepare_tools()` enriches the `invoke_skill` tool description with available skills, `_add_skill_tools()` dynamically adds skill tools to the agent's tool set.

**Flow:**
1. Agent YAML defines `skills: [code-review, git-workflow]`.
2. At tool preparation time, `invoke_skill`'s description is enriched with the list of available skills and their descriptions.
3. When the LLM calls `invoke_skill(skill_name="code-review")`:
   - The skill is loaded and its `allowed_tools` are added to the agent's tool set for subsequent LLM calls.
   - The skill's Markdown body is returned as the tool result (instructions for the LLM).
4. `ToolExecutor` checks `_is_tool_allowed_via_skill()` to permit tools granted by active skills.

### 8.8 Orchestrator

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

**Cooperative pause/cancellation:** The orchestrator checks the session status (via DB poll) before each agent run and after each agent completes. If the status is `paused` or `cancelled`, it stops executing further runs. The agent loop also checks the session status between LLM iterations. This means stopping is cooperative -- it happens at the next check point, not mid-LLM-call. See section 8.9 for the full stop and resume architecture.

**Retry from agent run:** The `POST /api/sessions/{id}/retry-from/{run_id}` endpoint spawns a background task that uses `RevertService` to revert the target run and all subsequent runs, then calls `execute_pending_runs()` to re-execute them. `RevertService` handles git revert (via `revert_to_commit` MCP tool), PR cleanup, and DB record management.

### 8.9 Pause and Resume

The platform supports two kinds of pause: **automatic** (tool approval / HITL questions) and **user-initiated** (stop button).

#### Automatic Pause (Approval / HITL)

When an agent encounters a tool that requires approval or a HITL question:

1. The `ToolExecutor` creates an `Approval` or `Question` record.
2. The agent run is marked `PAUSED_TOOL` or `PAUSED_HITL`.
3. The orchestrator stops executing further agents.
4. The frontend polls for pending approvals/questions and presents them to the user.
5. When the user responds, the API calls the orchestrator's resume method.
6. The orchestrator reconstructs the agent's message history from `LlmCall` and `ToolCall` records.
7. The agent loop continues from the iteration where it paused.

#### User-Initiated Stop & Resume

Users can stop any running session and resume it later with full context preservation.

**Stop flow:**

1. The user clicks the **Stop** button (visible during `active`, `paused_approval`, and `paused_hitl` states).
2. `POST /api/chat/{session_id}/cancel` sets `session.status = 'paused'` in the database.
3. Both the orchestrator loop (between agent runs) and the agent loop (between LLM iterations) poll the session status from the database and detect the pause.
4. The current LLM call and tool execution completes, then the agent stops cleanly at the next check point (cooperative cancellation).
5. For sessions already paused for approval or HITL (no background task running), the status change is immediate.

**Resume flow:**

1. The user clicks the **Continue** button (visible when session status is `paused`).
2. `POST /api/sessions/{session_id}/resume` spawns a background task.
3. The background task calls `agent.continue_run()`, which uses `reconstruct_from_db()` (`druppie/agents/message_history.py`) to rebuild the full LLM conversation from `LlmCall` and `ToolCall` database records.
4. The agent loop continues execution from where it left off.
5. After the current agent completes, the orchestrator continues executing remaining pending agent runs.

**Zombie session recovery:**

On application startup, the system detects "zombie" sessions -- sessions that were in `active` status when the server stopped (e.g., due to a reboot or crash). These sessions are automatically marked as `paused` so users can resume them via the Continue button.

**Status model:**

| Status | Meaning | Set By |
|--------|---------|--------|
| `active` | Processing in progress | Orchestrator on session start / resume |
| `paused` | Stopped by user or recovered after reboot | Cancel endpoint / startup recovery |
| `paused_approval` | Waiting for tool approval | ToolExecutor |
| `paused_hitl` | Waiting for user answer (HITL) | ToolExecutor |
| `completed` | All agents finished | Orchestrator |
| `failed` | Error occurred | Orchestrator |
| `cancelled` | Internal only -- planner superseded old pending runs | Planner (via `make_plan`) |

Note: `CANCELLED` is never set by user actions. It is only used internally by the planner when it creates a new plan that supersedes previously pending agent runs.

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
| `SANDBOX_CONTROL_PLANE_URL` | `http://sandbox-control-plane:8787` | Sandbox control plane endpoint |
| `SANDBOX_API_SECRET` | `sandbox-dev-secret` | HMAC-SHA256 secret for sandbox auth tokens |
| `SANDBOX_MEMORY_LIMIT` | `4g` | Docker memory limit per sandbox container |
| `SANDBOX_CPU_LIMIT` | `2` | Docker CPU limit per sandbox container |

### 9.2 Configuration Files

| File | Purpose |
|------|---------|
| `druppie/core/mcp_config.yaml` | MCP server URLs, tool schemas, approval rules, parameter injection |
| `druppie/agents/definitions/*.yaml` | Agent definitions (prompt, tools, model config) |
| `druppie/agents/definitions/system_prompts/*.yaml` | Composable system prompts (see Section 8.2) |
| `docker-compose.yml` | Infrastructure service definitions (at repository root) |
| `.env` | Environment variable overrides |
| `.env.example` | Documented template for environment variables |
| `druppie/sandbox-config/` | OpenCode config and agent prompts injected into sandboxes |

---

## 10. Sandbox Infrastructure (Open-Inspect)

### 10.1 Architecture Overview

Open-Inspect is integrated as a git submodule at `vendor/open-inspect/` (from `nuno-git/background-agents`, branch `feature/docker-compose-local-dev`). It provides isolated Docker sandboxes where coding agents can clone a project, write code, run tests, commit, and push — all without touching the shared workspace directly.

Three Docker services power the sandbox infrastructure:

- **sandbox-control-plane** (port 8787): HTTP API for session and event management, SQLite storage, coordinates sandbox lifecycle
- **sandbox-manager** (port 8000): Creates and manages sandbox Docker containers, enforces resource limits, handles snapshots
- **sandbox-image-builder** (one-shot): Builds the `open-inspect-sandbox:latest` image; Docker caches it so it only rebuilds when the Dockerfile changes

Communication flow: Druppie backend (built-in tool) → control plane API → sandbox manager → Docker containers. On completion, the control plane sends a webhook back to the backend.

### 10.2 Docker Compose Services

| Service | Build Context | Port | Key Env Vars | Volumes | Role |
|---------|--------------|------|-------------|---------|------|
| `sandbox-control-plane` | `vendor/open-inspect` (`packages/local-control-plane/Dockerfile`) | 8787 | `PORT`, `DATA_DIR`, `SANDBOX_MANAGER_URL`, `MODAL_API_SECRET`, `ZAI_API_KEY` | `sandbox_data:/data` | HTTP API for session/event management, SQLite storage |
| `sandbox-manager` | `vendor/open-inspect` (`packages/local-sandbox-manager/Dockerfile`) | 8000 | `SANDBOX_RUNTIME=docker`, `SANDBOX_IMAGE`, `DOCKER_NETWORK`, `DOCKER_MEMORY_LIMIT`, `DOCKER_CPU_LIMIT` | `sandbox_snapshots:/data/snapshots`, Docker socket | Creates/manages sandbox containers, enforces limits |
| `sandbox-image-builder` | `vendor/open-inspect` (`packages/local-sandbox-manager/Dockerfile.sandbox`) | — | — | — | One-shot build producing `open-inspect-sandbox:latest`; Docker caches the image |

### 10.3 `execute_coding_task` Built-in Tool

Defined in `druppie/agents/builtin_tools.py`. This is a **built-in tool** (not an MCP tool) — it runs inside the backend process. It delegates a coding task to an isolated sandbox and uses a **webhook + pause/resume** pattern instead of long-polling.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `task` | str | (required) | Coding task description / prompt |
| `agent` | str | `druppie-builder` | Sandbox agent (`druppie-builder` for coding, `druppie-tester` for testing) |
| `repo_name`, `repo_owner`, `session_id`, `project_id`, `user_id` | str | (auto-injected) | Context parameters injected by parameter injection |

Agents that can use this tool declare it via `extra_builtin_tools: [execute_coding_task]` in their YAML definition (currently: `builder`, `tester`).

**Auth:** HMAC-SHA256 tokens in the format `{unix_ms_timestamp}.{hmac_sha256_hex_signature}`, matching Open-Inspect's `verifyInternalToken`. A fresh token is generated for every API request to the control plane. The secret is `SANDBOX_API_SECRET`.

**Execution flow (fire-and-forget with webhook callback):**

1. **Create session** — `POST /sessions` on the control plane with repo URL, agent config, and LLM model
2. **Send prompt with callback** — `POST /sessions/{id}/message` with the task description plus `callbackUrl` and `callbackSecret`. The callback URL points to `POST /api/sandbox-sessions/{id}/complete` on the Druppie backend.
3. **Register ownership** — `POST /api/sandbox-sessions/internal/register` on the Druppie backend to map the sandbox session ID to the requesting user
4. **Return immediately** — The tool returns `{"status": "waiting_sandbox", "sandbox_session_id": "..."}`. The tool executor detects this status and sets the tool call to `WAITING_SANDBOX`, which pauses the agent (agent run → `PAUSED_SANDBOX`, session → `paused_sandbox`).
5. **Webhook callback** — When the sandbox completes (or is cancelled), the control plane POSTs to the callback URL with an HMAC-signed payload. The webhook endpoint fetches final events, extracts changed files and agent output, completes the tool call, and resumes the agent via `Orchestrator.resume_after_sandbox()`.

**Status model:**

| Level | Status | Meaning |
|-------|--------|---------|
| ToolCallStatus | `WAITING_SANDBOX` | Tool call dispatched, waiting for webhook |
| AgentRunStatus | `PAUSED_SANDBOX` | Agent paused while sandbox executes |
| AgentRunStatus | `PAUSED_CRASHED` | Agent crashed, session paused for recovery |
| SessionStatus | `paused_sandbox` | Session paused for sandbox, visible in UI |
| SessionStatus | `paused_crashed` | Session paused due to crash, visible in UI |

**Webhook endpoint:** `POST /api/sandbox-sessions/{sandbox_session_id}/complete` (in `druppie/api/routes/sandbox.py`). Verifies HMAC-SHA256 signature via `X-Signature` header, then:

1. Finds the `WAITING_SANDBOX` tool call via the `tool_call_id` FK on `sandbox_sessions` (direct lookup, no full table scan)
2. Fetches final events from control plane (`GET /sessions/{id}/events?limit=500`)
3. Extracts changed files and agent output from events
4. Completes the tool call with result payload
5. Resumes the agent asynchronously via Starlette `BackgroundTasks` (not `asyncio.create_task`)

**Tool call result (after webhook):**

```python
{
    "success": bool,
    "sandbox_session_id": str,
    "status": "completed" | "failed",
    "event_count": int,
    "changed_files": [{"path": str, "action": str}],
    "agent_output": str,        # Last 5000 chars of agent output
}
```

### 10.4 Agent Config Injection

Sandbox agents are configured via files in `druppie/sandbox-config/`:

- **`opencode-config.json`** — Sets `default_agent` to `druppie-builder` and grants broad tool permissions
- **`agents/druppie-builder.md`** — Coding agent prompt: implements features, writes code, mandatory git workflow (`git add <files>` → `git commit` → `git push origin HEAD`), must output a structured `---SUMMARY---` block
- **`agents/druppie-tester.md`** — Testing agent prompt: writes and runs tests, same mandatory git workflow, reports results in structured format

Configuration is injected into sandbox containers via the `OPENCODE_CONFIG_CONTENT` environment variable. `OPENCODE_DISABLE_PROJECT_CONFIG=true` prevents user `.opencode/` overrides inside the sandbox.

Agent parameter threading passes through 5 layers: MCP server → control plane router → session instance → bridge → OpenCode API.

### 10.5 Sandbox Session Ownership

The `sandbox_sessions` table (`druppie/db/models/sandbox_session.py`) maps control plane session IDs to Druppie user IDs:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `sandbox_session_id` | str (unique, indexed) | Control plane session ID |
| `session_id` | UUID (nullable, FK → sessions) | Druppie chat session |
| `user_id` | UUID (FK → users) | Owning user |
| `tool_call_id` | UUID (nullable, FK → tool_calls, indexed) | Linked tool call for direct webhook lookup |
| `webhook_secret` | str (nullable) | Per-session HMAC secret for webhook verification |
| `created_at` | datetime | Registration timestamp |
| `updated_at` | datetime | Last update timestamp |
| `completed_at` | datetime (nullable) | Completion timestamp |

**Registration flow:** After creating a sandbox session, the built-in tool calls `POST /api/sandbox-sessions/internal/register` (authenticated via internal API key, not user tokens). The repository's `create()` method is idempotent — it returns the existing record if the sandbox session ID is already registered.

**Tool call linkage:** The `tool_call_id` FK enables direct lookup from webhook handler → tool call without full table scans. This is set by `SandboxSessionRepository.update_tool_call_id()` after the tool executor stores the WAITING_SANDBOX status.

**Events proxy:** `GET /api/sandbox-sessions/{session_id}/events` (in `druppie/api/routes/sandbox.py`) proxies events from the control plane. Before forwarding, it:

1. Looks up ownership via `SandboxSessionRepository.get_by_sandbox_id()`
2. Calls `check_resource_ownership(user, mapping.user_id)` — returns **403** for non-owners
3. Admins bypass the ownership check

