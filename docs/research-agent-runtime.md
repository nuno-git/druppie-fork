# Agent Runtime Research — Architecture Decisions

> **Status**: Research (pending decisions)
> **Goal**: Replace `druppie/agents/loop.py` and the old sandbox-based execution prototype with a unified Python agent runtime library
> **Key property**: `done()` enforcement at the loop level — agents CANNOT exit without calling done()

---

## 1. Current Architecture (What We Have)

### Two Separate Agent Runtimes

| | Core Runtime (`loop.py`) | Old Sandbox Prototype |
|---|---|---|
| Language | Python | TypeScript (legacy, removed) |
| LLM calls | `druppie/llm/litellm_provider.py` | Separate SDK |
| Tool access | MCP servers (coding, docker, etc.) | Sandbox HTTP daemon (raw REST) |
| Agents | router, BA, AR, developer, builder, test_executor, deployer, summarizer | planner, builder, tester, verifier, pusher, explorer, router |
| done() enforcement | None — prompt-only | None — prompt-only |
| Subagents | No | Yes |
| Lifecycle | Per-session, shared MCP connections | Per `execute_coding_task` call, fresh sandbox |

### Tool Access Layers (Current)

Agents get tools from THREE sources:

```
1. Builtin tools     → done, hitl_ask_question, execute_coding_task, invoke_skill, set_intent, make_plan
2. MCP tools         → coding (read_file, write_file, bash, ...), docker (build, run, ...), web, archimate
3. Skill-granted     → invoke_skill("code-review") → unlocks coding:read_file + coding:list_dir
```

Each source has different registration, execution, and permission logic.

### Tool Scoping (New Architecture)

| MCP Server | Scope | How Context Isolation Works |
|------------|-------|----------------------------|
| **Sandbox MCP** (per agent) | Per-agent — 1 container per agent run | Complete isolation. Own filesystem. Synced via Git (fetch/pull at start, commit/push at end). |
| **Docker MCP** (port 9002) | Global — 1 shared server | For infrastructure deployment (build, run, compose_up). Sandboxes can't access host Docker. |
| **Core-tools MCP** | Global — 1 shared server | Druppie session management (hitl, plan, intent, skill, execute_coding_task). |
| **Web MCP** | Global — 1 shared server | Stateless. No context needed. |

### Skills System (Current)

Skills are **reusable instruction + tool-grant bundles** in `druppie/skills/<name>/SKILL.md`:

```yaml
---
name: code-review
description: Reviews code for quality, security, and best practices
allowed-tools:
  coding:
    - read_file
    - list_dir
---
# Skill instructions in markdown...
```

Flow:
1. Agent YAML declares `skills: [code-review, git-workflow]`
2. `invoke_skill` builtin tool is added to the agent's tool list (with enum constrained to declared skills)
3. LLM calls `invoke_skill(skill_name="code-review")` → gets skill instructions as tool result
4. Skill's `allowed-tools` EXPAND the agent's available MCP tools dynamically
5. LLM can now use tools it couldn't access before (e.g., coding:read_file for an agent that didn't have it in `mcps:`)

Skills are a **secondary access path** — they unlock tools the agent doesn't have in its YAML.

### Agent Definition Format (Current)

All 30+ fields in `AgentDefinition` (`druppie/domain/agent_definition.py`):

| Field | Type | Purpose |
|-------|------|---------|
| `id`, `name`, `description` | str | Identity |
| `category` | str | Organizational tag |
| `system_prompt` | str | Main instructions |
| `system_prompts` | list[str] | Named fragments from `system_prompts/*.yaml` |
| `skills` | list[str] | Skills the agent can invoke |
| `mcps` | list or dict | MCP servers + optional tool whitelist |
| `extra_builtin_tools` | list[str] | Builtin tools to add (on top of done + hitl) |
| `excluded_builtin_tools` | list[str] | Builtin tools to remove |
| `sandbox_constraints` | object | Limits on sandbox agents/targets |
| `approval_overrides` | dict | Per-tool approval settings |
| `allowed_next_agents` | list[str] | Agents this agent can route to |
| `completion_preconditions` | list | Required tool calls before done() |
| `required_summary_status` | object | Required keywords in done() summary |
| `llm_profile`, `temperature`, `max_tokens`, `max_iterations` | various | LLM settings |

---

## 2. Questions and Decisions

### Decision 1: Skills — How Should They Work in the New Runtime?

**Current behavior**: Skills are a builtin tool (`invoke_skill`) that returns instructions AND dynamically expands the agent's available MCP tools.

**Option A: Keep as-is (builtin meta-tool)**
- `invoke_skill` remains a builtin tool
- When called, loads SKILL.md content, returns it, and expands tool set
- Agent runtime handles tool expansion dynamically
- Pro: Preserves existing behavior, on-demand loading
- Con: Skills are special-cased, not regular tools

**Option B: Skills are resolved at agent startup, not on-demand**
- Agent YAML declares `skills: [code-review]`
- At agent startup, ALL declared skills are loaded
- Skill instructions are appended to the system prompt
- Skill `allowed-tools` are added to the initial tool set
- No `invoke_skill` tool needed
- Pro: Simpler — skills are just prompt + tool grants, resolved once
- Con: Loses on-demand aspect, loads all skills even if unused (wastes context)

**Option C: Skills are MCP tools on a "skills" MCP server**
- Create a skills MCP server that exposes each skill as a tool
- `invoke_skill("code-review")` becomes a regular MCP call
- But tool expansion still needs agent runtime support
- Pro: Unified protocol, discoverable
- Con: Over-engineered, tool expansion is still special

**Recommendation**: Skills become MCP tools on the Druppie core-tools MCP server. The agent runtime supports generic dynamic tool expansion — if ANY MCP tool result contains `allowed-tools`, the runtime expands the available tool set. This is not Druppie-specific; any MCP server can use this mechanism.

**Tool expansion schema** (Proposal A):
```json
{
    "content": "Skill instructions in markdown...",
    "allowed_tools": {
        "sandbox": ["read_file", "list_dir"]
    }
}
```

The runtime sees `allowed_tools`, finds the matching MCP connection name from `mcp_connections`, and adds those specific tools to the LLM's visible tool list.

**SKILL.md migration**: All existing skills reference `coding:` as the MCP server name. Bulk-update all SKILL.md files: `coding:` → `sandbox:`. This is a simple find-and-replace since the tool names stay the same, only the MCP connection name changes.

---

### Decision 2: Tool Scoping — REMOVED

**Status**: Superseded by D19.

D2 originally described a "hybrid" approach with shared coding MCP for core agents. D19 removes the shared coding MCP entirely — all file operations go through per-agent sandboxes. The tool scoping is now:

- **Per-agent sandbox MCP** — for ALL file operations (read, write, bash, git, etc.)
- **Shared Docker MCP** — for infrastructure deployment (build, run, compose_up)
- **Shared core-tools MCP** — for Druppie session management (hitl, plan, intent, skill, etc.)
- **Shared Web/Archimate MCP** — for stateless tools

**Subagent sandbox sharing rule**: Top-level agents each get their own sandbox container. Subagents spawned within a parent agent (via the `subagents` builtin) SHARE the parent's sandbox container — they do NOT get their own.

Example:
```
developer agent  → own sandbox container A
   └─ subagents({agent: "coding_planner"}) → coding_planner gets own sandbox B (agent definition has sandbox in mcps)
        ├─ builder subagent  → shares sandbox B with planner
        ├─ tester subagent   → shares sandbox B with planner
        └─ verifier subagent → shares sandbox B with planner
```

---

### Decision 3: Sandbox MCP Server — How Should the Sandbox Expose Tools?

**Current (legacy)**: The old sandbox daemon spoke raw HTTP (POST /read, POST /exec, etc.). The legacy prototype called it directly.

**We agreed**: Make the sandbox speak MCP so there's ONE provider class.

**How to implement**:

| Option | Description | Effort |
|--------|-------------|--------|
| **A: Run coding MCP server inside sandbox** | The existing `druppie/mcp-servers/coding/` runs inside the container. Already has all file ops. Add sandbox-specific tools (git init, bundle import/export) as extra MCP tools. | Low — reuse existing server |
| **B: Thin MCP wrapper around daemon** | A 50-line FastMCP server that proxies MCP calls to the sandbox daemon's HTTP endpoints. | Low — new but simple |
| **C: Replace daemon with native MCP** | Remove the daemon entirely. The MCP server does filesystem operations directly (it's inside the container, it has access). | Medium — need to handle SSE streaming for bash |

**Recommendation**: Option A. The coding MCP server already does everything the sandbox needs. Just run it inside the container and add 2-3 sandbox-specific tools.

---

### Decision 4: Subagents — How Does the Runtime Handle Them?

**Current (legacy prototype)**: The old prototype used a `subagents()` tool that accepted `tasks: [{agent, task}]` and spawned agents recursively, sharing the same sandbox client.

**Key insight from user**: Subagents should NOT share the parent's ToolProvider. Each agent declares its own `mcps` in its definition. The runtime resolves tool access per-agent.

#### Per-Agent Tool Resolution

Each agent definition declares its own tool access. The runtime resolves this per-agent:

```python
# run() receives agent definitions + MCP connections, NOT a single ToolProvider
result = await agent_loop.run(
    agent=planner_definition,
    agent_loader=lambda name: load_definition(name),  # resolves subagents
    mcp_connections={
        "sandbox": MCPClient("http://sandbox-xyz:9001"),
        "core-tools": MCPClient("http://core-tools:9003"),
    },
    prompt="...",
    llm=llm_client,
)
```

When planner calls `subagents({agent: "builder", task: "..."})`:
1. Loop calls `agent_loader("builder")` → builder_definition
2. builder_definition.mcps = `{sandbox: [read, write, edit, bash, grep, find, ls]}`
3. Loop resolves against `mcp_connections` → scoped ToolProvider for builder
4. Recursive `run(builder_definition, task, scoped_provider, llm)`

Each agent gets exactly the tools its definition declares:

```
planner      → mcps: {}                                    → done + subagents only
  ├─ builder  → mcps: {sandbox: [read, write, edit, bash]}  → implements code
  ├─ tester   → mcps: {sandbox: [read, bash, grep]}         → runs tests
  ├─ verifier → mcps: {sandbox: [read, bash]}               → builds & verifies
  └─ pusher   → mcps: {sandbox: [push_to_remote, create_pr]}→ pushes code
```

All hit the same sandbox MCP server — but each agent only sees its declared tools.
The LLM can't use tools outside its scope.

#### Why Not Share ToolProvider?

Shared ToolProvider means shared tool access:
- Builder would see `push_to_remote` (from pusher's scope) — shouldn't have it
- Tester would see `write` (from builder's scope) — tester is read-only
- Planner would see ALL tools — it's an orchestrator, shouldn't touch files

Per-agent resolution means the agent definition is the **single source of truth** for tool access.

#### Subagent Event Tracking

- `subagent_start` / `subagent_end` events with `parentAgentId` linkage
- Same as the old sandbox journal pattern
- Caller subscribes via event callbacks → writes to DB or logs

---

### Decision 5: What Stays as Builtin Tools vs MCP Tools?

**Current builtin tools** (defined in `druppie/agents/builtin_tools.py`):

| Tool | Purpose | Should be... |
|------|---------|-------------|
| `done` | Mark work complete | **Builtin** — enforced by the loop. The loop can't work without this. |
| `hitl_ask_question` | Ask user a question | **Builtin** — needs session context, not a file operation |
| `hitl_ask_multiple_choice_question` | Ask user a multiple choice | **Builtin** — same |
| `invoke_skill` | Load skill instructions + expand tools | **Builtin** — meta-tool that changes tool availability |
| `execute_coding_task` (legacy) | **REMOVED** — replaced by recursive subagents (D27) | |
| `set_intent` | Router sets intent | **Builtin** — session management |
| `make_plan` | Planner creates plan | **Builtin** — session management |
| `create_message` | Summarizer creates message | **Builtin** — session management |
| `test_report` | Test executor reports results | **Builtin** — session management |

**Pattern**: Tools that need session/project context OR change tool availability are builtin. Tools that do file/infrastructure operations are MCP.

**For the sandbox coding subagents** (builder, tester, verifier, pusher):

| Tool | Purpose | Should be... |
|------|---------|-------------|
| `done` (sandbox version) | Mark subagent complete | **Builtin** — same as core done |
| `subagents` | Spawn child agents | **Builtin** — meta-tool, recursive loop call |
| `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls` | File operations in sandbox | **MCP** — from sandbox MCP server |
| `push_to_remote` | Git push | **MCP** — from sandbox MCP server (or git MCP) |
| `create_pr` | Create pull request | **MCP** — from git provider |

**Decision needed**: Should `push_to_remote` and `create_pr` be MCP tools on the sandbox MCP server, or separate builtin tools?

**Recommendation**: MCP tools. The sandbox MCP server can expose git operations as MCP tools. This keeps the runtime clean — only done, hitl, skill, and subagents are builtin.

---

### Decision 6: Agent Definition Unification

**Current**: Two definition formats:
- Core agents: YAML files with 30+ fields (`druppie/agents/definitions/*.yaml`)
- Coding subagents: Markdown files with frontmatter (legacy format)

**Should we unify?**

**Option A: Keep both formats, support both in the runtime**
- The definition loader can parse both YAML and .md-with-frontmatter
- Pro: No migration needed
- Con: Two formats to maintain

**Option B: Migrate coding subagents to YAML**
- Move legacy sandbox agent definitions to `druppie/agents/definitions/`
- Use the same YAML format
- Pro: One format, one loader
- Con: Migration effort

**Option C: Migrate everything to .md-with-frontmatter**
- Use the legacy sandbox format for all agents
- Pro: Markdown is better for long system prompts
- Con: Loses YAML-specific features (complex nested fields)

**Recommendation**: Option B. YAML already supports all the fields. Coding subagents are simpler (fewer fields) so migration is trivial. And they should live in the backend anyway (user said "for the backend agents, directly in the backend").

---

### Decision 7: Event System — How Does the Runtime Communicate Progress?

**Current (core)**: `AgentLoop` writes directly to DB (ToolCall model, timeline entries).
**Current (legacy)**: Old sandbox prototype logged journal events via HTTP POST to a backend ingest endpoint → DB.

**For the new runtime**:
```python
# Event callbacks — the caller subscribes
async def on_event(event: AgentEvent):
    # Backend: write to DB
    # Application: log/display
    pass

result = await agent_loop.run(
    agent_def,
    prompt,
    tool_provider,
    event_callbacks=[on_event],
)
```

**Event types needed**:
- `turn_start` / `turn_end` — per LLM turn
- `tool_call` / `tool_result` — per tool invocation
- `subagent_start` / `subagent_end` — per subagent spawn (with `parent_agent_id` and `depth` fields for nesting)
- `done` — when done() is called
- `llm_retry` — when the LLM call is retried (from D16)
- `enforcement_retry` — when the loop forces another turn because done() wasn't called
- `error` — on exceptions

**Decision needed**: Do we need ALL these events, or a subset?

**Recommendation**: Start with tool_call, tool_result, subagent_start, subagent_end, done, llm_retry, enforcement_retry. Add more as needed.

---

### Decision 8: LLM Client — Use LiteLLM Directly

**Current**: Backend has `druppie/llm/` with `ChatLiteLLM` that supports `achat(messages, tools)` and returns `LLMResponse` with `tool_calls`.

**For the new runtime**: The runtime does NOT define a custom LLMClient protocol. Instead, it accepts a standard litellm `acompletion()` callable, configured by the caller.

**Key points**:
- The runtime accepts a standard litellm `acompletion()` callable, configured by the caller
- The caller (Druppie backend) already has ChatLiteLLM + FallbackLLM wrapping litellm (in `druppie/llm/`)
- The runtime just calls `await llm(messages=..., tools=..., **kwargs)` and gets a standard response
- LLM profile resolution (which model, which provider, fallbacks) is handled entirely by the CALLER, not the runtime
- The runtime receives a pre-configured litellm callable — it doesn't know about profiles, fallbacks, or providers

**Loop.run() signature**:
```python
async def run(
    self,
    agent: AgentDefinition,
    agent_loader: Callable[[str], AgentDefinition],
    mcp_connections: dict[str, MCPClient],
    prompt: str,
    llm: Callable,  # litellm.acompletion or wrapper — configured by caller
    event_callbacks: list[EventCallback] = [],
    config: LoopConfig = LoopConfig(),
    cancellation_token: CancellationToken | None = None,
) -> AgentResult
```

Note: `llm` is just `Callable` — any async callable that takes messages and returns a standard litellm response. No custom protocol. The caller wraps ChatLiteLLM/FallbackLLM around it.

**Recommendation**: The runtime is agnostic to LLM implementation — it just expects a callable with the litellm signature.

---

## 3. Proposed Architecture

### Package Structure

```
druppie/agent_runtime/
├── __init__.py              # Public API
├── types.py                 # AgentResult, DoneResult, LoopConfig, AgentState, ToolCallRecord, events list
├── loop.py                  # AgentLoop — the core loop with done() enforcement
├── definition.py            # AgentDefinition loader (YAML + MD frontmatter)
├── events.py                # EventEmitter — callback registry
└── tools/
    ├── __init__.py
    └── base.py              # ToolProvider ABC, done tool, subagents tool
```

### The Loop (simplified)

```python
class AgentLoop:
    async def run(
        self,
        agent_def: AgentDefinition,
        agent_loader: Callable[[str], AgentDefinition],
        mcp_connections: dict[str, MCPClient],
        prompt: str,
        llm: LLMClient,
        event_callbacks: list[EventCallback] = [],
        config: LoopConfig = LoopConfig(),
    ) -> AgentResult:

        # 1. Build tool list: provider tools + builtin (done, subagents)
        # 2. Run loop
        #    - Call LLM
        #    - If tool_calls: execute, check for done()
        #    - If text-only: INJECT ERROR, continue (enforcement)
        #    - If max_turns: retry with short budget
        #    - If retries exhausted: auto-generate done result
        # 3. Return AgentResult
```

### How Each Agent Type Uses It

**Core agents (BA, AR, developer):**
```python
# Backend code
tool_provider = MCPToolProvider(
    mcp_client=MCPClient("http://module-coding:9001"),
    injection_rules=mcp_config["coding"]["inject"],
    context={"session_id": session.id, "project_id": project.id, ...}
)
result = await agent_loop.run(ba_definition, prompt, tool_provider, llm)
# Backend stores result in DB
```

**Sandbox coding agents (planner → builder → tester → verifier → pusher):**
```python
# Backend code (inside execute_coding_task)
tool_provider = MCPToolProvider(
    mcp_client=MCPClient(f"http://sandbox-{sandbox_id}:9001"),
    context={"sandbox_id": sandbox_id}
)
result = await agent_loop.run(planner_definition, prompt, tool_provider, llm)
# planner can spawn subagents via the subagents builtin tool
# subagents each get their own scoped ToolProvider resolved from their agent definition's mcps
# they all point to the same sandbox MCP server, but each agent only sees its declared tools
```

**Applications:**
```python
# Application code
tool_provider = MCPToolProvider(
    mcp_client=MCPClient("http://module-ocr:9010"),
    context={"app_id": app_id, "user_id": user_id}
)
result = await agent_loop.run(my_agent_definition, prompt, tool_provider, my_llm)
# Application stores result however it wants
```

### What Gets Removed

| Component | Replaced by |
|-----------|-------------|
| `druppie/agents/loop.py` | `agent_runtime.loop.AgentLoop` |
| Legacy `pi_agent/` (TypeScript codebase) | `agent_runtime.loop.AgentLoop` |
| `@mariozechner/pi-coding-agent` SDK | Nothing — loop is pure Python |
| Legacy pi_agent journal.ts (HTTP ingest) | Event callbacks → direct DB writes |
| Legacy pi_agent sandbox-ops.ts (raw HTTP) | Sandbox MCP server |
| Legacy pi_agent done.ts | Built into the loop |
| Legacy pi_agent subagents.ts | Built into the loop |
| `execute_coding_task` (legacy) | REMOVED — replaced by recursive subagents (D27) |
| `druppie/mcp-servers/coding/` (global coding MCP, port 9001) | REMOVED — replaced by per-agent sandbox MCP |

### What Stays

| Component | Change needed |
|-----------|---------------|
| `druppie/llm/` (ChatLiteLLM, profiles, fallback) | None — passed to the runtime |
| `druppie/skills/` (SKILL.md files) | None — loaded by builtin invoke_skill |
| `druppie/agents/definitions/*.yaml` | None — loaded by definition.py |
| `druppie/agents/definitions/system_prompts/*.yaml` | None — loaded by definition.py |
| `druppie/agents/builtin_tools.py` | Refactored — extract execute_coding_task, hitl tools |
| `druppie/execution/tool_executor.py` | Simplified — provider handles execution |
| `druppie/execution/mcp_http.py` | Replaced by MCPToolProvider |
| `druppie/mcp-servers/coding/` | Also runs inside sandbox containers |

---

## 4. Implementation Phases

### Phase 1: Core Library (testable in isolation)
- `types.py`, `definition.py`, `events.py`, `tools/base.py`, `loop.py`
- Tests with mock LLM + mock ToolProvider
- done() enforcement verified in tests
- Subagent recursion verified in tests

### Phase 2: MCPToolProvider + Sandbox MCP
- `MCPToolProvider` in the backend (wraps official MCP client)
- Make sandbox speak MCP (run coding MCP server inside container)
- Integration test: provider → MCP server → real operations

### Phase 3: Replace Core Agent Loop
- Backend creates `AgentLoop` with `MCPToolProvider` for core agents
- Migrate builtin tools (done, hitl, invoke_skill, execute_coding_task)
- All core agents go through new loop
- E2E test: full pipeline (router → BA → AR → developer)

### Phase 4: Replace Legacy Sandbox Agents
- Backend creates `AgentLoop` with sandbox `MCPToolProvider` for coding agents
- Move legacy sandbox agent definitions to backend YAML format
- Subagent support verified: planner → builder → tester → verifier → pusher
- E2E test: execute_coding_task with planner flow

### Phase 5: Remove Legacy Prototype
- Delete legacy `pi_agent/` directory
- Remove Node.js from sandbox
- Update Docker Compose
- Clean up legacy pi_agent_runner.py

---

## 5. The Builtin vs MCP Question — Deep Analysis

### The Core Problem

If `hitl_ask_question`, `make_plan`, `set_intent` are **builtin tools** baked into the agent runtime library:

```
druppie/agent_runtime/loop.py  ←  contains hitl_ask_question, make_plan, set_intent
         │
         ├── Used by Druppie backend  →  Works! Has sessions, projects, etc.
         │
         └── Used by Application       →  BROKEN. No session management. 
                                           What does hitl_ask_question even mean 
                                           in an app that has no Druppie session?
```

The library becomes Druppie-specific. Applications can't use it cleanly.

### Three Approaches

#### Approach A: Builtin Tools (Current + My Earlier Proposal)

```
┌──────────────────────────────────────┐
│         Agent Runtime Library         │
│                                      │
│  Builtins:                           │
│    ✅ done()        — exit signal     │
│    🔧 hitl_ask     — ask user        │
│    🔧 make_plan    — create plan     │
│    🔧 set_intent   — set intent      │
│    🔧 invoke_skill — load skills     │
│    🔧 execute_coding_task           │
│    🔧 create_message                │
│    🔧 test_report                   │
│                                      │
│  Problem: 7 of 8 builtins are        │
│  Druppie-specific. Not reusable.     │
└──────────────────────────────────────┘
         │                    │
    ┌────▼────┐         ┌────▼────┐
    │ Druppie │         │  App    │
    │  Has    │         │  No     │
    │sessions │         │sessions │
    │  ✅     │         │  ❌     │
    └─────────┘         └─────────┘
```

**Verdict**: Not reusable. The library is Druppie-specific.

---

#### Approach B: All Tools Are MCP (Pure)

```
┌──────────────────────────────────────┐
│         Agent Runtime Library         │
│                                      │
│  The library knows about:            │
│    ✅ "done" tool name (enforced)    │
│    ✅ "subagents" tool (recursive)   │
│    ❌ Nothing else                   │
│                                      │
│  ALL tools come from ToolProvider:   │
│    (which is an MCP connection)      │
└──────────────────────────────────────┘
         │                    │
    ┌────▼──────────┐   ┌────▼──────────┐
    │   Druppie     │   │  Application  │
    │               │   │               │
    │ Connects to:  │   │ Connects to:  │
    │ ┌───────────┐ │   │ ┌───────────┐ │
    │ │core-tools │ │   │ │app-tools  │ │
    │ │ MCP server│ │   │ │ MCP server│ │
    │ │           │ │   │ │           │ │
    │ │ • done    │ │   │ │ • done    │ │
    │ │ • hitl    │ │   │ │ • search  │ │
    │ │ • plan    │ │   │ │ • read_db │ │
    │ │ • intent  │ │   │ │ • notify  │ │
    │ │ • skill   │ │   │ │ • custom  │ │
    │ └───────────┘ │   │ └───────────┘ │
    │ ┌───────────┐ │   │               │
    │ │coding MCP │ │   │  App picks    │
    │ │ • read    │ │   │  whatever     │
    │ │ • write   │ │   │  tools it     │
    │ │ • bash    │ │   │  needs        │
    │ └───────────┘ │   │               │
    │ ┌───────────┐ │   │               │
    │ │docker MCP │ │   │               │
    │ │ • build   │ │   │               │
    │ └───────────┘ │   │               │
    └───────────────┘   └───────────────┘
```

**The library is truly generic.** Druppie puts its tools on MCP servers. Applications put their tools on MCP servers. The library doesn't care.

**But**: Every caller MUST provide a `done` tool via their MCP server. The library only enforces that `done` is called — it doesn't define what `done` does.

**Problem**: Forgetting to add `done` to the MCP server means the loop runs forever. The library needs a fallback.

---

#### Approach C: Minimal Builtin + All Others MCP (Recommended)

```
┌──────────────────────────────────────┐
│         Agent Runtime Library         │
│                                      │
│  The library provides:               │
│    ✅ done()        — ALWAYS present, │
│                       minimal version │
│    ✅ subagents()   — if agent has    │
│                       spawn list      │
│                                      │
│  The library does NOT provide:       │
│    ❌ hitl_ask_question              │
│    ❌ make_plan                      │
│    ❌ set_intent                     │
│    ❌ invoke_skill                   │
│    ❌ execute_coding_task            │
│                                      │
│  These come from MCP servers.        │
└──────────────────────────────────────┘
         │                    │
    ┌────▼──────────┐   ┌────▼──────────┐
    │   Druppie     │   │  Application  │
    │               │   │               │
    │ ToolProviders:│   │ ToolProviders:│
    │               │   │               │
    │ MCP 1: core-  │   │ MCP 1: their  │
    │   tools       │   │   own MCP     │
    │   • hitl_ask  │   │   server      │
    │   • make_plan │   │   • search    │
    │   • set_intent│   │   • read_db   │
    │   • skill     │   │   • notify    │
    │   • exec_code │   │               │
    │               │   │ Done: builtin │
    │ MCP 2: coding │   │ (automatic)   │
    │   • read_file │   │               │
    │   • write     │   │               │
    │   • bash      │   │               │
    │               │   │               │
    │ Done: builtin │   │               │
    │ (automatic)   │   │               │
    └───────────────┘   └───────────────┘
```

**`done` is the only builtin.** It's always present. The loop enforces it. Every agent gets it automatically. No MCP server needs to provide it.

**`subagents` is the other builtin.** Only present if the agent definition has a `spawn` list. It's recursive loop calling — the library must own this because it IS the loop.

**Everything else is an MCP tool.** Druppie's hitl, make_plan, etc. become an MCP server. The library is clean and reusable.

---

### How Each Druppie Tool Moves

| Current Builtin | Becomes | Why |
|----------------|---------|-----|
| `done` | **Stays builtin** | The loop enforces it. Must always be present. |
| `subagents` | **Stays builtin** | It IS the loop (recursive call). Can't be external. |
| `hitl_ask_question` | **MCP tool on Druppie core MCP** | Needs session management. App-specific. |
| `hitl_ask_multiple_choice` | **MCP tool on Druppie core MCP** | Same as above. |
| `make_plan` | **MCP tool on Druppie core MCP** | Planner-specific. Session-scoped. |
| `set_intent` | **MCP tool on Druppie core MCP** | Router-specific. Session-scoped. |
| `invoke_skill` | **MCP tool on Druppie core MCP** | Druppie skill system. Not generic. |
| `execute_coding_task` | **REMOVED** — replaced by recursive subagents (D27) | |
| `create_message` | **MCP tool on Druppie core MCP** | Summarizer-specific. Session-scoped. |
| `test_report` | **MCP tool on Druppie core MCP** | Test executor-specific. |

### What About Tool Expansion (Skills)?

Skills expand the agent's available MCP tools. Currently `invoke_skill` does this as a builtin. If `invoke_skill` becomes an MCP tool on the Druppie core MCP server, the tool expansion still needs to work:

```
1. Agent YAML: skills: [code-review]
2. Tool list includes: invoke_skill (from Druppie core MCP)
3. LLM calls: invoke_skill(skill_name="code-review")
4. Druppie core MCP returns: skill instructions + allowed-tools list
5. Agent runtime detects allowed-tools in the response
6. Agent runtime dynamically adds those MCP tools to the available set
7. LLM can now use coding:read_file (which it couldn't before)
```

The agent runtime needs ONE piece of Druppie-aware logic: **if a tool result contains `allowed-tools`, expand the tool set.** This is a generic capability — "dynamic tool expansion from tool results" — not Druppie-specific. Any MCP server could return `allowed-tools` to expand what the agent can access.

---

### Diagram: Full Flow Comparison

#### Druppie Core Agent (e.g., Business Analyst)

```
┌─────────────────────────────────────────────────────────┐
│                     Backend Process                      │
│                                                         │
│  AgentLoop.run(ba_definition, prompt, ...)              │
│    │                                                    │
│    ├── ToolProvider 1: MCP → core-tools server          │
│    │     ├── done (builtin, auto-added)                 │
│    │     ├── hitl_ask_question                          │
│    │     ├── invoke_skill                               │
│    │     └── make_plan (if planner)                     │
│    │                                                    │
│    ├── ToolProvider 2: MCP → sandbox (own container)     │
│    │     ├── read_file                                   │
│    │     ├── write_file                                  │
│    │     ├── list_dir                                    │
│    │     └── run_git                                     │
│    │                                                    │
│    └── Builtin: done + subagents (if spawn list)        │
│                                                         │
│  LLM: ChatLiteLLM (from druppie/llm/)                  │
│  Events: → write to DB                                 │
└─────────────────────────────────────────────────────────┘
```

#### Druppie Sandbox Coding Agent (e.g., Planner → Builder)

```
┌─────────────────────────────────────────────────────────┐
│                     Backend Process                      │
│                                                         │
│  AgentLoop.run(                                         │
│    agent=planner_def,                                   │
│    agent_loader=load_from_definitions,                  │
│    mcp_connections={"sandbox": MCPClient(...)},         │
│    prompt=...,                                          │
│  )                                                      │
│                                                         │
│  planner_def.mcps: {} → only done + subagents           │
│    │                                                    │
│    └── subagents({agent: "builder", task: "..."})       │
│          │                                              │
│          ├── agent_loader("builder") → builder_def      │
│          ├── builder_def.mcps:                          │
│          │     sandbox: [read, write, edit, bash]       │
│          ├── resolve → scoped ToolProvider for builder   │
│          └── AgentLoop.run(builder_def, task, scoped)   │
│                                                         │
│    └── subagents({agent: "tester", task: "..."})        │
│          │                                              │
│          ├── agent_loader("tester") → tester_def        │
│          ├── tester_def.mcps:                           │
│          │     sandbox: [read, bash, grep]              │
│          ├── resolve → scoped ToolProvider for tester   │
│          └── AgentLoop.run(tester_def, task, scoped)    │
│                                                         │
│  Same sandbox MCP server. Different tool scopes.        │
│  LLM: ChatLiteLLM                                      │
│  Events: → write to DB                                 │
└─────────────────────────────────────────────────────────┘
```

#### Application Agent (e.g., chatbot with OCR)

```
┌─────────────────────────────────────────────────────────┐
│                   Application Process                    │
│                                                         │
│  AgentLoop.run(my_agent_def, user_message, ...)         │
│    │                                                    │
│    ├── ToolProvider 1: MCP → module-ocr server          │
│    │     ├── extract_text                               │
│    │     └── extract_structured                         │
│    │                                                    │
│    ├── ToolProvider 2: MCP → app-tools server           │
│    │     ├── search_documents                           │
│    │     └── send_notification                          │
│    │                                                    │
│    └── Builtin: done (automatic)                        │
│                                                         │
│  LLM: their LLM (litellm, openai, whatever)            │
│  Events: → their logging/metrics                       │
└─────────────────────────────────────────────────────────┘
```

Same library. Same loop. Same done() enforcement. Different tools, different LLM, different storage.

---

### Diagram: Where `done` Lives

```
                    ┌─────────────────┐
                    │   Agent Loop    │
                    │                 │
                    │  Enforces:      │
                    │  "done must be  │
                    │   called"       │
                    │                 │
                    │  Provides:      │
                    │  done() tool    │
                    │  (always)       │
                    │                 │
                    │  Provides:      │
                    │  subagents()    │
                    │  (if spawn list)│
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         ┌─────▼─────┐ ┌─────▼─────┐
         │  MCP to    │ │  MCP to   │
         │ core-tools │ │ sandbox   │
         │            │ │ (per-agent│
         │ • hitl     │ │ container)│
         │ • plan     │ │           │
         │ • intent   │ │ • read    │
         │ • skill    │ │ • write   │
         │ • exec_pi  │ │ • bash    │
         │            │ │ • git     │
         └────────────┘ └───────────┘

  The loop ONLY provides done + subagents.
  Everything else is an MCP tool from outside.
```

---

### Diagram: What Needs a "Druppie Core MCP Server"

Currently these are builtins in `builtin_tools.py`. In the new architecture, they become tools on a **Druppie Core MCP Server**:

This server runs **in-process** inside the Druppie backend — NOT as a separate container.
It directly imports `druppie/db/models/` and `druppie/repositories/` for database access.
No separate deployment, no inter-process communication overhead.

Implementation: a FastMCP server instance registered as an in-process MCP connection,
directly accessible by the agent runtime without HTTP.

Agents that need these tools list them in their `mcps:` field:
```yaml
# business_analyst.yaml
mcps:
  core-tools: [hitl_ask_question, invoke_skill]
  coding: [read_file, list_dir, make_design]
```

Agents that DON'T need them (like the builder in sandbox):
```yaml
# builder.yaml (in sandbox)
mcps:
  sandbox: [read_file, write_file, bash, grep, find, ls]
  # No core-tools — builder doesn't need hitl or session management
```

Applications:
```yaml
# app-agent.yaml (in application)
mcps:
  ocr: [extract_text]
  app-tools: [search_documents, send_notification]
  # No core-tools — no Druppie session management needed
```

---

## 7. Updated Decision: Builtin vs MCP

**Revised recommendation**: Only `done` and `subagents` are builtins. Everything else is MCP.

| Tool | Builtin? | Where it lives |
|------|----------|---------------|
| `done` | **Yes** — loop enforcement + validation | Inside the agent runtime library |
| `subagents` | **Yes** — recursive loop | Inside the agent runtime library |
| `hitl_ask_question` | No | Druppie core-tools MCP server |
| `hitl_ask_multiple_choice` | No | Druppie core-tools MCP server |
| `make_plan` | No | Druppie core-tools MCP server |
| `set_intent` | No | Druppie core-tools MCP server |
| `invoke_skill` | No | Druppie core-tools MCP server |
| `execute_coding_task` | No | Druppie core-tools MCP server |
| `create_message` | No | Druppie core-tools MCP server |
| `test_report` | No | Druppie core-tools MCP server |
| `read_file`, `bash`, etc. | No | Coding MCP / Sandbox MCP |

This makes the library **truly generic** — it knows about LLM loops, done enforcement, and subagent recursion. Nothing else.

---

## 8. Done() Validation — What Stays in the Library

### `done()` Is More Than Just an Exit Signal

The `done` builtin has three responsibilities:

1. **Exit signal** — Tells the loop to stop (the enforcement layer)
2. **Result capture** — Captures `message` and `variables` from the LLM's tool call
3. **Precondition validation** — Checks agent-specific rules before accepting the done() call

### What Are Completion Preconditions?

Agent definitions can declare rules that must be satisfied before `done()` is accepted. If the rules fail, the loop rejects `done()` and returns the error message to the LLM — the agent must retry.

```yaml
# business_analyst.yaml
completion_preconditions:
  - summary_contains: "DESIGN_APPROVED"
    unless_summary_contains: "REQUIREMENT_CHALLENGE outcome: HARD"
    required_tools:
      - tool_name: "make_design"
        min_calls: 1
      - tool_name: "run_git"
        min_calls: 1
    error_message: >
      PRECONDITION FAILED: You cannot call done() with DESIGN_APPROVED without
      first writing docs/functional-design.md AND committing it to git.
```

### How It Works

```
1. LLM calls: done(message="Agent BA: DESIGN_APPROVED - created FD", variables={})
2. Loop intercepts the done() call
3. Loop checks completion_preconditions from agent definition:
   ✓ summary contains "DESIGN_APPROVED" → YES
   ✓ unless summary contains "REQUIREMENT_CHALLENGE outcome: HARD" → NO (not present)
   → precondition is ACTIVE, must check required_tools
   ✗ Was "make_design" called? → NO
4. Loop REJECTS done(), returns error_message to LLM
5. LLM must call make_design first, then retry done()
```

### Why This Belongs in the Library (Not in MCP)

```
┌──────────────────────────────────────────────────────┐
│                  done() builtin                       │
│                                                      │
│  Inputs (from agent definition):                     │
│    • completion_preconditions: list of rules         │
│    • required_summary_status: required keywords      │
│                                                      │
│  Internal state (the loop already tracks this):      │
│    • tool_call_history: every tool call this run     │
│    • turn_count: how many turns so far               │
│                                                      │
│  Validation checks:                                  │
│    1. Does summary contain required strings?          │
│    2. Unless exemption string is present?             │
│    3. Were required tools called min N times?         │
│    4. Does summary have a required status keyword?    │
│                                                      │
│  No external services needed:                        │
│    • No DB queries                                   │
│    • No MCP calls                                    │
│    • No session management                           │
│    • Just checks the tool call history + summary     │
│                                                      │
│  → Generic. Works for Druppie AND applications.      │
│  → An app agent can define its own preconditions     │
│    (e.g., "must call search before done")             │
└──────────────────────────────────────────────────────┘
```

This is NOT Druppie-specific. It's a general concept: "validate done() against tool call history before accepting." The agent definition declares the rules. The library enforces them.

### Data Model for Preconditions

```python
@dataclass
class RequiredToolCall:
    tool_name: str           # "make_design"
    min_calls: int = 1       # must be called at least this many times

@dataclass
class CompletionPrecondition:
    summary_contains: str | None = None
    unless_summary_contains: str | None = None
    required_tools: list[RequiredToolCall] = field(default_factory=list)
    error_message: str = ""

@dataclass
class CompletionSummaryRequirement:
    one_of: list[str]       # e.g., ["DESIGN_APPROVED", "DESIGN_REJECTED"]
```

### Validation Flow

```python
# Inside done() builtin
def _validate_done(self, summary: str, variables: dict, tool_history: list) -> str | None:
    """Returns error message if validation fails, None if it passes."""
    
    # Check required_summary_status
    if self.agent_def.required_summary_status:
        if not any(kw in summary for kw in self.agent_def.required_summary_status.one_of):
            return f"Summary must contain one of: {self.agent_def.required_summary_status.one_of}"
    
    # Check completion_preconditions
    for precondition in self.agent_def.completion_preconditions:
        # Skip if unless condition is met
        if precondition.unless_summary_contains and precondition.unless_summary_contains in summary:
            continue
        
        # Only check if summary contains the trigger string
        if precondition.summary_contains and precondition.summary_contains not in summary:
            continue
        
        # Check required tool calls
        for required in precondition.required_tools:
            count = sum(1 for tc in tool_history if tc.name == required.tool_name)
            if count < required.min_calls:
                return precondition.error_message
    
    return None  # All checks passed
```

---

## 9. Updated Decision Summary

| # | Decision | Recommendation | Status |
|---|----------|---------------|--------|
| D1 | Skills handling | MCP tool on core-tools server + dynamic tool expansion in library | ✅ Decided |
| D2 | Tool scoping | REMOVED — archived, concepts persist in D19/D29 | ✅ Superseded |
| D3 | Sandbox MCP implementation | Run coding MCP server inside sandbox container | ✅ Decided |
| D4 | Subagent tool access | Per-agent resolution from mcp_connections. NOT shared ToolProvider. | ✅ Decided |
| D5 | Builtin vs MCP tools | Only done + subagents are builtin. Everything else = MCP | ✅ Decided |
| D6 | Agent definition format | Migrate to YAML, one format in backend | ✅ Decided |
| D7 | Event granularity | Subset — tool_call, tool_result, subagent_start/end (with parent/depth), done, llm_retry, enforcement_retry | ✅ Decided |
| D8 | LLM client interface | Use litellm directly — runtime accepts callable, caller handles profiles + fallbacks | ✅ Decided |
| D9 | done() validation | Builtin — preconditions + summary status checked against tool history | ✅ Decided |
| D10 | Druppie core-tools MCP | In-process server for hitl, plan, intent, skill, create_message, test_report | ✅ Decided |
| D11 | Long-running tools (pause/resume) | Generic _pending convention + serialize/deserialize state | ✅ Decided |
| D12 | Approval system | Outside runtime — in MCP/ToolProvider layer, Druppie core-tools MCP | ✅ Decided |
| D13 | execute_coding_task non-pi | REMOVED — only one execute_coding_task (ex-pi) | ✅ Superseded by D27 |
| D14 | done() scope | Exit + validation only. Summary/routing = caller responsibility | ✅ Decided |
| D15 | Pause states | One generic _pending. Caller discriminates reason | ✅ Decided |
| D16 | LLM retry | Inside runtime. Retry ALL errors. Configurable retries + exponential backoff | ✅ Decided |
| D17 | Context compaction | REMOVED — removed compaction, replaced by D25 forced-done | ✅ Decided |
| D18 | Parallel subagents | Day-one support via asyncio.gather | ✅ Decided |
| D19 | Remove coding MCP | Sandbox for ALL file ops. Per-agent sandbox synced via Git. Docker MCP stays. | ✅ Decided |
| D20 | Warm sandbox pool | Configurable pool of pre-started containers. No git fetch/pull until use. | ✅ Decided |
| D21 | Git push/PR tools | On sandbox MCP server, not core-tools MCP | ✅ Decided |
| D22 | Core-tools MCP data access | Direct DB connection, shared ORM/repo layers, reuse existing code | ✅ Decided |
| D23 | Event storage | Stateful — all events stored internally + callbacks for streaming | ✅ Decided |
| D24 | Pause/resume edge cases | Multi-tool + _pending: pause all, serialize all results. Cancellation token. JSON format. | ✅ Decided |
| D25 | Context overflow | Force done() with summary when approaching context limit | ✅ Decided |
| D26 | LLM client configuration | Caller configures litellm callable with ChatLiteLLM + FallbackLLM + profiles | ✅ Decided |
| D27 | Subagents-only architecture | No special coding task tool. All agent spawning via subagents builtin. Infinite recursive depth with max_subagent_depth config. Sandbox auto-created per agent def. | ✅ Decided |
| D28 | Shared sandbox policy | Subagents within a coding task share ONE sandbox. Agent-level responsibility to avoid file conflicts. Pragmatic first iteration. | ✅ Superseded by D29 |
| D29 | Agent-level sandbox & git config | Per-agent sandbox config in YAML (mcps.sandbox with tools + git scope). ToolProvider determines sharing based on git scope. | ✅ Decided |
| D30 | make_design tool — sandbox MCP with auto-commit | make_design lives in sandbox MCP, available only to agents that explicitly list it (architect, business_analyst). Auto-commits to git after writing. Pre-validate: Mermaid syntax check via ToolProvider. Approval gate: architect role requires human approval. Frontend renders markdown + Mermaid in approval gateway. | ✅ Decided |
| D31 | Subagent timeline representation | Separate agent_run with parent_agent_run_id FK. Same table, same schema, just with an optional FK. Simple to query, easy to nest in API response. | ✅ Decided |
| D32 | Subagent event ownership | Events reference the subagent's own agent_run_id. API assembles nested timeline by querying all agent_runs and building tree using parent_agent_run_id. | ✅ Decided |
| D33 | Subagent run status tracking | Same status field as primary agents. Subagents MCP creates agent_run with status=running, updates to completed/error/cancelled when done. | ✅ Decided |
| D34 | Agent run sequence numbering | sequence_number only for primary agents (make_plan ordering). Subagents ordered by parent's timeline position, no own sequence_number. | ✅ Decided |
| D35 | Event storage granularity | Full events — all tool calls, tool results, subagent starts/ends, LLM turns, errors. Storage is cheap, debugging is important. | ✅ Decided |
| D36 | Context overflow state persistence | Force done() with auto-summary when approaching context limit (aligned with D25). Runtime forces one more LLM call with only done() available. | ✅ Decided |
| D37 | Multiple pending tools resume strategy | Resume all at once. Runtime stores all pending tools in AgentState. Caller waits for all answers before resuming. | ✅ Decided |
| D38 | Subagent depth tracking | Runtime config only (max_subagent_depth in LoopConfig, default 10). Subagents MCP receives current depth, rejects spawns that exceed limit. | ✅ Decided |
| D39 | Agent state serialization format | JSON. AgentState is message history, tool call tracking, preconditions state — all easily JSON-serializable. Stored as JSON text in DB. | ✅ Decided |
| D40 | Summary accumulation strategy | Query DB each time. Simple, always correct, crash-safe. Query filters by session_id, status=completed, orders by sequence_number. | ✅ Decided |
| D41 | Tool Call → Subagent Linking | source_tool_call_id FK on agent_runs. Bi-directional link: tool_calls.agent_run_id → parent agent, agent_runs.source_tool_call_id → spawning tool call. Works for parallel subagents. | ✅ Decided |
| D42 | Parallel Subagent Representation | One tool_call, multiple child runs. LLM makes one subagents() call → one tool_call record. Children point to it via source_tool_call_id, ordered by started_at. | ✅ Decided |
| D43 | Resume State — Serialized Blob vs Event Reconstruction | Reconstruct from events. Events are the single source of truth for timeline, streaming, AND resume. No serialized blob. On resume, caller queries events from DB, converts back to LLM message format, passes as initial_messages. | ✅ Decided |
| D44 | Sandbox Container Lifecycle on Pause/Resume | Stop container on pause, accept work loss. Coding agents instructed via system prompt to always commit before calling tools that cause pauses. Soft constraint, not mechanically enforced. Warm pool has fresh containers ready. On resume, new container created from latest git state. Always stop on done() — next agent starts fresh from git. | ✅ Decided |
| D45 | AgentState and Events — Unify or Separate? | Events only (D43) vs unified event log vs both. Trade-off: reconstruction overhead vs storage vs simplicity. | ✅ Decided |
| D46 | agent_runs and agent_state_events — Separate or Merged? | Header-detail pattern: agent_runs = header (status, summary, variables), agent_state_events = details (conversation log). Linked by FK. Fast status queries (indexed, native types, FK constraints). Two tables small price for correct separation. | ✅ Decided |

---

## 10. Long-Running Tool Calls — Pause/Resume

### The Problem

When all tools are MCP, long-running operations (HITL questions waiting hours for user response, approval gates, sandbox tasks) can't hold an HTTP connection open. MCP is synchronous request-response.

### Current Flow (builtin tools, in-process)

```
1. Agent calls hitl_ask_question("React or Vue?")
2. Tool is in-process → backend PAUSES agent loop
3. Backend serializes state to DB, frees HTTP connection
4. ... hours pass ...
5. User answers → backend loads state → RESUMES agent loop
```

### New Flow (MCP tools, generic pause/resume)

```
1. Agent calls hitl_ask_question on core-tools MCP
2. MCP server returns: {"_pending": true, "_resume_id": "abc123"}
3. AgentLoop detects _pending → SERIALIZE state → return PendingResult
4. Backend stores serialized state in DB → HTTP freed
5. ... hours pass ...
6. User answers → backend loads state → loop.resume(state, tool_result)
7. Agent continues
```

### Interface

```python
@dataclass
class AgentState:
    """Serializable snapshot — everything needed to resume."""
    messages: list[dict]
    agent_id: str
    pending_tool_call_id: str
    turn_count: int
    tool_history: list[ToolCallRecord]
    loop_config: LoopConfig

@dataclass
class AgentResult:
    # ... existing fields ...
    pending: AgentState | None = None  # set when tool returns _pending

class AgentLoop:
    async def run(self, ...) -> AgentResult:
        """Returns completion OR pending state."""
        ...
    
    async def resume(self, state: AgentState, tool_result: str) -> AgentResult:
        """Resume from paused state with the tool result."""
        ...
```

### Pending Detection

Any MCP tool can trigger a pause by returning `_pending: true` in its result:

```json
// HITL question pending user response
{"_pending": true, "_resume_id": "hitl_abc123", "message": "Question sent to user"}

// Approval gate pending architect review  
{"_pending": true, "_resume_id": "approval_def456", "message": "Awaiting approval"}

// Sandbox task running (could take minutes)
{"_pending": true, "_resume_id": "sandbox_ghi789", "message": "Sandbox executing..."}
```

The runtime checks for `_pending: true`. It doesn't know or care WHY the tool is pending — it just serializes and returns.

### Backend Usage

```python
# Start agent
result = await agent_loop.run(...)

if result.pending:
    # Save state to DB, free resources
    await db.save_agent_state(session_id, result.pending)
    return

# Normal completion
await db.save_agent_result(session_id, result)

# Resume when external event occurs (user answer, approval, sandbox done)
async def on_resume(session_id, resume_id, answer):
    state = await db.load_agent_state(session_id)
    result = await agent_loop.resume(state, tool_result=answer)
    
    if result.pending:
        await db.save_agent_state(session_id, result.pending)  # another pause
    else:
        await db.save_agent_result(session_id, result)  # completed
```

### Why This Is Generic

- Runtime doesn't know about HITL — any MCP tool can return `_pending`
- Caller (backend/app) decides persistence and webhook strategy
- Applications can use their own "pending" tools (e.g., "wait for payment")
- The same pause/resume mechanism handles ALL async operations

### Updated Decision

| D11 | Long-running tools (pause/resume) | Generic _pending convention + serialize/deserialize state. Not HITL-specific. | ✅ Decided |

---

## 11. Post-Review Decisions

### Decision D12: Approval System — Outside Agent Runtime

**Decision**: Approvals are handled OUTSIDE the agent runtime, in the ToolProvider/MCP layer.

How it works:
- The agent runtime calls the ToolProvider (which is an MCP connection)
- If the MCP server determines approval is needed, it returns {"_pending": true, "_resume_id": "approval_xxx", "_pause_reason": "approval"}
- The agent runtime treats this the same as any other _pending result — serialize state, return PendingResult
- The caller (backend) handles the approval workflow: create Approval DB record, wait for human, resume

For Druppie:
- Approval logic lives in the Druppie core-tools MCP server
- The MCP server checks: global mcp_config.yaml rules, agent approval_overrides, required_role
- Approval is configurable per-application — the runtime doesn't know about it

Why: Approval is application-specific. Druppie has role-based approvals. An app might have none. The runtime is generic.

User quote: "lets keep this outside the agent runtime. we call the toolprovider. here is where these things should be managed. for druppie core thus in the mcp for druppie core tools."

---

### Decision D13: Remove legacy execute_coding_task (superseded by D27)

**Decision**: Remove the legacy execute_coding_task (OpenCode/sandbox) tool entirely. Only the renamed execute_coding_task survives as an MCP tool.

Rationale: Two parallel coding pipelines is unnecessary complexity. One unified execute_coding_task is cleaner.

Status: Legacy execute_coding_task is REMOVED. The renamed tool survives as an MCP tool on the core-tools server.

**Superseded by D27** — execute_coding_task removed entirely, all agent spawning via subagents builtin.

---

### Decision D14: done() — Only Exit + Validation in Runtime

**Decision**: The agent runtime's done() ONLY handles:
1. Exit signal (tells the loop to stop)
2. Result capture (summary + variables from the LLM's tool call)
3. Precondition validation (checks agent-specific rules before accepting)

The runtime does NOT handle:
- Summary accumulation across agents (collecting previous agent summaries, deduplication)
- next_agent routing (inserting agent runs, manipulating sequence numbers)
- Inter-agent context passing (relaying summaries to next pending agent)

These are handled by the CALLER (backend) after done() returns AgentResult. The runtime returns a raw DoneResult(summary, variables, done_called=True) and the backend decides what to do with it.

Why: Summary accumulation and routing are Druppie-specific orchestration patterns. Applications may not need them. The runtime stays generic.

User quote: "we do not handle this in the agent runtime. We handle this outside the agent runtime in the core agents. Here we run multiple agents and do things like summaries, etc to create networks of agents. so answer B."

---

### Decision D15: One Generic Pause State

**Decision**: One generic _pending mechanism. The runtime doesn't care WHY a tool paused.

The MCP tool returns: {"_pending": true, "_resume_id": "xxx", ...}
The runtime serializes state and returns PendingResult. Period.

The caller (backend) can add extra metadata for its own tracking (pause_reason, approval_id, etc.), but the runtime ignores it.

Current system has 3 pause states: WAITING_USER_INPUT, WAITING_APPROVAL, WAITING_SANDBOX.
New system: one _pending, caller discriminates.

User quote: "just one pause state is good i think."

---

### Decision D16: LLM Retry in Agent Runtime

**Decision**: The agent runtime handles LLM retries internally.

Configurable via LoopConfig:
- max_retries: int = 3
- retry_base_delay: float = 1.0 (exponential backoff: base * 2^attempt)
- respect_retry_after: bool = true (honor Retry-After headers)

Retry on ALL LLM errors (both retryable and non-retryable) for now. Error classification will be refined during implementation.

On retry, emit enforcement_retry event. The caller can log/track retries.

User quote: "leave this in the agent runtime."

---

### Decision D17: No Context Compaction

**Decision**: Remove context compaction / session compaction from the design entirely.

The runtime does NOT manage context window limits. If the conversation exceeds the LLM's context window, the LLM call fails and the retry mechanism (D16) handles it.

If compaction is needed in the future, it would be a caller-side concern (the caller could trim messages before calling resume).

User quote: "remove this feature."

**Note**: D25 (context overflow → forced done) replaces compaction with a different strategy. D17 removes the old compaction mechanism; D25 provides the new overflow handling.

---

### Decision D18: Parallel Subagents from Day One

**Decision**: The subagents builtin tool supports parallel execution from day one.

The LLM can call subagents with multiple tasks:
subagents({tasks: [{agent: "builder", task: "..."}, {agent: "tester", task: "..."}]})

The runtime executes them concurrently (asyncio.gather). Each subagent gets its own:
- AgentDefinition (from agent_loader)
- Scoped ToolProvider (resolved from mcp_connections per agent's mcps)
- Event callbacks (with parentAgentId linkage)
- LLM client (same client or per-agent model)

Results are collected and returned as a combined tool result.

Error handling: If one subagent fails, the parent can decide (via the tool result) whether to continue.

**Parallel subagent error handling**:
When parallel subagents are spawned and some fail while others succeed:
- ALL subagents run to completion (no cancellation of siblings on failure)
- Results are returned as a list, each with its own status: `{agent: string, status: 'success' | 'error', result: AgentResult | Error}`
- The parent agent receives both successful results and error details
- The parent decides how to handle partial failures (retry failed ones, proceed with successful ones, or abort)
- Error details include: agent name, error message, partial events captured before failure

User quote: "A. Yes, from day one."

---

### Decision D19: Remove Coding MCP — Sandbox for All File Operations

**Decision**: Remove the global coding MCP server (port 9001) entirely. ALL file operations go through per-agent sandboxes.

How it works:
- Every agent that needs file access gets its own sandbox container
- The coding MCP server runs INSIDE each sandbox (same as current execute_coding_task behavior)
- No shared coding MCP server — no global file access
- Each sandbox is isolated: own filesystem, own MCP server instance

Sandbox synchronization between agents:
- At the START of each agent run: the sandbox automatically does `git fetch` + `git pull` from the project repo (Gitea)
- At the END of each agent run: the agent is instructed to commit and push changes back to Gitea (via system prompt). No runtime enforcement.
- Git commit/push is NOT enforced by the runtime. Agents are instructed via their system prompts to commit and push. The caller (backend) may also verify git state after done() returns. But done() itself has no git awareness — it only does exit + validation (per D14).
- The next agent's sandbox pulls the latest state from Gitea

What stays:
- Docker MCP server (port 9002) stays as a shared MCP — it's for deploying on the system infrastructure (build, run, compose_up). Sandboxes can't do this because they don't have access to the host Docker daemon.
- Web MCP, archimate MCP, etc. — unchanged, still shared/global

Tool scoping becomes simpler:
```
Before:  coding MCP (shared) + docker MCP (shared) + sandbox MCP (per coding task)
After:   sandbox MCP (per agent, for file ops) + docker MCP (shared, for infra) + core-tools MCP (for session mgmt)
```

Agent YAML examples:
```yaml
# business_analyst.yaml — needs to write functional design
mcps:
  sandbox: [read_file, write_file, list_dir, run_git]  # own sandbox
  core-tools: [hitl_ask_question, invoke_skill]

# developer.yaml — needs to read design, write code
mcps:
  sandbox: [read_file, write_file, bash, grep, find, ls, run_git]  # own sandbox
  core-tools: [execute_coding_task, invoke_skill]

# builder.yaml (subagent inside execute_coding_task) — code implementation
mcps:
  sandbox: [read_file, write_file, edit, bash, grep, find, ls]  # same sandbox as parent

# architect.yaml — needs docker for deployment review
mcps:
  sandbox: [read_file, list_dir, run_git]  # own sandbox
  docker: [build, run]  # shared Docker MCP
  core-tools: [hitl_ask_question, invoke_skill]
```

Why: Eliminates the complexity of a shared coding MCP server with injected params for context isolation. Each sandbox is naturally isolated — no need for session_id injection, workspace selection, or multi-tenant safety checks. Git becomes the synchronization mechanism, which is already the source of truth.

User quote: "i also wanna remove the coding module. Since we have a new sandbox in execute coding task i think we should only use this. this should just be a generic tool available for all agents."

---

### Decision D20: Warm Sandbox Pool

**Decision**: Use a configurable warm pool of sandbox containers for faster startup.

How it works:
- A configurable number of sandbox containers are pre-started and kept idle
- When an agent needs a sandbox, it takes one from the pool instead of waiting for cold start
- Pool size is configurable (default: 2-3)
- If pool is empty, fall back to creating a new container (slower but still works)
- Idle containers are recycled after a configurable timeout

**Important**: Warm containers do NOT git fetch/pull. The git fetch/pull only happens when an agent actually starts using the container. This prevents stale state accumulation in idle containers.

**Configuration in LoopConfig**:
```python
@dataclass
class LoopConfig:
    ...
    sandbox_pool_size: int = 3          # Number of warm sandbox containers (D20)
    sandbox_pool_recycle_s: int = 3600  # Recycle containers after 1 hour (D20)
    max_subagent_depth: int = 10        # Max recursion depth for subagents (D27)
```
The warm pool is managed by the caller (backend), not the runtime. The runtime requests a sandbox from the ToolProvider, which pulls from the pool.

Why: Sandbox creation can take 10-30 seconds. For lightweight agents (BA writing a markdown file), this overhead is unacceptable. A warm pool keeps response times fast.

User quote: "use a warm pool that is configurable."

---

### Decision D21: Git Push/PR Tools on Sandbox MCP

**Decision**: `push_to_remote` and `create_pr` are MCP tools on the sandbox MCP server, NOT on the core-tools MCP.

Rationale: These operations happen inside the sandbox container where the git repo lives. The sandbox MCP server has direct access to the filesystem and git credentials.

User quote: "sandbox mcp pls."

---

### Decision D22: Core-tools MCP Uses Existing ORM/Repo Layers

**Decision**: The Druppie core-tools MCP server connects directly to the database using the existing ORM models and repository layer from `druppie/db/` and `druppie/repositories/`.

How it works:
- Core-tools MCP server imports `druppie/db/models/` and `druppie/repositories/`
- Uses the same SQLAlchemy session management
- No new data access layer needed
- Shares the existing `druppie/domain/` models for input/output

For invoke_skill tool expansion: uses the existing `druppie/skills/` loading infrastructure. The `allowed-tools` response schema follows the existing SKILL.md frontmatter format.

For MCP client: reuse existing code from `druppie/core/` (MCP HTTP client, tool registry) as much as possible rather than pulling in a new library.

User quote: "direct db connection pls." / "shared orm yes just use the existing layers for repo etc." / "use existing code as much as possible."

---

### Decision D23: Stateful Event Storage

**Decision**: The agent runtime stores ALL events internally (stateful), not just emits them via callbacks.

How it works:
- Every event (tool_call, tool_result, subagent_start/end, done, error, etc.) is stored in a list during the run
- Events are accessible via `AgentResult.events` after the run completes
- Callbacks are ALSO fired (for real-time streaming to frontend)
- On pause/resume: events are included in AgentState serialization so they survive across pauses
- On subagent completion: subagent events are nested under the parent's events

Error propagation for subagents (D18): if a subagent fails, the error is propagated as-is in the subagent_end event. The parent agent sees the error in the combined tool result and decides how to proceed. Simple and transparent.

User quote: "everything is statefull. store it." / "just propagate the error. keep things simple but nice."

---

### Decision D24: Pause/Resume Edge Cases

**Decision**: Defined behavior for multi-tool calls, parallel subagents, and cancellation.

**Multi-tool-call + _pending**: If the LLM calls multiple tools in one response and one returns `_pending`:
- The runtime executes ALL tools in parallel
- Collects ALL results (both completed and pending)
- If ANY tool returned _pending, the entire turn is paused
- ALL results (including completed ones) are serialized in AgentState
- On resume, all results are available to the LLM

**When multiple tools in a batch return `_pending`**:
- The agent is paused
- ALL tool results (both completed and pending) are gathered
- Completed results are stored in agent state
- Pending results include their resume identifiers
- On resume, ONLY the pending tools are re-executed (completed results are reused from state)
- If different `_resume_id` values exist, ALL must be resolved before the agent continues
- The LLM receives all results (completed + resumed) as a single batch

**Parallel subagent + _pending**: If parallel subagents are running and one returns _pending:
- Only that subagent is paused (its state serialized)
- Other subagents continue to completion normally
- The parent agent cannot continue until ALL subagent results are collected
- So the parent is effectively stuck waiting for the paused subagent
- On resume (external trigger), the paused subagent continues, returns result, parent gets all results

**Serialization format**: JSON. AgentState is serialized as JSON for storage in DB.
Large tool results (file contents) may be truncated or referenced by ID rather than inlined.

**Cancellation**: The runtime supports cancellation via a cancellation token.
```python
class CancellationToken:
    def cancel(self) -> None: ...
    @property
    def is_cancelled(self) -> bool: ...

# Caller creates token, passes to run()
result = await agent_loop.run(..., cancellation_token=token)
# User clicks "stop" → token.cancel()
# Runtime checks token between turns, raises AgentCancelledError if set
```
Cancels ALL running agents (including subagents). Clean shutdown — no partial state saved.

---

### Decision D25: Context Overflow Handling

**Decision**: When the conversation approaches the LLM's context window limit, the runtime forces `done()` with a summary.

How it works:
- LoopConfig has a `max_context_tokens` field (default: from LLM model's limit)
- Before each LLM call, the runtime estimates total token count from messages
- If estimated tokens exceed `max_context_tokens - buffer`:
  1. Inject a system message: "You have reached the context limit. Call done() NOW with a summary of your progress so far. Include what you've completed and what remains."
  2. Force one more LLM call with ONLY the `done` tool available
  3. If LLM calls done() → normal completion with the summary
  4. If LLM doesn't call done() → auto-generate done result: "Context limit reached. Summary: [last N chars of conversation]"

The caller sees this as a normal AgentResult with a flag indicating context overflow.

This replaces the removed compaction feature (D17) with a hard boundary that gracefully degrades.

---

### Decision D26: LLM Client Configuration — Profiles and Fallback

**Decision**: The CALLER (not the runtime) resolves LLM profiles and configures the litellm callable using existing infrastructure from `druppie/llm/` (ChatLiteLLM + FallbackLLM + profiles).

**Key points**:
- D26 is about HOW the caller configures the litellm callable, NOT about extending a custom protocol
- The runtime doesn't know about profiles, model names, or providers — it receives a pre-configured litellm callable
- The caller resolves `llm_profile` from agent YAML → looks up `llm_profiles.yaml` → creates ChatLiteLLM(wrapped in FallbackLLM) → passes to runtime
- The runtime just calls `await llm(messages=..., tools=..., **kwargs)` and gets a standard litellm response

**Profile resolution** (caller-side):
1. Agent YAML declares `llm_profile: standard`
2. Caller loads `llm_profiles.yaml` → resolves first valid {provider, model} pair based on available API keys
3. Caller creates `ChatLiteLLM(provider, model)` — optionally wrapped in `FallbackLLM` with secondary provider
4. Caller passes the ready-made litellm callable to the runtime

**Fallback behavior** (in caller's LLM wrapper, NOT runtime):
- FallbackLLM wraps primary + secondary LLM instances
- On ANY LLMError from primary → switches to secondary automatically
- Runtime doesn't know about fallback — it just calls the litellm callable

**Retry behavior** (D16, in runtime):
- Runtime retries on ANY LLM error (retryable + non-retryable for now)
- Configurable: `max_retries=3`, `retry_base_delay=1.0` (exponential backoff)

**Subagent LLM**: Subagents can use a different model than parent.
- Agent definition has `llm_profile` field
- When spawning a subagent, caller provides the resolved litellm callable for that agent's profile
- If not specified, subagent inherits parent's litellm callable

---

### Decision D27: Subagents-Only Architecture — No Special Coding Task Tool

**Decision**: Remove `execute_coding_task` entirely. ALL agent spawning uses the `subagents` builtin — fully recursive, infinite depth, parallel capable.

**Practical limits**:
- `max_subagent_depth: int = 10` in LoopConfig (configurable)
- Runtime tracks current depth per agent chain
- If depth exceeds max, the subagent call returns an error instead of spawning
- Circular reference detection: runtime tracks agent IDs in the current chain, rejects if the same agent ID appears twice

How it works:
- Any agent can call `subagents({tasks: [{agent: "coding_planner", task: "..."}]})`
- The runtime loads the coding_planner definition via `agent_loader`
- If coding_planner's definition has `sandbox` in its `mcps` → caller creates a sandbox container for it
- coding_planner runs in its own sandbox with full file access
- coding_planner can call `subagents({tasks: [{agent: "builder", ...}, {agent: "tester", ...}]})`
- builder and tester share coding_planner's sandbox (D28 shared sandbox policy, superseded by D29)
- builder can call `subagents({agent: "explorer", ...})` → infinite recursive depth

Sandbox creation is triggered by agent definition, not by a special tool:
```
agent_loader("coding_planner") → definition.mcps = {sandbox: [read, write, edit, bash]}
→ caller sees "sandbox" in mcps → creates sandbox container → provides MCP connection
→ runtime runs coding_planner with the sandbox ToolProvider
```

Example flow:
```
developer agent (own sandbox A)
  └── subagents({agent: "coding_planner", task: "Build login page"})
        → coding_planner gets own sandbox B (git fetch/pull at start)
        └── subagents([
              {agent: "builder", task: "Implement login form"},
              {agent: "builder", task: "Implement auth logic"}  // parallel!
            ])
              → both builders share sandbox B
              → builder 1 writes login.tsx
              → builder 2 writes auth.ts
        └── subagents({agent: "tester", task: "Test login flow"})
              → tester shares sandbox B
              → runs tests, reports results
        └── done(summary: "Login page built and tested")
        → git commit + push from sandbox B
  ← developer gets coding_planner's result
  └── continues with next task
```

Why: Eliminates the special `execute_coding_task` tool entirely. The `subagents` builtin is the universal mechanism for spawning any agent. Simpler architecture, one pattern for everything.

Implications:
- `execute_coding_task` is removed from the core-tools MCP (D10 updated)
- The core-tools MCP only has: hitl_ask_question, make_plan, set_intent, invoke_skill, create_message, test_report
- Sandbox creation is a caller-side concern triggered by agent definition's `mcps`
- The agent runtime is agnostic to sandbox creation — it just receives `mcp_connections` and resolves tools

---

### Decision D28: Shared Sandbox Policy — Agent-Level Responsibility (superseded by D29)

**Decision**: All subagents within a coding task share ONE sandbox container. The agent/planner is responsible for ensuring parallel subagents don't work on the same files. No isolation between subagents — simpler architecture, lower resource usage. This is a pragmatic first iteration — can be changed to full isolation later if needed.

**How it works**:
- Subagents spawned by a parent agent (via `subagents` builtin) all use the same sandbox container
- The parent agent (typically a planner) must coordinate via prompts to prevent file conflicts
- Example: two parallel builder subagents should be assigned different files or directories
- If file conflicts become a real problem in practice, we can introduce per-agent isolation later without changing the runtime API

**Example flow** (from D27, consistent with this decision):
```
developer agent (own sandbox A)
  └── subagents({agent: "coding_planner", task: "Build login page"})
        → coding_planner gets own sandbox B (git fetch/pull at start)
        └── subagents([
              {agent: "builder", task: "Implement login form"},
              {agent: "builder", task: "Implement auth logic"}  // parallel!
            ])
              → both builders share sandbox B
              → builder 1 writes login.tsx
              → builder 2 writes auth.ts
```

**Why**: Keep it simple for now. Agent-level coordination (via prompts) is sufficient for most cases. If file conflicts become a real problem, we can introduce per-agent isolation later without changing the runtime API.

User quote: "shared sandbox, agent's responsibility to avoid conflicts, simple approach for now, can change later"

> **Superseded by D29** — Agent-level sandbox configuration provides a more complete model.

---

### Decision D29: Agent-Level Sandbox & Git Configuration (supersedes D28)

**Decision**: Sandbox configuration is per-agent in YAML under `mcps.sandbox`. The `git` field controls repository scope: `current_project` | `other_projects` | `update_core`. Sandbox sharing is determined by the ToolProvider based on git scope matching. No explicit `none` option — absence of `mcps.sandbox` means no sandbox.

**How it works**:

Each agent definition declares its sandbox needs in YAML:

```yaml
# builder.yaml
role: subagent
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, push_changes]
    git: current_project
  core-tools: [make_plan]

# update_core_builder.yaml
role: subagent
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, push_changes]
    git: update_core
  core-tools: [make_plan]

# explore_other_projects.yaml
role: subagent
mcps:
  sandbox:
    tools: [read_file]
    git: other_projects
  core-tools: []

# planner.yaml
role: primary
mcps:
  core-tools: [make_plan, hitl_ask_question]

# developer.yaml
role: both
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, push_changes]
    git: current_project
  core-tools: [make_plan, hitl_ask_question]
```

**Key concepts**:

- `mcps.sandbox.tools` — which sandbox MCP tools the agent gets. `push_changes` is a sandbox MCP tool — included for agents that can push, excluded for read-only agents. The sandbox MCP tools listed in YAML examples are representative. The full tool list will be defined during implementation based on the current coding MCP's tools (read_file, write_file, edit_file, bash, make_design, push_changes, list_dir, batch_write_files, delete_file, search_files, get_file_info, etc.).
- `mcps.sandbox.git` — which git scope:
   - `current_project`: The user's project being worked on (cloned from Gitea)
   - `other_projects`: Other projects for reference (read-only, all projects cloned). All projects in Gitea that the session user has access to are cloned into the sandbox. The agent receives a project listing tool to know what's available. This scales with Gitea — clone is read-only, no push.
   - `update_core`: Druppie's core repository (cloned from GitHub for self-modification)
- If no `mcps.sandbox` section → no sandbox, no git, no file tools.
- `role` field — determines where agent can appear in flows: `primary` (top-level), `subagent` (spawned by parent), `both` (can be either). Role enforcement happens in the ToolProvider, not the agent runtime. When the ToolProvider receives a `subagents()` call, it loads the target agent's YAML and checks the `role` field. If a `subagent`-only agent is called at the top level (not via subagents()), the ToolProvider rejects it with an error. The runtime remains generic — it doesn't know about roles.

**Sandbox sharing logic** (handled by ToolProvider, not runtime):

| Parent Git | Subagent Git | Result |
|---|---|---|
| none (no sandbox) | current_project | New sandbox for subagent |
| current_project | current_project | Share parent's sandbox |
| current_project | update_core | New sandbox (different git) |
| none | none | No sandbox |
| update_core | update_core | Share parent's sandbox |
| any | other_projects | New sandbox (read-only) |

**Push/PR tool behavior**:

`push_changes` is a sandbox MCP tool. However, the actual push/PR operation runs **outside** the sandbox container:

1. Agent calls `push_changes` tool (inside sandbox)
2. ToolProvider intercepts the call
3. ToolProvider (which has git credentials) extracts changes from sandbox via `git bundle`
4. ToolProvider pushes to Gitea/GitHub directly
5. ToolProvider creates PR via API

This separation keeps git credentials out of the sandbox while still allowing agents to trigger pushes.

**Read-only enforcement for `other_projects`**:

For `git: other_projects`, the sandbox is created normally with all projects cloned in. However, the `tools` list only includes read tools:

```yaml
mcps:
  sandbox:
    tools: [read_file]  # No write_file, edit_file, bash, push_changes
    git: other_projects
```

This is mechanical enforcement — the LLM literally cannot call write tools because they're not in its tool list. No runtime checks needed.

**One git per agent**:

Each agent can have only one git scope. If you need multiple git scopes, use multiple agents. Example:

```yaml
# Agent that reads from other_projects and writes to current_project
# → Not possible as a single agent. Split into two:

# explorer.yaml (reads other_projects)
role: subagent
mcps:
  sandbox:
    tools: [read_file]
    git: other_projects

# implementer.yaml (writes current_project)
role: subagent
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash]
    git: current_project
```

**Flow examples**:

```
Session: user project X
planner (no sandbox)
  └→ subagents(developer)
      developer (git: current_project → ToolProvider creates sandbox, clones project X)
        └→ subagents(coding_planner)
            coding_planner (git: current_project → ToolProvider shares developer's sandbox)
              └→ subagents([builder, builder])
                  both builders (git: current_project → share same sandbox)

architect (no sandbox)
  └→ subagents(update_core_builder)
      update_core_builder (git: update_core → ToolProvider creates NEW sandbox, clones GitHub core)
      → works on core independently

business_analyst (no sandbox)
  └→ subagents(explore_other_projects)
      explore_other_projects (git: other_projects → new sandbox, all projects cloned, read-only tools only)
```

**Relationship to D19**:

D19 removes the global coding MCP and introduces "per-agent sandbox containers." D29 is the concrete realization of this — the per-agent sandbox containers are now configured via `mcps.sandbox` in agent YAML. The ToolProvider creates and manages these containers based on the agent's git scope.

**Relationship to D20**:

D20 introduces a warm pool of sandbox containers. D29 is consistent with this — the ToolProvider pulls containers from the warm pool when creating sandboxes for agents based on their `mcps.sandbox.git` scope.

User quote: "sandbox config in agent YAML under mcps.sandbox, ToolProvider handles sharing, no git:none option, push_changes as sandbox tool"

---

### Decision D30: make_design Tool — Sandbox MCP with Auto-Commit

**Decision**: `make_design` is a sandbox MCP tool with automatic git commit and push. It's only available to agents that explicitly list it in their `mcps.sandbox.tools` — currently only `architect` and `business_analyst`. NOT available to all sandbox agents by default — restricted per agent YAML.

**Key points**:

- `make_design` lives in the **sandbox MCP** — it's a file write operation with extras
- Available only to agents that explicitly list it in their `mcps.sandbox.tools` — currently only `architect` and `business_analyst`
- NOT available to all sandbox agents by default — restricted per agent YAML
- **Auto-commits to git after writing** — design docs are architectural milestones, always saved immediately
- Pre-validate hook: Mermaid syntax validation runs via ToolProvider (backend-side, before tool executes)
- Approval gate: architect role requires human approval (existing behavior, configured via ToolProvider approval_overrides)
- The git push happens via ToolProvider (same mechanism as `push_changes` — ToolProvider has credentials, extracts via git bundle, sandbox has no creds)
- What it does: validates Mermaid syntax in markdown content, writes file to sandbox workspace, auto-commits and pushes
- `make_design` is the ONLY sandbox tool that auto-commits. Regular `write_file` does NOT auto-commit — agents write many files and commit when ready via `push_changes`
- Frontend renders the design document in the approval gateway — user can see the rendered markdown + Mermaid diagrams before approving

**YAML examples**:

```yaml
# architect.yaml
role: primary
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, make_design, push_changes]
    git: current_project
  core-tools: [hitl_ask_question, make_plan]

# business_analyst.yaml
role: primary
mcps:
  sandbox:
    tools: [read_file, make_design]
    git: current_project
  core-tools: [hitl_ask_question]

# builder.yaml — no make_design
role: subagent
mcps:
  sandbox:
    tools: [read_file, write_file, edit_file, bash, push_changes]
    git: current_project
  core-tools: [make_plan]
```

**Flow example**:

```
architect → make_design(path="docs/technical-design.md", content="# Design\n```mermaid\n...")
  → Pre-validate: Mermaid syntax check (ToolProvider, backend-side)
  → Approval gate: architect role → pause for human approval
  → Human approves → write file to sandbox workspace
  → Auto git commit + push (via ToolProvider, using git bundle mechanism)
  → Design doc is now committed and visible in Gitea/GitHub
```

---

## 13. MCPToolProvider Design

### Interface

The ToolProvider is the execution layer between the agent runtime and MCP servers.

```python
class ToolProvider(Protocol):
    async def list_tools(self) -> list[dict]:
        """Return ALL tools from connected MCP servers (no filtering)."""
        ...
    
    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool with pre-validation and approval gates.
        
        Pipeline:
        1. Pre-validation hook (if configured) — run validation tool first
        2. Approval gate — check if tool needs approval → return _pending if yes
        3. Execute — call the MCP server
        """
        ...
    
    async def close(self) -> None:
        """Clean up MCP connections."""
        ...
```

### Role Enforcement for Subagents

When the ToolProvider receives a `subagents()` tool call (via `execute("subagents", args)`), it enforces role restrictions:

1. ToolProvider loads the target agent definitions specified in the `subagents` call
2. For each target agent, ToolProvider checks the `role` field in the agent's YAML definition
3. If a `subagent`-only agent (role="subagent") is called at the top level (not via subagents()), the ToolProvider rejects it with an error
4. Role enforcement is part of the ToolProvider's `execute()` method — it's not a separate method
5. The runtime doesn't need to know about roles — it just passes the `subagents` call to the ToolProvider

This ensures that agents designed only as subagents cannot be invoked directly as top-level agents, maintaining proper flow control.

### Who Does What

| Concern | Handled by | How |
|---------|-----------|-----|
| Tool filtering (what LLM sees) | **Agent runtime** | Filters provider's tool list by agent definition's `mcps` field |
| Skill tool expansion | **Agent runtime** | Adds new tools to LLM's visible list on `allowed_tools` response |
| Pre-validation (e.g., mermaid format check) | **ToolProvider** | Pre-execution hook: calls validation MCP tool before the real call |
| Approval gates | **ToolProvider** | Checks approval rules before MCP execution; returns `_pending` if needed |
| Actual tool execution | **ToolProvider** | Calls the MCP server after validation + approval pass |

### Pre-Validation + Approval Flow

Example: `make_design` needs mermaid format validation + architect approval.

```
1. LLM calls make_design(content="graph TD...")
2. Runtime calls provider.execute("make_design", {content: "..."})
3. Provider: pre-validation hook
   ├── Call mermaid_validate(content) on MCP server
   ├── If validation fails → return error to LLM immediately (no approval wasted)
   └── If validation passes → continue
4. Provider: approval gate
   ├── Check: does make_design need approval for this agent?
   ├── Yes → return {"_pending": true, "_resume_id": "approval_xxx"}
   └── User approves (hours later)
5. Provider: actual execution
   └── Call make_design(content) on MCP server → return result
```

### Approval Configuration

Approval rules are configured per-tool, per-agent in the agent YAML:

```yaml
# architect.yaml
approval_overrides:
  "sandbox:make_design":
    requires_approval: true
    required_role: architect
    pre_validate: "validate_mermaid"  # optional pre-validation tool
```

The ToolProvider reads these rules at construction time. For the Druppie backend, the provider is configured with the agent's approval_overrides from the YAML definition.

For applications: the ToolProvider has no approval rules by default. Applications can register pre-execution hooks as needed.

---

## 14. Database & Schema Decisions

### Decision D31: Subagent Timeline Representation

**Question**: How should subagent runs appear in the session timeline?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Nested in tool_call event | Subagent run is a special field on the parent's subagents() tool_call event | Simple, no schema change | Hard to query, events buried in JSON |
| B: Separate agent_run with parent_agent_run_id FK | Subagent gets its own agent_run row with parent_agent_run_id column | Easy to query, same schema as primary agents | Need to filter by parent for nesting |
| C: Separate table for subagent_runs | Dedicated table for subagent runs | Clean separation | Duplicate schema, more complex joins |

**Decision**: **B** — Separate agent_run with parent_agent_run_id FK. Same table, same schema, just with an optional FK. Simple to query, easy to nest in API response, no duplication.

---

### Decision D32: Subagent Event Ownership

**Question**: How should subagent events be stored?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Events reference subagent's agent_run_id | Each event has agent_run_id FK. Subagent events point to the subagent's agent_run | Clean, queryable by agent | Need to join for full timeline |
| B: Events reference parent's agent_run_id | Subagent events are stored under the parent agent_run | Simple timeline query | Ambiguous which tool calls belong to subagent vs parent |
| C: Duplicate events | Events stored under both parent and subagent | Both views work | Data duplication, inconsistency risk |

**Decision**: **A** — Events reference the subagent's own agent_run_id. The API assembles the nested timeline by querying all agent_runs for the session and building the tree using parent_agent_run_id.

---

### Decision D33: Subagent Run Status Tracking

**Question**: How should we track subagent run status?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: In-memory only, events tell the story | No status field, reconstruct from events | No state to manage | Expensive to query status |
| B: agent_run.status field (same as primary) | Subagent agent_run has status: running/completed/error/cancelled | Same as primary, simple | Need to update on completion |
| C: Status in parent's tool_result | Subagent status embedded in the parent's subagents() tool result | No extra query | Can't query subagent status directly |

**Decision**: **B** — Same status field as primary agents. The subagents MCP creates the agent_run with status=running, updates to completed/error/cancelled when done. Simple, consistent, queryable.

---

### Decision D34: Agent Run Sequence Numbering

**Question**: How should we order agent runs in the session?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Auto-increment sequence_number | Each new agent_run gets next sequence_number | Simple ordering | Subagents don't get sequence numbers (they're inline) |
| B: Fractional sequence numbers | Subagents get 4.5 between 4 and 5 | Works but ugly | Floating point issues, confusing |
| C: Integer sequence for primary, no sequence for subagents | Primary agents get sequence_number (for make_plan ordering), subagents don't need one (ordered by parent) | Clean separation | Need to explain two ordering schemes |

**Decision**: **C** — sequence_number is only for primary agents (make_plan ordering). Subagents are ordered by their parent's timeline position. They don't need their own sequence_number.

---

### Decision D35: Event Storage Granularity

**Question**: What events should we store?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Full events (every tool call, every LLM turn) | Store everything | Complete audit trail | Large storage, lots of data |
| B: Summary events only (agent start, agent done, errors) | Only major milestones | Small storage | Loses tool call details, hard to debug |
| C: Configurable per agent | Agent YAML defines what events to emit | Flexible | Complex config, inconsistent |

**Decision**: **A** — Full events. Storage is cheap, debugging is important. All tool calls, tool results, subagent starts/ends, LLM turns, errors. The callback receives everything, the caller decides what to persist.

---

### Decision D36: Context Overflow State Persistence

**Question**: How should we handle context overflow?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Force done(), no state | Runtime forces done() with auto-summary, run ends normally | Simple, no special state | Agent loses context, can't continue |
| B: Auto-compact and continue | Summarize conversation history and continue | Agent keeps going | Complex, may lose important details |
| C: Force done() with overflow flag | Force done() with AgentResult having an overflow indicator | Caller knows it was forced, can handle specially | Still ends the run |

**Decision**: **A** (aligned with D25) — Force done(). The runtime detects context overflow, forces one more LLM call with only done() available, auto-generates summary if needed. The caller sees a normal completed result. If the planner needs to handle this, it can via the summary content.

---

### Decision D37: Multiple Pending Tools Resume Strategy

**Question**: When an agent pauses for multiple pending approvals and user approves one, how should we resume?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Resume all at once | Wait until ALL pending tools are resolved, then resume | Simple, one resume call | User might want to approve one at a time |
| B: Resume per tool | Resume as each tool is approved, re-pause for remaining | More granular | Complex state management |
| C: Batch resume | User approves subset, runtime resumes with those, pauses for rest | Flexible | Complex |

**Decision**: **A** — Resume all at once. The runtime stores all pending tools in AgentState. When the caller resumes, it provides all answers. If user only answered some, the caller waits for all before resuming. Simple state management.

---

### Decision D38: Subagent Depth Tracking

**Question**: How should we track and limit subagent nesting depth?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Runtime config (max_subagent_depth) | LoopConfig has max_subagent_depth=10. Subagents MCP checks depth before spawning | Centralized, configurable | Need to pass depth to subagents MCP |
| B: Per-agent config in YAML | Each agent YAML defines max_depth | Per-agent control | Inconsistent, harder to enforce globally |
| C: Both — global max + per-agent override | Global default in LoopConfig, agents can override lower | Flexible | More complex |

**Decision**: **A** — Runtime config only (max_subagent_depth in LoopConfig, default 10). The subagents MCP receives the current depth from the runtime and rejects spawns that would exceed the limit. Simple, centralized.

---

### Decision D39: Agent State Serialization Format

**Question**: What format should we use for serializing paused agent state?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: JSON | Human-readable, debuggable, works with any DB column | Can't serialize arbitrary Python objects | We control the types, so this is fine |
| B: Pickle | Preserves full object graph | Not human-readable, security risks | Overkill for message history |
| C: MessagePack | Binary, compact, fast | Not human-readable, extra dependency | Marginal size improvement |

**Decision**: **A** — JSON. The AgentState is just message history (list of dicts), tool call tracking (list of dicts), and preconditions state (dict). All easily JSON-serializable. Stored as JSON text in the DB.

---

### Decision D40: Summary Accumulation Strategy

**Question**: How should the caller build the accumulated summary for each agent?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Query DB each time | Before each run, query all completed agent_runs for summaries | Always up-to-date, simple | Extra DB query per agent |
| B: Maintain in-memory accumulator | Caller keeps a running string of summaries | No extra query | State management, crash recovery |
| C: Store accumulated summary on session | Session record has accumulated_summary field | Fast read, always available | Data duplication, need to update |

**Decision**: **A** — Query DB each time. Simple, always correct, crash-safe. The query is cheap (filter by session_id, status=completed, order by sequence_number). No state management needed.

---

### Decision D41: Tool Call → Subagent Linking

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: source_tool_call_id FK on agent_runs | agent_runs has FK pointing to the tool_call that spawned it. Bi-directional link. | Clear, queryable, works with parallel | One extra column |
| B: child_run_id on tool_calls | tool_calls has FK pointing to the child run | Direct link from parent side | Won't work for parallel (one tool_call → multiple children) |
| C: Junction table | tool_call_subagents(tool_call_id, agent_run_id, order) | Most flexible | Extra table, overkill for 1:N |

**Decision**: **A** — source_tool_call_id FK on agent_runs. The agent_runs table gets a `source_tool_call_id` column pointing to the tool_call that created it. This gives us a bi-directional link: tool_calls.agent_run_id → parent agent, agent_runs.source_tool_call_id → spawning tool call. Works for parallel subagents (one tool_call, multiple child runs all pointing to the same source_tool_call_id).

---

### Decision D42: Parallel Subagent Representation

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: One tool_call, multiple child runs | subagents([a, b]) creates ONE tool_call with TWO agent_runs | Matches LLM reality (one call), simple | Need to parse arguments to know which agent is which |
| B: One tool_call per subagent | subagents([a, b]) creates TWO tool_calls | Each child linked to exactly one tool_call | Doesn't match LLM reality, need to split one response |
| C: Hybrid | One parent tool_call + individual child tool_calls | Both views available | Data duplication |

**Decision**: **A** — One tool_call, multiple child runs. The LLM makes one subagents() call, we store one tool_call record. The child agent_runs all have source_tool_call_id pointing to that one tool_call. Children are ordered by started_at. This matches the LLM's actual behavior and keeps the data model simple.

---

### Decision D43: Resume State — Serialized Blob vs Event Reconstruction

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Serialized AgentState blob | Runtime returns a serialized state object when paused. Caller stores it in DB. On resume, loads and passes it back. | Fast resume (no reconstruction), simple runtime interface | Two representations of same data (events + state), extra DB column, deserialization complexity, state can drift from events |
| B: Reconstruct from events | No serialized state. On resume, caller queries all events for the agent_run from DB, converts them back to LLM message format, passes as initial_messages. | Single source of truth (events only), no extra DB column, no serialization format to maintain, always consistent | Slower resume (query + reconstruct), need a reconstructor function |
| C: Both — blob for fast path, events as fallback | Store both serialized state AND events. Resume from blob normally, reconstruct from events if blob is missing/corrupt. | Best of both worlds | Maximum complexity, two things to keep in sync |

**Decision: B** — Reconstruct from events. Events are the single source of truth for timeline, streaming, AND resume. No serialized blob. On resume, the caller queries events from DB, converts them back to LLM message format (system message, assistant turns, tool calls, tool results), and passes the reconstructed messages as `initial_messages` to `run()`. This eliminates the AgentState class entirely and keeps the data model simple. Resume is slightly slower (query + reconstruct) but for a human-approval flow, a few hundred milliseconds is negligible.

---

### Decision D44: Sandbox Container Lifecycle on Pause/Resume

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Keep running while paused | Container stays alive during pause. No state loss. | Simple, no work lost | Wastes resources, containers idle for hours |
| B: Stop container, auto-commit WIP first | Auto-commit with WIP message, then stop. Resume clones from git. | No work loss, saves resources | WIP commits in git history, messy |
| C: Stop container, accept work loss | Stop container on pause. Uncommitted changes lost. Resume starts fresh from git. | Simplest, clean git history | Possible work loss |
| D: TTL-based | Keep for 30min, then stop with WIP commit | Handles short and long pauses | More complex, two code paths |

**Decision: C** — Stop container on pause, accept work loss. Coding agents are instructed via system prompt to always commit before calling tools that cause pauses (hitl_ask_question, approval gates). This is a soft constraint, not mechanically enforced. The warm pool always has fresh containers ready. On resume, a new container is created from the latest git state. Always stop on done() as well — next agent starts fresh from git.

---

### Decision D45: AgentState and Events — Unify or Separate?

The runtime loop maintains conversation history as a list of LLM messages. Events are individual records of what happened. On resume, we reconstruct LLM messages from events. On timeline fetch, we reconstruct a hierarchical view from events. This is double reconstruction of the same data.

Key insight: AgentState is only ever appended to (add turns, tool calls, results — never remove). Each append IS an event. So AgentState IS an event log, just stored differently. The LLM message format is almost exactly what we'd store as an event — just add timestamp, sequence_number, and metadata.

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Events only, reconstruct on demand (current decision D43) | Events stored in relational tables (agent_runs, tool_calls, llm_calls). On resume: query + reconstruct LLM messages. On timeline: query + reconstruct hierarchy. | Familiar relational model, individual record queries work well, FK integrity | Double reconstruction (resume + timeline), N+1 queries for timeline, 200+ lines of reconstruction code |
| B: Unified event log (AgentState = events) | Single append-only table (agent_state_events). Each entry IS an LLM message with added metadata. On resume: load + simple filter (10 lines). On timeline: load + single-pass projection (50 lines). | Single source of truth, no reconstruction, simpler code, single-query timeline, aligns with event sourcing | Less natural for individual record queries, JSONB for some fields, migration effort |
| C: Keep both (serialized AgentState + events) | Store both a serialized state blob AND individual events. Resume from blob, timeline from events. | Fast resume (load blob), queryable timeline | Dual representation, state can drift from events, extra storage |

**Decision: B** — Unified event log. A single append-only table (`agent_state_events`) stores all state entries. Each entry IS an LLM message with added metadata (timestamp, sequence_number, tokens, etc.). On resume, load entries and filter to LLM messages (simple map, ~10 lines). On timeline, load entries and project to hierarchical view (single pass, ~50 lines). This eliminates ~200 lines of reconstruction code, solves the N+1 query problem for timeline, and provides a single source of truth. The data structure is literally the LLM message format with DB fields added.

---

### Decision D46: agent_runs and agent_state_events — Separate or Merged?

agent_runs stores run-level metadata (status, summary, variables, sequence_number, parent FKs) — one row per agent execution. agent_state_events stores the conversation log — N rows per agent execution. They are linked by agent_state_events.agent_run_id → agent_runs.id. Should they be merged into one table?

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A: Keep separate | agent_runs = header row (status, summary, variables). agent_state_events = detail rows (conversation log). Linked by FK. | Fast status queries (indexed column, not JSONB filter). Native types, FK constraints. Hot-path queries (find pending runs, get summary) are O(1). | Two tables to understand. |
| B: Merge into one | Single table. Run metadata becomes fields on a special "run_start" event. Status/summary stored as metadata. | One table, one concept. | Slow status queries (JSONB filter on every loop iteration). No FK constraints on status. Complex JSONB updates. All hot-path queries become slower. |
| D: Header-detail framing | Same as A but framed explicitly as header-detail pattern. agent_runs is the header, events are the details. | Same performance as A. Clearer mental model. | Same as A. |

**Decision: A** — Keep separate. agent_runs is queried independently for hot-path operations: finding next pending run (every loop iteration), getting summary/variables, token aggregation, zombie recovery. These would all become slow JSONB queries if merged. The status field is a native column with FK constraints — cannot drift from events. Two tables is a small price for correct separation of concerns.
