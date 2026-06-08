6. [Critical Bugs](#critical-bugs)
7. [Security Concerns](#security-concerns)
8. [Code Quality Issues](#code-quality-issues)
9. [Test Coverage Assessment](#test-coverage-assessment)
10. [What Got Deleted](#what-got-deleted)
11. [Database Schema Changes](#database-schema-changes)
12. [Recommendations](#recommendations)

---

## Executive Summary

This is a **massive PR** that fundamentally rearchitects how Druppie executes AI agents. It replaces the old monolithic agent loop with a clean, modular `agent_runtime` library, introduces per-agent sandbox containers with Docker-in-Docker isolation, adds subagent spawning with recursive depth tracking, and restructures all agent YAML definitions into a hierarchical folder layout.

The **good news**: The core `agent_runtime` library is well-architected with clean layering, Protocol-based abstractions, and comprehensive test coverage. The sandbox isolation model is solid.

The **bad news**: The PR is too large to review properly in one pass. The compatibility bridge layer (`compat.py`) is the weakest link — 747 lines of dense coupling code with wrong log levels, encapsulation breaks, and excessive DB commits. There are also a few runtime bugs in the MCP server code and missing implementations for tested features.

**Verdict**: The architecture is sound, but the PR needs targeted fixes before merge. I'd recommend splitting into 2-3 smaller PRs if possible, but if that's not practical, at minimum fix the critical bugs listed below.

---

## What This PR Does

In plain terms, here's what changed:

### The Core Idea
Druppie runs AI agents (like a "developer" agent that writes code, a "planner" agent that creates plans, etc.). Previously, the code that ran these agents was a monolithic Python script. This PR extracts it into a **standalone library** called `agent_runtime` that can theoretically work without the rest of Druppie.

### What's New
1. **Agent Runtime Library** (`druppie/agent_runtime/`): A clean Python library for executing agents with LLM loops, tool routing, event tracking, and subagent spawning
2. **Per-Agent Sandbox Containers**: Instead of sharing a filesystem, each agent gets its own isolated Docker container with Docker-in-Docker support (so agents can run `docker compose` inside their sandbox)
3. **Subagent Spawning**: Agents can now spawn child agents (e.g., an "ultimate_dev" orchestrator spawns "developer", "test_builder", "reviewer" as subagents)
4. **YAML-Driven Agent Definitions**: Agent configs moved from code to YAML files with tool access rules, LLM settings, completion preconditions, and subagent lists
5. **`done()` Enforcement**: Agents MUST call a `done()` tool to complete, with preconditions and summary status requirements
6. **Live Bash Output**: Frontend now shows real-time output from long-running bash commands in sandboxes
7. **Developer Page**: New frontend page for running agents directly

### What's Deleted
1. **`background-agents/` subtree**: 382 files deleted — this was an external Node.js sandbox control plane that's been entirely replaced by the new Python-based sandbox system
2. **`druppie/opencode/`**: The OpenCode integration package (17 files) removed
3. **`druppie/api/routes/sandbox.py`**: 803 lines of old sandbox routes removed
4. **`druppie/core/sandbox_auth.py`**: Sandbox auth removed
5. **`druppie/db/models/sandbox_session.py`**: Sandbox session model removed
6. **`druppie/db/seed.py`**: Seed data removed
7. **Old agent YAMLs**: `builder.yaml`, `developer.yaml`, `reviewer.yaml`, `update_core_builder.yaml`, `data_analyst.yaml`, `documenter.yaml` all removed and replaced

---

## Architecture Overview

```
NEW ARCHITECTURE:
                              ┌──────────────────┐
                              │  Agent YAML files │
                              │  (definitions/)   │
                              └────────┬─────────┘
                                       │ parse
                              ┌────────▼─────────┐
                              │  agent_runtime/   │
                              │  ┌──────────────┐ │
                              │  │ AgentLoop    │ │  LLM <-> Tool call cycle
                              │  │   loop.py    │ │  with done() enforcement
                              │  ├──────────────┤ │
                              │  │ Definition   │ │  YAML parsing
                              │  │   definition │ │
                              │  ├──────────────┤ │
                              │  │ SubagentsMCP │ │  Recursive subagent spawning
                              │  │ subagents.py │ │  (depth=10, parallel gather)
                              │  ├──────────────┤ │
                              │  │ Tools        │ │  done(), MCP routing,
                              │  │  provider.py │ │  approval gates
                              │  ├──────────────┤ │
                              │  │ Events       │ │  Event emission + callbacks
                              │  │  events.py   │ │
                              │  └──────────────┘ │
                              └────────┬─────────┘
                                       │ bridge
                              ┌────────▼─────────┐
                              │   compat.py       │  747-line compatibility layer
                              │   (the weird one) │  connecting new runtime to old backend
                              └────────┬─────────┘
                                       │
                              ┌────────▼─────────┐
                              │   runtime_v2.py   │  AgentV2 facade
                              └────────┬─────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                   │
           ┌────────▼───────┐ ┌───────▼────────┐ ┌───────▼────────┐
           │  Orchestrator   │ │  ToolExecutor  │ │  MCP Servers   │
           │  (session mgmt) │ │  (validation,  │ │  (sandboxed    │
           │  (parent chain) │ │   access ctrl) │ │   Docker exec) │
           └────────────────┘ └────────────────┘ └────────────────┘
```

### Key Design Decisions
- **Protocol-based abstraction**: `ToolProvider` uses Python's `Protocol` for structural typing
- **Event-driven**: All state changes emit `AgentEvent` instances with real-time callbacks
- **`done()` enforcement**: Agents MUST call `done()` — no silent completion allowed
- **Parallel subagents**: `asyncio.gather` for concurrent execution
- **Storage-agnostic intent**: Core library doesn't know about databases (though this is violated in `SessionPauseToken`)

---

## Deep Dive: `compat.py`

This is the file you specifically asked about. It's located at `druppie/agent_runtime/compat.py` (747 lines). Here's what it does and why it's "weird".

### What `compat.py` Is

It's a **bridge/adapter layer** that connects the new `agent_runtime` library (clean, standalone) to the old Druppie backend (messy, coupled to databases and repositories). Think of it as a translator — the new runtime speaks one language, the old backend speaks another, and `compat.py` translates between them.

### The 4 Key Components

| Component | Purpose | Lines |
|-----------|---------|-------|
| `adapt_llm()` | Wraps old `BaseLLM.achat()` into the async callable format the new runtime expects | ~50 |
| `DruppieToolProvider` | Implements the new `ToolProvider` protocol by routing tool calls through the old `ToolExecutor` and `ExecutionRepository` | ~300 |
| `create_event_persister()` | Creates a callback that translates runtime events into old DB operations (create LLM calls, update agent status, etc.) | ~200 |
| `old_definition_to_new()` | Converts old Pydantic `AgentDefinition` models to new dataclass format | ~80 |
| `SubagentsMCPConnection` | Wraps `SubagentsMCP` as an in-process connection for the tool provider | ~80 |

### Why It Feels "Weird"

1. **It's massive** — 747 lines for a "compatibility layer" that should ideally be thin. The `create_event_persister()` function alone is ~180 lines of dense nested code.

2. **Wrong log levels everywhere** — Uses `logger.warning()` for messages like:
   ```python
   logger.warning("LLM_RESPONSE debug [agent_run=%s]: data_keys=%s, ...")
   logger.warning("LLM_RESPONSE create_llm_call OK [agent_run=%s]: ...")
   logger.warning("LLM_RESPONSE update_llm_response OK [llm_call=%s]")
   ```
   These are DEBUG/INFO messages, not warnings. In production, your log monitoring will be flooded with false alarms.

3. **Breaks encapsulation** — The event persister directly sets private attributes on `DruppieToolProvider`:
   ```python
   tool_provider._last_tool_call_id = tc_id       # external code setting private attrs
   tool_provider._last_tool_call_name = tool_name  # this breaks OOP principles
   tool_provider.set_llm_call_id(llm_call_id)      # this one at least uses a method
   ```

4. **Excessive DB commits** — The `llm_response` event handler alone makes 6-8 separate `db.commit()` calls:
   ```python
   execution_repo.update_status(agent_run_id, "RUNNING")
   execution_repo.db.commit()          # commit 1
   # ... create LLM call
   execution_repo.db.commit()          # commit 2
   # ... update LLM response
   execution_repo.db.commit()          # commit 3
   # ... update tokens
   execution_repo.db.commit()          # commit 4
   ```
   If any of these fail partway through, you get partial state in the database. Should be a single transaction.

5. **Fragile tool name parsing** — MCP tools are named like `coding_read_file` and split with `tool_name.split("_", 1)`. A tool named `my_cool_read_file` would parse as server="my", tool="cool_read_file" — which is wrong. There's no escaping mechanism.

6. **The `tool_call` event handler has special-case for `done`** — It manually creates tool call records and patches them back into the LLM call's `response_tool_calls` list, all through raw DB queries bypassing the repository pattern. This is ~50 lines of fragile bookkeeping.

7. **`DruppieToolProvider` is doing too much** — It's simultaneously:
   - A tool list builder (merging builtin + MCP + subagent tools)
   - A tool executor (routing to builtin, HITL, MCP, or subagent execution)
   - A DB record creator (creating tool_call records for every execution)
   - A state manager (tracking llm_call_id, last_tool_call_id, tools_cache)

   These should be at least 2-3 separate classes.

### What Should Happen to It

Ideally, `compat.py` is **temporary** — it exists to bridge the gap while the old backend is incrementally migrated to use the new runtime directly. Over time, the old backend's repository pattern, DB operations, and tool execution should be refactored to align with the new runtime's interfaces, and `compat.py` should shrink. If it's not temporary, the design needs rethinking.

---

## Key Change Areas

### 1. Agent Runtime Library (`druppie/agent_runtime/`)

**11 new files, ~2,570 lines added**

| File | Lines | Purpose |
|------|-------|---------|
| `loop.py` | 596 | Core LLM<->tool turn cycle with enforcement |
| `compat.py` | 747 | Bridge to old backend |
| `subagents.py` | 369 | Parallel subagent spawning |
| `definition.py` | 271 | YAML definition parsing |
| `types.py` | 147 | Core dataclasses (events, results, config) |
| `tools/provider.py` | 133 | Tool routing protocol + MCP implementation |
| `tools/done.py` | 154 | `done()` tool with preconditions + validation |
| `events.py` | 47 | Event emission + callbacks |
| `tools/mcp.py` | 45 | MCP connection type |
| `__init__.py` | 59 | Public API exports |
| `tools/__init__.py` | 0 | Empty |

**Assessment**: The core library (everything except `compat.py`) is well-designed with clean separation of concerns. The Protocol-based `ToolProvider`, event-driven architecture, and `done()` enforcement system are good patterns.

### 2. AgentV2 Facade (`druppie/agents/runtime_v2.py`)

**589 lines, new file**

This is the "glue" class that the orchestrator uses to run agents. It:
- Loads agent YAML definitions
- Creates adapted LLM (via `compat.py`)
- Creates tool providers (via `compat.py`)
- Creates event persisters (via `compat.py`)
- Wires up subagent connections for recursive spawning
- Bridges results back to the old dict format

**Issue**: The subagent wiring section (lines ~330-380) is a deeply nested closure factory that's hard to follow. It recursively creates its own nested `SubagentsMCPConnection` — this is the kind of code that works but nobody can modify confidently.

### 3. Orchestrator Changes (`druppie/execution/orchestrator.py`)

**+300/-24 lines modified**

The orchestrator now:
- Uses `AgentV2` instead of old `Agent`
- Walks parent chains when subagents complete (resumes parent when all siblings done)
- Handles multi-leaf resume for parallel paused subagents
- Creates separate DB sessions for concurrent leaf operations
- Runs language detection on HITL answers (not just initial messages)

**Good**: Separate DB sessions per leaf for parallel resume is correct concurrency hygiene.

**Issue**: `_walk_parent_chain` has no depth limit. A deeply nested subagent tree could blow the stack.

### 4. MCP Server Rewrite (`druppie/mcp-servers/module-coding/`)

**`v1/tools.py`: 1670 -> 2819 lines (+2200/-1670)**

Complete architectural shift from shared filesystem to sandbox orchestrator:
- Per-session Docker containers via Sysbox runtime
- All file/bash/git operations proxied through `docker exec`
- No git credentials in sandbox (push_changes uses git bundle extraction on host)
- GitHub App authentication for `update_core` flow
- Warm pool management, network isolation tiers
- Test framework detection, TDD validation, project discovery tools

**Issue**: At 2819 lines / 102KB, this is a massive single file that needs splitting.

### 5. Tool Executor Upgrades (`druppie/execution/tool_executor.py`)

**+34/-18 lines modified**

Added:
- Argument validation against tool schemas
- Pre-validation hooks (separate validation tool before approval gate)
- Skill-based tool access control
- Custom timeouts for long-running commands (up to 60 min for bash)
- Argument normalization (strips null values from LLM arguments)

### 6. YAML Agent Restructuring

**Before**: Flat `definitions/` folder
```
definitions/
  builder.yaml
  developer.yaml
  planner.yaml
  ...
```

**After**: Hierarchical task-based folders
```
definitions/
  coding/
    project/   (ultimate_dev, developer, builder_planner, test_builder, ...)
    core/      (ultimate_dev_core, core_explorer, core_builder_subagent)
  general/     (router, planner, architect, business_analyst, summarizer)
  system_prompts/ (shared prompt fragments)
  llm_profiles.yaml
```

New YAML fields: `role`, `subagents`, `done_variables`, `completion_preconditions`, `required_summary_status`, `llm_profile`, `skills`, `system_prompts`, `allowed_next_agents`, `sandbox_constraints`, `thinking`, `reasoning_effort`.

### 7. Frontend Changes

| File | Change |
|------|--------|
| `DeveloperPage.jsx` | **NEW** - 355 lines, agent execution UI |
| `SessionDetail.jsx` | +322/-177 - Subagent rendering, retry UI |
| `DebugEventLog.jsx` | +160/-86 - Recursive subagent display, raw/parsed toggle |
| `SandboxEventCard.jsx` | **REMOVED** - 829 lines deleted |
| `HITLQuestionMessage.jsx` | +42/-8 - Resume button for paused sessions |

### 8. LLM Provider Upgrades

- **Unified LiteLLM provider**: Now the sole provider, supporting ZAI, DeepInfra, DeepSeek, Azure Foundry, Ollama
- **Thinking/reasoning support**: Per-profile thinking configuration
- **Raw request/response capture**: Full API data stored for debugging
- **Argument repair**: Best-effort JSON fixing for malformed LLM outputs

---

## Critical Bugs

### Bug 1: `create_pr` Gitea Path Crashes
**File**: `druppie/mcp-servers/module-coding/v1/tools.py`
**Severity**: HIGH — runtime crash

The `create_pr` function has a code path where `api_url` and `payload` variables are used but only defined inside the `update_core` (GitHub) branch. The Gitea path references these variables without defining them. This means **Gitea PR creation will crash at runtime** with `NameError: name 'api_url' is not defined`.

### Bug 2: Missing Role Enforcement in Subagents
**File**: `druppie/agent_runtime/subagents.py`
**Severity**: MEDIUM — test failure

The test `test_role_enforcement_subagent_only_at_top_level` expects agents with `role="subagent"` to be rejected at `current_depth=0`, but `spawn_one()` has no role check. The test documents intended behavior that isn't implemented.

### Bug 3: Missing Circular Reference Detection in Subagents
**File**: `druppie/agent_runtime/subagents.py`
**Severity**: MEDIUM — test failure

The test `test_circular_reference_detection` expects "Circular reference" errors when an agent is already in the `agent_chain`, but `spawn_one()` never checks the chain for circular references. The `agent_chain` is constructed but never used for this purpose.

### Bug 4: Mutable Default Argument
**File**: `druppie/agent_runtime/loop.py`
**Severity**: MEDIUM — subtle runtime bug

```python
def __init__(self, ..., event_callbacks: list[Callable[[AgentEvent], None]] = []):
```
This is the classic Python mutable default argument gotcha. The same list object is shared across all instances that don't pass this argument. Events added to one agent's callbacks will appear in another's.

### Bug 5: Duplicate Git Bundle Creation in `push_changes`
**File**: `druppie/mcp-servers/module-coding/v1/tools.py`
**Severity**: LOW — wasted work

When `scope == "update_core"`, the git bundle is created twice (once in the shared path, once in the scope-specific path). The second creation overwrites the first, so the first is wasted work.

---

## Security Concerns

### 1. Global SSL Verification Disabled
**File**: `druppie/llm/litellm_provider.py`
**Severity**: HIGH

```python
litellm.ssl_verify = False  # Set globally when Ollama is configured
```
This disables SSL verification for ALL litellm calls, not just Ollama ones. If other providers (ZAI, DeepInfra, Azure) are also configured, their API calls will also skip SSL verification. This enables man-in-the-middle attacks on API key transmission.

### 2. API Key Prefix Logged
**File**: `druppie/llm/litellm_provider.py`
**Severity**: MEDIUM

```python
api_key_prefix=self.api_key[:8] + "..."
```
Even truncated, logging any part of API keys is a security risk in production. The first 8 characters of an API key significantly narrow the search space.

### 3. Raw Request/Response Storage
**Files**: `druppie/db/models/llm_call.py`, `druppie/agent_runtime/compat.py`
**Severity**: LOW

Full raw API requests and responses (including potentially sensitive user data) are now stored in the database as JSON columns. While `compat.py` strips `api_key` and `token` keys, there's no guarantee all sensitive data is caught. Consider adding a data retention policy.

---

## Code Quality Issues

### Size and Organization
| Issue | File | Lines |
|-------|------|-------|
| **Too large** | `v1/tools.py` | 2,819 |
| **Too large** | `compat.py` | 747 |
| **Too large** | `planner.yaml` system prompt | 370 |
| **Too large** | `loop.py` `run()` method | ~300 |
| **Too large** | `orchestrator.py` | ~700 |
| **Vestigial** | `v1/module.py` | 47 (duplicates tools.py patterns) |

### Design Issues
| Issue | Location | Description |
|-------|----------|-------------|
| Wrong log levels | `compat.py` | `logger.warning()` for debug/info messages |
| Encapsulation break | `compat.py` | External code sets private `tool_provider._*` attrs |
| Excessive commits | `compat.py` | 6-8 `db.commit()` per event instead of 1 transaction |
| Fragile tool parsing | `compat.py` | `tool_name.split("_", 1)` for MCP routing |
| Global mutable state | `tools.py` | `sandbox_containers`, `_container_locks` dicts |
| Thread safety | `tools.py` | Race condition in `_get_container_lock` |
| Storage-agnostic violation | `types.py` | `SessionPauseToken` imports DB models directly |
| Mixed old/new imports | `tool_executor.py` | Still imports from old `runtime.py` |
| No depth limit | `orchestrator.py` | `_walk_parent_chain` has unbounded recursion |
| `_estimate_tokens` | `loop.py` | `len(str(msg)) // 4` — no documentation |
| Suffix matching | `tools/done.py` | `_count_tool_calls` matches by suffix (fragile) |

### Missing Implementations
| Feature | Test File | Implementation |
|---------|-----------|----------------|
| Role enforcement | `test_subagents.py` | Not in `subagents.py` |
| Circular reference detection | `test_subagents.py` | Not in `subagents.py` |

---

## Test Coverage Assessment

**Overall**: Comprehensive for unit tests, good assertion quality, but missing integration tests.

| Test File | Lines | Tests | Quality |
|-----------|-------|-------|---------|
| `test_loop.py` | 872 | ~26 | Good — covers done enforcement, pause/resume, cancellation, overflow |
| `test_definition.py` | 329 | ~25 | Very thorough — edge cases, validation, defaults |
| `test_subagents.py` | 705 | ~25 | Excellent — recursion, sandbox sharing, error propagation |
| `test_orchestrator_subagents.py` | 584 | ~16 | Very good — includes StrEnum regression tests |
| `test_tools_done.py` | — | ~20 | Good — schema generation, preconditions, validation |
| `test_tools_provider.py` | — | ~15 | Good — routing, approval gates |
| `test_types.py` | — | ~15 | Good |
| `test_events.py` | — | ~10 | Good |
| `test_tools_mcp.py` | — | ~5 | Good |

**Gaps**:
1. **2-3 tests will FAIL** because role enforcement and circular reference detection are tested but not implemented
2. No integration test for the full pipeline (YAML -> runtime -> LLM -> done)
3. No test for `break_on_failure` behavior mentioned in docs
4. No test for `coding_networks` property

---

## What Got Deleted

### `background-agents/` (382 files)
The entire Node.js sandbox control plane (from `nuno120/background-agents`). This included:
- Control plane (Cloudflare Workers, Durable Objects)
- GitHub bot, Linear bot
- Local control plane, sandbox manager
- Web dashboard (React)
- CI/CD workflows, Terraform configs
- ~50,000+ lines of TypeScript

**Replaced by**: The Python-based sandbox system in `v1/tools.py` using Sysbox containers.

### `druppie/opencode/` (17 files)
OpenCode integration package — removed as it's been replaced by the agent runtime.

### `druppie/api/routes/sandbox.py` (803 lines)
Old sandbox REST API routes — replaced by new sandbox management in MCP server.

### `druppie/db/models/sandbox_session.py`, `druppie/core/sandbox_auth.py`, `druppie/db/seed.py`
Sandbox session model, auth, and seed data — all removed as the sandbox architecture changed.

### Old Agent YAMLs
`builder.yaml`, `developer.yaml`, `reviewer.yaml`, `update_core_builder.yaml`, `data_analyst.yaml`, `documenter.yaml` — all deleted and replaced by new hierarchical structure.

---

## Database Schema Changes

### New Columns (all additive, safe)
| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `agent_runs` | `spawning_tool_call_id` | UUID (FK) | Links subagent runs to spawning tool call |
| `tool_calls` | `sandbox_waiting_at` | DateTime | Sandbox timeout watchdog timestamp |
| `llm_calls` | `thinking_content` | Text | LLM reasoning output |
| `llm_calls` | `raw_request` | JSON | Full API request for debugging |
| `llm_calls` | `raw_response` | JSON | Full API response for debugging |

### Dropped
| Table | Impact |
|-------|--------|
| `sandbox_sessions` | Entire table removed (replaced by in-memory tracking) |

Per project policy (no migrations, reset DB), all changes are compatible with a full DB reset.

---

## Recommendations

### Must Fix Before Merge
1. **Fix `create_pr` Gitea crash** — `api_url` and `payload` are undefined in the Gitea code path
2. **Fix mutable default argument** in `loop.py` — change `event_callbacks=[]` to `event_callbacks=None` and default inside the method
3. **Fix global SSL verify** — scope `ssl_verify = False` to Ollama calls only, not globally
4. **Either implement or remove tests** for role enforcement and circular reference detection in `subagents.py`

### Should Fix Before Merge
5. **Fix wrong log levels** in `compat.py` — change `logger.warning()` to `logger.debug()` for non-warning messages
6. **Fix encapsulation break** — use proper methods instead of setting private attributes
7. **Consolidate DB commits** — use single transactions instead of 6-8 separate commits per event
8. **Fix `_get_container_lock` race condition** — use `setdefault` or a module-level lock
9. **Remove duplicate `BLOCKED_COMMAND_PATTERNS`** — either import from `module.py` or delete `module.py`

### Should Fix Soon After Merge
10. **Split `v1/tools.py`** (2819 lines) into modules: `container_mgmt.py`, `git_ops.py`, `test_tools.py`, `project_discovery.py`
11. **Decompose `loop.py` `run()` method** (300 lines) into smaller methods
12. **Decompose `create_event_persister()`** (180 lines) into a class with methods per event type
13. **Add depth limit** to `_walk_parent_chain` in orchestrator
14. **Remove API key prefix logging** from litellm provider
15. **Add data retention policy** for raw request/response storage

### Nice to Have
16. **Split PR into smaller pieces** if still possible — the current 591-file diff is extremely hard to review thoroughly
17. **Add integration tests** that verify the full pipeline (YAML -> runtime -> mock LLM -> done)
18. **Upgrade Docker in Docker** from 20.10.24 to a more recent version
19. **Consider `compat.py` a temporary migration layer** with a plan to phase it out
20. **Simplify planner's 370-line system prompt** — consider partial deterministic routing instead
