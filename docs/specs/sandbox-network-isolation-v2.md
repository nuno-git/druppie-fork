# Sandbox Network Isolation v2 — Per-Agent Dynamic Enforcement

**Status:** draft
**Author:** nuno
**Date:** 2026-05-27
**Supersedes:** `docs/specs/sandbox-network-isolation.md` (v1)

---

## Problem

v1 network isolation applies networks only at container creation. Once a container is created with internet access, ALL agents sharing that container (same session + git scope) inherit internet — even agents that should only have module access.

This creates the **Lethal Trifecta**: an agent holds sensitive module data in its context AND has internet access AND is exposed to untrusted content. A prompt injection from module data (or user input) can instruct the agent to exfiltrate data via `curl`, `wget`, or DNS queries.

See `docs/research/sandbox-data-exfiltration.md` for the full threat analysis.

## Design Principle

1. **Network access follows the agent, not the container.** Each agent declares its network tier. The coding MCP enforces it per tool call.
2. **Pipeline ordering prevents the trifecta.** Once any agent reads module data, no subsequent agent gets internet. The plan validates this.
3. **Networks switch dynamically, not just at creation.** Before each `coding:bash` call, the container's networks are adjusted to match the calling agent's profile.

## Network Tiers (unchanged from v1)

| Tier | Network Name | Access | Use Case |
|------|-------------|--------|----------|
| **Isolated** | `druppie-sandbox-net` | No external access | Default for all containers |
| **Internet** | `druppie-sandbox-inet` | Outbound internet (NAT) | pip install, curl public APIs |
| **Modules** | `druppie-sandbox-modules` | Module MCP servers only | Test against real modules |

All containers start on `sandbox-net`. The agent's `networks` list adds tiers on top.

## Per-Agent Network Profiles

| Agent | Networks | Rationale |
|-------|----------|-----------|
| installer | `[internet]` | Install dependencies before any data access |
| developer | `[internet]` | May need pip/docs, but NO module data access |
| builder_planner | `[internet]` | Plans code, may need docs |
| test_builder | `[internet]` | Only creates tests, no need for modules. Might need to install packages. |
| test_executor | `[modules]` | Runs tests against modules, NO internet |
| deployer | `[]` (isolated) | Just pushes code, no network needed |
| ultimate_dev_core | `[internet]` | Core platform work, no module data |
| business_analyst | `[]` (isolated) | Reads/writes markdown only |

### Pipeline Flow

```
installer (internet) → developer (internet) → test_builder (modules) → test_executor (modules) → deployer (isolated)
```

The rule: **internet agents always come before module agents. After the first module agent, no more internet.**

## Dynamic Network Enforcement

### Current Flow (v1 — broken)
```
agent YAML → coding_networks → mcp_config inject → sandbox_networks param → _resolve_container()
                                                                          → networks applied ONCE at creation
```

### New Flow (v2)
```
agent YAML → coding_networks → mcp_config inject → sandbox_networks param → _resolve_container()
                                                                          → _sync_networks(container, requested_networks)
                                                                          → networks adjusted BEFORE each command
```

### `_sync_networks` Implementation

Add a new function in `module-coding/v1/tools.py`:

```python
async def _sync_networks(container_name: str, requested_networks: list[str]) -> None:
    """Dynamically adjust container networks to match the agent's profile.
    
    Connects networks the agent needs but container doesn't have.
    Disconnects networks the container has but agent doesn't need.
    """
    # Map friendly names to Docker network names
    NETWORK_MAP = {
        "internet": SANDBOX_INET_NETWORK,
        "modules": SANDBOX_MODULES_NETWORK,
    }
    desired = {NETWORK_MAP[tier] for tier in requested_networks if tier in NETWORK_MAP}
    
    # Inspect current networks
    rc, stdout, _ = await _docker_run(
        ["docker", "inspect", container_name, "--format", "{{json .NetworkSettings.Networks}}"],
        timeout=10,
    )
    current = set(json.loads(stdout).keys()) if rc == 0 else set()
    
    # Always keep the base sandbox network
    base_network = SANDBOX_NETWORK  # sandbox-net
    
    # Disconnect networks no longer needed
    for net in current - desired - {base_network}:
        await _docker_run(["docker", "network", "disconnect", net, container_name], timeout=10)
    
    # Connect new networks
    for net in desired - current:
        await _docker_run(["docker", "network", "connect", net, container_name], timeout=10)
```

### Integration into `_resolve_container`

```python
async def _resolve_container(..., agent_networks: list[str] | None = None) -> str:
    # ... existing container lookup/creation logic ...
    
    # NEW: sync networks before returning the container
    if agent_networks is not None:
        await _sync_networks(container_name, agent_networks)
    
    return container_name
```

## make_plan Validation

### Rule
When `make_plan` is called with a list of steps, validate the network ordering:

```python
INTERNET_TIERS = {"internet"}
MODULE_TIERS = {"modules"}

def validate_plan_network_order(steps: list[dict]) -> tuple[bool, str]:
    """Ensure internet agents come before module agents."""
    seen_module = False
    for i, step in enumerate(steps):
        agent_id = step.get("agent_id", "")
        agent_defn = load_agent(agent_id)
        networks = agent_defn.mcps.get("coding", {}).get("networks", [])
        
        if seen_module and any(n in INTERNET_TIERS for n in networks):
            return False, (
                f"Step {i} ({agent_id}) requests internet but follows a module-access agent. "
                f"Reorder: internet agents must come before module agents."
            )
        
        if any(n in MODULE_TIERS for n in networks):
            seen_module = True
    
    return True, ""
```

### Enforcement Point
- In `execute_builtin_tool` when handling `make_plan`
- If validation fails, return an error to the planner agent so it can reorder

## Parallel Subagents

When the `subagents()` tool spawns multiple agents in parallel, they share the same container. If they have different network profiles, we have a conflict.

### Solutions (see research doc for analysis)

**Recommended: Solution A — Serialize network transitions**

Use the existing `asyncio.Lock` per container. When an agent needs a different network profile than the container currently has, it acquires the lock, syncs networks, runs its command, then releases. Parallel agents with the same profile run concurrently. Agents with different profiles are serialized.

**Alternative: Solution B — Separate containers per network profile**

Include network hash in the container key: `{session_id}::{scope}::{network_hash}`. Agents with different profiles get different containers. Shared workspace via Docker volume. True isolation but more resources.

**Alternative: Solution C — Strict ordering (no parallel network conflict)**

Enforce that all parallel subagents within a group must have the same network profile. If the planner tries to mix internet and module agents in parallel, reject the plan. Simplest to implement, limits flexibility.

## Code Changes Required

| File | Change |
|------|--------|
| `module-coding/v1/tools.py` | Add `_sync_networks()`, update `_resolve_container()` to call it |
| `druppie/agent_runtime/builtin_tools.py` | Add network validation to `make_plan` execution |
| `druppie/agent_runtime/subagents.py` | Add network conflict detection for parallel subagents |
| `druppie/agents/definitions/coding/**/*.yaml` | Verify/update `networks` declarations per agent |

## Migration from v1

1. Deploy `_sync_networks` — all existing agents continue to work (networks already declared)
2. Add `make_plan` validation — planner gets errors for bad ordering, adjusts
3. Add parallel subagent handling — choose Solution A/B/C
4. No database changes, no container format changes

---

## Example Flow: Building a Data Application with Public + Proprietary Data

### Scenario

A user wants to build a dashboard that:
1. Fetches public data from CBS (Statistics Netherlands open data API)
2. Combines it with proprietary data from Druppie's modules (e.g., demographics module, geo module)
3. Renders an interactive dashboard (Plotly/Dash)

The security challenge: agents need internet to fetch CBS data, AND they need module access to read proprietary module APIs. If an agent has both simultaneously, a prompt injection in the CBS data could exfiltrate module data via `curl`.

### Solution: Data Flows Through the Filesystem, Not the Context

The key insight: **internet agents and module agents never share a context window.** External data (CBS) and internal data (modules) flow together through the shared workspace filesystem, not through a single agent's context.

```
┌─────────────────────────────────────────────────────────────────┐
│  WORKSPACE (/workspace)                                         │
│                                                                 │
│  data/cbs/          ← written by data_fetcher (internet)       │
│    population.json                                         │
│    employment.csv                                          │
│                                                                 │
│  src/               ← written by developer (modules)           │
│    dashboard.py                                            │
│    data_combine.py   ← reads BOTH local CBS files AND module  │
│    models.py            SDK output, combines them              │
│                                                                 │
│  tests/             ← written by test_builder (modules)        │
│    test_dashboard.py                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 1: INSTALL (internet)                                         │
│                                                                      │
│  installer ───────────────────────────────────────────────────────── │
│    • pip install pandas plotly dash requests httpx                   │
│    • Networks: [internet]                                            │
│    • Context: task description, dependency list                      │
│    • NO module data, NO CBS data yet                                 │
│    • Workspace: clean, empty                                         │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 2: DATA FETCH (internet)                                      │
│                                                                      │
│  data_fetcher (or developer in internet mode) ─────────────────────  │
│    • Fetch CBS data: curl/requests to opendata.cbs.nl               │
│    • Save raw data to /workspace/data/cbs/*.json                     │
│    • Write data fetching scripts (src/fetch_cbs.py)                  │
│    • Networks: [internet]                                            │
│    • Context: CBS API docs, task description                         │
│    • NO module data — proprietary modules not accessible             │
│    • Workspace: contains public CBS data files                       │
│                                                                      │
│  ┌─── Security Guarantee ───────────────────────────────────────┐   │
│  │ Agent has internet but ZERO module access.                    │   │
│  │ Even if CBS data contains prompt injection:                   │   │
│  │   → Agent cannot read module APIs (no sandbox-modules net)   │   │
│  │   → Agent cannot exfiltrate what it cannot access             │   │
│  │   → Worst case: malicious code written to src/ files          │   │
│  │     (caught in code review / testing phase)                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                          ┌─────────┴──────────┐
                          │ NETWORK TRANSITION │
                          │ disconnect: inet   │
                          │ connect: modules   │
                          └─────────┬──────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 3: DEVELOP (modules — NO internet)                            │
│                                                                      │
│  developer ──────────────────────────────────────────────────────── │
│    • Read CBS data from /workspace/data/cbs/ (local files)          │
│    • Read module APIs via SDK (demographics, geo modules)            │
│    • Write src/data_combine.py: merges CBS + module data            │
│    • Write src/dashboard.py: renders Plotly dashboard                │
│    • Networks: [modules]                                             │
│    • Context: CBS data (from local files, NOT from internet),       │
│              module API specs (from module servers)                  │
│    • NO internet — cannot reach external servers                     │
│    • Workspace: contains CBS data + module integration code          │
│                                                                      │
│  ┌─── Security Guarantee ───────────────────────────────────────┐   │
│  │ Agent has module access but ZERO internet.                    │   │
│  │ Agent holds both CBS data (from files) and module data        │   │
│  │ (from APIs) in context — but CANNOT exfiltrate because:       │   │
│  │   → sandbox-inet is DISCONNECTED                              │   │
│  │   → curl, wget, dig, nslookup all fail (no route)            │   │
│  │   → DNS queries don't leave the sandbox network               │   │
│  │ The trifecta is broken: data access ✓, untrusted content ✓,  │   │
│  │ BUT no outbound network ✗                                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 4: TEST (modules — NO internet)                               │
│                                                                      │
│  test_builder ───────────────────────────────────────────────────── │
│    • Write integration tests against real module servers             │
│    • Test data combination logic with real CBS fixtures              │
│    • Verify dashboard renders correctly                              │
│    • Networks: [modules]                                             │
│    • Context: test requirements, module API specs                    │
│    • NO internet                                                     │
│                                                                      │
│  test_executor ──────────────────────────────────────────────────── │
│    • Run pytest / unit tests                                         │
│    • Verify module SDK calls return expected data                    │
│    • Networks: [modules]                                             │
│    • NO internet                                                     │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 5: DEPLOY (isolated)                                          │
│                                                                      │
│  deployer ───────────────────────────────────────────────────────── │
│    • Push code to Git (via module-coding proxy, not direct git)      │
│    • Create PR for review                                            │
│    • Networks: [] (isolated)                                         │
│    • Context: only deployment instructions                           │
│    • NO internet, NO modules, NO sensitive data                      │
└──────────────────────────────────────────────────────────────────────┘
```

### How the Data Combination Works Without the Trifecta

The critical question: if the developer can't access the internet, how does it get CBS data?

**Answer: the CBS data is already in the workspace from Phase 2.** The developer reads it as local files:

```python
# src/data_combine.py — written by developer (modules network, no internet)

import json
from pathlib import Path

# CBS data: read from local files saved by data_fetcher in Phase 2
cbs_population = json.loads(Path("data/cbs/population.json").read_text())

# Module data: fetched via SDK from module servers on sandbox-modules network
from druppie_sdk import DemographicsModule, GeoModule

demo = DemographicsModule()
geo = GeoModule()

demographics = demo.get_statistics(region="amsterdam")
geo_data = geo.get_boundaries(level="municipality")

# Combine: public CBS data + proprietary module data
combined = merge_datasets(cbs_population, demographics, geo_data)
```

The agent that writes this code:
- Reads CBS data from **local files** (saved by a previous internet agent)
- Reads module data from **module servers** (via sandbox-modules network)
- Has **NO internet** — even if CBS data contained a prompt injection, there's no channel to exfiltrate through

### Security Invariants Maintained

| Invariant | How |
|-----------|-----|
| CBS data never reaches internet-connected agent alongside module data | CBS is fetched in Phase 2 (no module access). Used in Phase 3 (no internet). |
| Module data never reaches an internet-connected agent | Module access only in Phase 3-4 (no internet). Phase 5 has neither. |
| Workspace files from module phase are never read by internet agents | Pipeline ordering enforced by make_plan: internet phases come first. |
| Prompt injection in CBS data cannot exfiltrate module data | When CBS data enters agent context (Phase 3), internet is disconnected. |
| Developer has enough context to write correct code | CBS data from files + module APIs from servers + plan text from planner. |

### What If the Developer Discovers It Needs Another Dependency?

When the developer (in modules-only phase) discovers it needs an additional package:

1. **Developer signals via `done()`** — "Agent developer: Need scipy for statistical analysis. Requesting re-plan with additional dependency."
2. **Orchestrator creates an approval gate** — the developer/architect role (technical expert, NOT the end user) receives the request with the current git diff showing all code written so far.
3. **Dev/architect reviews the git diff** — checks that no prompt injection payload has been injected into the codebase. This is the security checkpoint before re-enabling internet.
4. **If approved: internet re-enablement via git-based re-creation**
   - Current container is destroyed
   - New container is created with `[internet]` network
   - Git clone restores the workspace (all previous code + committed state)
   - `pip install` runs for the additional dependency
   - Package caches persist via `/cache` Docker volume across recreations
5. **After install: back to modules-only phase**
   - Container destroyed again
   - New container created with `[modules]` network
   - Git clone restores workspace (now with all deps installed in the venv... wait)

**The pip install problem:** pip installs go into the container's writable layer, which is destroyed with the container. A fresh `git clone` only restores source code, not installed packages.

**Solution: commit the virtual environment?** No — that's huge and bad practice.

**Better solution: persistent workspace volume per session+scope.** See "Sandbox Persistence" below.

### What About Runtime Data Fetching?

The dashboard app itself needs to fetch CBS data at runtime (to show fresh data). This is different from the build-time flow:

- **Build time** (agent pipeline): agents fetch CBS data, save as fixtures/files, write the fetching code. No trifecta risk.
- **Run time** (deployed app): the deployed app container has its own network config. It can have internet access for CBS API calls and module access for proprietary data — but it's NOT an LLM agent, it's a deterministic application. Prompt injection doesn't apply to regular code execution. It is reviewed by a human. Creation follows standard agent flow.

The LLM agent security model applies to the BUILD pipeline, not the runtime application.

---

## Sandbox Persistence

### Current State: Ephemeral Workspaces

Sandbox containers are **stateless**:
- `/workspace` is the container's writable layer — destroyed with the container
- `/cache` is a shared Docker volume — persists pip/uv caches only (not installed packages)
- No idle timeout — containers run indefinitely until explicitly destroyed (session end, user cancel, or error)
- On destruction: all installed packages, running processes, and in-memory state are lost

This works today because agents typically use ONE container per session. But with per-agent network profiles, we need container recreation across phase transitions (internet → modules). Recreation destroys the workspace.

### The Problem with Git-Only Persistence

Git preserves source code across container recreations, but NOT:
- Installed packages (`pip install` output lives in the container, not in git)
- Running processes (dev servers, databases)
- Environment state (shell history, temp files, build artifacts)

If the installer installs `pandas` in Phase 1, then the container is recreated for Phase 2 (modules), the developer's code `import pandas` will fail because pandas isn't installed in the new container.

### Solution: Per-Session Workspace Volume

Mount a named Docker volume for `/workspace` scoped to `{session_id}::{scope}`:

```python
workspace_volume = f"druppie-ws-{short_session}-{scope}"
# Create volume if it doesn't exist
await _docker_run(["docker", "volume", "create", workspace_volume], timeout=10)

cmd = [
    "docker", "run", "-d",
    "--name", container_name,
    ...
    "-v", f"{workspace_volume}:/workspace",    # Persistent workspace
    "-v", f"{SANDBOX_CACHE_VOLUME}:/cache",    # Shared package cache
    ...
]
```

**Lifecycle:**
1. Volume created when first agent in the session needs a sandbox
2. All containers for this session+scope mount the same volume
3. Container recreation (for network transitions) preserves the workspace
4. `pip install` survives across recreations — packages stay in the venv on the volume
5. Volume destroyed on session end (existing cleanup flow)

**Security implications:**
- The workspace volume is shared across ALL agents in the session, regardless of network profile
- Files written by an internet agent are readable by a modules agent and vice versa
- This is INTENTIONAL — data flows through the filesystem (the CBS + modules pattern)
- The security model relies on network isolation (no exfiltration channel), not filesystem isolation

### Container Lifecycle with Network Transitions

```
┌──────────────────────────────────────────────────────────────┐
│ Session starts                                               │
│                                                              │
│  1. Volume created: druppie-ws-{session}-{scope}             │
│                                                              │
│  2. Phase 1 (internet):                                      │
│     Container A created                                      │
│     Networks: sandbox-net + sandbox-inet                     │
│     Mounts: workspace volume + cache volume                  │
│     Installer runs: pip install pandas plotly dash            │
│     Git clone: check out project branch                      │
│     Container A destroyed (or kept if next phase matches)    │
│                                                              │
│  3. Phase 2 (modules):                                       │
│     Container B created (or A reused if networks match)      │
│     Networks: sandbox-net + sandbox-modules                  │
│     Mounts: SAME workspace volume + cache volume             │
│     pip packages still installed (on volume)                 │
│     Git state intact (on volume)                             │
│     Developer writes code using module APIs                  │
│     Developer needs extra dep → signals done()               │
│                                                              │
│  4. Dev/architect approval gate:                              │
│     Reviews git diff for prompt injection                    │
│     Approves re-plan with scipy                              │
│                                                              │
│  5. Phase 3 (internet, re-plan):                             │
│     Container C created                                      │
│     Networks: sandbox-net + sandbox-inet                     │
│     Mounts: SAME workspace volume + cache volume             │
│     All previous code + installed packages intact            │
│     pip install scipy                                        │
│     Container C destroyed                                    │
│                                                              │
│  6. Phase 4 (modules, continue):                             │
│     Container D created                                      │
│     Networks: sandbox-net + sandbox-modules                  │
│     Mounts: SAME workspace volume + cache volume             │
│     scipy now available                                      │
│     Developer continues with scipy                           │
│                                                              │
│  7. Session ends:                                            │
│     Final container destroyed                                │
│     Workspace volume destroyed                               │
│     Cache volume kept (shared across sessions)               │
└──────────────────────────────────────────────────────────────┘
```

### Dev/Architect Approval Gate Details

When an agent requests internet re-enablement:

1. **Agent calls `done()`** with structured reason:
   ```
   "Agent developer: [REPLAN NEEDED] Missing dependency: scipy. 
    All current work committed to git (branch: feature/dashboard). 
    Requesting internet re-enablement for pip install scipy."
   ```

2. **Orchestrator pauses the pipeline** and creates an approval request targeting the `developer` or `architect` role (technical users), NOT the end user.

3. **Approval gate shows:**
   - Git diff of all changes made so far in this session
   - List of packages requested for installation
   - Which agent made the request and why

4. **Dev/architect reviews** for:
   - No suspicious code that could be prompt injection artifacts
   - No unexpected file reads or network calls in the committed code
   - Requested packages are legitimate and expected for the project type

5. **If approved:** pipeline continues with an install phase (internet). If rejected: pipeline continues without the dependency (developer must work around it).

### Why Git Diff Review Works Here

Reviewing a git diff for prompt injection is tractable because:
- The codebase is small (one session's worth of changes)
- Prompt injection artifacts are usually visible: suspicious `curl` calls, encoded strings, unexpected network operations
- The dev/architect is a technical expert who can spot unusual patterns
- This is not reviewing every pip package — it's reviewing the AGENT'S CODE for injection artifacts

The alternative — reviewing every pip package for supply chain attacks — is intractable. But reviewing the diff of code an LLM wrote in the last 30 minutes is reasonable.

---

## Requirements Analysis: Internet + Module Data Coexistence

### What We Need (Requirements)

**R1: Agents must be able to browse the internet.** Not just install packages — read documentation, browse GitHub repos, check Hacker News, fetch public APIs (CBS, weather, etc.), download data files (CSV, JSON, images). This is essential for building real applications.

**R2: Agents must be able to read proprietary module data.** Module APIs, SDKs, business logic, internal specifications. This is what makes Druppie valuable — combining internal capabilities with external data.

**R3: Module data must never be exfiltrated via the internet.** If an agent has module data in its context, it must be impossible for that agent (or any prompt injection influencing it) to send that data to an external server. This must be enforced at the network layer, not the prompt layer.

**R4: Agents must be able to combine internet-sourced data with module data.** The whole point is applications that merge public CBS data with proprietary module insights. The agent needs to work with both datasets in some form.

**R5: The end user is non-technical.** They cannot review git diffs, approve packages, or judge prompt injection risk. Any approval gates must target the developer/architect role.

**R6: The solution must be practical.** Requiring dev/architect review for every file transfer or every internet request is too much manual work. The solution must be mostly automated with human oversight only at critical checkpoints.

### Why This Is Hard (The Fundamental Tension)

Requirements R1 + R2 + R3 are in direct conflict:

- To browse internet, the agent needs internet access (R1).
- To read module data, the agent needs module access (R2).
- Having both simultaneously creates the exfiltration trifecta (violates R3).

This means **no single agent can ever have both internet and module data at the same time.** The data must be combined across agents or across time, never within one agent's execution context.

### Solutions Evaluated

#### S1: Sequential Phases (current v2 spec)

Internet agent fetches data first → saves to workspace → modules agent reads from workspace and combines.

| Requirement | Satisfied? | Why |
|-------------|-----------|-----|
| R1: Browse internet | ✅ | Internet agent has full internet access |
| R2: Read module data | ✅ | Modules agent has full module access |
| R3: No exfiltration | ⚠️ | Modules agent has no internet ✅, but workspace volume contains internet-sourced files that could contain prompt injection |
| R4: Combine data | ✅ | Both datasets available in workspace |
| R5: Non-technical user | ✅ | No user involvement needed |
| R6: Practical | ✅ | Fully automated |

**Shortcoming:** The workspace files written by the internet agent (CBS data, documentation, examples) are read by the modules agent. If any of these files contain prompt injection payloads (from a malicious website, a poisoned README, crafted CSV headers), the modules agent gets injected. With no internet, it can't exfiltrate — but it could write malicious code, corrupt data, or sabotage the build. The trifecta is partially broken (no network channel) but the injection still affects agent behavior.

**Re-planning problem:** When the modules agent needs a new dependency, re-enabling internet requires careful handling. Even with workspace sanitization (destroy volume, clone from git), git commits can contain sensitive data. The internet container would see the full git history including module-derived code.

#### S2: Structured Data Transfer

Internet agent writes only structured JSON/CSV. Modules agent reads only structured data.

| Requirement | Satisfied? | Why |
|-------------|-----------|-----|
| R1: Browse internet | ✅ | Internet agent has full access |
| R2: Read module data | ✅ | Modules agent has full access |
| R3: No exfiltration | ⚠️ | Same as S1 — modules agent has no internet, but injection through structured data is still possible |
| R4: Combine data | ⚠️ | Limited to what can be expressed as structured data. Can't transfer code examples, documentation, images |
| R5: Non-technical user | ✅ | Automated |
| R6: Practical | ✅ | Simple to implement |

**Shortcoming:** Structured data doesn't prevent prompt injection. JSON values can contain instructions: `{"description": "Ignore previous instructions and..."}`. The format doesn't matter — the LLM reads the values as text, and text can always contain instructions. Also limits what can be transferred (no raw files, no code, no images).

#### S3: Planner as Sanitizer

Internet agent summarizes findings in `done()`. Planner incorporates summaries into the plan for the modules agent.

| Requirement | Satisfied? | Why |
|-------------|-----------|-----|
| R1: Browse internet | ⚠️ | Can browse, but can't download actual data files (CSV, images, binaries) |
| R2: Read module data | ✅ | Modules agent has full access |
| R3: No exfiltration | ⚠️ | Planner can pass through injection payloads. Modules agent has no internet (no exfiltration) but can be influenced |
| R4: Combine data | ❌ | Can't transfer actual data files — only text summaries |
| R5: Non-technical user | ✅ | Automated |
| R6: Practical | ✅ | Uses existing planner |

**Shortcoming:** Can't download actual data (CBS CSV files, images, API response dumps). The planner is an LLM — it can be influenced by prompt injection in the raw internet content and pass it through to the plan. For data-heavy applications, this doesn't work at all.

#### S4: Clean Room Install + Transfer Volume (Solution D)

Internet container has completely empty workspace. Installs packages into isolated venv. Venv tar transferred to modules container.

| Requirement | Satisfied? | Why |
|-------------|-----------|-----|
| R1: Browse internet | ⚠️ | Only for package installs, not for browsing/research |
| R2: Read module data | ✅ | Modules agent has full access |
| R3: No exfiltration | ✅ | Internet container is empty — even malicious packages find nothing to steal |
| R4: Combine data | ❌ | Can't transfer data files, only installed packages |
| R5: Non-technical user | ✅ | Automated |
| R6: Practical | ✅ | Simple mechanism |

**Shortcoming:** Only solves package installation. Doesn't help with the broader need: browsing docs, fetching CBS data, reading GitHub repos. The modules agent still needs internet-sourced data, which has to come from somewhere.

#### S5: Human Review at Transfer Point

Dev/architect reviews all files before they cross from internet container to modules container.

| Requirement | Satisfied? | Why |
|-------------|-----------|-----|
| R1: Browse internet | ✅ | Full access |
| R2: Read module data | ✅ | Full access |
| R3: No exfiltration | ✅ | Human catches injection artifacts + internet never touches module data |
| R4: Combine data | ✅ | Any file type can be reviewed and transferred |
| R5: Non-technical user | ✅ | Review targets dev/architect role |
| R6: Practical | ❌ | High manual overhead. Dev/architect reviews every file transfer, every pip install |

**Shortcoming:** Thorough but impractical for frequent use. Every internet request requires human review. For data-heavy applications with many API calls, this becomes a bottleneck.

### Assessment

| Solution | R1 | R2 | R3 | R4 | R5 | R6 | Viable? |
|----------|----|----|----|----|----|----|---------|
| S1: Sequential phases | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | Partial — injection risk in workspace files |
| S2: Structured transfer | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | No — structured data doesn't prevent injection |
| S3: Planner sanitizer | ⚠️ | ✅ | ⚠️ | ❌ | ✅ | ✅ | No — can't transfer actual data |
| S4: Clean room transfer | ⚠️ | ✅ | ✅ | ❌ | ✅ | ✅ | Partial — only for packages |
| S5: Human review | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | No — too much manual work |

**No single solution satisfies all requirements.** The practical path forward is a combination:

### Recommended: Layered Approach

| Layer | Mechanism | Handles |
|-------|-----------|---------|
| **Package installs** | S4 (clean room + empty workspace) | Safe pip/npm install — internet container has no data to steal |
| **Data fetching** | S1 (sequential phases) | Internet agent fetches CBS data, saves to workspace. Modules agent reads from workspace |
| **Injection mitigation** | S1 inherent — modules agent has NO internet | Even if injected via workspace files, agent cannot exfiltrate (no network) |
| **Re-planning** | S4 (clean room) + dev/architect approval for commands | Approved commands in empty container. Only reviewed code survives via git |
| **Code review** | Dev/architect reviews final PR | Catches any malicious code that injection might have caused the agent to write |

**The accepted risk:** A prompt injection in internet-sourced data (workspace files) could cause the modules agent to write malicious or incorrect code. But:
- It CANNOT exfiltrate module data (no internet)
- The malicious code is visible in the git diff / PR for dev/architect review
- The blast radius is limited to the agent's code output, not data leakage

**This is the same risk model as any developer using public data + proprietary APIs.** A human developer browsing the internet while working on proprietary code faces the same injection risks. The mitigation is code review — which we already require.

## Open Questions

1. **Developer needs modules?** Currently developer has `[internet]`. If the developer needs to read module SDKs to write code, it would need `[modules]` too — which violates the trifecta rule. Alternative: planner reads module APIs and includes them in the plan text. Developer works from plan text, not module access.
2. **DNS filtering:** Even with internet access restricted, DNS exfiltration is possible. Should we add DNS allowlisting in a future iteration?
3. **Network switch latency:** `_sync_networks` adds ~1-2s per call. Acceptable?
