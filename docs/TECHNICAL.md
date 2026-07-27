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
| MCP ArchiMate | Python / FastMCP | 9006 | ArchiMate model operations (list, read, search, export) |
| MCP Azure DevOps | Python / FastMCP | 9012 | Backlog / work items for a single Azure DevOps project (read + write with approval) |
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
      datasources.py     # Connected services (data sources, DevOps, Entra status)
      users.py           # User profile (avatar endpoint)
  services/
    session_service.py
    approval_service.py
    question_service.py
    project_service.py
    workflow_service.py
    deployment_service.py
    revert_service.py
    avatar_service.py    # Entra ID profile photo fetch + disk cache
    document_formatter_service.py
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
    # (params/ removed — tool schemas now live in each module's v1/tools.py)
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
    runtime.py           # Legacy agent facade (public API)
    runtime_v2.py        # Current agent facade using agent_runtime library
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
    entra_token.py       # Entra ID token exchange, claim validation, email allowlist
    gitea.py             # Gitea API client
    mcp_config.yaml      # MCP server URLs, approval rules, injection, entra_scope
    mcp_config.py        # Loader for mcp_config.yaml
    tool_registry.py     # Discovers tools via tools/list at startup; MCPHttp consolidated here
  mcp-servers/
    module-coding/       # Port 9001 — file/git ops
      MODULE.yaml
      server.py
      v1/tools.py        # @mcp.tool() definitions (single source of truth for schemas)
      v1/module.py
    module-deploy/       # Port 9002 — container lifecycle
    module-filesearch/   # Port 9004 — local file search
    module-web/          # Port 9005 — web browsing/search
    module-archimate/    # Port 9006 — ArchiMate model ops
    module-registry/     # Port 9007 — platform catalog/discovery
    module-azuredevops/  # Port 9012 — read-only Azure DevOps backlog (single project)
      MODULE.yaml
      server.py
      v1/tools.py        # 3 read-only @mcp.tool()s — no project picker
      v1/module.py       # backlog ops, hard-scoped to AZURE_DEVOPS_PROJECT
      v1/client.py       # async ADO REST client, service-principal auth
    module-kubernetes/   # Port 9013 — read-only Kubernetes cluster status
      MODULE.yaml
      server.py
      v1/tools.py        # 4 read-only @mcp.tool()s — list_pods, list_nodes, list_services, get_cluster_health
      v1/module.py       # K8s client, in-cluster or kubeconfig auth
```

### Azure DevOps backlog MCP (single-project isolation)

`module-azuredevops` (port 9012) gives agents access to the backlog / work items of
**exactly one** Azure DevOps project. It supports two authentication modes:

1. **User-scoped OBO tokens (preferred):** When the logged-in user has a linked Entra
   identity, the backend exchanges the Keycloak broker refresh token for an Azure
   DevOps-scoped access token (`499b84ac-1321-427f-aa17-267ca6975798/.default`). This
   token is injected as a hidden `user_token` parameter via `mcp_config.yaml` rules.
   Operations are performed as the actual user.
2. **Service principal fallback:** For non-Entra users, authentication falls back to
   `ClientSecretCredential` (resource scope `{scope_id}/.default`). Tokens are fetched
   on demand and never written to disk.

Configuration is via env vars: `AZURE_DEVOPS_ORG_URL`, `AZURE_DEVOPS_PROJECT`,
`AZURE_DEVOPS_TENANT_ID`, `AZURE_DEVOPS_CLIENT_ID`, `AZURE_DEVOPS_CLIENT_SECRET`
(the server fails fast at startup if any are missing).

Project isolation is enforced in two independent layers:

1. **Azure-side (the real boundary):** grant the service principal access to only the
   one project. Any other project returns 403 from Azure itself.
2. **Server-side allowlist:** every tool is hard-scoped to `AZURE_DEVOPS_PROJECT` — the
   project is put in the REST path and the WIQL `[System.TeamProject]` clause, is never a
   tool argument, and there is no `list_projects` tool. So the server cannot be steered
   at another project even if the credential were over-scoped.

Read tools: `list_backlog_items`, `get_work_item`, `search_work_items`,
`get_current_sprint`, `get_sprint_summary`, `get_work_item_comments` (all
`requires_approval: false`). Write tools: `create_work_item`, `update_work_item`,
`add_work_item_comment` (`requires_approval: true`, `required_role: session_owner`).
Consumed by the **Product Owner** agent. Isolation is pinned by
`druppie/tests/test_azuredevops_isolation.py`.

### 2.6 Document Formatter Service

PDF compilation from native **Typst** source files authored by agents. The Documenter agent writes `.typ` files using the Rijnland corporate identity template, pushes them to Gitea, and calls `builtin:make_pdf_document` to generate PDFs.

**Flow:** Agent writes `.typ` file → pushes to Gitea → calls `builtin:make_pdf_document` → `PdfRenderService.get_or_create_pdf()` fetches source from Gitea → checks render cache (`pdf_renders` table keyed by Git blob SHA) → cache hit returns instantly; cache miss compiles via `DocumentFormatterService.compile_typ()` → stores PDF → creates `MessageAttachment` record → user downloads via `/api/attachments/{id}`.

**Template library:** `druppie/templates/documents/rijnland.typ` — exposes a `rijnland_doc(body, ...)` function with parameters for document type (FO, TO, technical_research, core_documentation), title, status, TOC, watermark, section breaks, and author. Agents import it with `#import "/druppie/templates/documents/rijnland.typ": rijnland_doc`. `base.typ` remains as a backward-compat alias but the Markdown conversion pipeline is gone.

**Rijnland corporate identity applied by the template:**

- Primary color `#0065BD` (PMS 300)
- Secondary palette: sand/zand, dark-blue, mint, brick
- Typography: Neusa Next Pro (brand headings) with Lato as fallback. Body uses `weight: "light"`; headings use `weight: "bold"`.
- Logo: `Logo-hoogheemraadschap-rijnland.png` centered on title page at 12cm wide; not shown on content pages
- Pay-off: "droge voeten, schoon water" on title page
- Grid-based margins: 25mm sides, 32mm bottom
- Draft watermark: semi-transparent rotated text in **foreground** layer (`transparentize(50%)`) when `include_watermark == true && status != "FINAL"` — visible above all content including title page
- Table of contents: optional via `include_toc`
- Tables: Rijnland blue header row, striped rows, rounded corners
- Code blocks: light blue background (`#E9EFFA`), rounded corners
- Footer: Full-bleed dijk-en-sloot shape (`dijkEnSloot.png`) above a Rijnland-blue bar. Right-aligned text: "Hoogheemraadschap van Rijnland | project-name — versie month year | page / total". Excluded from title page.
- Diagram rendering: Mermaid diagrams are rendered inline by the `@preview/mmdr:0.2.2` Typst package (pure Typst, no Chromium/Node.js). ArchiMate diagrams export to SVG via the `archimate:save_model` MCP tool (`module-archimate/v1/svg_export.py`, pure Python) and are embedded via `#image()` in the Typst source.

**Font path resolution:** The Dockerfile installs Typst CLI and sets `TYPST_FONT_PATHS` to `/app/druppie/templates/documents/assets/fonts`. Custom TTF/OTF files are referenced by their internal family name (verify with `typst fonts --font-path <dir>`). The Google Fonts Lato files register as family **"Lato"** — weight is controlled via Typst's `weight` parameter. Neusa Next Pro files register as family **"Neusa Next Pro"**.

**Test fixtures:** `druppie/templates/documents/test-inputs/` contains FO and TO `.typ` source files for pytest.

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

### 6.1 Module Convention

Each MCP server follows the **module convention**: it lives under `druppie/mcp-servers/module-<name>/` and has a standard layout:

```
module-<name>/
  MODULE.yaml       # Module metadata (name, version, description)
  server.py         # FastMCP app + versioned router mounting (/v1, /v2, ...)
  requirements.txt
  Dockerfile
  v1/
    tools.py        # @mcp.tool() definitions — single source of truth for tool schemas
    module.py       # Business logic
```

`v1/tools.py` is where tool names, descriptions, parameters, and pre-validation (`meta.pre_validate`) are declared via `@mcp.tool()` decorators. `server.py` mounts versioned sub-routers so multiple API versions can coexist on one port.

### 6.2 Configuration

`druppie/core/mcp_config.yaml` defines:

- **Server URLs** (with environment variable substitution)
- **Approval requirements** per tool (which role can approve)
- **Parameter injection rules** (what context values get auto-injected)

Tool schemas are **not** stored here. At startup, `ToolRegistry` calls each server's `tools/list` endpoint to discover live schemas. This ensures there is one source of truth (the `@mcp.tool()` decorator) rather than two (config file + decorator).

### 6.3 Coding Server (port 9001)

File and git operations within workspace sandboxes.

| Tool | Approval | Description |
|------|----------|-------------|
| `read_file` | None | Read file from workspace |
| `write_file` | None (overridable per agent) | Write file to workspace |
| `batch_write_files` | None (overridable per agent) | Write multiple files at once |
| `list_dir` | None | List directory contents |
| `delete_file` | None | Delete file from workspace |
| `run_git` | None | Execute whitelisted git commands (add, commit, push, status, checkout, log, diff, branch). Destructive flags blocked. Returns raw output. |
| `create_pull_request` | None | Create PR on Gitea |
| `merge_pull_request` | Developer | Merge PR and delete branch |
| `execute_coding_task` | None | Execute coding task in isolated sandbox |
| `make_design` | None (overridable per agent) | Write design document (FD/TD) with Mermaid syntax validation; file is rejected if Mermaid contains errors |
| `revert_to_commit` | None (internal) | Hard reset + force push to a target commit |
| `close_pull_request` | None (internal) | Close a PR on Gitea without merging |

### 6.4 Docker Server (port 9002)

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

### 6.5 Web / Bestand-Zoeker Server (port 9005)

Web browsing and local file search within datasets.

| Tool | Approval | Description |
|------|----------|-------------|
| `search_files` | None | Text search in local files |
| `list_directory` | None | List files in dataset |
| `read_file` | None | Read file from dataset |
| `fetch_url` | None | Fetch content from URL |
| `search_web` | None | Web search |
| `get_page_info` | None | Get web page metadata |

### 6.6 File Search Server (port 9004)

Local file search capability over mounted dataset volumes.

### 6.7 ArchiMate Server (port 9006)

ArchiMate model operations. Two surfaces co-exist on one server:

- **Read-only WILMA reference model** mounted from `module-archimate/models/WILMA-exchange.xml` (Open Exchange XML).
- **Read-write per-project model** living in the session workspace at `docs/architecture.archimate` (also Open Exchange XML, committed to Gitea alongside `docs/technical-design.md`).

The `WORKSPACE_ROOT` volume is shared with `module-coding`, so the same on-disk file is visible to both MCPs — the architect mutates it through write tools here and commits it through `coding.run_git`.

Read tools (WILMA + project model):

| Tool | Approval | Description |
|------|----------|-------------|
| `list_models` / `get_statistics` / `list_elements` / `get_element` / `list_views` / `get_view` / `search_model` / `get_impact` | None | Query WILMA elements, relationships, views, and impact paths |
| `assess_layout` | None | Element/connection count + density recommendation for a view (used to decide when to recommend `request_full_relayout`) |

Write tools (per-project `docs/architecture.archimate`, **all ungated** — the architect builds the plate freely; the single human review point is the `coding:make_design` gate on `docs/technical-design.md` where the reviewer sees the markdown + embedded plate as one artifact):

| Tool | Description |
|------|-------------|
| `create_element` / `update_element` / `delete_element` | Element CRUD (delete cascades to dependent relationships and view nodes) |
| `create_relationship` / `update_relationship` / `delete_relationship` | Relationship CRUD with valid types (Composition, Aggregation, Serving, Realization, Flow, Triggering, Access, …) |
| `add_to_view` / `add_connection_to_view` / `remove_from_view` | View composition; `add_to_view` chooses a free position for new nodes while preserving existing x/y. Views themselves are created by the composite builders (`add_layered_view` / `add_cooperation_view`); there is no standalone view-CRUD tool. |
| `get_or_create_wilma_reference` | Idempotent import of a WILMA element into the project model with the original identifier preserved (read-only locally via a `wilma-source=true` property) |
| `save_model` | Persist buffered mutations to disk; also writes a per-view SVG to `docs/diagrams/<view-name>.svg` so the plates are visible directly in Gitea |
| `request_full_relayout` | Clears positions on a view so the frontend's elkjs runs a fresh layout; destructive of manual position tweaks, hence approval-gated |

Implementation:

- `v1/writer.py` — buffered ElementTree document model with mutation API and an ID-aware free-region heuristic for new node placement.
- `v1/write_tools.py` — FastMCP tool definitions on top of the writer, plus per-`session_id` `WriteSessionRegistry` that resolves the workspace path matching the `coding` MCP's convention.
- `v1/svg_export.py` — stdlib SVG renderer that mirrors the frontend renderer (layer colors, relationship markers); runs at save time, never blocks the save itself.
- Read-only `module.py` + read-only tools are unchanged from earlier WILMA work.

### 6.8 RAG Architecture (Distributed Vector Storage)

Vector storage for RAG lives in each app's own database, not in a
central module. Every app template ships with `pgvector/pgvector:pg16`
and an `app/rag.py` helper that provides `index_documents()` and
`search()` against the app's own Postgres. Embeddings are generated
via the stateless `module-llm` `embed` tool (called through the SDK).

This gives each app full data isolation — no shared database, no
cross-project access. The `rag-patterns` skill captures the per-layer
design decisions the Architect documents in a TD; platform defaults
are seeded into every project via §5 of the platform technical
standards.

### 6.9 Data Access Server (port 9010)

Adapter-based access to heterogeneous data sources (Azure SQL, Azure Data Lake) plus inline chart generation. Full reference: [`docs/MCP/data-access.md`](MCP/data-access.md).

| Tool | Approval | Description |
|------|----------|-------------|
| `list_sources` | None | List configured data sources |
| `test_connection` | None | Verify a source is reachable |
| `list_available_data` | None | List tables (SQL) or files (Data Lake) |
| `get_schema` | None | Column metadata for a table/file |
| `read_data` | None | Read rows (capped; goes into context) |
| `execute_query` | None | Free-form read-only SELECT/WITH (SQL only) |
| `download_data` | None | Stream a table/file to the workspace as CSV/Parquet |
| `create_chart` | None | Chart inline values (returns a `chart` spec) |
| `create_chart_from_source` | None | Read + aggregate a source server-side, return a `chart` spec |

**Charting data flow.** `create_chart_from_source` keeps raw data out of the LLM context: for SQL sources the `GROUP BY` is pushed into the database (`build_sql_aggregation_query`); for Data Lake files the whole file is read into MCP-server memory and aggregated in Python. Either way only a small JSON spec (the chart) is returned — no file is written, and the aggregation covers the full dataset (`full_dataset`/`rows_scanned` report any sampling). The spec is emitted as a ` ```chart ` fenced code block; the chat frontend renders it via `frontend/src/components/ChartBlock.jsx` (registered for the `chart` language in `ChatHelpers.jsx`, mirroring how `MermaidBlock` handles `mermaid`) using `recharts`. 13 chart types span XY, proportion, and multi-series families.

### 6.10 Declarative Parameter Injection

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

### 6.11 Layered Approval System

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
module-coding       FastMCP           :9001   File/git operations
module-deploy       FastMCP           :9002   Docker operations
module-filesearch   FastMCP           :9004   File search
module-web          FastMCP           :9005   Web browsing
module-archimate    FastMCP           :9006   ArchiMate models
module-registry     FastMCP           :9007   Platform catalog/discovery
adminer             Adminer           :8081   DB admin UI
sandbox-control-plane  Node.js        :8787   Sandbox session/event management
sandbox-manager     Node.js           :8000   Sandbox container lifecycle
sandbox-image-builder  Docker         -       Builds open-inspect-sandbox:latest image
```

### 7.2 Network

All containers share a single bridge network: `druppie-new-network`. Internal communication uses container hostnames (e.g., `druppie-db`, `keycloak`, `gitea`, `module-coding`).

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
| `sandbox_dep_cache` | `/cache` (sandbox containers) | Shared dependency cache for npm/pnpm/bun/pip/uv |
| Docker socket | `/var/run/docker.sock` | Allows backend and MCP Docker to manage containers |

### 7.4 Health Checks

Every service has a Docker health check. Services with dependencies use `condition: service_healthy` to enforce startup order:

```
druppie-db  <-- keycloak (via keycloak-db)
            <-- gitea (via gitea-db)
            <-- druppie-backend
                   <-- druppie-frontend
                   <-- module-coding (depends on gitea)
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

### 7.6 Sandbox Security Architecture

Sandbox containers are hardened with multiple isolation layers:

**Capability reduction:** All Linux capabilities are dropped (`--cap-drop=ALL`), then only 3 are re-added: `CHOWN` and `FOWNER` (shared cache file ownership), `NET_RAW` (health checks). Combined with `--security-opt=no-new-privileges` to block setuid/setgid escalation. See `docker_manager.py`.

**Non-root execution:** Sandboxes run as `sandbox:1000` (non-root user created in `Dockerfile.sandbox:83-84`).

**Network isolation:** Sandboxes join `druppie-sandbox-network`, an isolated bridge network. Only the control plane bridges both networks — sandboxes cannot reach the database, Keycloak, Gitea, or backend directly.

**Resource limits:** CPU, memory, and PID limits are configured via environment variables (`SANDBOX_MEMORY_LIMIT`, `SANDBOX_CPU_LIMIT`).

### 7.7 Shared Dependency Cache

A named Docker volume (`druppie_sandbox_dep_cache`) is mounted at `/cache` inside every sandbox container. Environment variables in `Dockerfile.sandbox` point each package manager to a subdirectory (`/cache/npm`, `/cache/pnpm`, `/cache/bun`, `/cache/uv`, `/cache/pip`).

**Supply-chain hardening:**
- Package manager configs (`.npmrc`, `.pnpmrc`, `pip.conf`) enforce HTTPS-only registries with `strict-ssl=true`
- `UV_INDEX_URL` is set to `https://pypi.org/simple/`
- npm lockfile enforcement: `package-lock=true`

**Cache scanner:** A `cache-scanner` service (`Dockerfile.cache-scanner`) runs the [OSV scanner](https://github.com/google/osv-scanner) (v2.3.3, SHA256-verified binary) against all cached packages. It discovers npm/pnpm `package.json` files and pip `METADATA`/`PKG-INFO` files, then runs a recursive vulnerability scan. Usage: `docker compose --profile scan-cache run --rm cache-scanner`.

**Emergency purge:** The `reset-cache` profile service stops all sandbox containers, removes the cache volume, and recreates it empty. Usage: `docker compose --profile reset-cache run --rm reset-cache`.

**Cache entry logging:** The sandbox entrypoint (`entrypoint.py`) diffs cache snapshots before and after execution, emitting structured `cache.new_entries` JSON log events per package manager.

### 7.8 Database Reset

Two reset options are available:

```bash
# Soft reset: drops application tables (projects, sessions, etc.), keeps users
docker compose --profile reset-db up

# Hard reset: wipes all volumes, restarts everything fresh
docker compose --profile reset-hard up
```

The soft reset is useful during development when you want to clear session/project data without re-running Keycloak/Gitea setup. The hard reset is a full wipe that requires re-initialization.

### 7.9 Profiles

| Profile | Purpose |
|---------|---------|
| `infra` | Infrastructure only (DBs, Keycloak, Gitea, MCP servers) |
| `dev` | Development mode with hot reload (backend via uvicorn --reload, frontend via Vite HMR) |
| `prod` | Production mode (static builds) |
| `init` | One-time Keycloak and Gitea setup (creates realm, users, OAuth apps) |
| `reset-db` | Soft reset: drops application tables, keeps users |
| `reset-hard` | Hard reset: wipes all volumes, reinitializes everything |
| `reset-cache` | Purge sandbox dependency cache (stops sandboxes, removes + recreates volume) |
| `scan-cache` | Scan cached dependencies for vulnerabilities (OSV scanner) |

### 7.10 Cross-Platform Support

The Docker Compose setup works on Windows, macOS, and Linux. Shell scripts use LF line endings (enforced via `.gitattributes`) and Dockerfiles include `sed` commands to strip any CRLF characters that may be introduced on Windows.

---

## 8. Agent System

### 8.1 Agent Definitions

Twelve agents are defined as YAML files in `druppie/agents/definitions/`:

| Agent | Role | Builtin Tools | MCP Access | Skills |
|-------|------|---------------|------------|--------|
| `router` | Classifies user intent, selects project | `set_intent` | None | — |
| `planner` | Creates execution plan (which agents to run) | `make_plan` | None | — |
| `business_analyst` | Gathers requirements from user | Default | `coding` (read_file, make_design, list_dir) | `making-mermaid-diagrams` |
| `architect` | Designs system architecture, writes specs | Default | `coding` (read_file, make_design, list_dir), `archimate` (read + write) | `making-mermaid-diagrams`, `making-archimate-diagrams` |
| `builder_planner` | Creates implementation plans, writes builder_plan.md | Default | `coding` | — |
| `test_builder` | Generates tests (TDD Red Phase) | Default | `coding` | — |
| `builder` | Implements code to pass tests (TDD Green Phase) | Default | `coding` | — |
| `test_executor` | Runs tests, iteratively fixes code | `test_report` | `coding` | — |
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
| `tool_only_communication` | Enforces that agents communicate only through tool calls |
| `summary_relay` | How to read previous agent summaries and format your own via `done()` |
| `done_tool_format` | Mandatory `done()` output format rules |
| `workspace_state` | Shared workspace and git branch rules |

Agents declare which system prompts to include via the `system_prompts` list in their YAML definition. At runtime, the agent's `_build_system_prompt()` method loads each system prompt and appends it (in order) after the agent's own `system_prompt` text, before tool instructions are added.

Agents without a `system_prompts` list (or with an empty list) receive no system prompts. Currently, 9 agents include all 4 system prompts: architect, builder, builder_planner, business_analyst, deployer, developer, planner, test_builder, and test_executor. The router, summarizer, and reviewer agents do not include system prompts.

### 8.3 Agent Runtime Architecture

The agent runtime is split into focused modules:

| Module | Class | Purpose |
|--------|-------|---------|
| `runtime.py` | `Agent` | Legacy facade — coordinates loader, prompt builder, and loop |
| `runtime_v2.py` | `AgentV2` | Current runtime facade — integrates with the `agent_runtime` library; maps pause reasons (including Entra auth) via `_infer_pause_reason()` |
| `loop.py` | `AgentLoop` | Core LLM ↔ tool-calling loop, skill tool enrichment |
| `definition_loader.py` | `AgentDefinitionLoader` | Loads YAML definitions and system prompts |
| `message_history.py` | `reconstruct_from_db()` | Rebuilds agent message history from DB for resume; handles orphaned `tool_use` blocks during Entra auth resume |
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
   f. If waiting_sandbox -> pause agent, return (webhook will resume)
   g. If "done" tool -> agent complete, return
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

`druppie/core/tool_registry.py` is the single source of truth for all tool definitions at runtime. It combines:
- **MCP tools** — discovered at startup by calling each server's `tools/list` endpoint (live schema, no duplication with config files)
- **Builtin tools** (done, make_plan, hitl_ask_question, etc.)

Each tool is represented by a `ToolDefinition` (`druppie/domain/tool.py`) which contains:
- Tool metadata (name, description, server)
- JSON schema for parameters (fetched from the module's `@mcp.tool()` decorator)
- Approval requirements (from `mcp_config.yaml`)

`druppie/tools/params/` (previously hand-maintained Pydantic models per tool) no longer exists. Schemas come exclusively from the modules.

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

**ContextVar DB sessions:** The tool executor uses a ContextVar-based DB session pattern (`self._active_db`) for database access during tool execution. Entra token retrieval and injection follow this pattern to ensure correct session scoping in async contexts.

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

**Decision-guide skills.** Agent intake steps contain pattern-detection trigger lines that instruct an agent to call `invoke_skill(...)` proactively when specific design signals match. For in-app LLM workflows the responsibility is split along the architect/builder_planner role boundary: the Architect's Step 1 intake (in `druppie/agents/definitions/architect.yaml`) invokes `llm-orchestration-in-apps` to decide the **WHAT** (workflow pattern and agency level via a strict hierarchy) without naming any framework — which respects the architect's own rule that it never names concrete libraries; capability placement is left to the architect's generic reuse decision framework rather than re-derived per skill. The Builder-Planner's intake (`builder_planner.yaml`, which now carries a `skills:` block) invokes `llm-orchestration-standard` to decide the **HOW** (the single platform standard: plain Python everywhere, with the single agent built as a small core-style tool-loop rather than an agent framework; access-pattern; code placement). Both skills share one platform-research document (`docs/LLM-orchestration/llm-orchestration-in-apps.md`) that leads with the standard and demotes the framework survey to an appendix. End-to-end verification runs via the seed tool test `testing/tools/architect-fd-llm-chain-pending.yaml`, which pauses on the FD-approval gate so an analyst can drive the loop manually from `/evaluations` + `/tasks`.

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
- `resume_after_entra_auth()`: Resumes an agent paused for Entra ID authorization. Uses `AgentV2` to continue the run after the frontend auto-submits the broker token exchange.

All methods reconstruct agent state from the database (LLM call history, tool call results) so the agent can continue where it left off.

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

### 8.10 Scheduled Jobs (Cron Pipeline)

The cron job pipeline lets administrators schedule recurring tasks via YAML definitions in `druppie/jobs/definitions/*.yaml`. Jobs are loaded into `job_definitions` on startup; execution instances are tracked in `job_runs`.

**Architecture:**

```
YAML files  →  JobService.load_definitions_from_yaml()  →  job_definitions (DB)
                                                   ↓
                                        JobScheduler._check_jobs()
                                                   ↓
                                              job_runs (DB)
                                                   ↓
                                        Orchestrator.execute_pending_runs()
```

**Components:**

| Layer | File | Responsibility |
|-------|------|---------------|
| API | `api/routes/jobs.py` | List, trigger, list runs |
| Service | `services/job_service.py` | Load YAML, trigger, schedule |
| Repository | `repositories/job_repository.py` | DB access + claim compare-and-swap |
| Domain | `domain/job.py` | Pydantic models |
| Models | `db/models/job.py` | `JobDefinition`, `JobRun` |

**Key design decisions:**

1. **No pagination on `JobDefinitionList`** — Job definitions are YAML-scoped configuration objects, not growing event history. A typical deployment has < 50 definitions. `JobRunList` *does* have pagination because runs accumulate indefinitely.

2. **Atomic claim via UPDATE-WHERE** — `JobRepository.claim_job_trigger()` uses an `UPDATE ... WHERE last_triggered_at < scheduled_time` so multiple backend instances can safely race for the same scheduled slot without duplicate runs.

3. **YAML validation at load time** — `JobService.load_definitions_from_yaml()` validates each file before DB insertion: required fields (`name`, `schedule`, `agent_id`, `prompt`), cron syntax (via `croniter`), and agent existence (via filesystem check). Invalid files are logged and skipped entirely; no broken definitions are recorded.

---

## 9. Kubernetes Deployment

### 9.1 Helm Chart

The Helm chart (`helm/druppie/`) deploys the full Druppie platform to Kubernetes. It translates every service from `docker-compose.yml` into native Kubernetes resources:

| Docker Compose Service | Kubernetes Resource |
|------------------------|---------------------|
| PostgreSQL databases (3) | StatefulSets with volumeClaimTemplates (5Gi each) |
| Keycloak, Gitea, Backend, Frontend | Deployments with readiness/liveness probes |
| MCP modules (8) | Deployments, individually toggleable via `values.yaml` |
| Init container | Helm post-install hook Job |
| Shared volumes | PersistentVolumeClaims (workspace 10Gi, dataset 5Gi, sandbox-bundles 5Gi, gitea-data 5Gi) |
| Bridge network | ClusterIP Services (15) + NetworkPolicies (5) |
| Port mappings | Ingress with path-based routing via nginx |

### 9.2 Template Helpers

`_helpers.tpl` provides reusable template functions: name/fullname generation, standard Kubernetes labels (app, chart, release), selector labels, image rendering (with `imagePullPolicy: IfNotPresent` for local images), and external URL construction from `global.domain` and `global.ingress.port`.

### 9.3 Ingress and Routing

Two Ingress resources handle all external traffic on a single domain:

**Main ingress** routes by path prefix:
- `/api` → backend (pass-through, backend expects `/api` prefix)
- `/realms`, `/resources`, `/admin`, `/js`, `/welcome` → Keycloak
- `/` → frontend (catch-all)

**Gitea ingress** uses a path rewrite annotation to strip `/git/` before forwarding to Gitea.

### 9.4 NetworkPolicies

Five policies control traffic:
- `app-net`: allows intra-namespace communication + ingress from `ingress-nginx` namespace + HTTPS egress (port 443) + DNS egress
- `sandbox-net`: sandbox pods accept ingress only from backend and module-coding
- `sandbox-inet`: sandbox pods can reach the internet but not private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- `sandbox-modules`: module-coding accepts ingress only from backend
- `sandbox-modules-docker`: module-deploy accepts ingress only from backend

### 9.5 Init System

A Helm post-install hook Job (`init-job.yaml`) runs `setup_keycloak.py` after Keycloak and Gitea are healthy. It creates the Druppie realm, OAuth clients, roles, and test users. The Job uses init containers that wait for Keycloak and Gitea readiness before running.

### 9.6 Kind Cluster Configs

Two Kind configurations are provided in `kind/`:

| File | Nodes | Port Mapping | Use Case |
|------|-------|--------------|----------|
| `cluster-dev.yaml` | 1 control-plane | 9080→80, 8443→443 | Local dev with ingress |
| `cluster.yaml` | 1 control-plane + 2 workers | 80, 443 + NodePorts 30000-30003 | Multi-node testing |

Both use pod subnet `10.244.0.0/16` and service subnet `10.96.0.0/12`.

### 9.7 Helper Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup-kind.sh` | Creates Kind cluster, installs nginx ingress, builds and loads all images |
| `scripts/build-and-load.sh` | Builds all Docker images and loads them into an existing Kind cluster |
| `scripts/port-forward.sh` | Sets up kubectl port-forward for direct service access (bypasses ingress) |

### 9.8 Secrets and ConfigMap

A single Secret holds all sensitive values (DB passwords, Keycloak admin creds, Gitea token, LLM API keys). A single ConfigMap holds all non-secret environment variables (service URLs, MCP module URLs, CORS origins, Vite build vars). Both are referenced by deployments via `envFrom`.

Secrets are stored as plaintext in `values.yaml` — intended for local dev only. Production deployments should use an external secrets manager (Vault, AWS Secrets Manager, etc.).

---

## 10. Configuration

### 10.1 Environment Variables

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
| `SANDBOX_MEMORY_LIMIT` | `12g` | Docker memory limit per sandbox container |
| `SANDBOX_CPU_LIMIT` | `4` | Docker CPU limit per sandbox container |

### 10.2 Configuration Files

| File | Purpose |
|------|---------|
| `druppie/core/mcp_config.yaml` | MCP server URLs, approval rules, parameter injection (tool schemas live in each module's `v1/tools.py`) |
| `druppie/agents/definitions/*.yaml` | Agent definitions (prompt, tools, model config) |
| `druppie/agents/definitions/system_prompts/*.yaml` | Composable system prompts (see Section 8.2) |
| `docker-compose.yml` | Infrastructure service definitions (at repository root) |
| `.env` | Environment variable overrides |
| `.env.example` | Documented template for environment variables |
| `druppie/sandbox-config/` | OpenCode config and agent prompts injected into sandboxes |

---

## 11. Sandbox Infrastructure (Open-Inspect)

> Full documentation: [docs/SANDBOX.md](SANDBOX.md) — covers architecture, OpenCode integration, provider resilience, Kata Containers, and security.

[Open-Inspect](https://github.com/nuno120/background-agents) (our fork, branch `druppie`) is integrated as a git submodule at `background-agents/`. Sandbox containers run OpenCode `v1.2.22` (pinned in `Dockerfile.sandbox`). They provide isolated Docker sandboxes where coding agents can clone a project, write code, run tests, commit, and push — all without touching the shared workspace.

### 11.1 Services

| Service | Port | Role |
|---------|------|------|
| `sandbox-control-plane` | 8787 | Session/event management, SQLite storage, coordinates lifecycle |
| `sandbox-manager` | 8000 | Creates/manages sandbox containers, enforces resource limits |
| `sandbox-image-builder` | — | One-shot build producing `open-inspect-sandbox:latest` |

### 11.2 `execute_coding_task` Built-in Tool

Defined in `druppie/agents/builtin_tools.py`. Delegates a coding task to a sandbox using a **webhook + pause/resume** pattern:

1. Creates sandbox session on control plane
2. Sends task prompt with `callbackUrl` and `callbackSecret`
3. Registers ownership in `sandbox_sessions` table
4. Returns `WAITING_SANDBOX` — agent pauses, thread freed
5. On completion, control plane POSTs webhook → handler fetches events, completes tool call, resumes agent

**Auth:** HMAC-SHA256 tokens (`{unix_ms_timestamp}.{hmac_sha256_hex_signature}`), verified by Open-Inspect's `verifyInternalToken`.

### 11.3 Status Model

| Level | Status | Meaning |
|-------|--------|---------|
| ToolCallStatus | `WAITING_SANDBOX` | Tool dispatched, waiting for webhook |
| AgentRunStatus | `PAUSED_SANDBOX` | Agent paused while sandbox runs |
| AgentRunStatus | `PAUSED_CRASHED` | Agent crashed, session paused for recovery |
| SessionStatus | `paused_sandbox` | Visible in UI as paused |
| SessionStatus | `paused_crashed` | Visible in UI as crashed |

### 11.4 Sandbox Session Ownership

The `sandbox_sessions` table maps control plane session IDs to Druppie users:

| Column | Type | Description |
|--------|------|-------------|
| `sandbox_session_id` | str (unique, indexed) | Control plane session ID |
| `session_id` | UUID (nullable, FK → sessions) | Druppie chat session |
| `user_id` | UUID (FK → users) | Owning user |
| `tool_call_id` | UUID (nullable, FK → tool_calls, indexed) | Direct webhook lookup |
| `webhook_secret` | str (nullable) | Per-session HMAC secret |

The `tool_call_id` FK enables direct lookup from webhook → tool call without table scans. Events proxy (`GET /api/sandbox-sessions/{id}/events`) enforces ownership — non-owners get 403, admins bypass.

---

## 11. Agent Runtime Library (`druppie/agent_runtime/`)

### 11.1 Design Principle

The `agent_runtime` package is a **storage-agnostic, self-contained agent execution library** with zero coupling to `druppie.db`, `druppie.domain`, or `druppie.repositories`. It defines its own types (dataclasses, not Pydantic), its own event system, and its own tool routing. The only external dependencies are stdlib and PyYAML.

This library can execute an LLM agent loop with MCP tool calling, event emission, subagent spawning, and sandbox management without touching any database or web framework.

### 11.2 Dependencies

| Dependency | Purpose |
|------------|---------|
| Python stdlib | Core types, async IO, dataclasses |
| PyYAML | Agent definition parsing |

No Pydantic, no SQLAlchemy, no FastAPI, no LiteLLM. All domain types use `@dataclass` for zero-framework overhead.

### 11.3 Layer Architecture (Bottom-Up)

The package is organized in strict dependency layers. Higher layers import from lower layers, never the reverse.

```
Layer 0: types.py          Core types (dataclasses)
Layer 1: definition.py     YAML parsing + schema generation
Layer 2: events.py         EventEmitter (callback-based)
Layer 3: compaction.py     Context estimation + LLM-summarized compaction
Layer 4: tools/mcp.py      MCPConnection type
Layer 5: tools/done.py     DoneTool with dynamic schema + validation
Layer 6: tools/provider.py ToolProvider protocol + MCPToolProvider
Layer 7: loop.py           AgentLoop main execution loop
Layer 8: subagents.py      Parallel subagent spawning
Layer 9: compat.py         Bridge from old Druppie backend to the runtime
```

#### Layer 0: `types.py` — Core Types

Defines the foundational data structures used by all higher layers:

| Type | Purpose |
|------|---------|
| `AgentEvent` | Lifecycle event emitted during execution (agent_start, agent_end, tool_call, tool_result, etc.) |
| `AgentResult` | Final result returned by `AgentLoop.run()` — contains output, status, and metadata |
| `LoopConfig` | Configuration for the agent loop (max iterations, timeouts, temperature, etc.) |
| `CancellationToken` | Cooperative cancellation check (polled between iterations) |
| `DoneResult` | Structured result from the `done` tool (summary, status, preconditions) |
| `RequiredToolCall` | Specifies a tool that must be called before the agent can finish |
| `CompletionPrecondition` | A condition that must be satisfied for the agent to complete |
| `CompletionSummaryRequirement` | Defines what the summary must contain |
| `AgentLoopError` | Base exception for loop errors |
| `AgentCancelledError` | Raised when the cancellation token is triggered |

#### Layer 1: `definition.py` — Agent Definition Parsing

Parses YAML agent definition files into structured types. Also provides `build_done_schema()` which dynamically generates the JSON schema for the `done` tool based on the agent's declared summary requirements and preconditions.

#### Layer 2: `events.py` — EventEmitter

Callback-based event system. Consumers register handlers for named events. The loop emits events at key lifecycle points:

| Event | When |
|-------|------|
| `agent_start` | Loop begins execution |
| `agent_end` | Loop completes (success or failure) |
| `tool_call` | A tool invocation starts |
| `tool_result` | A tool invocation completes |
| `subagent_start` | A subagent is spawned |
| `subagent_end` | A subagent completes |
| `context_compressed` | Conversation body summarized to relieve context pressure |
| `context_overflow` | Context window exceeds limits |

#### Layer 3: `compaction.py` — Message Compaction

Manages context pressure with a calibrated token estimator and an LLM-based summarizer. `MessageCompactor.estimate_tokens()` approximates token usage from message chars (calibrated against real `prompt_tokens` from each LLM response). When usage crosses `CompactionConfig.summarization_threshold`, `compress()` summarizes the conversation body via the LLM and replaces it with a single summary message, keeping the system + user header intact (falling back to a static notice if summarization fails). `truncate_tool_result()` caps oversized tool outputs.

#### Layer 4: `tools/mcp.py` — MCP Connection

Defines the `MCPConnection` type representing a connection to a single MCP server (URL, headers, metadata). Used by `MCPToolProvider` to route tool calls.

#### Layer 5: `tools/done.py` — Done Tool

Implements the `DoneTool` with a **dynamically generated schema** derived from the agent definition. Validation follows a three-stage pipeline:

1. **Schema validation** — arguments must conform to the generated JSON schema
2. **Summary status check** — the `summary_status` field must match allowed values
3. **Preconditions check** — all declared `CompletionPrecondition` items must be satisfied

Agents cannot finish until all preconditions are met and a valid summary is provided.

#### Layer 6: `tools/provider.py` — Tool Provider

Defines the `ToolProvider` protocol (abstract interface) and `MCPToolProvider` implementation:

```
ToolProvider (protocol)
  |-- list_tools()        -> list of available tools
  |-- call_tool(name, args) -> tool result
  |-- get_tool_schema(name) -> JSON schema

MCPToolProvider (implementation)
  |-- Routes calls to MCPConnection per server
  |-- One MCPConnection per configured MCP server
```

The protocol allows alternative tool backends (e.g., builtins, mocks) without modifying the loop.

#### Layer 7: `loop.py` — AgentLoop

The main execution loop. Orchestrates the full agent lifecycle:

```
AgentLoop.run(llm, tool_provider, definition, events, cancellation_token)
  |
  |-- 1. Build messages from definition (system prompt + user prompt)
  |-- 2. Call LLM with messages + tool schemas
  |-- 3. Parse response for tool calls
  |-- 4. Route each tool call through ToolProvider
  |-- 5. If "done" tool -> validate + return AgentResult
  |-- 6. If context overflow -> truncate and retry
  |-- 7. If cancellation triggered -> raise AgentCancelledError
  |-- 8. If pause detected -> yield control
  |-- 9. Otherwise -> append results, loop to step 2
```

Key responsibilities:

- **LLM interface**: The `llm` parameter is an async callable compatible with litellm's `acompletion` signature. The library does not import litellm — it receives the callable from the caller.
- **Tool routing**: All tool calls go through the `ToolProvider` protocol.
- **Context overflow**: Detects when the message history exceeds the model's context window and truncates older messages.
- **Done enforcement**: The `done` tool is always available. Agents must call it to finish.
- **Pause detection**: Checks the cancellation token between iterations for cooperative stopping.

#### Layer 8: `subagents.py` — Subagent Management

`SubagentsMCP` provides parallel subagent spawning with safety guardrails:

| Feature | Behavior |
|---------|----------|
| Parallel spawning | Multiple subagents run concurrently via `asyncio` |
| Depth limits | Maximum nesting depth prevents infinite recursion |
| Circular detection | Tracks active agent IDs to prevent re-entrant cycles |
| Sandbox sharing | Subagents inherit the parent's sandbox context |

#### Layer 9: `compat.py` — Backend Compatibility Bridge

Bridges the storage-agnostic runtime to the existing Druppie backend without modifying either. Provides `adapt_llm()` (wraps the old `BaseLLM` as the runtime's async LLM callable), `DruppieToolProvider` (implements the `ToolProvider` protocol over the old `ToolExecutor`/builtin tools, persisting every call to the DB via short-lived sessions), `create_event_persister()` (an event callback that maps runtime `AgentEvent`s to DB writes for runs, LLM calls, tool calls, and compaction events), `SubagentsMCPConnection` (in-process MCP wrapper around `SubagentsMCP`), and `old_definition_to_new()` (converts the old Pydantic `AgentDefinition` to the new dataclass). Also bridges the `waiting_entra_auth` pause status from the `ToolExecutor` to the new runtime's pause/resume mechanism.

### 11.4 Data Flow

```
AgentDefinition (YAML)
  |
  v
AgentLoop.run(llm, tool_provider, ...)
  |
  |-- LLM call (async callable)
  |     |
  |     v
  |   Tool calls (parsed from LLM response)
  |     |
  |     v
  |   ToolProvider.call_tool(name, args)
  |     |
  |     v
  |   MCPToolProvider -> MCPConnection -> MCP server (HTTP)
  |
  |-- EventEmitter callbacks (lifecycle events)
  |
  v
AgentResult (output, status, metadata)
```

### 11.5 LLM Interface

The library accepts an **async callable** as its LLM interface, compatible with litellm's `acompletion`:

```python
async def llm(messages: list, tools: list, **kwargs) -> LLMResponse:
    ...
```

The library never imports litellm directly. The caller (typically the druppie backend) wraps litellm or any compatible provider and passes the callable. This keeps the library provider-agnostic.

### 11.6 Tool Routing

```
AgentLoop
  |
  v
ToolProvider (protocol)
  |
  v
MCPToolProvider
  |
  +-- MCPConnection (server A)  ->  HTTP POST to MCP server A
  +-- MCPConnection (server B)  ->  HTTP POST to MCP server B
  +-- ...
```

Each MCP server has its own `MCPConnection`. The provider maps tool names to their originating server and routes calls accordingly.

### 11.7 Coexistence with Existing Agent System

The `agent_runtime` library is **completely separate** from the existing agent system in `druppie/agents/` and `druppie/execution/`:

| Aspect | Existing (`druppie/agents/` + `druppie/execution/`) | Library (`druppie/agent_runtime/`) |
|--------|------------------------------------------------------|-------------------------------------|
| Types | Pydantic models (`druppie/domain/`) | Dataclasses (self-contained) |
| Storage | Direct DB access via repositories | Storage-agnostic, no DB dependency |
| Tool routing | `ToolExecutor` + `ToolRegistry` | `ToolProvider` protocol |
| Event system | None (DB writes for status) | `EventEmitter` callbacks |
| LLM calls | `LLMService` singleton | Async callable injection |
| Agent definitions | `AgentDefinitionLoader` (YAML + DB) | `definition.py` (YAML only) |

Zero modifications are required to existing code when using the library. Both systems can coexist in the same process.

### 11.8 Test Suite

179 tests in `druppie/tests/agent_runtime/` with a shared `conftest.py` providing:

| Fixture | Purpose |
|---------|---------|
| `MockLLM` | Simulates LLM responses (configurable per-call) |
| `mock_mcp_connection` | Simulates MCP server connections with canned responses |

Tests cover all layers: type construction, YAML parsing, event emission, tool routing, loop iteration, done enforcement, subagent spawning, and sandbox pool management.

---

## 12. Translation Service

The platform provides automatic translation so agents always work in English while users interact in their own language.

### 12.1 Architecture

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `TranslationService` | `druppie/core/translation.py` | Singleton; calls DeepInfra's Qwen/Qwen3-32B for all translations |
| `LanguageDetector` | `druppie/core/language_detection.py` | Hybrid detection: keyword heuristics + `langdetect` library |
| `HumanInput` | `druppie/execution/human_input.py` | Wraps user text with detected language metadata |

The translation service is separate from the main LLM provider — it always uses DeepInfra regardless of `LLM_PROVIDER`. This requires `DEEPINFRA_API_KEY` to be set. If the key is missing, `TranslationNotAvailableError` is raised on first use (not silently swallowed).

### 12.2 Data Flow

```
User (Dutch) → Orchestrator → [detect language] → [translate to English] → Router/Planner/Agent
                                                                                    │
Agent (English) ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
    │
    ├─► HITL question → [translate question + choices to Dutch] → User
    ├─► make_design   → [translate content] → Dutch file alongside English original
    └─► done (summary) → [translate to Dutch] → Chat timeline
```

### 12.3 Integration Points

| Point | File | What happens |
|-------|------|--------------|
| User message | `orchestrator.py` ~line 189 | Detect language, translate to English |
| HITL answer | `orchestrator.py` ~line 748 | Translate answer to English (session language unchanged) |
| HITL question | `tool_executor.py` ~line 877 | Translate question + choices to user's language |
| Design document | `tool_executor.py` ~line 723 | Translate content, inject `translated_content`/`translated_path` |
| MCP write | `tool_executor.py` ~line 1040 | Write Dutch file via second MCP `write_file` call |
| Summarizer message | `builtin_tools.py` ~line 731 | Translate to session language before storing |
| Agent prompt | `prompt_builder.py` ~line 82 | Inject English-only instruction block |

### 12.3.1 HITL Answer Field Naming

The tool call result for answered HITL questions stores two versions of the answer:

| Field | Content | Consumed by |
|-------|---------|-------------|
| `user_answer` | Original answer in the user's language (what they typed) | Frontend display |
| `answer_english` | Translated to English (for the agent) | Agent via `message_history.py` |

`message_history.py` strips `user_answer` before reconstructing tool results for agent context, so agents only see the English version.

### 12.3.2 HITL Question Bilingual Storage

HITL questions store both the translated (display) and original (English) versions:

| Column | Content | Where shown |
|--------|---------|-------------|
| `Question.question` | Translated to user's language | Chat timeline, HITL UI |
| `Question.question_english` | Original English from agent | Debug/inspect panel, session API |
| `Question.choices` | Translated choices | Chat timeline |
| `Question.choices_english` | Original English choices | Debug/inspect panel |

The debug panel (`DebugEventLog.jsx`) shows an "Original (English)" section on HITL tool calls when `question_english` is present, making it easy to compare what the agent generated vs what the user saw.

### 12.4 Design Document Translation Paths

| English path | Dutch path |
|--------------|------------|
| `docs/functional-design.md` | `docs/functioneel-ontwerp.md` |
| `docs/technical-design.md` | `docs/technisch-ontwerp.md` |
| `docs/technical-research.md` | `docs/technisch-onderzoek.md` |

### 12.5 Session Language

Stored in `sessions.language` (VARCHAR(10), nullable). Set on the first user message and locked — HITL answers do not update it, preventing a Dutch user's English-sounding answer from flipping the session language.

### 12.6 Error Handling

- `TranslationNotAvailableError` (missing API key) propagates — the session fails with a clear error message.
- Transient translation errors (API timeouts, empty responses) fall back to the original English text with a logged warning.
- Startup validation logs a warning when `DEEPINFRA_API_KEY` is not set.
- Test framework pre-flight check: `runner.py` logs a warning before executing agent tests when `DEEPINFRA_API_KEY` is missing, and wraps `TranslationNotAvailableError` with a clear "set it in .env" message in test results.

---

## 13. In-cluster LLM Benchmark Sweep

The benchmark sweep (`benchmarks/k8s/benchmark-all-models.sh`) benchmarks every
candidate LLM in the `ka-k8s-ai` cluster and publishes the results. Operator
runbook: [benchmarks/README.md](../benchmarks/README.md#in-cluster-automated-sweep).
This section describes the artifact/data flow.

### 13.1 Data flow

```
candidates.yaml                (control surface: fit class + per-model serving profile)
      │
      ▼
benchmark-all-models.sh         (per model: benchmark-if-fits vs skip-with-reason;
      │                          served-in-place vs free-a-GPU + temp bench isvc)
      ▼
per-model job.yaml Job          (llm-benchmark-<slug>; runs benchmarks.runner once,
      │                          emits report.txt + results.json between ===MARKERS===)
      ▼
pod-log marker scrape           (===REPORT_TXT_START/END=== -> results-incluster/<slug>/report.txt
      │                          ===RESULTS_JSON_START/END=== -> temp WORKDIR/results-<slug>.json)
      ▼
compare_models.py  +  update_test_matrix.py     (both import report_metrics.py — the shared parser)
      │                          │
      ▼                          ▼
COMPARISON-MATRIX.md      MODEL-TEST-MATRIX.md   (in benchmarks/results-incluster/)
      │
      ▼
publish_to_aigit.py             (stable per-slug paths -> branch benchmarks/auto-results -> PR into colab-dev)
```

### 13.2 Components

- **`candidates.yaml`** — canonical candidate list. Drives the fit-class size-skip
  and supplies per-model serving `profile:` blocks (vLLM args/image overrides).
- **`benchmark-all-models.sh`** — discovers `models.inference.llmkube.dev` CRDs,
  benchmarks each (in place if served, else on a GPU freed by scaling
  `FREE_SERVICE` 1→0 with Flux suspended), and orchestrates the matrix + publish
  steps. Never edits a tracked file — it generates per-model TEMP configs/manifests
  in a `mktemp` WORKDIR and applies `job.yaml` with a unique per-model name.
- **`job.yaml`** — the benchmark Job. Runs `benchmarks.runner` once, tees the
  console report to `/results/report.txt`, and prints both the report and the
  results JSON between marker lines so the orchestrator can scrape them out of the
  pod logs.
- **`report_metrics.py`** — the **shared, stdlib-only `report.txt` parser** imported
  by both `compare_models.py` and `update_test_matrix.py`, so the two matrices can
  never drift. It parses the headline metrics (median TTFT, median decode tok/s,
  latency-500, context-64k TTFT, tool 10-3 delta, stress stddev, error count).
- **`compare_models.py`** → `COMPARISON-MATRIX.md` (headline per-model metrics).
  **`update_test_matrix.py`** → `MODEL-TEST-MATRIX.md` (candidate status:
  Tested / To-test / Skipped). Both read `results-incluster/<slug>/` for `report.txt`
  and `SKIPPED.txt`.
- **`publish_to_aigit.py`** — walks the staged results dir and PUTs each file to a
  stable path under `benchmarks/results-incluster/` on branch
  `benchmarks/auto-results` (private-CA aigit, `verify=False`), then opens/updates
  a PR into `colab-dev`.

### 13.3 Source of truth

The per-run result **JSONs are transient**: they live only in the sweep's temp
WORKDIR and are discarded with it on exit. The committed **`report.txt`** (one per
model, under `results-incluster/<slug>/`) is the reproducible source of truth —
re-running `compare_models.py` / `update_test_matrix.py` against the committed
`report.txt` files deterministically reproduces both matrices. No `.json`/`.csv`
is written into `results-incluster/`.

