# Druppie Platform -- Functional Features

Druppie is a governance platform where users describe what they want built in natural language, and a pipeline of specialized AI agents collaborates to gather requirements, design architecture, write code, and deploy working applications -- with human approval gates at every critical step.

---

## Core Philosophy: Agents Act Only Through Tools

Every action an agent takes goes through a **tool call** -- either an **MCP tool** provided by an external server, or a **builtin tool** provided by the platform itself.

**Builtin tools** are provided by the platform to every agent: `done` (signal completion and pass a summary to the next agent), `hitl_ask_question` (pause and ask the user a free-form question), and `hitl_ask_multiple_choice_question` (pause and present choices). Three additional builtins are restricted: `set_intent` (Router only -- declares the session intent and creates the project/repo), `make_plan` (Planner only -- creates an ordered list of agent steps to execute), and `invoke_skill` (agents with skills configured -- invokes a predefined skill and gains temporary tool access).

**MCP tools** are provided by external MCP servers over HTTP (e.g., `read_file`, `write_file`, `docker:build`). Which tools each agent can call is configured in its YAML definition.

Because all actions are tool calls, every action can be logged, inspected, and gated behind approval workflows.

---

## Agent Pipeline

Nine agents are defined. Seven are functional; two are stubs.

### Functional Agents

| Agent | Purpose | Key Behavior |
|-------|---------|--------------|
| **Router** | Classifies user intent | Determines whether the request is `create_project`, `update_project`, or `general_chat`. Can ask clarifying questions. Has web search access. |
| **Planner** | Orchestrates the pipeline | Creates execution plans as ordered sequences of agent steps. Re-evaluates after each major phase. Manages design loops (BA/Architect) and execution loops (Developer/Deployer). Max 15 iterations. |
| **Business Analyst** | Gathers requirements | Engages the user in structured dialogue (root cause analysis, stakeholder mapping, elicitation). Produces `functional_design.md`. Considers security and compliance by design. Handles revision cycles when the Architect sends feedback. Max 50 iterations. |
| **Architect** | Designs system architecture | Reviews the functional design against NORA standards and water authority architecture principles. Three outcomes: APPROVE (writes `architecture.md`), FEEDBACK (sends specific items back to BA), or REJECT (communicates directly with user). Applies Security by Design and Compliance by Design. Max 50 iterations. |
| **Developer** | Writes and modifies code | Implements features in git-managed workspaces. Handles branch creation, file writes, commits, pull requests, and merges. For `create_project`, works on main; for `update_project`, works on feature branches. Max 100 iterations. |
| **Deployer** | Builds and deploys via Docker | Clones from git, builds Docker images, runs containers with auto-assigned ports (9100-9199). Verifies health via container logs. For preview deploys, asks the user for feedback before finalizing. Max 100 iterations. |
| **Summarizer** | Creates completion messages | Reads all previous agent summaries and produces a concise, user-friendly message. Always the final step. Max 5 iterations. |

### Stub Agents (Not Yet Invoked)

| Agent | Intended Purpose |
|-------|-----------------|
| **Tester** | Run tests and validate implementations |
| **Reviewer** | Code review for quality, security, and best practices |

These agents are defined with system prompts and MCP tool access but are never included in plans by the Planner.

---

## Workflows

### create_project

A new project is created from scratch:

1. **Router** classifies intent as `create_project`, assigns a project name
2. **Planner** creates the initial plan: BA, Architect, then re-evaluate
3. **Business Analyst** gathers requirements via HITL dialogue, writes `functional_design.md`
4. **Architect** reviews the functional design:
   - If feedback needed: sends items back to BA (design loop)
   - If approved: writes `architecture.md`
5. **Planner** re-evaluates: plans Developer and Deployer
6. **Developer** implements the code on main, commits and pushes
7. **Deployer** builds Docker image, runs container, asks user for preview feedback
8. **Planner** re-evaluates based on user feedback:
   - If approved: plans Summarizer
   - If changes requested: loops back to Developer, then Deployer
9. **Summarizer** creates the final user-facing summary

### update_project

An existing project is modified via feature branches:

1. **Router** classifies intent as `update_project`, identifies the project
2. **Planner** creates the initial plan
3. **Developer** creates a feature branch (branch setup only)
4. **Business Analyst** reads existing code, gathers change requirements
5. **Architect** reviews the change design
6. **Planner** re-evaluates designs (design loop if needed)
7. **Developer** implements changes on the feature branch
8. **Deployer** builds and deploys a preview container (keeps production running)
9. **Planner** re-evaluates based on user feedback:
   - If approved: Developer merges PR, Deployer does final deploy from main
   - If changes requested: loops back to Developer on the feature branch
10. **Summarizer** creates the final summary

### general_chat

The Router classifies the request as conversational, answers the question directly via HITL, and completes without planning.

---

## Authentication and Roles

Authentication is handled by Keycloak via OAuth 2.0 / OIDC. Roles control what each user can approve -- the approval system (next section) depends entirely on these role assignments.

### Roles

| Role | Description |
|------|-------------|
| admin | Full platform access; can act on any approval regardless of required role |
| architect | Can approve architecture designs and merge-to-main operations |
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

- **Role-filtered view**: Users only see approvals they are authorized to act on based on their roles. A developer sees Docker and PR merge approvals; an architect sees merge-to-main approvals; admins see everything.
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
| `hitl_ask_multiple_choice_question` | Multiple choice with predefined options and an optional "Other" free-text field |

Both types pause the agent loop until the user responds. Questions appear as interactive cards in the chat timeline.

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
- **Polling**: Active sessions poll at 500ms intervals; session lists poll at 5s intervals. Polling stops when a session completes or fails.

---

## Tool System & Configuration

This section covers how tools, approvals, and agents are configured. The concepts above (agents, workflows, approvals) are all driven by these configuration files.

### MCP Configuration (`mcp_config.yaml`)

The central `mcp_config.yaml` file is the single source of truth for all MCP tool definitions, approval rules, and parameter injection. It defines:

1. **Which MCP servers exist** and how to reach them (URL from environment variables)
2. **Every tool's schema** -- name, description, parameters, and required/optional fields
3. **Global approval rules** -- which tools require approval and from which role
4. **Parameter injection rules** -- which parameters are auto-injected from session context and hidden from the agent. This can be used later for authentication.

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

  # Tool definitions with schemas and approval rules
  tools:
    - name: read_file
      description: "Read the contents of a file"
      requires_approval: false
      parameters:
        type: object
        properties:
          path:
            type: string
            description: "Path to the file"
        required: [path]

    - name: merge_to_main
      description: "Merge a branch into main"
      requires_approval: true        # Approval gate
      required_role: architect        # Only architects can approve
      parameters: ...
```

The approval rules defined here are the **global defaults**. They apply to all agents unless an agent's YAML definition overrides them via `approval_overrides`. This creates a two-layer approval system: `mcp_config.yaml` sets the baseline, agent YAML files can tighten it for specific agents.

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

#### System Prompt Placeholders

Agent system prompts can contain two placeholders that are resolved at runtime:

- **`[COMMON_INSTRUCTIONS]`** -- Replaced with the contents of `agents/definitions/_common.md`, a shared prompt fragment that standardizes behavior across agents. It covers the summary relay protocol (how agents read previous summaries and format their own via `done()`), the mandatory `done()` output format, and workspace state rules (e.g., don't create branches unless asked). Currently included by: Planner, Business Analyst, Architect, Developer, Deployer.
- **`[TOOL_DESCRIPTIONS_PLACEHOLDER]`** -- Replaced at runtime with a formatted list of the MCP tools the agent is allowed to call (based on its `mcps` config). Each tool entry includes its name, description, parameters, and whether it requires approval. This is generated dynamically from `mcp_config.yaml` so the agent's prompt always reflects the current tool definitions.

Both placeholders are optional -- agents that don't include them simply won't get the injected content.

Key sections:

- **`mcps`**: Maps MCP server names to the list of tools the agent is allowed to call. An agent cannot call tools not listed here, even if the MCP server exposes them.
- **`approval_overrides`**: Overrides the global approval configuration for specific tools. For example, `write_file` requires no approval globally, but the Business Analyst definition adds an override requiring `business_analyst` role approval. The Architect similarly overrides it to require `architect` role approval.
- **`provider` / `model`**: Primary LLM provider and model for this agent. Resolved via a chain: override env var → agent YAML → fallback → global default.
- **`fallback_provider` / `fallback_model`**: Optional fallback LLM used at runtime when the primary provider returns retryable errors (rate limits, server errors).
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
  bestand-zoeker:
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
