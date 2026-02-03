# Druppie - Sprint Plan & Retrospective

## What We Have Today

### The Core Loop

Druppie runs a multi-agent orchestration loop that takes a user message and turns it into a working, deployed application.

```
User Message
    ↓
┌─────────┐
│  Router  │  → Classifies intent, creates project in Gitea
└────┬─────┘
     ↓
┌─────────┐
│ Planner  │  → Plans agents: business_analyst → architect → developer → deployer → planner
└────┬─────┘
     ↓
  Agents execute in sequence
     ↓
┌─────────┐
│ Planner  │  → Reads user feedback, re-evaluates
└────┬─────┘
     │
     ├── User happy?  → Plans: summarizer → Done
     │
     └── User wants changes? → Plans new agents: developer → deployer → planner
                                                                          ↓
                                                                   (loop repeats)
```

### 9 Agents (YAML-Defined)

All agents are defined declaratively in `agents/definitions/*.yaml` with system prompts, MCP tool access, model config, and approval overrides.

| Agent | Role | MCP Access |
|-------|------|------------|
| **Router** | Intent classification, project routing | None (builtin `set_intent` only) |
| **Planner** | Execution plan creation, re-evaluation loop | None (builtin `make_plan` only) |
| **Business Analyst** | Gathers requirements, writes `functional_design.md` | Coding MCP |
| **Architect** | System design, writes `architecture.md` | Coding MCP (approval required for `write_file`) |
| **Developer** | Writes code, manages branches, creates PRs | Coding MCP |
| **Deployer** | Builds Docker images, runs containers, preview URLs | Docker MCP |
| **Summarizer** | User-facing completion message | None (builtin `create_message` only) |
| **Tester** | Runs tests, validates implementations | Coding MCP |
| **Reviewer** | Code review for quality/security | Coding MCP |

### MCP Gateway with Argument Injection

Two MCP microservices provide sandboxed tool access:

**Coding MCP (port 9001)** — File & git operations:
- `read_file`, `write_file`, `batch_write_files`, `list_dir`, `delete_file`
- `create_branch`, `commit_and_push`, `get_git_status`
- `create_pull_request`, `merge_pull_request`

**Docker MCP (port 9002)** — Container lifecycle:
- `build`, `run`, `stop`, `remove`, `logs`
- `list_containers`, `inspect`, `exec_command`

**Argument injection** is declarative (defined in `mcp_config.yaml`). Hidden parameters like `session_id`, `repo_name`, and `repo_owner` are stripped from the LLM's tool schema and injected from the session context at execution time. The LLM never sees or hallucinates these values.

### Approval Workflow

Tool calls can require approval based on:
- **Global defaults** — e.g., `docker:build` requires `developer` role
- **Per-agent overrides** — e.g., architect's `write_file` requires `architect` approval, developer's doesn't

When approval is needed, execution pauses. The frontend shows an approval card with the tool call details. A user with the required role approves or rejects. Execution resumes from the exact checkpoint.

### Human-in-the-Loop (HITL)

Agents can ask the user questions mid-execution via builtin tools:
- `hitl_ask_question` — free-form text
- `hitl_ask_multiple_choice_question` — predefined options

The deployer uses this to ask "Does this preview look good?" after deploying. The user's answer feeds back into the planner re-evaluation loop.

### Git & Project Integration

- Projects are automatically created in Gitea when the router detects `create_project` intent
- Each session gets an isolated workspace (cloned repo)
- Update flows use feature branches with PR-based merging
- Full git history is preserved

### Tool Call Handling

- Primary: OpenAI-compatible function calling format
- Fallback: XML parsing for models (like GLM) that don't reliably use function calling
- All tool calls are persisted in the database with arguments, results, and status

### Frontend

React app with:
- Chat interface with real-time polling (0.5s for active sessions)
- Session timeline showing agent runs, tool calls, LLM calls
- Approval cards with approve/reject actions
- HITL question cards with answer input
- Project list and detail views
- Deployment status and preview URLs
- Debug pages for MCP, approvals, and projects

### Infrastructure

PostgreSQL (app DB) + Keycloak (auth) + Gitea (git) + two MCP servers, all running via Docker Compose. Three test users with different roles (admin, architect, developer).

### LLM Provider Support

Abstracted provider layer supporting:
- Z.AI (GLM-4.7) — primary
- DeepInfra (Qwen, OpenAI-compatible) — alternative
- Mock — for testing
- Per-agent model config in YAML (currently all use same model)

---

## What Works

- Full create_project and update_project flows end-to-end
- Router correctly classifies intent and creates projects in Gitea
- Planner creates reasonable execution plans
- All 9 agents execute their roles
- MCP argument injection keeps agents sandboxed
- Approval workflow pauses/resumes execution correctly
- HITL questions work, deployer feedback loop works
- Planner re-evaluation loop iterates on user feedback (max 3 rounds)
- Git operations: branching, committing, PRs, merging
- Docker build and deploy with preview URLs
- Token tracking per agent run and session
- Session state fully persisted — can resume after any pause
- Frontend renders full timeline with all agent activity

**It doesn't work perfectly every time** — agents sometimes produce incomplete code, make wrong assumptions, or need multiple iterations. But the orchestration, tooling, and governance layer is solid.

---

## What Needs Improvement

### 1. Agent Skills & Capabilities

**Problem:** Agents are only as good as their prompts and available tools. They often produce subpar output because they lack the right primitives.

**Improvements:**
- [ ] Add `edit_file` to Coding MCP (currently only `write_file` — agents rewrite entire files for small changes)
- [ ] Add `read_multiple_files` to Coding MCP (agents can only read one file at a time)
- [ ] Add `search_files` / `grep` to Coding MCP (agents can't search for patterns across a codebase)
- [ ] Add `run_command` to Coding MCP (agents can't run linters, tests, or build commands in the workspace)
- [ ] Improve agent system prompts with better coding patterns, error handling guidance
- [ ] Add few-shot examples to agent definitions for common tasks
- [ ] Add `read_url` or `web_search` tool so agents can look up documentation

### 2. MCP Tool Reuse in Built Applications

**Problem:** We define MCP tools (coding, docker) for our agents, but the applications built by the developer agent can't use them. If a user asks for "an app that manages Docker containers," the developer writes code from scratch instead of leveraging our existing MCPs.

**Improvements:**
- [ ] Design an MCP SDK/client library that built applications can import
- [ ] Create a registry of available MCPs that applications can discover
- [ ] Expose MCP tools as REST APIs that applications can call (with auth)
- [ ] Generate client code for MCP tools in the target language (Python, JS)
- [ ] Propagate approval requirements to downstream MCP usage

### 3. Kubernetes Migration

**Problem:** Currently running on Docker Compose. Not production-ready for multi-user, multi-tenant, or scalable deployments.

**Improvements:**
- [ ] Containerize all services with proper health checks
- [ ] Create Kubernetes manifests (Deployments, Services, Ingress)
- [ ] Move MCP servers to K8s pods with proper resource limits
- [ ] Workspace isolation via ephemeral pods or PVCs
- [ ] Helm chart or Kustomize for environment management
- [ ] CI/CD pipeline for deployments
- [ ] Secrets management (Vault or K8s secrets)
- [ ] Horizontal scaling for MCP servers and backend

### 4. Sub-Agents

**Problem:** Agents execute linearly. A developer agent that needs to research, plan, code, and test does everything in one long run. Complex tasks would benefit from decomposition.

**Improvements:**
- [ ] Allow agents to spawn sub-agents (child agent runs)
- [ ] Sub-agent inherits parent context but has its own tool scope
- [ ] Parent agent can wait for sub-agent completion or continue
- [ ] Sub-agent results roll up to parent agent
- [ ] Tree-structured agent runs (currently flat sequence)
- [ ] Define sub-agent access in agent YAML

### 5. Model Selection per Agent

**Problem:** All agents currently use the same LLM model. Router and planner don't need the same model as developer. Some agents could use cheaper/faster models.

**Improvements:**
- [ ] Make `model` field in agent YAML actually route to different models
- [ ] Support multiple LLM providers simultaneously
- [ ] Model tiers: fast/cheap for router/planner, capable for developer/architect
- [ ] Cost tracking per model
- [ ] A/B testing framework for model comparisons
- [ ] Fallback chains: try Model A, fall back to Model B on failure

### 6. MCP Authorization

**Problem:** MCP servers currently trust any caller with the right session context. No authentication between services.

**Improvements:**
- [ ] Add JWT/token auth to MCP server endpoints
- [ ] Centralized auth middleware (single codebase for all MCPs)
- [ ] Per-user, per-project permission scoping
- [ ] Rate limiting per agent/session
- [ ] Audit logging for all MCP calls
- [ ] mTLS between backend and MCP servers

### 7. Workflows (Automated Execution Plans)

**Problem:** The planner creates plans from scratch every time. Common patterns (deploy a React app, add a REST endpoint) could be pre-defined workflows.

**Improvements:**
- [ ] Define workflow templates in YAML (sequence of agents + MCP tools)
- [ ] Planner can select a workflow instead of building a plan from scratch
- [ ] Workflows can include conditional steps, branching logic
- [ ] Workflows can call MCP tools directly (no agent needed for simple operations)
- [ ] Workflow library: common patterns like "scaffold project", "add feature", "deploy update"
- [ ] User-defined workflows via UI

### 8. Parallel Agent Execution

**Problem:** Agents execute strictly sequentially. Business analyst and architect could potentially run in parallel. Multiple developers could work on different files simultaneously.

**Improvements:**
- [ ] Add parallel execution support to the orchestrator
- [ ] Planner can specify parallel groups in the plan
- [ ] Dependency graph: agent B starts when agent A completes
- [ ] Workspace-level locking for parallel file operations
- [ ] Merge strategies for parallel git operations
- [ ] Fan-out/fan-in patterns: spawn N agents, collect all results

### 9. Real-Time Updates (WebSocket)

**Problem:** Frontend polls every 0.5s. This is wasteful and introduces latency. No streaming of LLM output.

**Improvements:**
- [ ] WebSocket connection for session updates
- [ ] Stream LLM tokens to frontend in real-time
- [ ] Push notifications for approval requests
- [ ] Live agent status updates
- [ ] Reduce server load from polling

### 10. Observability & Debugging

**Problem:** When things go wrong, it's hard to diagnose. Debug pages exist but are rudimentary.

**Improvements:**
- [ ] Structured logging with correlation IDs (session_id, agent_run_id)
- [ ] OpenTelemetry tracing across backend → MCP servers
- [ ] LLM call replay: re-run an agent with the same context
- [ ] Cost dashboard: token usage per agent, per session, per user
- [ ] Agent performance metrics: success rate, average iterations, common failures
- [ ] Error categorization: LLM error vs. tool error vs. logic error

### 11. Testing & Reliability

**Problem:** Test coverage is minimal. Agent behavior is non-deterministic. Hard to regression test.

**Improvements:**
- [ ] End-to-end test suite with mock LLM provider
- [ ] Golden test cases: known inputs → expected agent behavior
- [ ] MCP server unit tests
- [ ] Integration tests for approval/HITL flows
- [ ] Chaos testing: what happens when MCP server is down mid-execution?
- [ ] Retry logic for transient failures (LLM timeouts, MCP errors)

### 12. Multi-Tenancy & User Experience

**Problem:** Single-tenant setup. No team collaboration. Limited project management.

**Improvements:**
- [ ] Team/organization support
- [ ] Shared projects with role-based access
- [ ] Session handoff between users
- [ ] Project templates
- [ ] Notification system for approvals
- [ ] Mobile-friendly UI

---

## Priority Ranking

| Priority | Item | Impact | Effort |
|----------|------|--------|--------|
| **P0** | Coding MCP improvements (edit_file, read_multiple, search, run_command) | High — directly improves agent output quality | Medium |
| **P0** | Model selection per agent | High — cost savings + better results per task | Low |
| **P1** | Sub-agents | High — unlocks complex task decomposition | High |
| **P1** | MCP authorization | High — security requirement for any real deployment | Medium |
| **P1** | Workflows | High — reduces LLM cost, improves reliability for common tasks | Medium |
| **P1** | Parallel agent execution | Medium — speeds up multi-agent flows | High |
| **P2** | MCP reuse in built apps | High — major differentiator, but complex | High |
| **P2** | Kubernetes migration | High — required for production | High |
| **P2** | WebSocket real-time updates | Medium — better UX, less server load | Medium |
| **P2** | Observability | Medium — needed for debugging at scale | Medium |
| **P3** | Testing & reliability | Medium — long-term investment | High |
| **P3** | Multi-tenancy | Medium — needed for growth | High |
