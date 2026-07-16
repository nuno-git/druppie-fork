# Coding Agent Improvement: Reliable Application Building

**Epic:** Coding Agent Quality
**Story:** Deliver a coding agent that can reliably build real applications end-to-end, backed by a clean agent runtime that natively supports subagents, per-agent sandboxes, and done() enforcement.

---

## Background & Context

We want coding agents that work. Not sometimes, not with luck, but reliably. Agents that can take a specification and build a working application without crashing, stopping mid-task, or requiring constant human babysitting.

We've tried twice. Both attempts taught us something.

### Phase 1: OpenCode / background-agents

The first attempt used OpenCode (open-inspect/background-agents) running inside sandbox containers (Kata/Sysbox). The idea was solid: a server-first coding agent runtime in isolated containers. In practice, the coding agent would randomly crash, stop mid-task, or fail silently. The architecture was complex (Cloudflare Workers + Modal + WebSocket bridges) with many failure modes: sandbox spawn failures, snapshot restore failures, stale heartbeats, WebSocket reconnection issues, OpenCode process crashes. For a governance platform that needs predictable execution, this was not workable.

### Phase 2: Standalone TypeScript agent (legacy, removed)

A standalone TypeScript agent was built as a prototype. It used an "agent-out, sandbox-as-tool" pattern: orchestrator on the host, LLM calls on the host, file and bash operations RPC'd into a sandbox container via a Python daemon. It had 5 agents (analyst, planner, builder, verifier, pr-author) with a phase loop and retry logic.

The problem: it was a completely separate system from Druppie's agent framework. Its own agent definitions (.md files with YAML frontmatter), its own tool system, its own flow execution, no concept of governance or approval workflows. Making it work within Druppie's session flow required ugly glue code, and it never felt like a native part of the system. This was replaced by native sandbox-based execution via the agent runtime.

### Phase 3 (current): Native coding agents in Druppie's runtime

The decision: stop bolting on external coding agent frameworks. Instead, refactor Druppie's own agent runtime so it can support coding agents natively. Coding agents become just another type of agent in the system. Same runtime, same governance, same approval workflows as business analysts and architects. The runtime gets the capabilities coding agents need: subagent spawning, per-agent sandbox containers, enforced completion.

---

## What We're Doing

### Foundation: Agent Runtime Refactor

The prerequisite. Druppie's agent runtime needs to be clean, reusable, and capable of supporting coding agents with sandbox access. This is the infrastructure work that makes reliable coding agents possible.

The unified runtime (`druppie/execution/agent_runtime/`) is a Python library providing:

- Turn-based LLM interaction with tool execution
- `done()` enforcement: agents MUST call `done()` to exit. The loop forces it mechanically if they don't.
- Subagent spawning: agents can spawn child agents inline
- Per-agent sandbox containers via MCP
- Context overflow handling
- Cancellation support
- Storage-agnostic design: event callbacks for persistence, no direct DB access

Subagents are defined in YAML (`subagents: [builder, tester]`). When an agent calls the `subagents()` tool, the runtime spawns child AgentLoop instances. Two-layer validation (schema enum + server-side), depth limit of 10, circular reference detection. Subagents run inline (parent waits), not DB-driven like planner scheduling.

Each agent that needs file access gets its own sandbox container via a Sandbox MCP server. Agents sharing the same git scope share the same container. A warm pool of pre-started containers handles performance. The sandbox provides tools like `read_file`, `write_file`, `bash`, `push_changes`, and `make_design`.

### Goal: Coding Agents That Work

The actual point. With the runtime foundation in place, coding agents should be able to:

- Build real applications end-to-end (like vergunningzoeker) without crashing or stopping randomly
- Coordinate through a hierarchy: developer spawns coding_planner, which spawns builder(s) and tester(s) in parallel, all sharing the same sandbox container
- Participate in governance workflows: HITL approval gates during coding, same approval flows as other agents
- Recover from errors: build failures, test failures, tool errors, all handled gracefully instead of silently dying

```
developer -> coding_planner -> [builder(s), tester(s)]
```

The developer is a regular agent in the Druppie session flow. It spawns `coding_planner` as a subagent, which in turn spawns builders and testers in parallel. All share the same sandbox container (same git scope).

---

## Acceptance Criteria

**Coding agent reliability:**
- [ ] Coding agent can build the vergunningzoeker application end-to-end without crashing
- [ ] Coding agent does not randomly stop or crash during execution
- [ ] HITL (human-in-the-loop) approval works correctly during coding tasks
- [ ] Coding agents use the same governance and approval workflows as other agents (no special paths)

**Subagent hierarchy:**
- [ ] Subagent spawning works: developer spawns coding_planner, which spawns builder(s) and tester(s)

**Sandbox integration:**
- [ ] Sandbox containers are created per-agent and shared when agents have the same git scope

**Runtime quality:**
- [ ] All existing agents (router, planner, business_analyst, architect, developer, summarizer) continue to work as before
- [ ] `done()` enforcement works: agents cannot exit without calling `done()`, and the loop forces it if they try
- [ ] Agent runtime is storage-agnostic: no direct DB access from the runtime library
- [ ] The agent runtime library is reusable by external applications, not just Druppie internals

---

## Coding Agent Improvement Areas

The runtime refactor is the foundation. The next step is iterating on coding agent quality itself. These are the areas we want to improve, building on top of the new runtime.

### Agent flow and coordination
Better handoffs between planner, builder, and tester. When should the planner create one builder vs. many? How does the tester know what to verify? How do builders working on related files coordinate?

### Skill development
What skills do coding agents actually need? File reading, bash execution, and PR creation are the basics. What about design generation, dependency management, or test framework setup? Skills should be modular and composable.

### Prompt engineering
Better system prompts for coding tasks. Prompts that give the agent clear structure: understand the spec, plan the implementation, write code incrementally, verify as you go. Prompts that handle ambiguity gracefully instead of spiraling.

### Error recovery
What happens when a build fails? When tests fail? When a tool returns an error? The agent should diagnose, fix, and retry, not crash or give up. This includes recognizing when to ask for human help vs. when to try again autonomously.

### Iterative refinement
Verifier loops and fix-and-retry cycles. The coding agent should be able to run its own tests, see what fails, fix it, and try again. Multiple rounds of build-test-fix until the application works.

### Multi-file coordination
When builders work on related files in parallel, they need to stay consistent. Shared conventions for imports, interfaces, and data structures. The planner should generate contracts that builders follow.

---

## Technical Notes

- All tools are served via MCP servers. Four types: sandbox, core-tools, subagents, docker.
- Agent definitions live in YAML files (`agents/definitions/*.yaml`), not in the database or in code.
- `done()` is mechanically enforced. The loop injects a system message forcing completion if the agent doesn't call it.
- Subagents run inline within the parent's execution context. The parent agent waits for all children to complete.
- Credentials never enter sandbox containers.
- No JSON/JSONB columns. No database migrations. Schema changes go through SQLAlchemy model updates + DB reset.

---

## Out of Scope

- Migrating legacy test suites from the old sandbox prototype to the new runtime
- Building a visual agent flow editor or DAG UI
- Multi-agent negotiation or voting protocols
- Persistent sandbox state across sessions (beyond git commits)
- Cost tracking or token budget enforcement per agent run
- Agent marketplace or third-party agent loading

---

## References

- `docs/TECHNICAL.md` §11 (Agent Runtime Library) — As-built runtime reference (canonical)
- `docs/reference/agent-runtime.md` — Full runtime specification (historical design detail)
- `background-agents/` — Original background-agents system (legacy reference)
- `druppie/execution/agent_runtime/` — Runtime implementation
- `druppie/agents/definitions/` — Agent YAML definitions
