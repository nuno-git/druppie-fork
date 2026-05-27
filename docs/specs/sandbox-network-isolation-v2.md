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

**Key design principle: defer module data access as late as possible.** All coding, testing, dependency installation, and internet research happens FIRST with internet access. Module data enters only at the integration step — after all code is written and tested with mocks. This minimizes re-planning (costly due to clean room process) because the developer has internet throughout the coding phase.

| Agent | Networks | Rationale |
|-------|----------|-----------|
| installer | `[internet]` | Install all dependencies before any work |
| data_fetcher | `[internet]` | Fetch public data (CBS, APIs), browse docs |
| developer | `[internet]` | Write code with mocks for module APIs, has internet for docs/packages |
| test_builder | `[internet]` | Write tests using mocks, can verify with real libs |
| module_integrator | `[modules]` | Swap mocks for real module SDK calls, NO internet |
| module_tester | `[modules]` | Run integration tests against real module servers |
| deployer | `[]` (isolated) | Push code via proxy, no network needed |
| ultimate_dev_core | `[internet]` | Core platform work, no module data |
| business_analyst | `[]` (isolated) | Reads/writes markdown only |

### Pipeline Flow

```
installer (internet) → data_fetcher (internet) → developer (internet) → test_builder (internet) → module_integrator (modules) → module_tester (modules) → deployer (isolated)
```

**Why this ordering minimizes re-planning:**
- Developer has internet for the ENTIRE coding phase — can pip install, browse docs, fetch APIs at any time
- All dependencies are resolved while internet is available
- Code is tested with mocks — if tests pass with mocks, they'll likely pass with real modules
- Module integration is just "swap mock imports for real imports" — rarely needs new packages
- Only ONE network transition (internet → modules) instead of back-and-forth

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
│  src/               ← written by developer (internet, mocks)   │
│    mocks/                                                     │
│      demographics_mock.py  ← mock module clients               │
│      geo_mock.py                                            │
│    dashboard.py                                            │
│    data_combine.py   ← reads local CBS files + mock module    │
│    models.py            output, combines them                   │
│                                                                 │
│  tests/             ← written by test_builder (internet, mocks)│
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
│  data_fetcher ────────────────────────────────────────────────────── │
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
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 3: DEVELOP (internet — uses mocks, NOT modules)               │
│                                                                      │
│  developer ──────────────────────────────────────────────────────── │
│    • Read CBS data from /workspace/data/cbs/ (local files)          │
│    • Write mock module clients (src/mocks/demographics_mock.py,     │
│      src/mocks/geo_mock.py) based on API specs from the plan        │
│    • Write src/data_combine.py: merges CBS data + mock module data  │
│    • Write src/dashboard.py: renders Plotly dashboard                │
│    • Networks: [internet]                                            │
│    • Context: CBS data (from local files), plan text with module    │
│              API specs, mock response definitions                    │
│    • Internet available — can pip install, browse docs, curl APIs    │
│    • Workspace: contains CBS data + dashboard code + mock clients    │
│                                                                      │
│  ┌─── Security Guarantee ───────────────────────────────────────┐   │
│  │ Agent has internet but NO module data.                         │   │
│  │ Developer uses mocks — proprietary module APIs never accessed. │   │
│  │ Even if CBS data contains prompt injection:                    │   │
│  │   → Agent has no proprietary data to steal (mocks only)        │   │
│  │   → Worst case: malicious code written to src/ files           │   │
│  │     (caught in code review / testing phase)                    │   │
│  │ Re-planning is almost never needed — developer has internet    │   │
│  │ for the entire coding phase (pip install, browse docs freely)  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 4: TEST (internet — uses mocks)                               │
│                                                                      │
│  test_builder ───────────────────────────────────────────────────── │
│    • Write unit tests using mock module clients                      │
│    • Write integration tests (CBS data + mock modules)               │
│    • Test error handling, edge cases                                 │
│    • Verify dashboard renders correctly with mock data               │
│    • Networks: [internet]                                            │
│    • Context: test requirements, mock API specs                      │
│    • Internet still available — can install test deps if needed       │
│    • NO module data — tests validate logic with mocks only           │
│                                                                      │
│  ┌─── Security Guarantee ───────────────────────────────────────┐   │
│  │ Same as Phase 3: internet available, but NO proprietary data. │   │
│  │ Tests exercise logic without touching real module APIs.        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                          ┌─────────┴──────────┐
                          │ NETWORK TRANSITION │
                          │ disconnect: inet   │
                          │ connect: modules   │
                          │ (ONE-WAY, no back) │
                          └─────────┬──────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 5: MODULE INTEGRATION (modules — NO internet)                 │
│                                                                      │
│  module_integrator ──────────────────────────────────────────────── │
│    • Replace mock imports with real SDK calls                        │
│    • from src.mocks.demographics_mock → from druppie_sdk            │
│    • Remove mock files                                               │
│    • Adjust code if real SDK returns different field names           │
│    • Networks: [modules]                                             │
│    • Context: existing code (from workspace), module API specs      │
│              (from module servers), CBS data (from local files)      │
│    • NO internet — cannot reach external servers                     │
│    • Workspace: contains CBS data + real module integration code     │
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
│  │ Re-planning is rare here — developer already installed all    │   │
│  │ packages during Phase 3. Integration is just "swap imports."  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 6: MODULE TESTING (modules)                                   │
│                                                                      │
│  module_tester ──────────────────────────────────────────────────── │
│    • Run existing tests against real module servers                  │
│    • SDK calls hit real APIs via sandbox-modules network             │
│    • Fix any issues (field name mismatches, edge cases)              │
│    • All tests pass with real module data                            │
│    • Networks: [modules]                                             │
│    • Context: test results, module API responses                    │
│    • NO internet                                                     │
└──────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 7: DEPLOY (isolated)                                          │
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

The critical question: how do internet-sourced CBS data and proprietary module data get combined without any agent ever having both simultaneously?

**Answer: the developer writes code using MOCKS for module APIs. Real module data enters only at the integration step (Phase 5), when internet is already disconnected.**

```python
# src/data_combine.py — written by developer (internet network, using mocks)

import json
from pathlib import Path

# CBS data: read from local files saved by data_fetcher in Phase 2
cbs_population = json.loads(Path("data/cbs/population.json").read_text())

# Module data: uses MOCK during development (Phase 3)
# Real SDK swap happens in Phase 5 by module_integrator
from src.mocks.demographics_mock import MockDemographicsModule
from src.mocks.geo_mock import MockGeoModule

demo = MockDemographicsModule()
geo = MockGeoModule()

demographics = demo.get_statistics(region="amsterdam")
geo_data = geo.get_boundaries(level="municipality")

# Combine: public CBS data + mock module data
combined = merge_datasets(cbs_population, demographics, geo_data)
```

Then in Phase 5, the module_integrator swaps mocks for real SDK calls:

```python
# After integration (Phase 5, modules network, no internet):
from druppie_sdk import DemographicsModule, GeoModule

demo = DemographicsModule()
geo = GeoModule()

demographics = demo.get_statistics(region="amsterdam")
geo_data = geo.get_boundaries(level="municipality")

combined = merge_datasets(cbs_population, demographics, geo_data)
```

The data flow:
- **Phase 2** (internet): CBS data fetched, saved as local files
- **Phase 3** (internet): Developer reads CBS files, writes code using MOCK module clients
- **Phase 4** (internet): Tests exercise logic with mock data
- **Phase 5** (modules, NO internet): Real module SDK calls replace mocks. Agent now has BOTH CBS data (from files) AND module data (from APIs) in context — but NO internet to exfiltrate through

### Security Invariants Maintained

| Invariant | How |
|-----------|-----|
| CBS data never reaches internet-connected agent alongside module data | CBS is fetched in Phase 2 (no module access). Used in Phase 3-4 with mocks (no real module data). Module data enters only in Phase 5 (no internet). |
| Module data never reaches an internet-connected agent | Module access only in Phase 5-6 (no internet). Phase 7 has neither. Developer (Phase 3-4) uses mocks only. |
| Workspace files from module phase are never read by internet agents | Pipeline ordering enforced by make_plan: all internet phases (1-4) come first. Module phases (5-6) come after the irreversible network transition. |
| Prompt injection in CBS data cannot exfiltrate module data | When module data enters agent context (Phase 5), internet is disconnected. Developer (Phase 3) has CBS data but uses mocks — no proprietary data to steal. |
| Developer has enough context to write correct code | CBS data from files + mock module clients based on API specs in plan + internet for docs/packages. Real module APIs swapped in at integration. |
| Re-planning is minimized | Developer has internet for entire coding phase (Phase 3-4). Need a package? pip install. Need docs? Browse freely. Only the module_integrator (Phase 5) has no internet, and it rarely needs new packages. |

### What If the Developer Discovers It Needs Another Dependency?

With the deferred-modules ordering, the developer has **internet for the entire coding phase**. Need `scipy`? Just `pip install scipy` — no re-plan, no approval gate, no clean room process. The developer can browse docs, install packages, and fetch APIs freely during Phases 3-4.

Re-planning is only needed if the **module_integrator** (Phase 5, modules network, NO internet) discovers that the real SDK requires an additional package that wasn't installed during the internet phase. This is rare because:
- The developer already installed likely-needed packages during Phase 3
- Module integration is typically just "swap mock imports for real imports" — rarely needs new packages
- If the plan includes module SDK specs, the installer can pre-install SDK dependencies

If re-planning IS needed from the module phase:

1. **Module integrator signals via `done()`** — "Agent module_integrator: Need aiohttp for real SDK. Requesting re-plan with additional dependency."
2. **Orchestrator creates an approval gate** — the developer/architect role reviews the request with the current git diff.
3. **Dev/architect reviews the git diff** — checks that no prompt injection payload has been injected into the codebase. This is the security checkpoint before re-enabling internet.
4. **If approved: clean room re-enablement**
   - Current container is destroyed
   - Workspace volume DESTROYED (contains module data — must not reach internet)
   - Fresh workspace volume created (empty)
   - Transfer volume created
   - New container created with `[internet]`, EMPTY workspace, transfer volume mounted
   - `pip install` runs for the additional dependency
   - Internet container destroyed
   - Fresh workspace volume created, git clone restores code
   - Transfer volume contents (installed packages) extracted into workspace
   - New container with `[modules]` network, full workspace restored

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

If the installer installs `pandas` in Phase 1, then the network transitions to modules for Phase 5, the module_integrator's code `import pandas` still works because the workspace volume persists across network transitions.

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
│  2. Phases 1-4 (ALL internet):                               │
│     Container A created                                      │
│     Networks: sandbox-net + sandbox-inet                     │
│     Mounts: workspace volume + cache volume                  │
│                                                              │
│     Phase 1 - installer:                                     │
│       pip install pandas plotly dash requests httpx scipy    │
│       Git clone: check out project branch                    │
│                                                              │
│     Phase 2 - data_fetcher:                                  │
│       Fetch CBS data, save to /workspace/data/cbs/           │
│       Browse docs, write research notes                      │
│                                                              │
│     Phase 3 - developer:                                     │
│       Write dashboard code using mock module clients          │
│       Read CBS data from local files                         │
│       Need a package? Just pip install (internet available)  │
│                                                              │
│     Phase 4 - test_builder:                                  │
│       Write and run tests using mocks                        │
│       Need test deps? pip install (still internet)           │
│                                                              │
│     Container A reused across ALL four phases (same network) │
│                                                              │
│  3. NETWORK TRANSITION (ONE-WAY, irreversible):              │
│     _sync_networks():                                        │
│       docker network disconnect sandbox-inet container-A     │
│       docker network connect sandbox-modules container-A     │
│                                                              │
│  4. Phases 5-6 (modules — NO internet):                      │
│     Container A (network switched to modules)                │
│     Networks: sandbox-net + sandbox-modules                  │
│     Mounts: SAME workspace volume + cache volume             │
│     pip packages still installed (on volume)                 │
│     Git state intact (on volume)                             │
│                                                              │
│     Phase 5 - module_integrator:                             │
│       Replace mock imports with real SDK calls               │
│       Adjust code for real API responses                     │
│                                                              │
│     Phase 6 - module_tester:                                 │
│       Run tests against real module servers                  │
│       Fix field name mismatches                              │
│                                                              │
│  5. Phase 7 (isolated):                                      │
│     Container A (network switched to isolated)               │
│     _sync_networks():                                        │
│       docker network disconnect sandbox-modules container-A  │
│     Networks: sandbox-net only                               │
│                                                              │
│     Phase 7 - deployer:                                      │
│       Push to git, create PR                                 │
│                                                              │
│  6. Session ends:                                            │
│     Container A destroyed                                    │
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

**Re-planning problem:** When the modules agent needs a new dependency, re-enabling internet requires careful handling. Even with workspace sanitization (destroy volume, clone from git), git commits could contain sensitive data. The internet container would see the full git history including module-derived code.

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

1. ~~**Developer needs modules?**~~ ANSWERED: Developer uses mocks for module APIs. Real module access deferred to `module_integrator` agent. Developer has `[internet]` for the entire coding phase. See "Per-Agent Network Profiles" and "Complete End-to-End Flow."
2. **DNS filtering:** Even with internet access restricted, DNS exfiltration is possible. Should we add DNS allowlisting in a future iteration?
3. **Network switch latency:** `_sync_networks` adds ~1-2s per call. With deferred-modules ordering there's only ONE transition (internet → modules), so this is minimal impact. Acceptable?

---

## Complete End-to-End Flow: How Everything Fits Together

This section shows how all the recommended solutions combine into one coherent system. We use the same scenario throughout: **building a dashboard that combines CBS public data with proprietary module data**.

### The Key Insight: Defer Module Access

Module data access is deferred to the **latest possible point** in the pipeline. The developer writes and tests all code using **mocks** for module APIs. This means:

- The developer has internet access for the **entire coding phase** (pip install, browse docs, fetch CBS data, test with real libraries)
- Re-planning is almost never needed because all dependencies are installed while internet is available
- Module data enters the picture only at the integration step — just "swap mock imports for real imports"

### The Cast of Characters

| Role | Who | Network Access | Has Module Data? | Has Internet? |
|------|-----|---------------|------------------|---------------|
| **End User** | Non-technical business person | N/A | No | No |
| **Dev/Architect** | Technical expert (approves things) | N/A | Can review | Can review |
| **Installer Agent** | Automated | `[internet]` | No | Yes |
| **Data Fetcher Agent** | Automated | `[internet]` | No | Yes |
| **Developer Agent** | Automated | `[internet]` | No (uses mocks) | Yes |
| **Test Builder Agent** | Automated | `[internet]` | No (uses mocks) | Yes |
| **Module Integrator Agent** | Automated | `[modules]` | Yes | No |
| **Module Tester Agent** | Automated | `[modules]` | Yes | No |
| **Deployer Agent** | Automated | `[]` isolated | No | No |

### The Infrastructure

```
Docker Networks:
  sandbox-net        — base network, no internet, no modules (all containers get this)
  sandbox-inet       — outbound internet (NAT)
  sandbox-modules    — can reach module MCP servers only

Docker Volumes per session:
  druppie-ws-{session}-{scope}       — persistent workspace (code, data files)
  druppie-transfer-{session}-{scope} — clean room transfer volume (only if re-plan needed)
  sandbox_dep_cache                  — shared package cache (pip, npm) — persists across sessions
```

### Step-by-Step Flow

```
═══════════════════════════════════════════════════════════════════
STEP 1: PLANNING
═══════════════════════════════════════════════════════════════════

  Router agent classifies the user's request.
  Planner agent creates a plan:
  
  Plan:
    1. installer:       "Install pandas, plotly, dash, requests, httpx, 
                         scipy (for statistical analysis)"
    2. data_fetcher:    "Fetch CBS population data from opendata.cbs.nl,
                         save to /workspace/data/cbs/"
    3. developer:       "Build dashboard combining CBS data with module 
                         data. Use mocks for DemographicsModule and 
                         GeoModule. Write mock responses based on the 
                         module API specs in the plan."
    4. test_builder:    "Write tests using the same mocks. Test data 
                         processing, chart rendering, API error handling."
    5. module_integrator:"Replace mock imports with real Druppie SDK 
                         calls. Wire up real DemographicsModule and 
                         GeoModule."
    6. module_tester:   "Run integration tests against real module servers"
    7. deployer:        "Push to git, create PR"
  
  make_plan validates:
    ✅ Steps 1-4 have [internet], come first
    ✅ Steps 5-6 have [modules], come after internet steps
    ✅ Step 7 has [] (isolated), comes last
    ✅ No internet step follows a modules step — PASS

═══════════════════════════════════════════════════════════════════
STEP 2: INSTALL DEPENDENCIES (INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: installer
  Container: A
  Networks: sandbox-net + sandbox-inet
  Workspace volume: druppie-ws-{session}-{scope} (empty)
  
  What happens:
    1. Container created, git clone into /workspace
    2. pip install pandas plotly dash requests httpx scipy
       (generous install — includes likely-needed packages to avoid re-plan)
    3. Agent calls done()

  Security:
    Container has internet ✅, NO module access ✅
    Workspace is nearly empty — nothing to steal ✅

═══════════════════════════════════════════════════════════════════
STEP 3: FETCH PUBLIC DATA (INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: data_fetcher
  Container: A (reused — same [internet] network)
  Workspace volume: has installed packages
  
  What happens:
    1. Fetch CBS data via curl/requests
    2. Save to /workspace/data/cbs/population.json, employment.json
    3. Browse plotly.com, dash docs for API reference
    4. Save research notes to /workspace/research/
    5. Agent calls done()

  Security:
    Internet access ✅, NO module access ✅
    CBS data saved to workspace (may contain injection, but container 
    is about to be destroyed anyway — module agents will read these files 
    later WITHOUT internet)

═══════════════════════════════════════════════════════════════════
STEP 4: DEVELOP DASHBOARD WITH MOCKS (INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: developer
  Container: A (reused — still on [internet])
  Workspace volume: has packages + CBS data + research notes
  
  What happens:
    1. Read CBS data from /workspace/data/cbs/
    2. Read research notes from /workspace/research/
    3. Write mock module clients:
    
       # src/mocks/demographics_mock.py
       class MockDemographicsModule:
           def get_statistics(self, region):
               return {"region": region, "population": 900000, 
                       "age_groups": {"0-18": 0.2, "18-65": 0.6, "65+": 0.2}}
       
       # src/mocks/geo_mock.py
       class MockGeoModule:
           def get_boundaries(self, level):
               return {"type": "FeatureCollection", "features": [...]}
    
    4. Write dashboard code using mocks:
       # src/dashboard.py
       from src.mocks.demographics_mock import MockDemographicsModule
       from src.mocks.geo_mock import MockGeoModule
       import plotly.express as px
       import pandas as pd
       
       # Load CBS data
       cbs = pd.read_json("data/cbs/population.json")
       
       # Use mock module data
       demo = MockDemographicsModule()
       geo = GeoMockModule()
       ...
    
    5. Discover need for another package? Just pip install it — 
       internet is available! No re-plan needed.
    6. Need to look up Plotly docs? Just curl them — internet available!
    7. Agent calls done():
       "Agent developer: Dashboard implemented with mock module clients.
        CBS data loaded, charts render correctly. Used mocks for 
        DemographicsModule and GeoModule. Ready for integration."

  Security:
    Internet access ✅ (developer can pip install, browse freely)
    NO module data in context ✅ (using mocks, not real modules)
    CBS data in workspace — but developer doesn't have module data, 
    so even if CBS data has injection, there's nothing proprietary to steal

  WHY THIS IS THE KEY INSIGHT:
    The developer has internet for the ENTIRE coding phase.
    Need scipy? pip install scipy. No re-plan, no approval gate.
    Need to check Stack Overflow? Browse freely.
    The only thing the developer can't do is access real module APIs —
    but mocks work fine for writing the code structure.

═══════════════════════════════════════════════════════════════════
STEP 5: TEST WITH MOCKS (INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: test_builder
  Container: A (reused — still on [internet])
  Workspace volume: has everything from previous steps
  
  What happens:
    1. Write unit tests using mocks
    2. Write integration tests (CBS data + mock modules)
    3. Test error handling, edge cases
    4. Run pytest — all tests pass with mocks
    5. Agent calls done()

  Security:
    Still on internet ✅, still NO module data ✅
    Tests validate the logic without touching proprietary APIs

═══════════════════════════════════════════════════════════════════
NETWORK TRANSITION: INTERNET → MODULES (ONE-WAY, NO GOING BACK)
═══════════════════════════════════════════════════════════════════

  Container A still exists. All internet work is done.
  This is the ONE AND ONLY network transition.
  
  _sync_networks() is called:
    docker network disconnect sandbox-inet container-A
    docker network connect sandbox-modules container-A
  
  After this: container has NO internet. Module access enabled.
  This transition is IRREVERSIBLE — no more internet for this session.

═══════════════════════════════════════════════════════════════════
STEP 6: INTEGRATE REAL MODULES (MODULES — NO INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: module_integrator
  Container: A (network switched to modules)
  Networks: sandbox-net + sandbox-modules
  Workspace volume: has all code, tests, CBS data, installed packages
  
  What happens:
    1. Replace mock imports with real SDK calls:
    
       # Before (written by developer with mocks):
       from src.mocks.demographics_mock import MockDemographicsModule
       demo = MockDemographicsModule()
       
       # After (written by module_integrator):
       from druppie_sdk import DemographicsModule
       demo = DemographicsModule()
    
    2. This is typically a search-and-replace operation:
       - Find all mock imports
       - Replace with real SDK imports
       - Remove mock files
    3. Real SDK calls may return different field names or structures —
       agent adjusts the code to match
    4. Agent calls done()

  Security:
    Module access ✅ (reads proprietary APIs)
    NO internet ✅ (sandbox-inet disconnected)
    Agent now has BOTH CBS data (from workspace files) AND module data 
    (from SDK) in its context.
    
    IF CBS data contained prompt injection:
      → Agent might be influenced to write incorrect code
      → But it CANNOT exfiltrate module data (no internet) ✅
      → Malicious code visible in git diff / PR review ✅

  WHY RE-PLANNING IS RARE HERE:
    The integration step is just "swap imports." It almost never needs
    new packages. The developer already installed everything needed
    during Step 4 (with internet). If by some rare chance a new package
    IS needed, the clean room re-plan process applies (see below).

═══════════════════════════════════════════════════════════════════
STEP 7: TEST WITH REAL MODULES (MODULES — NO INTERNET)
═══════════════════════════════════════════════════════════════════

  Agent: module_tester
  Container: A (reused — still on [modules])
  
  What happens:
    1. Run existing tests against real module servers
    2. SDK calls hit real APIs via sandbox-modules network
    3. Fix any issues (field name mismatches, etc.)
    4. All tests pass
    5. Agent calls done()

═══════════════════════════════════════════════════════════════════
STEP 8: DEPLOY (ISOLATED)
═══════════════════════════════════════════════════════════════════

  Agent: deployer
  Container: A (network switched to isolated)
  
  _sync_networks():
    docker network disconnect sandbox-modules container-A
  
  Networks: sandbox-net only
  1. git push (via module-coding proxy)
  2. create PR
  3. Dev/architect reviews PR (final code review)
  4. Agent calls done()

═══════════════════════════════════════════════════════════════════
CLEANUP
═══════════════════════════════════════════════════════════════════

  1. Container A destroyed
  2. Workspace volume destroyed
  3. Package cache volume KEPT (shared across sessions)
```

### Re-Planning: The Rare Case

With the deferred-modules ordering, re-planning is **rare** because the developer has internet for the entire coding phase. But if the module_integrator (Step 6) discovers it needs a new package:

1. **Module integrator calls `done()`** with structured reason:
   ```
   "Agent module_integrator: [REPLAN NEEDED] Real DemographicsModule SDK 
    requires aiohttp. Requesting: pip install aiohttp==3.9.5"
   ```

2. **Dev/architect approval gate** shows:
   - Exact command: `pip install aiohttp==3.9.5`
   - Git diff of all changes (including integration code)
   - Agent making the request and why

3. **If approved — clean room process:**
   - Container destroyed
   - Workspace volume DESTROYED (contains module data — must not reach internet)
   - Fresh workspace volume created (empty)
   - Transfer volume created
   - New container created with [internet], EMPTY workspace, transfer volume mounted
   - `pip install aiohttp==3.9.5` into transfer volume
   - Internet container destroyed
   - Fresh workspace volume created, git clone restores code
   - Transfer volume contents extracted into workspace
   - New container with [modules] network, full workspace restored

4. **If rejected:** module_integrator works around it (use stdlib, find alternative).

### Security Guarantees Summary

| Threat | How We Prevent It |
|--------|-------------------|
| Malicious pip package steals workspace data | Internet container has empty workspace (clean room) or no module data (Steps 2-5) |
| Prompt injection in CBS data exfiltrates module data | Module data only accessible when internet is disconnected |
| Prompt injection causes malicious code in repo | All code visible in git diff / PR for dev/architect review |
| Re-enablement gives internet access to module data | Workspace destroyed before internet container starts — clean room |
| DNS exfiltration | sandbox-modules has no internet — DNS queries don't route |
| Agent sneaks internet access after modules phase | Network transition is irreversible — make_plan enforces ordering |

### Why This Ordering Is Better Than "Internet → Modules → Internet"

| Concern | Old ordering (modules early) | New ordering (modules late) |
|---------|------------------------------|----------------------------|
| Re-planning frequency | High — developer often needs new packages during coding | Low — developer has internet for entire coding phase |
| Clean room cost | Paid every time re-plan is needed | Rarely needed |
| Number of network transitions | Multiple (internet → modules → internet → modules) | ONE (internet → modules, irreversible) |
| Developer productivity | High friction — can't pip install or browse docs | Low friction — full internet access while coding |
| Module data exposure | Module data in context during coding → larger window | Module data in context only during integration → minimal window |

---

## Open Design Question: Research & Exploration Phase

### The Problem

In the current pipeline design (deferred-modules ordering), module data is accessed only at the very end — during the module_integrator step, with no internet. This is secure but creates a problem for the **research/exploration phase**.

Before the user decides what to build, agents need to explore what's possible:
- What modules are available?
- What data do they provide?
- What APIs do they expose?
- What can you build by combining module X with public data source Y?

This research phase currently (in development branches) involves a BA/data analyst agent that reads real module APIs and data to write a functional design that tells the user: "here's what you could build." The user then picks a direction.

**The tension:** This research requires module data access, but the research phase also benefits from internet access (browsing public data sources, checking CBS APIs, reading documentation). Under our security model, no single agent should have both.

### Why This Matters

If we defer module access to the end, the planner writes a plan based on GUESSES about what modules can do. The plan might be wrong — "combine demographics module with CBS data" when the demographics module doesn't actually provide the fields the plan assumes. This wastes the entire pipeline's time.

The research phase is where we learn what's actually possible. It's upstream of everything else. Getting it wrong cascades into wasted work.

### Solutions

#### RS1: Static Module Catalog

Module capabilities are documented in a **static catalog** — a curated file that describes each module's API schema, available data fields, and example responses. This is NOT live module data — it's a human-maintained reference document.

```
docs/module-catalog.yaml (or similar):

modules:
  demographics:
    description: "Provides population statistics by region"
    api_version: "v1"
    endpoints:
      - name: get_statistics
        params: {region: string, year?: int}
        returns: {region: string, population: int, age_groups: dict}
        example: {region: "amsterdam", population: 900000, age_groups: {"0-18": 0.2}}
  
  geo:
    description: "Provides geographic boundaries and spatial data"
    endpoints:
      - name: get_boundaries
        params: {level: string}
        returns: {type: "FeatureCollection", features: [...]}
```

The catalog is included in the BA/planner agent's system prompt or loaded as a tool context. The agent knows what modules CAN do without ever calling them.

**How the flow works:**
1. BA agent reads the static catalog (in prompt, no sandbox needed)
2. BA agent also browses internet (CBS APIs, public data sources) — has internet
3. BA writes functional design: "Combine CBS population data with demographics module (which provides regional statistics) and geo module (which provides municipal boundaries)"
4. The FD references module capabilities from the catalog, not live data
5. The builder later confirms these capabilities match reality during module_integrator step

| Criterion | Assessment |
|-----------|-----------|
| Security | ✅ No live module data accessed during research. Catalog is curated, static, contains no proprietary runtime data |
| Accuracy | ⚠️ Catalog might be outdated or incomplete. Module APIs may have changed since last catalog update |
| Effort | ⚠️ Catalog must be maintained manually. Every module API change requires catalog update |
| User experience | ✅ BA can freely combine module knowledge with internet research in one agent |
| Internet needed? | ✅ BA has internet for public data, catalog is in prompt (no module network needed) |

**Shortcoming:** The catalog is a abstraction layer between the agent and reality. If the catalog says a module provides field X but it actually provides field Y, the plan is wrong. The module_integrator step catches this, but only after the entire pipeline has run.

---

#### RS2: Dual-Agent Research (Modules Agent + Internet Agent)

Two separate agents research in parallel:
- **Modules researcher** (sandbox with [modules], no internet) — calls real module APIs, explores actual capabilities, writes a capabilities report
- **Internet researcher** (sandbox with [internet], no modules) — browses CBS, public APIs, docs, writes a data availability report

The planner combines both reports to write the functional design.

```
Internet researcher:
  Networks: [internet]
  Explores: CBS APIs, public data sources, documentation
  Output: /workspace/research/public-data-report.md
    "CBS provides population data via opendata.cbs.nl/ODataFeed/...
     Fields: Region, Year, Population, Age_Group
     Format: JSON, paginated, free access"

Modules researcher:
  Networks: [modules]
  Explores: DemographicsModule.get_statistics(), GeoModule.get_boundaries()
  Output: /workspace/research/module-capabilities.md
    "Demographics module provides: regional population stats, age distributions
     Geo module provides: municipal boundaries as GeoJSON
     Combined: can map demographics data onto geographic regions"

Planner (no sandbox):
  Reads both reports
  Writes functional design combining findings
```

**How the flow works:**
1. Router spawns both researchers in parallel
2. Modules researcher calls real APIs, gets actual responses, writes accurate report
3. Internet researcher browses real public data, writes data availability report
4. Both reports go to planner (no sandbox, no network access — just reads files)
5. Planner writes FD based on both reports
6. Neither researcher ever has both module data AND internet

| Criterion | Assessment |
|-----------|-----------|
| Security | ✅ Clean separation — modules researcher has no internet, internet researcher has no module data |
| Accuracy | ✅ Modules researcher calls REAL APIs — capabilities are accurate, not from a stale catalog |
| Effort | ✅ No manual maintenance — agent discovers capabilities by calling real APIs |
| User experience | ✅ Accurate FD based on real capabilities and real public data |
| Internet needed? | ✅ Internet researcher has internet. Modules researcher has modules. Neither has both. |

**Shortcoming:** The planner reads both reports and combines them in its prompt. If the modules researcher's report contains prompt injection (from malicious module data — unlikely since modules are internal, but possible), the planner could be influenced. But the planner has NO sandbox, NO tools, NO network — it only produces text. Blast radius is limited instruction other agents to exfiltrate.

The bigger shortcoming: the modules researcher has module data in its context but no internet. It writes a capabilities report. That report is then read by agents with internet access later (the developer). If the report contains injection payloads from module data... but module data is OUR data, not untrusted external data. The injection threat comes from PUBLIC data (internet), not from our own modules.

---

#### RS3: Modules-First Research Phase (Separate Sandbox)

The research phase runs BEFORE the main pipeline, in a completely separate sandbox session. A research agent gets [modules] access, explores capabilities, writes a capabilities document. This document is then included in the main pipeline's agent prompts. The main pipeline never accesses modules during the research phase.

```
Research session (separate, isolated):
  Agent: modules_explorer
  Networks: [modules]
  Task: "Explore all available module APIs and document their capabilities"
  Output: capabilities-report.json
    {modules: [{name: "demographics", endpoints: [...], fields: [...]}]}

Main pipeline session:
  BA agent has capabilities-report.json in prompt (from research session)
  BA agent has [internet] for public data research
  BA writes FD using catalog + internet research
  Main pipeline proceeds with deferred-modules ordering
```

| Criterion | Assessment |
|-----------|-----------|
| Security | ✅ Complete separation — research session and main pipeline are different sandboxes |
| Accuracy | ✅ Real API calls in research session |
| Effort | ⚠️ Two sessions per project — more infrastructure complexity |
| User experience | ⚠️ Slower — research session must complete before main pipeline starts |
| Internet needed? | ⚠️ Research session has NO internet (only modules). Can't combine with public data research in same agent. |

**Shortcoming:** The research agent can explore module APIs but can't simultaneously check public data sources to see what's combinable. The BA still needs internet for that. So the flow becomes: modules exploration → capabilities report → BA reads report + browses internet → FD. This works but is sequential and slower.

---

#### RS4: Module API Specs in Agent System Prompt (Baked Knowledge)

Module API specifications are baked into the agent's system prompt at load time. When an agent is initialized, the system injects a "module capabilities" section listing all available modules, their endpoints, parameter schemas, and return types.

This is similar to RS1 (static catalog) but the "catalog" is auto-generated from the module MCP server's tool schemas — not manually maintained.

```
Agent system prompt injection:
  "You have access to the following Druppie modules:
   
   DemographicsModule:
     get_statistics(region: str, year?: int) → 
       {region: str, population: int, age_groups: {group: str, percentage: float}}
     
   GeoModule:
     get_boundaries(level: str) → 
       {type: str, features: [{geometry: GeoJSON, properties: dict}]}
   
   These modules will be available during the module integration step.
   During development, use mocks based on these schemas."
```

| Criterion | Assessment |
|-----------|-----------|
| Security | ✅ Schema metadata, not live data — no proprietary runtime values |
| Accuracy | ✅ Auto-generated from real MCP tool schemas — always up to date |
| Effort | ✅ No manual maintenance — schemas come from the module MCP servers |
| User experience | ✅ Agent knows what's possible from the start |
| Internet needed? | ✅ No network needed — schemas are in the prompt |

**Shortcoming:** Schemas describe the API shape (parameters, return types) but NOT the actual data available. The agent knows DemographicsModule has `get_statistics(region)` but doesn't know what regions are available, what years have data, or what the actual values look like. This is enough for planning ("I'll use demographics data by region") but not for data exploration ("the demographics module shows Amsterdam has 900K population, we could highlight that").

---

### Recommendation

| Scenario | Recommended Solution | Why |
|----------|---------------------|-----|
| API shape discovery (what endpoints exist, what params) | **RS4** (auto-generated schemas in prompt) | Zero maintenance, always accurate, no network needed |
| Data exploration (what actual values are available) | **RS2** (dual-agent research) | Real API calls, accurate data, clean security separation |
| Quick prototyping (just need module names + descriptions) | **RS1** (static catalog) | Simplest, good enough for initial planning |
| Maximum security (no trust in module data at all) | **RS3** (separate research session) | Complete isolation between research and main pipeline |

**Practical recommendation: RS4 + RS2 combined.**

1. **RS4** provides the baseline — auto-generated API schemas in every agent's prompt. All agents know what modules CAN do from the start, without any network access.

2. **RS2** provides the deep exploration — when the BA needs to know what actual data is available (not just the API shape), the modules researcher explores real APIs and writes a capabilities report.

The flow becomes:
```
1. Agent initialized with RS4 schemas in prompt (auto-generated)
2. BA/planner already knows module API shapes → can propose rough ideas
3. If user wants detailed exploration: dual-agent research (RS2)
   - Modules researcher explores real data (modules network)
   - Internet researcher explores public data (internet network)
   - Planner combines into FD
4. Main pipeline proceeds with deferred-modules ordering
```

This is secure because:
- RS4 schemas are metadata, not data — no exfiltration value
- RS2 modules researcher has no internet — can't exfiltrate even if module data is injected
- RS2 internet researcher has no modules — can't access proprietary data
- The planner has no sandbox/tools — can only produce text, can't exfiltrate

---

## Honest Assessment: The Unresolved Tension

### Why All Research Phase Solutions Fall Short

The previous section proposed four solutions (RS1-RS4) for the research/exploration phase. On closer analysis, they all share the same fundamental problem.

#### The Data Flow Problem

Information from modules must somehow reach the developer agent (which has internet). Every solution creates a "bridge" — a file, a report, a prompt injection — that carries module-derived information into an internet-connected context.

```
Modules (sensitive) → [BRIDGE] → Internet-connected agent

The bridge is always the leak path.
```

| Solution | What crosses the bridge | Why it's a problem |
|----------|------------------------|-------------------|
| RS1 (static catalog) | Module names, API schemas, descriptions | Reveals what data assets and capabilities we have — competitively sensitive |
| RS2 (dual-agent) | Capabilities report with real API responses | Contains actual module data. Report flows to planner → plan text → developer (internet) |
| RS3 (separate session) | Capabilities report file | Same as RS2 — the report file is the bridge |
| RS4 (schemas in prompt) | API shapes, parameter names, return types | Even API shapes reveal capabilities. "get_financial_metrics(company_id)" tells you we have financial data |

#### Why RS4 Is Not Safe

API schemas look harmless but they are intelligence:
- `DemographicsModule.get_statistics(region, year)` → "we have demographic data by region"
- `FinancialModule.get_metrics(company_id)` → "we have company financial data"
- `RiskModule.calculate_score(entity, category)` → "we have risk scoring capabilities"

This metadata tells a competitor or attacker exactly what our platform can do. It's the same reason AWS doesn't publish all its internal service APIs — the API surface IS the product intelligence.

#### Why RS2 Is Not Safe

The capabilities report flows through this chain:

```
modules_researcher (modules, no internet)
  → writes capabilities_report.md
  → planner reads it (no sandbox, but produces text)
  → plan text goes into developer prompt
  → developer has internet

If capabilities_report.md contains: "Demographics module returns 
{region: 'amsterdam', population: 900000, gdp_per_capita: 52000}"

Then the developer's context (with internet) contains this data.
A prompt injection from a browsed website could exfiltrate it.
```

The bridge is the plan text itself. Once module-derived information enters the developer's prompt, the trifecta is re-established: the developer holds module data AND has internet AND processes untrusted content (from browsed websites, CBS data files, etc.).

### The Fundamental Constraint

**If we define module-derived information as sensitive, then NO agent with internet access can ever receive ANY information derived from modules.** Not schemas, not reports, not summaries, not even "you could build X with module Y."

This creates a paradox:
- The BA needs module knowledge to write a useful functional design
- The developer needs the functional design to write code
- The developer needs internet to write and test code
- Therefore: module-derived information reaches an internet-connected agent

### Three Ways To Resolve The Paradox

#### Resolution A: Accept That API Schemas Are Not Sensitive

**Redefine what "sensitive" means.** API schemas (endpoint names, parameter types, return shapes) are treated as non-sensitive — like public API documentation. Only the actual DATA returned by the APIs is considered sensitive.

This is how most platforms work:
- Stripe publishes its API docs publicly (schemas, endpoints, parameters)
- The actual transaction data is sensitive and access-controlled
- Knowing Stripe has a `GET /charges` endpoint is not a security risk

If we adopt this model:
- RS4 (schemas in prompt) is safe — schemas are public knowledge
- RS2 (dual-agent) is needed only for data exploration, not schema discovery
- The developer knows module API shapes but not actual data values
- Actual data values only enter context during module_integrator step (no internet)

**What this means for Druppie:** Module API schemas become part of the platform documentation. They're designed to be public. Proprietary value is in the DATA the modules provide, not the fact that they exist.

**Accepted risk:** Competitors learn what modules we offer. But this is standard in SaaS — your product page already lists capabilities. The API schema is just a more detailed version of that.

#### Resolution B: Two Fully Separate Pipelines

Run two completely independent pipelines that never share information:

```
Pipeline A: Module Exploration Pipeline
  Networks: [modules] only (NO internet, ever)
  Agents: modules_researcher → module_designer
  Output: functional_design.md (written WITHOUT internet knowledge)
  The FD contains module capabilities + proposed application design
  This FD is delivered to the dev/architect (human) for review

Pipeline B: Implementation Pipeline  
  Networks: [internet] then [modules]
  Agents: installer → developer → tester → module_integrator → deployer
  Input: functional_design.md (from Pipeline A, but...)
  
  Problem: if the FD contains module knowledge, Pipeline B's 
  developer (internet) receives module-derived information.
```

This doesn't actually solve the problem — the FD is still the bridge. Unless the FD is written WITHOUT referencing specific module capabilities, in which case... what was the point of Pipeline A?

The only way this works: Pipeline A produces an FD that describes the APPLICATION (user-facing features) without describing the MODULES that power it. The developer then implements the application based on the feature description, and the module_integrator connects it to the actual modules.

**This is actually viable:** "Build a dashboard showing regional population comparison with age distribution charts" (application description) vs. "Use DemographicsModule.get_statistics() which returns {region, population, age_groups}" (module knowledge). The developer can build the first without the second — using mocks with reasonable assumptions about data shape.

#### Resolution C: Human-In-The-Loop At The Research Boundary

The dev/architect (human) acts as the bridge. No agent ever crosses the boundary.

```
Module exploration:
  modules_researcher agent (modules, no internet)
  explores real module APIs
  writes capabilities report
  → dev/architect reviews the report (human reads it)

Public data exploration:
  internet_researcher agent (internet, no modules)
  explores CBS, public APIs
  writes data availability report
  → dev/architect reviews the report (human reads it)

Functional design:
  dev/architect (human) writes the FD themselves
  using knowledge from both reports
  The FD contains human-curated module + public data knowledge
  
Implementation:
  developer agent receives the human-written FD
  The FD may contain module knowledge, but the dev/architect 
  decided what to include — it's a human-controlled information flow
```

**The security model:** The human is the trusted information channel. They read both reports and write an FD that contains only what they consider safe to share with an internet-connected agent. They're the security boundary.

**Accepted risk:** The human might include too much module detail in the FD, effectively leaking it to the developer's internet-connected context. But this is a HUMAN decision, not an automated leak. The human is accountable.

### Assessment

| Resolution | Security | Practicality | Accuracy |
|------------|----------|-------------|----------|
| A: Schemas are non-sensitive | ⚠️ Depends on what you consider sensitive | ✅ Simple, automated | ✅ Always up to date |
| B: Separate pipelines + feature-only FD | ✅ Developer never sees module knowledge | ⚠️ FD must be written without module references | ⚠️ Developer guesses data shapes from feature description |
| C: Human as the bridge | ✅ Human controls information flow | ❌ Manual FD writing for every project | ✅ Human ensures accuracy |

### No Clean Answer

The research phase exposes a genuine architectural tension that network-level isolation cannot fully resolve. Information must flow from modules to internet-connected agents for the pipeline to work. The question is: **what information, and who controls the flow?**

Resolution A (accept schemas as non-sensitive) is the most pragmatic if the business model allows it — most SaaS platforms treat their API docs as public. Resolution C (human bridge) is the most secure but requires manual work for every project. Resolution B (feature-only FD) is theoretically clean but practically fragile.

This decision is a **product/architecture decision**, not a security decision. It depends on: what is Druppie's competitive moat? Is it the existence of the modules (known to customers), or the data they return (only accessible through the platform)?
