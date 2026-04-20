# Druppie Platform -- Functional Features

Druppie is a governance platform where users describe what they want built in natural language, and a pipeline of specialized AI agents collaborates to gather requirements, design architecture, write code, and deploy working applications -- with human approval gates at every critical step.

---

## Core Philosophy: Agents Act Only Through Tools

Every action an agent takes goes through a **tool call** -- either an **MCP tool** provided by an external server, or a **builtin tool** provided by the platform itself.

**Builtin tools** are provided by the platform to every agent: `done` (signal completion and pass a summary to the next agent), `hitl_ask_question` (pause and ask the user a free-form question), and `hitl_ask_multiple_choice_question` (pause and present choices). Additional builtins are restricted to specific agents: `set_intent` (Router only -- declares the session intent and creates the project/repo), `make_plan` (Planner only -- creates an ordered list of agent steps to execute), `test_report` (Test Executor only -- structured test iteration reporting), `invoke_skill` (agents with skills configured -- invokes a predefined skill and gains temporary tool access), and `execute_coding_task` (Developer/Update Core Builder -- delegates coding to an isolated sandbox).

**MCP tools** are provided by external MCP servers over HTTP (e.g., `read_file`, `write_file`, `docker:build`). Which tools each agent can call is configured in its YAML definition.

Because all actions are tool calls, every action can be logged, inspected, and gated behind approval workflows.

---

## Agent Pipeline

Thirteen agents are defined. Twelve are functional; one is a stub.

### Functional Agents


| Agent | Purpose | Key Behavior |
|-------|---------|--------------|
| **Router** | Classifies user intent | Determines whether the request is `create_project`, `update_project`, or `general_chat`. Can ask clarifying questions. Has web search access. |
| **Planner** | Orchestrates the pipeline | Creates execution plans as ordered sequences of agent steps. Re-evaluates after each major phase. Manages design loops (BA/Architect) and execution loops (Developer/Deployer). Max 15 iterations. |
| **Business Analyst** | Gathers requirements | Engages the user in structured dialogue using a funnel approach (max 1 question at a time, almost always multiple choice). Produces `functional_design.md` via the `make_design` tool with built-in Mermaid validation. Considers security and compliance by design. Handles revision cycles when the Architect sends feedback. Supports `NO_FD_CHANGE` pass-through for technical fixes. Max 50 iterations. |
| **Architect** | Designs system architecture | Reviews the functional design against NORA standards and water authority architecture principles. Four outcomes: APPROVE (writes `technical_design.md` via `make_design`), APPROVE_CORE_UPDATE (same, but signals the project modifies Druppie's own codebase), FEEDBACK (sends specific items back to BA), or REJECT (communicates directly with user). Has access to ArchiMate models via MCP. Can create Mermaid diagrams with built-in syntax validation. Applies Security by Design and Compliance by Design. Max 50 iterations. |
| **Builder Planner** | Creates implementation plans | Reads `functional_design.md` and `technical_design.md`, writes `builder_plan.md` with code standards, test framework, test strategy, solution strategy, and change approach. Guides the downstream builder. Max 30 iterations. |
| **Builder** | Sole execution agent | Delegates ALL coding work to OpenCode sandbox agents via `execute_coding_task`. Four modes with distinct done() signals: **TDD CYCLE** (druppie-test-writer → druppie-implementer → druppie-test-runner, with up to 3 retry strategies — signals `TDD_PASSED` / `TDD_FAILED`), **BRANCH SETUP** (`BRANCH_CREATED`), **IMPROVEMENT** (`IMPROVEMENT_DONE`), **MERGE** (`MERGED`). No direct coding MCPs. Max 30 iterations. |
| **Update Core Builder** | Implements Druppie core changes | Delegates coding to a dual-repo sandbox via `execute_coding_task` with the `druppie-core-builder` sandbox agent. The sandbox clones Druppie's GitHub repo into `/workspace/core/` and the project repo (with FD/TD) into `/workspace/project/`. Creates a PR targeting `colab-dev` on GitHub. The `done()` tool requires approval from a user with the `developer` role — the reviewer merges the PR on GitHub before approving. Max 100 iterations. |
| **Deployer** | Builds and deploys via Docker | Clones from git, builds Docker images, runs containers with auto-assigned ports (9100-9199). Verifies health via container logs. For preview deploys, asks the user for feedback before finalizing. Max 100 iterations. |
| **Reviewer** | Code review | Reviews code for quality, security, and best practices. |
| **Tester** | Testing | Writes and runs tests to validate implementations. |
| **Summarizer** | Creates completion messages | Reads all previous agent summaries and produces a concise, user-friendly message. Always the final step. Max 5 iterations. |

### Stub Agents (Not Yet Invoked)

| Agent | Intended Purpose |
|-------|-----------------|
| **Reviewer** | Code review for quality, security, and best practices |

This agent is defined with system prompts and MCP tool access but is never included in plans by the Planner.


---

## Workflows

### create_project

A new project is created from scratch:

1. **Router** classifies intent as `create_project`, assigns a project name
2. **Planner** creates the initial plan: BA, Architect, then re-evaluate
3. **Business Analyst** gathers requirements via HITL dialogue, writes `functional_design.md`
4. **Architect** reviews the functional design:
   - If feedback needed: sends items back to BA (design loop)
   - If approved: writes `technical_design.md`
5. **Planner** re-evaluates: plans Builder Planner
6. **Builder Planner** reads design documents, writes `builder_plan.md` with implementation strategy
7. **Builder** (TDD CYCLE mode) drives the full Red → Green → Verify loop via OpenCode sandbox agents:
   - `druppie-test-writer` writes tests, `druppie-implementer` implements code, `druppie-test-runner` runs tests
   - On test failure, retries up to 3 times with different strategies (TARGETED_FIXES → REWRITE → SIMPLIFY)
   - Signals `TDD_PASSED` or `TDD_FAILED` in `done()`
   - On `TDD_FAILED`, Planner escalates to user via HITL with three choices:
     - Continue with specific instructions: Builder runs a fresh TDD cycle with user guidance
     - Deploy with warning: Deployer deploys despite failing tests
     - Abort project: Summarizer ends the workflow
8. **Deployer** builds Docker image, runs container, asks user for preview feedback
9. **Planner** re-evaluates based on user feedback:
    - If approved: plans Summarizer
    - If changes requested: loops back to Builder (IMPROVEMENT mode), then Deployer
10. **Summarizer** creates the final user-facing summary

### update_project

An existing project is modified via feature branches:

1. **Router** classifies intent as `update_project`, identifies the project
2. **Planner** creates the initial plan
3. **Builder** (BRANCH SETUP mode) creates a feature branch
4. **Business Analyst** reads existing code, gathers change requirements
5. **Architect** reviews the change design (design loop with BA if needed)
6. **Builder Planner** reads design documents, writes `builder_plan.md`
7. **Builder** (TDD CYCLE mode) drives the full Red → Green → Verify loop via OpenCode sandbox agents; signals `TDD_PASSED` or `TDD_FAILED`
8. **Deployer** builds and deploys a preview container (keeps production running)
9. **Planner** re-evaluates based on user feedback:
    - If approved: Builder (MERGE mode) merges PR, Deployer does final deploy from main
    - If changes requested: loops back to Builder (IMPROVEMENT mode) on the feature branch
10. **Summarizer** creates the final summary

### Core Update (Druppie self-improvement)

When a project involves modifying Druppie's own codebase, the Architect signals `DESIGN_APPROVED_CORE_UPDATE` instead of `DESIGN_APPROVED`. The Planner then routes to the `update_core_builder` agent, which creates a PR on GitHub for human review. After the core changes are merged, the Architect runs again to design the actual project, and the normal pipeline continues.

The session intent stays `create_project` or `update_project` throughout — there is no separate `update_core` intent. The core update is a detour within the normal flow, not a separate workflow.

**Pipeline:**

1. **Router** classifies intent as `create_project` (a project record and Gitea repo are created as usual)
2. **Business Analyst** gathers requirements, writes `functional_design.md`
3. **Architect** (run 1) reviews the design, writes `technical_design.md`, detects the project modifies Druppie's codebase, signals `DESIGN_APPROVED_CORE_UPDATE`
4. **Update Core Builder** delegates to a dual-repo sandbox via `execute_coding_task`:
   - Sandbox clones Druppie's GitHub repo into `/workspace/core/` and the project repo (with FD/TD) into `/workspace/project/`
   - The `druppie-core-builder` sandbox agent reads design docs from `/workspace/project/`, implements changes in `/workspace/core/`
   - Creates a `core/` branch from `colab-dev`, commits, pushes via the git proxy
   - Creates a PR on GitHub targeting `colab-dev` via the GitHub API proxy
   - Calls `done()` — which requires approval from a user with the `developer` role
   - The reviewer merges the PR on GitHub, then approves `done()` in Druppie
5. **Architect** (run 2) designs the actual project with the core changes now in place, signals `DESIGN_APPROVED`
6. Normal pipeline continues: Builder Planner → Test Builder → Builder → Test Executor → Deployer → Summarizer

**Key characteristics:**
- The Architect detects core changes by checking if the project adds, modifies, or removes anything in the Druppie codebase/repository itself
- Git provider routing is determined by the calling agent: `update_core_builder` uses GitHub, all other agents use Gitea
- Authentication via GitHub App installation tokens (short-lived, ~1 hour) — the sandbox only sees proxy URLs, not real tokens
- The `done()` approval gate ensures a human developer reviews and merges the PR before the pipeline continues
- No deploy or merge step for core changes — PRs are always reviewed and merged by humans on GitHub

**Prerequisites:** Requires a GitHub App configured with Contents R/W, Pull Requests R/W, and Metadata R permissions, plus `DRUPPIE_REPO_OWNER` and `DRUPPIE_REPO_NAME` env vars pointing to the Druppie repo.

### general_chat

The Router classifies the request as conversational, answers the question directly via HITL, and completes without planning.

---

## Authentication and Roles

Authentication is handled by Keycloak via OAuth 2.0 / OIDC. Roles control what each user can approve -- the approval system (next section) depends entirely on these role assignments.

### Roles

| Role | Description |
|------|-------------|
| admin | Full platform access; can act on any approval regardless of required role |
| architect | Can approve architecture designs |
| developer | Can approve Docker operations and pull request merges |
| business_analyst | Can approve functional design writes |

Users can hold multiple roles. For example, the `architect` test user has both `architect` and `developer` roles, so they can approve both architecture and Docker operations.

### Test Users

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin (composite: user, developer, architect, business_analyst) |
| architect | Architect123! | architect |
| analyst | Analyst123! | business_analyst |
| developer | Developer123! | developer |
| normal_user | User123! | user |
| seniordev | Developer123! | developer |
| juniordev | Developer123! | developer |
| infra | Infra123! | infra-engineer |
| productowner | Product123! | product-owner |
| compliance | Compliance123! | compliance-officer |
| viewer | Viewer123! | viewer |

### Frontend Authentication

- Protected routes with role-based guards (e.g., admin-only database page)
- JWT Bearer token injected on all API requests
- Silent SSO check on page load; automatic token refresh on expiry
- User profile and role display on the Settings page

---

## Approval Workflow

When an agent calls a tool that requires approval, the workflow pauses until an authorized user approves or rejects. Only users whose roles match the tool's `required_role` (or admins) can act. Approval rules are configured in `mcp_config.yaml` (global defaults) and can be tightened per-agent in agent YAML files (see Tool System & Configuration below).

### Tasks Page (Approval Queue)

The **Tasks page** (`/tasks`) is the dedicated approval management interface. It serves as a centralized queue where users review and act on all pending approvals across all sessions.

- **Role-filtered view**: Users only see approvals they are authorized to act on based on their roles. A developer sees Docker and PR merge approvals; admins see everything.
- **Approval cards**: Each card shows the tool name, MCP server, full arguments (with expandable file content previews for write operations), the requesting agent, and a link to the parent session.
- **Approve/reject actions**: Users approve or reject each item. Rejections require a reason that is passed back to the agent.
- **Polling**: The Tasks page polls for new approvals every 1 second.

### Approvals in Chat

Approval cards also appear **inline in the chat timeline** of the session that triggered them. This gives users context about where in the workflow the approval was requested. Users can approve or reject directly from the chat view without navigating to the Tasks page if they have the assigned role.

---

## Human-in-the-Loop (HITL)

Agents can pause execution to ask the user questions. Two interaction types are available:

| Type | Description |
|------|-------------|
| `hitl_ask_question` | Free-form text question; the user types a response |
| `hitl_ask_multiple_choice_question` | Multiple choice with predefined options; an "Other (specify)" free-text option is always appended automatically by the platform — agents should never add it themselves |

Both types pause the agent loop until the user responds. Questions appear as interactive cards in the chat timeline.

### Mermaid Diagram Validation

Design documents written via the `make_design` tool include built-in Mermaid syntax validation. The validator runs **before the approval gate**, catching common LLM mistakes so agents can fix errors without wasting human reviewer time. If validation fails, the tool call is rejected with actionable error messages and the agent retries with corrected content.

The validator checks for:
- Backslash-escaped quotes (`\"` — invalid in Mermaid)
- Nested delimiters (`[((`, `))]` — malformed shapes)
- Single-dash arrows (`->` instead of `-->`)
- Reserved `end` keyword used as node ID
- Smart/curly quotes (unicode instead of ASCII)
- Unicode characters (em dashes, unicode arrows)

---

## Chat and Conversations

The primary interface is a chat page where users submit natural language requests. Each request starts a session that progresses through a multi-agent pipeline.

- **Natural language input**: Users describe what they want ("Build me a todo app", "Add a login page to my project").
- **Real-time timeline**: The chat view shows a full timeline of the session: user messages, agent runs, LLM calls, tool invocations, approvals, and HITL questions.
- **Expandable details**: Each timeline entry (LLM call, tool call) can be expanded to inspect arguments, results, and errors for debugging.
- **Session sidebar**: Lists all sessions with project context; click to load any session.
- **Follow-up messages**: After a session completes, users can send follow-up messages to continue the conversation in the same session context.
- **Inline approval cards**: When an agent needs approval to proceed, an approval card appears directly in the timeline.
- **Inline HITL cards**: When an agent asks a question, an input card appears in the timeline for the user to respond.
- **Polling**: Active sessions poll at 500ms intervals; session lists poll at 5s intervals. Polling stops when a session completes, fails, or is paused.

---

## Session Control

### Stop & Resume

Users can **stop** any running session and **resume** it later -- all context is preserved.

**How it works:**

- Click **Stop** to pause execution. The current LLM call and tool execution completes, then the agent stops cleanly.
- Click **Continue** to resume from where it left off. The agent reconstructs its state from the database and continues.
- Works for **all users**, not just admins.
- **Survives system reboots**: On startup, the system detects "zombie" sessions (sessions that were active when the server stopped) and marks them as paused so users can resume them.

**Status model:**

| Status | Meaning | Visual Indicator |
|--------|---------|------------------|
| `active` | Processing in progress | Blue pulsing dot |
| `paused` | Stopped by user or recovered after reboot | Amber dot |
| `paused_approval` | Waiting for tool approval | Amber dot |
| `paused_hitl` | Waiting for user answer (HITL) | Amber dot |
| `paused_sandbox` | Waiting for sandbox completion | Amber dot |
| `completed` | All agents finished | Green dot |
| `failed` | Error occurred | Red dot |

**Design choice: Stop button visible during HITL/approval waits.** The Stop button remains visible when the session is waiting for approval or a HITL answer (`paused_approval`, `paused_hitl`). This is intentional because in the future, multiple agents may work in parallel -- some may be actively running while others wait for user input. The Stop button ensures users can always halt all active work.

**API endpoints:**

- `POST /api/chat/{session_id}/cancel` -- Soft-stop a session (sets status to `paused`, always resumable)
- `POST /api/sessions/{session_id}/resume` -- Resume a paused session

**Architecture notes:**

- Pause uses a DB-polling mechanism: the cancel endpoint sets `session.status = 'paused'` in the database, and both the orchestrator loop (between agent runs) and the agent loop (between LLM iterations) detect it and stop gracefully.
- Resume spawns a background task that calls `agent.continue_run()`, which reconstructs the full LLM conversation from database records, then continues execution.
- `CANCELLED` status is only used internally by the planner when it supersedes old pending runs with a new plan. It is never set by user actions.

### Retry from Agent Run

Users can retry a session from any agent run via the **Retry** button in the Inspect view's agent detail panel. Clicking Retry shows a confirmation dialog explaining that the target agent and all subsequent agents will be reverted and re-executed.

**How it works:**

1. The backend reverts git state to the commit before the target agent run (`git reset --hard` + `git push --force` via the `revert_to_commit` MCP tool)
2. Any open pull requests created by reverted agents are closed via the Gitea API
3. If a planner is in the revert set: the planner is reset to PENDING, everything after it is deleted (make_plan will recreate them on re-execution)
4. If no planner: all target runs are reset to PENDING with execution artifacts cleared
5. The orchestrator re-executes the pending runs

If the git revert fails, the retry aborts and the session is marked as failed (agents never re-execute against stale git state).

---

## Tool System & Configuration

This section covers how tools, approvals, and agents are configured. The concepts above (agents, workflows, approvals) are all driven by these configuration files.

### MCP Configuration (`mcp_config.yaml`)

`mcp_config.yaml` defines:

1. **Which MCP servers exist** and how to reach them (URL from environment variables)
2. **Global approval rules** -- which tools require approval and from which role
3. **Parameter injection rules** -- which parameters are auto-injected from session context and hidden from the agent

Tool schemas (names, descriptions, parameters) are **not** defined here. They are the sole responsibility of each MCP module's `@mcp.tool()` decorators (see MCP Module Convention below). At startup, the `ToolRegistry` fetches live schemas from each server via `tools/list`.

Each MCP server is declared as a top-level block:

```yaml
coding:
  url: ${MCP_CODING_URL}

  # Parameter injection (see Hidden Parameter Injection below)
  inject:
    session_id:
      from: session.id
      hidden: true
    repo_name:
      from: project.repo_name
      hidden: true
      tools: [read_file, write_file, ...]

  # Approval rules per tool (no schema — schema comes from the module)
  tools:
    merge_pull_request:
      requires_approval: true        # Approval gate
      required_role: developer       # Only developers can approve
```

The approval rules defined here are the **global defaults**. They apply to all agents unless an agent's YAML definition overrides them via `approval_overrides`. This creates a two-layer approval system: `mcp_config.yaml` sets the baseline, agent YAML files can tighten it for specific agents.

### MCP Module Convention

Each MCP server lives in `druppie/mcp-servers/module-<name>/` and follows a standard layout:

```
module-<name>/
  MODULE.yaml       # Module metadata (name, version, description)
  server.py         # FastMCP app factory + versioned router mounting
  requirements.txt
  Dockerfile
  v1/
    tools.py        # @mcp.tool() definitions — single source of truth for schemas
    module.py       # Business logic called by tools
```

Key conventions:
- **`v1/tools.py` is the single source of truth** for tool names, descriptions, and parameter schemas. The `@mcp.tool()` decorator generates the JSON schema that `ToolRegistry` fetches at startup.
- **`server.py`** mounts versioned routers (e.g., `/v1`). Path-based routing allows `v2/`, `v3/`, ... to coexist without breaking existing clients.
- **`MODULE.yaml`** declares module metadata (name, current version, description).
- **Pre-validation** is declared via `meta.pre_validate` in tool decorators, replacing any hardcoded validation logic in the platform core.

### Agent Definitions (YAML)

Each agent is defined in a YAML file under `agents/definitions/`. The YAML controls everything about the agent's behavior and permissions:

```yaml
id: business_analyst
name: Business Analyst Agent
description: ...
system_prompt: |
  ...

# Which MCP tools this agent can call, grouped by server
mcps:
  coding:
    - read_file
    - write_file
    - list_dir

# Per-agent approval overrides (optional)
# Override global defaults for specific tools
approval_overrides:
  "coding:write_file":
    requires_approval: true
    required_role: business_analyst

# LLM configuration
model: glm-4
temperature: 0.2
max_tokens: 100000
max_iterations: 50
```

#### System Prompts

Agents can declare composable system prompts via the `system_prompts` list in their YAML definition. System prompts are YAML files in `agents/definitions/system_prompts/` that each contain a `name` and `prompt` field.

At runtime, the declared system prompts are loaded and appended (in order) after the agent's own `system_prompt` text.

Available system prompts:

| System Prompt | Purpose |
|----------|---------|
| `summary_relay` | How to read previous agent summaries and format your own via `done()` |
| `done_tool_format` | Mandatory `done()` output format rules |
| `workspace_state` | Shared workspace and git branch rules |
| `tool_only_communication` | Reinforces that agents must never add "Other" to multiple choice options — the platform handles it automatically |

Currently included by: Planner, Business Analyst, Architect, Builder Planner, Builder, Deployer, Update Core Builder. Agents without a `system_prompts` list receive no system prompts.

Key sections:

- **`mcps`**: Maps MCP server names to the list of tools the agent is allowed to call. An agent cannot call tools not listed here, even if the MCP server exposes them.
- **`approval_overrides`**: Overrides the global approval configuration for specific tools. For example, `write_file` requires no approval globally, but the Business Analyst definition adds an override requiring `business_analyst` role approval. The Architect similarly overrides it to require `architect` role approval.
- **`llm_profile`**: References a named profile from `llm_profiles.yaml` (e.g., `standard`, `cheap`). Each profile defines an ordered list of `{provider, model}` pairs. The resolver picks the first provider with a valid API key as primary, the next as runtime fallback.
- **`temperature` / `max_tokens`**: LLM generation parameters for this agent.
- **`max_iterations`**: Safety limit on the agent's tool-calling loop.

### Hidden Parameter Injection

Some tool parameters (like `session_id`, `repo_name`, `repo_owner`, `project_id`, `user_id`) are automatically injected from the session context and hidden from the LLM. This means the agent never sees these parameters in the tool schema and cannot manipulate them. They are declared in `mcp_config.yaml` with `hidden: true` and can be scoped to specific tools:

```yaml
coding:
  inject:
    session_id:
      from: session.id
      hidden: true              # Injected into all coding tools, invisible to LLM
    repo_name:
      from: project.repo_name
      hidden: true
      tools: [read_file, write_file, ...]   # Only injected for these tools
```

This ensures agents operate on the correct repository and session without being able to target arbitrary resources.

---

## Sandbox Coding (Isolated Execution)

Agents can delegate coding tasks to isolated Docker sandboxes. Each sandbox is a fresh container with git, [OpenCode](https://github.com/opencode-ai/opencode), and proxied LLM access. The sandbox clones the project from Gitea, executes the task, commits and pushes changes back.

**How it works (user perspective):**

1. An agent (e.g., Builder) calls `execute_coding_task` with a task description
2. The agent **pauses** (`paused_sandbox`) while the sandbox runs autonomously
3. When the sandbox completes, a webhook callback resumes the agent automatically
4. The chat timeline shows a **Sandbox Session card** with files changed, elapsed time, expandable events timeline, and full conversation history

**Sandbox agents:** Multiple preconfigured agents run inside sandboxes -- the TDD trio (`druppie-test-writer`, `druppie-implementer`, `druppie-test-runner`) drives the full TDD cycle; `druppie-builder` handles generic coding tasks (branch setup, improvements, merges); `druppie-tester` writes and runs tests outside the TDD flow; `druppie-core-builder` implements changes to Druppie's own codebase in a dual-repo sandbox. All enforce a mandatory git workflow: add, commit, push. No unpushed commits allowed.

**Profile-based LLM routing:** Each sandbox agent/subagent has its own model profile (e.g., `sandbox/druppie-builder`). The LLM proxy resolves profiles to real provider chains at request time, allowing different agents to use different models. Profiles are configured in `sandbox_models.yaml`.

**Provider resilience:** If an LLM provider fails mid-sandbox (any non-2xx response), a three-layer defense handles it: transparent proxy failover (sub-second, tries next provider in chain), failure detection signals, and Druppie-level retry with a new sandbox session. Set `LLM_FORCE_PROVIDER` and `LLM_FORCE_MODEL` to override all profiles with a single provider.

**`create-pull-request` tool:** Sandbox agents create PRs via the `create-pull-request` OpenCode tool, which calls the control plane `/sessions/:id/pr` endpoint. The tool auto-detects the current branch and defaults to `main` if no base branch is specified. For GitHub repos, agents specify `baseBranch="colab-dev"`.

**`repo_target` parameter:** `execute_coding_task` accepts a `repo_target` parameter: `"project"` (default) for single-repo sandboxes using the session's Gitea project, or `"druppie_core"` for dual-repo sandboxes that clone both Druppie's GitHub repo and the project repo (see Core Update workflow).

**Security:** Sandbox events are only visible to the owning user (admins can view any). Git and LLM credentials are proxied -- never exposed to sandbox code. Webhooks are HMAC-signed.

> See [docs/SANDBOX.md](SANDBOX.md) for full architecture details, OpenCode integration, provider resilience, and Kata Containers setup.

---

## Skills System

Skills are reusable prompt/instruction packages that grant agents temporary access to additional tools. Each skill is a Markdown file (`SKILL.md`) stored in `druppie/skills/<skill-name>/`.

### Skill Definition

A skill file has YAML frontmatter and a Markdown body:

```markdown
---
name: code-review
description: Perform a thorough code review
allowed-tools:
  coding:
    - read_file
    - list_dir
  web:
    - search_files
---
# Code Review Instructions

Review the code for quality, security, and best practices...
```

- **`name`** and **`description`**: Skill metadata (shown to the LLM in the `invoke_skill` tool description).
- **`allowed-tools`**: MCP tools that become available to the agent when this skill is invoked, grouped by MCP server.
- **Markdown body**: Instructions returned to the agent when the skill is invoked.

### How Skills Work

1. Agent definitions specify which skills they can use via the `skills:` field in their YAML:
   ```yaml
   skills:
     - code-review
     - git-workflow
   ```
2. When the agent calls `invoke_skill(skill_name="code-review")`:
   - The skill's `allowed_tools` are dynamically added to the agent's available tools for subsequent LLM calls.
   - The skill's Markdown body is returned as instructions to guide the agent.
3. The agent can now use the skill's tools until it completes the task or calls another skill.

### Skill-Based Tool Access

Tools granted via skills are checked in `ToolExecutor` alongside the agent's static MCP permissions. If a tool is not in the agent's YAML `mcps` list but is allowed by an active skill, the agent can still use it.

### Coding Standards and Templates

The Builder and Reviewer agents use skills to enforce project-specific coding standards and architecture patterns:

| Skill | Used By | Purpose |
|-------|---------|---------|
| `project-coding-standards` | Builder, Reviewer | Python/React code style, naming conventions, formatting rules, import conventions, and critical project rules |
| `fullstack-architecture` | Builder | Clean architecture patterns (Summary/Detail, Repository, Service, Route) and code templates for all component types |
| `standards-validation` | Reviewer | Structured validation checklist for architecture compliance and standards compliance |

**Builder behavior**: Before writing code for the Druppie codebase, the Builder invokes `fullstack-architecture` and `project-coding-standards` to load the architecture patterns and coding standards. New components are scaffolded from embedded templates (domain models with Summary/Detail pattern, repositories extending BaseRepository, services with constructor injection, thin API routes with Depends injection, and React pages with React Query).

**Reviewer behavior**: Before reviewing code, the Reviewer invokes `project-coding-standards` and `standards-validation` to load the validation checklist. Reviews include explicit architecture compliance and standards compliance sections, with critical violations (e.g., JSON/JSONB columns, business logic in routes) resulting in an automatic FAIL verdict.

---

## Shared Dependency Cache

Sandbox containers share a persistent dependency cache volume so that packages downloaded by one sandbox are available to all future sandboxes. This avoids redundant downloads, speeds up builds, and reduces external network traffic.

### How It Works

A named Docker volume (`druppie_sandbox_dep_cache`) is mounted at `/cache` inside every sandbox container. Environment variables point each package manager to a subdirectory:

| Package Manager | Env Var | Cache Path |
|----------------|---------|------------|
| npm | `NPM_CONFIG_CACHE` | `/cache/npm` |
| pnpm | `PNPM_STORE_DIR` | `/cache/pnpm` |
| Bun | `BUN_INSTALL_CACHE_DIR` | `/cache/bun` |
| uv | `UV_CACHE_DIR` | `/cache/uv` |
| pip | `PIP_CACHE_DIR` | `/cache/pip` |

The cache is transparent to agents — no YAML or prompt changes are needed. Package managers automatically read from and write to the shared volume via their standard environment variables.

### Security Controls

Five layers protect the cache from supply-chain attacks:

1. **HTTPS-only registries** — `.npmrc`, `.pnpmrc`, and `pip.conf` enforce `strict-ssl=true` and HTTPS registry URLs. `UV_INDEX_URL` is set to `https://pypi.org/simple/`.
2. **Lockfile enforcement** — `.npmrc` sets `package-lock=true`; pnpm creates lockfiles by default. This ensures reproducible installs.
3. **OSV vulnerability scanning** — A dedicated `cache-scanner` service scans all cached packages for known vulnerabilities using the [OSV scanner](https://github.com/google/osv-scanner) (binary verified by SHA256 checksum at build time).
4. **Non-root + minimal capabilities** — Sandboxes run as `sandbox:1000` (non-root). All Linux capabilities are dropped (`--cap-drop=ALL`), then only the minimum required set is re-added.
5. **Network isolation** — Sandbox containers run on `druppie-sandbox-network`, an isolated bridge network. Only the control plane bridges both networks; sandboxes cannot reach the database, Keycloak, Gitea, or backend directly.

### Cache Entry Logging

When a sandbox shuts down, the entrypoint diffs cache snapshots (taken at startup vs shutdown) and emits structured `cache.new_entries` JSON log events per package manager, including the sandbox ID, session ID, and up to 50 new entries per package manager. This captures packages installed during both the setup script and the main coding task.

### Commands

```bash
# Purge the dependency cache (stops sandboxes, removes + recreates volume)
docker compose --profile reset-cache run --rm reset-cache

# Scan cached packages for known vulnerabilities (OSV)
docker compose --profile scan-cache run --rm cache-scanner
```

---

## Project Management

- **Create**: Projects are created automatically when the Router classifies a `create_project` intent. Each project gets a Gitea repository.
- **List and detail**: The projects page shows all projects with status and information like the repository link.
- **Delete**: Projects can be deleted from the project detail view.
- **Stop deployments**: Running containers can be stopped from the project detail view.


---

## Dashboard

The dashboards goal is to provide an overview of platform activity. This page is a prototype and might not work correctly.

- **Total sessions**: Count of all sessions
- **Completed plans**: Count of successfully finished plans
- **Pending approvals**: Count of items awaiting approval (links to approvals page)
- **Token usage**: Aggregate token count and estimated cost across all projects
- **Recent plans**: Last 5 plans with status badges
- **Recent approvals**: Last 5 pending approval items
- **User roles**: Current user's assigned roles
- **System status**: Health indicators for Keycloak, Database, LLM provider, and Gitea

---

## Settings Page

The Settings page displays system configuration and status (read-only). This page too is a prototype and might not work correctly.

- User profile and assigned roles
- System health status (Keycloak, Database, LLM, Gitea)
- Environment, version, and LLM provider/model info
- Configured MCP servers with their available tools
- Configured agents with model parameters (model, temperature, max tokens) and MCP access
