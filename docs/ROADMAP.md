# Druppie Project Status and Roadmap

This document categorizes every feature into three tiers based on actual code analysis:
**(A) Works Today**, **(B) Implemented but Not Working/Incomplete**, and **(C) Future Improvements**.

Last verified: 2026-02-01, branch `refactor/clean-architecture`.

---

## A. What Works Today (Verified)

These features have complete, functioning code paths from frontend to backend.

### A1. Core Chat Pipeline (create_project intent)

The primary happy path works end-to-end:

1. User sends a message via `POST /api/chat`.
2. **Router agent** classifies intent as `create_project`, calls `set_intent()` which creates a Project record and a Gitea repository.
3. **Planner agent** calls `make_plan()` to create pending agent runs depending on system prompt
4. Agents execute in sequence, each calling `done()` which auto-accumulates summaries and relays them to the next agent.
5. Session transitions through `ACTIVE -> PAUSED_HITL / PAUSED_TOOL -> ACTIVE -> COMPLETED`.

**Files:** `druppie/execution/orchestrator.py`, `druppie/agents/runtime.py`, `druppie/agents/builtin_tools.py`, `druppie/api/routes/chat.py`.

### A2. Agent Definitions (7 of 9 actually used)

The following agents are referenced by the planner and execute in production workflows:

| Agent | File | Used in Plans |
|-------|------|---------------|
| `router` | `agents/definitions/router.yaml` | Always (seq 0) |
| `planner` | `agents/definitions/planner.yaml` | Always (seq 1) |
| `business_analyst` | `agents/definitions/business_analyst.yaml` | create_project, update_project |
| `architect` | `agents/definitions/architect.yaml` | create_project, update_project |
| `developer` | `agents/definitions/developer.yaml` | create_project, update_project |
| `deployer` | `agents/definitions/deployer.yaml` | create_project, update_project |
| `summarizer` | `agents/definitions/summarizer.yaml` | create_project, update_project |

### A3. LLM Providers

Three providers exist:

| Provider | File | Status | Native Tool Calling |
|----------|------|--------|---------------------|
| **Z.AI (zai)** | `druppie/llm/zai.py` | Working, currently active (`LLM_PROVIDER=zai` in `.env`) | No (uses XML `<tool_call>` parsing) |
| **DeepInfra** | `druppie/llm/deepinfra.py` | Working (API key commented out in `.env`) | Yes (`supports_native_tools = True`) |
| **Mock** | `druppie/llm/mock.py` | Working, for testing only | N/A |

Provider selection is via environment variable `LLM_PROVIDER` (values: `zai`, `deepinfra`, `mock`, `auto`). Auto mode prefers DeepInfra if a key is present, then Z.AI.

**File:** `druppie/llm/service.py` (singleton `LLMService`, global `get_llm_service()`).

### A4. Tool Approval System

The approval workflow functions end-to-end:

1. Agent calls an MCP tool (e.g., `docker:build`).
2. `ToolExecutor` checks `mcp_config.yaml` for approval requirements.
3. If approval is required, a `ToolApproval` record is created with status `WAITING_APPROVAL`, and the agent pauses (`PAUSED_TOOL`).
4. Frontend polls `GET /api/approvals` to show pending approvals filtered by user role.
5. User calls `POST /api/approvals/{id}/approve` or `/reject`.
6. Background task resumes via `Orchestrator.resume_after_approval()` which executes the tool and continues the agent.

Per-agent approval overrides work: `architect.yaml` and `business_analyst.yaml` define `approval_overrides` that require role-specific approval for `coding:write_file`.

**Files:** `druppie/execution/tool_executor.py`, `druppie/api/routes/approvals.py`, `druppie/core/mcp_config.yaml`.

### A5. HITL (Human-in-the-Loop) Questions

The question/answer workflow functions end-to-end:

1. Agent calls `hitl_ask_question` or `hitl_ask_multiple_choice_question`.
2. `ToolExecutor` creates a `Question` record in the database, agent pauses (`PAUSED_HITL`).
3. Frontend shows the question in the session timeline (via `GET /api/sessions/{id}`).
4. User submits answer via `POST /api/questions/{id}/answer`.
5. Background task resumes via `Orchestrator.resume_after_answer()`.

**Files:** `druppie/execution/tool_executor.py`, `druppie/api/routes/questions.py`.

### A6. MCP Microservices

Two MCP servers run as separate Docker containers:

| Service | Port | File | Key Tools |
|---------|------|------|-----------|
| **mcp-coding** | 9001 | `druppie/mcp-servers/coding/server.py` | `read_file`, `write_file`, `batch_write_files`, `commit_and_push`, `create_branch`, `create_pull_request`, `merge_pull_request`, `get_git_status`, `list_dir`, `delete_file` |
| **mcp-docker** | 9002 | `druppie/mcp-servers/docker/server.py` | `build`, `run`, `stop`, `logs`, `list_containers`, `inspect` |

Communication is via HTTP (`MCPHttp` class in `druppie/execution/mcp_http.py`). Tool configuration is in `druppie/core/mcp_config.yaml`.

Note: `run_tests` and `run_command` were removed from the coding MCP server (commit `c8efb66`).

### A7. Keycloak Authentication

Fully integrated:
- Backend validates JWT tokens from Keycloak.
- Frontend uses `keycloak-js` for login/logout (`frontend/src/services/keycloak.js`).
- Role-based access control: `admin`, `architect`, `developer` roles.
- Protected routes in frontend enforce authentication.
- Test users: `admin/Admin123!`, `architect/Architect123!`, `seniordev/Developer123!`.

### A8. Gitea Integration

Project creation automatically:
1. Creates a Gitea user (matching Keycloak username).
2. Creates a repository under that user.
3. Stores `repo_name`, `repo_url`, `repo_owner` on the Project record.

The coding MCP server clones from Gitea, writes files, and pushes back.

**File:** `druppie/core/gitea.py`, called from `druppie/agents/builtin_tools.py` (`set_intent` function).

### A9. Frontend Pages (Working)

| Route | Page | Status |
|-------|------|--------|
| `/` | Dashboard | Working -- shows service health, LLM provider info |
| `/chat` | Chat | Working -- primary chat interface |
| `/tasks` | Tasks | Working -- approvals view with pending questions and approvals |
| `/projects` | Projects | Working -- project grid with file browser |
| `/projects/:projectId` | ProjectDetail | Working -- tabbed project view |
| `/settings` | Settings | Working -- shows LLM provider, environment info |

**Debug pages** (accessible via Debug dropdown in nav):

| Route | Page | Status |
|-------|------|--------|
| `/debug-chat` | DebugChat | Working -- raw API debug interface for chat, shows JSON responses |
| `/debug-approvals` | DebugApprovals | Working -- raw API debug interface for approvals |
| `/debug-projects` | DebugProjects | Working -- raw API debug interface for projects and deployments |
| `/debug-mcp` | DebugMCP | Working -- raw API debug interface for MCP servers and tools |

### A10. API Routes

All registered routes in `druppie/api/main.py`:

| Prefix | Router File | Purpose |
|--------|-------------|---------|
| `/api/chat` | `routes/chat.py` | Process messages |
| `/api/sessions` | `routes/sessions.py` | Session list/detail |
| `/api/approvals` | `routes/approvals.py` | Approve/reject tools |
| `/api/questions` | `routes/questions.py` | Answer HITL questions |
| `/api/projects` | `routes/projects.py` | Project CRUD |

Working on;
| `/api/deployments` | `routes/deployments.py` | Deployment status |
| `/api/workspace` | `routes/workspace.py` | Workspace operations |
| `/api/agents` | `routes/agents.py` | Agent definitions |
| `/api/mcps` | `routes/mcps.py` | MCP server info |
| `/api/mcp` | `routes/mcp_bridge.py` | MCP tool proxy |

### A11. Docker Compose (Full Stack)

`druppie/docker-compose.yml` defines the complete stack:
- `druppie-db` (PostgreSQL 15)
- `keycloak-db` + `keycloak` (Keycloak 24.0)
- `gitea-db` + `gitea` (Gitea 1.21)
- `druppie-backend` (FastAPI)
- `mcp-coding` (port 9001)
- `mcp-docker` (port 9002)
- `adminer` (DB admin, port 8081)
- `druppie-frontend` (Vite/React)

### A12. Summary Relay System

The `done()` builtin tool implements accumulated summaries:
- Each agent's `done(summary=...)` call auto-collects summaries from all previously completed agents.
- The accumulated summary is prepended to the next pending agent's `planned_prompt`.
- This means each agent gets full context of what previous agents accomplished (URLs, branch names, container names). 

**File:** `druppie/agents/builtin_tools.py`, `done()` function.

---

## B. Implemented but Not Working / Incomplete

These features have code that exists but does not function correctly or is disconnected.

### B1. Per-Agent Model Selection (Defined but Ignored)

**What exists:** Every YAML definition has a `model` field (e.g., `model: glm-4`) and `temperature`/`max_tokens` fields.

**What actually happens:** The runtime (`runtime.py` line 158) calls `get_llm_service().get_llm()` which returns a **global singleton** LLM instance. The `model` field from the YAML is never passed to the LLM service. All agents use the same model configured via environment variables (`ZAI_MODEL=GLM-4.7` or `DEEPINFRA_MODEL`).

The `temperature` from YAML is also ignored -- the LLM is initialized once with its default temperature.

Only `max_tokens` from YAML is partially used: it is passed to `self.llm.achat(messages, openai_tools, max_tokens=self.definition.max_tokens)` at line 539, so per-agent `max_tokens` works, but per-agent `model` and `temperature` do not.

**Why it does not work:** `LLMService` is a singleton (`_llm_service` global in `llm/service.py`). It creates one LLM instance and reuses it for all agents. To support per-agent models, the service would need to create different LLM instances per model name, or the `Agent` class would need to instantiate its own LLM.

**Files:** `druppie/agents/runtime.py` (line 158), `druppie/llm/service.py` (singleton pattern).

### B2. Reviewer Agent (Defined but Never Used)

**What exists:** `agents/definitions/reviewer.yaml` -- a code review agent that reads files and writes `REVIEW.md`.

**Why it does not work:** The planner's system prompt (`planner.yaml` lines 23-29) lists only five available agents: `business_analyst`, `architect`, `developer`, `deployer`, `summarizer`. The `reviewer` is not in this list, so the planner will never include it in a plan. Additionally, the `make_plan` tool description (in `builtin_tools.py` line 160) explicitly documents `agent_id` as `"The agent to run (architect, developer, deployer)"`.

The reviewer could be loaded by the runtime if someone manually created an agent run with `agent_id="reviewer"`, but no automated path triggers it.

### B3. Tester Agent (Defined but Broken)

**What exists:** `agents/definitions/tester.yaml` -- a test runner agent that uses `coding:run_tests`.

**Why it does not work:** Two issues:
1. Like `reviewer`, the planner does not know about `tester` -- it is not listed in available agents.
2. The `run_tests` tool was **removed** from the coding MCP server (commit `c8efb66`). The YAML still references `run_tests` in its `mcps.coding` list, but the tool no longer exists on the MCP server. If the tester agent were to run, it would get a "tool not found" error.



### B4. E2E Tests (Exist but May Be Stale)

Three Playwright E2E test files exist:

| File | What It Tests |
|------|---------------|
| `frontend/tests/e2e/auth.spec.js` | Keycloak login/logout flow |
| `frontend/tests/e2e/deployment-approval.spec.js` | Deployment approval workflow |
| `frontend/tests/e2e/chat.spec.js` | Chat message sending |

These tests were written against earlier versions of the frontend and may reference old page selectors or API patterns. They have not been verified against the current pages.

### B5. general_chat Intent (Minimal Implementation)

**What exists:** The router can classify a message as `general_chat`. The planner's instructions say "For general_chat, just call done immediately."

**What actually happens:** When the router sets `intent=general_chat`, it first uses `hitl_ask_question` to answer the user's question (per router.yaml line 39-41), then calls `set_intent` and `done`. The planner then calls `done` immediately with no plan steps.

**Issue:** The system has a full agent pipeline (router + planner + other agents) to answer a simple questions but doesnt use it. The answer is delivered via `hitl_ask_question` from the router instead. Could be improved with knowledge about our actual system.

---

## C. Future Improvements / Roadmap

These are features that do not yet exist but would meaningfully improve the platform.

### C1. Per-Agent Model Selection

Allow each agent YAML's `model` and `temperature` fields to actually select different LLM instances. This would enable:
- Cheap/fast models for router and planner (classification tasks)
- Expensive/capable models for developer and architect (complex reasoning)
- Different providers per agent (e.g., DeepInfra for some, Z.AI for others)

**Implementation approach:** Replace the global singleton with a factory that caches LLM instances per `(provider, model)` tuple.

### C2. WebSocket Real-Time Updates

Build a WebSocket layer from scratch to push real-time updates to the frontend, eliminating the need for polling:
- Agent start/complete events
- Approval request notifications
- HITL question notifications
- Deployment complete events
- Approval decision updates

This would make the UI feel significantly more responsive.

### C3. Activate Reviewer and Tester Agents

1. Add `reviewer` and `tester` to the planner's available agents list.
2. Restore or rewrite `run_tests` tool in the coding MCP server.
3. Add reviewer and tester steps to the `create_project` and `update_project` workflows.
4. Consider a review gate before deployment.

### C4. Improve general_chat UX

The current `general_chat` path is heavy (2 LLM calls, creates a Question that must be "answered"). Options:
- Short-circuit at the router level: if `general_chat`, respond via `create_message` instead of `hitl_ask_question`.
- Skip the planner entirely for general_chat.
- Use a lighter-weight model for quick responses.

### C5. Clean Up Duplicate Frontend Pages (Done)

~~Remove the legacy pages or rename the "New" pages to replace them.~~ Resolved: the "New" pages have been renamed to Debug pages (`DebugChat.jsx`, `DebugApprovals.jsx`, `DebugMCP.jsx`, `DebugProjects.jsx`) and placed under a Debug dropdown in the navigation. The original pages are the primary nav items.

### C6. Streaming LLM Output

Currently agents run to completion before any output is visible. Adding streaming would allow:
- Progressive display of agent thinking
- Faster perceived responsiveness
- Early cancellation if the agent goes off track

### C7. Agent Execution Cancellation

No mechanism exists to cancel a running workflow. If an agent enters an infinite loop or makes bad decisions, there is no way to stop it other than killing the process. Adding a cancel endpoint (`POST /api/sessions/{id}/cancel`) would be useful.

### C8. Multi-Model Orchestration

Allow the system to use different LLM providers for different tasks within a single session:
- Use a fast model for routing/planning
- Use a capable model for coding
- Use a vision model for reviewing UI screenshots

### C9. Agent Memory / Context Window Management

Long sessions with many tool calls can exceed LLM context windows. No context window management exists:
- No message truncation or summarization
- No sliding window
- No context-aware pruning

This will cause failures on long-running update_project workflows (8 steps, each with multiple LLM calls).

### C10. Observability and Monitoring

- No metrics collection (Prometheus, etc.)
- No distributed tracing
- Structured logging exists (structlog) but no log aggregation
- The Debug page provides some visibility but is manual

### C11. Error Recovery and Retry

- No automatic retry for failed LLM calls (rate limits, timeouts)
- No retry for failed MCP tool calls
- No mechanism to restart a failed agent run from where it stopped
- Session goes to `FAILED` status with no recovery path

### C12. Multi-User / Concurrent Sessions

- No load testing or concurrency testing
- The global LLM singleton may have issues with concurrent requests
- No rate limiting on the chat endpoint
- No queue for background orchestrator tasks (uses raw `asyncio.create_task`)

### C13. Production Deployment Configuration

- No production docker-compose or Kubernetes manifests
- No TLS/HTTPS configuration
- No secret management (API keys are in `.env` file)
- Keycloak runs in `start-dev` mode
- No backup/restore procedures

### C14. Project/Session Cleanup

- No mechanism to delete projects or sessions
- No cleanup of Docker containers from failed/abandoned deployments
- No workspace cleanup for old git clones
- Docker volumes grow indefinitely

### C15. Test Coverage

- Backend unit tests may exist (`cd druppie && pytest`) but coverage is unknown
- E2E tests exist but may be stale
- No integration tests for the full pipeline
- No load tests
