# Sprint Overzicht: Coding Agent Runtime

> Dit is een apart document naast `docs/stories/coding-agent-improvement.md`. Het documenteert wat er deze sprint is opgeleverd, met bewijs uit de code, en wat open staat voor de volgende sprint.

---

## 1. Agent Runtime Library gebouwd (`druppie/agent_runtime/`)

Een storage-agnostische Python library die agent executie drive. Geen DB imports, geen SQLAlchemy — herbruikbaar buiten Druppie.

**Bewijs:**

| Wat | Waar | Detail |
|-----|------|--------|
| **AgentLoop** — LLM ↔ tool turn cycle | `agent_runtime/loop.py` (498 regels) | Turn-based: call LLM, verwerk tool calls, repeat. Max 50 turns configureerbaar. |
| **done() enforcement** — agents moeten done() aanroepen | `loop.py:48-51` + `loop.py:94-117` | Als agent niet done() aanroept: system message injection "You must call done()". Na 3 enforcement retries: error. Bij context overflow (>150K tokens): done-tool als enige optie. |
| **LLM retry** — exponential backoff bij rate limits | `loop.py` (via `_call_llm_with_retries`) | Max 3 retries, base delay 1s, verdubbelt. |
| **Cancellation** — thread-safe stop | `types.py:74-89` | `CancellationToken` met lock. Loop checkt na elke turn. |
| **SubagentsMCP** — subagent spawning in-process | `subagents.py` (326 regels) | Parent roept `subagents(agents=[{agent, prompt}])`. Dynamic schema met enum van toegestane subagents. Inline execution: parent wacht. |
| **Depth limit** — max 10 niveaus recursie | `subagents.py:161-165` | `new_depth > config.max_subagent_depth` → error. |
| **Circular reference detection** — geen loops | `subagents.py` (agent_chain tracking) | Als agent ID al in chain → reject. |
| **Parallel spawning** — meerdere subagents tegelijk | `subagents.py:223` | `asyncio.gather` voor parallelle children. |
| **DoneTool validatie** — summary, variables, preconditions | `tools/done.py` (106 regels) | Dynamic JSON Schema, required_summary_status (one_of keywords), completion_preconditions (min tool calls, unless clauses). |
| **EventEmitter** — real-time event streaming | `events.py` (47 regels) | In-memory events + callbacks. Elke turn, tool call, error wordt gelogd. |
| **MCPConnection** — abstractie voor MCP servers | `tools/mcp.py` (45 regels) | URL-based of in-process. `call_tool()` met error handling. |
| **MCPToolProvider** — routeert tools naar juiste MCP server | `tools/provider.py` (140+ regels) | Tool name → server name mapping. Approval gates. |
| **Compat layer** — brug oude→nieuwe runtime | `compat.py` (710+ regels) | `adapt_llm()`, `DruppieToolProvider`, `create_event_persister()`, `old_definition_to_new()`, `SubagentsMCPConnection`. |

---

## 2. Alle agents draaien op nieuwe runtime

De orchestrator importeert `AgentV2` als `Agent` op 6 locaties in `druppie/execution/orchestrator.py` (regels 465, 709, 806, 941, 1012, 1198). De oude `Agent` class in `druppie/agents/runtime.py` wordt niet meer gebruikt.

**Bewijs:** `grep "runtime_v2" druppie/execution/orchestrator.py` → 6 hits, allemaal `from druppie.agents.runtime_v2 import AgentV2 as Agent`.

---

## 3. Sandbox Infrastructure

> **⚠️ Superseded — see [`docs/SANDBOX.md`](../SANDBOX.md).** This section
> describes the original per-agent **Docker/Sysbox** design. In production the
> coding sandbox is now a **gVisor**-isolated Kubernetes pod (agent-sandbox
> controller); Docker/Sysbox is only the *local dev* mode. The Sysbox /
> Docker-in-Docker / resource details below remain accurate for docker mode,
> but treat `docs/SANDBOX.md` as the source of truth for the runtime.

Per-agent Docker containers via `druppie/mcp-servers/module-coding/`.

### Container Lifecycle

| Wat | Waar | Detail |
|-----|------|--------|
| **Per session+git_scope** | `tools.py:331-333` | Container naam: `druppie-{session[:12]}-{git_scope}`. Agents met zelfde scope delen container. |
| **Auto-create bij eerste call** | `tools.py:545-547` | `_resolve_container()`: als geen container → `_create_sandbox_container()`. |
| **Destroy bij parent done()** | `tools.py:567-580` | `_destroy_all_for_session()`: alle containers voor een sessie gestopt + verwijderd. |
| **Subagent done() = NIET destroyen** | `subagents.py` (architectuur) | Alleen parent done/error/cancel triggert destroy. Child done stopt alleen de child execution. |
| **Dode container detectie** | `tools.py:539-543` | Als container niet running → uit cache, nieuwe aanmaken. |
| **Resources** | `tools.py:116-124` | 12GB memory, 4 CPUs, 32768 pids, 512MB tmpfs, Sysbox runtime. |
| **Docker-in-Docker** | `Dockerfile.sandbox:24-33` | Docker 20.10.24 + Compose v5.1.4 in sandbox. Agent kan eigen containers bouwen. |
| **Dependency cache** | `tools.py:348` | Gedeeld volume `sandbox_dep_cache` → pip/npm/uv cache persistent over containers. |

### Git Security

| Wat | Waar | Detail |
|-----|------|--------|
| **Credentials alleen bij clone** | `tools.py:296-309` | `_get_gitea_clone_url()` embed credentials, daarna `remote set-url` zonder credentials. |
| **push_changes via git bundle** | `tools.py` (push_changes tool) | Git bundle extractie op host, push vanuit host. Credentials nooit in container. |
| **create_pr via host API** | `tools.py` (create_pr tool) | Gitea/GitHub API call vanuit module-coding, niet vanuit sandbox. |
| **Bash blokkeert gevaarlijk git** | `tools.py` (bash tool) | Blocked: `git push`, `git credential`, destructive flags. |

### Netwerkisolatie (3 tiers)

Toegevoegd vanwege data_analyst agent die data-access MCP module nodig had. 

**Mechanisme (volledige keten):**
1. Agent YAML: `mcps: coding: networks: [internet]` 
2. `tool_context.py:163-171` — resolved `agent.coding_networks` uit agent definitie
3. `mcp_config.yaml:45-48` — injecteert als `sandbox_networks` parameter in alle coding tools
4. `tools.py:398-409` — `docker network connect` per tier bij container create

**Docker netwerken** (`docker-compose.yml:905-919`):
- `sandbox-net` — basis, `internal: true` (geen internet)
- `sandbox-inet` — internet toegang
- `sandbox-modules` — `internal: true`, MCP modules (data-access, filesearch, etc.) zitten hierop

**Agents per tier:**

| Tier | YAML config | Agents | Getest? |
|------|-------------|--------|---------|
| **Geen netwerk** | `networks: []` of geen config | explorer, reviewer | ❌ Niet getest |
| **Modules** | `networks: [modules]` | test_executor | ❌ Niet getest |
| **Internet** | `networks: [internet]` | developer, builder_planner, test_builder, core_builder_subagent | ❌ Niet getest |
| **Beide** | `networks: [internet, modules]` | (geen agent gebruikt dit momenteel) | ❌ Niet getest |

**⚠️ Status: geïmplementeerd en E2E getest ✅**

Test: `testing/tools/test-sandbox-networks.sh` — 6/6 tests geslaagd.

```
Test 1: Default sandbox (internal: true, no extra networks)
  ✅ Cannot reach internet
  ✅ Cannot reach module-filesearch

Test 2: Sandbox with [internet]
  ✅ CAN reach internet
  ✅ Cannot reach module-filesearch (correct)

Test 3: Sandbox with [modules]
  ✅ CAN reach module-filesearch: {"status":"healthy","module_id":"filesearch",...}
  ✅ Cannot reach internet (correct)
```

De modules sandbox kan via Docker DNS `http://module-filesearch:9004/health` bereiken en krijgt een JSON response terug. Internet is geblokkeerd (`sandbox-modules` is `internal: true`).

**Beperking:** De keten van YAML → context injection → `sandbox_networks` parameter is niet getest via de agent pipeline. Alleen de infrastructuur-laag (Docker netwerk connectiviteit) is bewezen. De volledige keten (agent YAML `networks: [modules]` → `tool_context.py` → `mcp_config.yaml` injectie → container krijgt netwerken) zou moeten werken op basis van code review, maar is niet end-to-end getest door een agent.

### MCP Tools in Sandbox

| Tool | Wat |
|------|-----|
| `read_file` | Bestand lezen uit container |
| `write_file` | Bestand schrijven naar container |
| `edit_file` | Search/replace edits in container |
| `bash` | Shell command met timeout, output capture, live streaming |
| `grep` | Regex search in container |
| `find` / `ls` | Bestanden zoeken/oplijsten |
| `run_tests` | Auto-detect pytest/vitest/jest, run, parse output |
| `push_changes` | Git bundle + push naar Gitea/GitHub |
| `create_pr` | PR aanmaken via API |
| `get_git_status` | Git status van workspace |
| `make_design` | Design doc schrijven met Mermaid validatie |
| `install_dependencies` | npm/pip install in container |
| `detect_test_framework` | Auto-detect test framework |

### Management API

| Endpoint | Wat |
|----------|-----|
| `POST /sandbox/cleanup/{session_id}` | Destroy alle containers voor sessie |
| `POST /sandbox/cleanup/{session_id}/{git_scope}` | Destroy specifieke container |
| `GET /sandbox/status` | Actieve containers + warm pool status |

---

## 4. Agent Hiërarchie

### Algemene agents

```
router (primary) → classifyt intent
planner (primary) → maakt plan met agent stappen
business_analyst (primary) → HITL + make_design, git: current_project
architect (primary) → make_design + read, git: current_project
summarizer (primary) → samenvatting
```

### Coding pipeline — project apps

```
ultimate_dev (primary, orchestrator)
  │
  ├── explorer (subagent) — read-only, networks: []
  │
  ├── builder_planner (subagent) — schrijft builder_plan.md
  │   └── kan explorer spawnen
  │
  ├── test_builder (subagent) — TDD Red Phase
  │   └── kan explorer spawnen
  │
  ├── developer (subagent) — TDD Green Phase
  │   └── kan explorer spawnen
  │
  ├── test_executor (subagent) — draait tests, PASS/FAIL
  │   └── kan explorer spawnen
  │
  ├── reviewer (subagent) — code review, APPROVE/REJECT
  │   └── kan explorer spawnen
  │
  └── deployer (subagent) — Docker build + deploy
      └── kan explorer spawnen
```

**TDD pipeline flow:** explorer → builder_planner → test_builder → developer → test_executor → [FAIL: terug naar developer, max 3x] → reviewer → [REJECT: terug naar developer] → deployer → [FAIL: terug naar developer] → done()

Alle delen `git: current_project` = zelfde sandbox container.

### Coding pipeline — Druppie core

```
ultimate_dev_core (primary, orchestrator)
  │
  ├── core_explorer (subagent) — kan zichzelf recursief spawnen (depth 10)
  │
  └── core_builder_subagent (subagent) — networks: [internet]
      └── maakt branch core/<desc> van colab-dev
      └── pytest + ruff + black
      └── pusht + opent PR
```

---

## 5. Developer Page

Standalone agent testing buiten de standaard pipeline.

| Wat | Waar |
|-----|------|
| Frontend | `frontend/src/pages/DeveloperPage.jsx` (350 regels) |
| Backend API | `druppie/api/routes/agent_test.py` |
| Spec | `docs/DEVELOPER_PAGE.md` |

Features: project selectie, agent selectie (primary/both roles), task prompt, execute button, polling, status badges, agent detail (role, git scope, MCPs, subagents).

---

## 6. Tests

| Wat | Waar |
|-----|------|
| Agent runtime unit tests (9 files) | `druppie/tests/agent_runtime/` |
| Sandbox MCP tests | `druppie/tests/mcp_servers/test_sandbox.py` |
| Orchestrator subagent tests | `druppie/tests/execution/test_orchestrator_subagents.py` |
| Evaluation framework | `druppie/testing/` |
| E2E setup tests | `testing/tools/` |

---

## 7. Open voor volgende sprint

| # | Wat | Waarom |
|---|-----|--------|
| 1 | **Core in sandbox installeren** | Agent moet Druppie core kunnen builden+testen in sandbox om eigen code te verifiëren |
| 2 | **Gespecialiseerde builders** (backend, frontend, db) | Betere codekwaliteit door agents met diepgaande kennis van hun laag |
| 3 | **Betere builder planner** (onderzoek + meerdere proposals) | Plannen zijn nu te oppervlakkig, moeten meerdere opties voorleggen met expert in the loop |
| 4 | **Foutherstel verbeteren** | Betere retry logic bij build/test/sandbox failures |
| 5 | **E2E vergunningzoeker** | Het uiteindelijke bewijs: agent bouwt volledige werkende applicatie |
| 6 | **Netwerkisolatie via agent pipeline testen** | Infrastructuur-laag is getest (6/6 ✅). De keten YAML → context injectie → container netwerken via een echte agent run is nog niet getest |
| 7 | **Wat kan de sandbox met modules doen in praktijk?** | test_executor heeft `networks: [modules]` maar het is onduidelijk wat de use case is. Kan de sandbox data-access MCP direct aanroepen (bash curl naar HTTP endpoint)? Of moet dit via een MCP client in de sandbox? |
