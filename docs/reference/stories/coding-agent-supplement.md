# Coding Agent Improvement — Sprint Resultaten & Open Punten

> Aanvulling op `docs/reference/stories/coding-agent-improvement.md`. Overkoepelend doel: de coding agent moet de vergunningzoeker applicatie end-to-end kunnen bouwen.

---

## Wat er deze sprint is gebouwd

### 1. Agent Runtime Library (`druppie/agent_runtime/`)

Een herbruikbare Python library die de kern vormt van agent executie.

#### AgentLoop (`loop.py`, 498 regels)

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RT-1 | Turn-based LLM ↔ tool-call loop: call LLM, process tool calls, repeat | ✅ |
| RT-2 | `done()` enforcement: als agent niet `done()` aanroept, injecteert loop system message met "You must call done()". Max 3 enforcement retries per turn | ✅ |
| RT-3 | Context overflow detectie: als tokens > `max_context_tokens` (150K default), forceert loop `done()` met alleen done-tool beschikbaar | ✅ |
| RT-4 | LLM retry met exponential backoff bij rate limits/server errors (max 3 retries, base delay 1s) | ✅ |
| RT-5 | Cancellation support via `CancellationToken` (thread-safe) — loop stopt na huidige turn | ✅ |
| RT-6 | Configurable `max_turns` (default 50), `max_retries`, `max_context_tokens` | ✅ |
| RT-7 | Event tracking: elke turn, tool call, tool result, LLM response, error wordt als `AgentEvent` gelogd | ✅ |
| RT-8 | Storage-agnostic: geen DB imports, geen SQLAlchemy. Alleen `AgentResult` met events teruggeven | ✅ |

#### AgentDefinition (`definition.py`, 271 regels)

YAML parser voor agent definities met full schema support.

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RD-1 | Parse YAML → `AgentDefinition` dataclass (id, name, description, role, system_prompt, mcps, subagents, skills) | ✅ |
| RD-2 | `role` validatie: `primary`, `subagent`, of `both` | ✅ |
| RD-3 | `done_variables` met JSON Schema validatie (required/optional, types, enums) | ✅ |
| RT-4 | `completion_preconditions`: conditionele tool call requirements (min_calls, summary_contains, unless_summary_contains) | ✅ |
| RD-5 | `required_summary_status`: summary moet bepaalde keywords bevatten (one_of) | ✅ |
| RD-6 | `approval_overrides`: per-tool approval configuratie (requires_approval, required_role, pre_validate) | ✅ |
| RD-7 | Dynamic `done()` JSON Schema gegenereerd op basis van done_variables | ✅ |
| RD-8 | `coding_networks` property: leest `networks` uit `mcps.coding` config | ✅ |

#### SubagentsMCP (`subagents.py`, 326 regels)

In-process MCP server voor subagent spawning.

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RS-1 | Parent agent roept `subagents(agents=[{agent, prompt}])` aan | ✅ |
| RS-2 | Dynamic schema: `enum` met alleen toegestane subagents (two-layer validation: schema enum + server-side) | ✅ |
| RS-3 | Recursion depth limit: max 10 levels (`max_subagent_depth`) | ✅ |
| RS-4 | Circular reference detection: agent chain tracking, reject als agent al in chain | ✅ |
| RS-5 | Inline execution: parent wacht tot children klaar zijn | ✅ |
| RS-6 | Parallel spawning via `asyncio.gather` (meerdere subagents tegelijk) | ✅ |
| RS-7 | Subagents delen sandbox container met parent (zelfde `git_scope`) | ✅ |
| RS-8 | Subagent `done()` vernietigt container NIET (parent heeft 'm nog nodig) | ✅ |
| RS-9 | Pause support: als child pauzeert (HITL), result bevat `_pending=True` met juiste `AgentRunStatus` mapping | ✅ |
| RS-10 | Role enforcement: `subagent`-only agents kunnen niet op top level worden gespawnd | ✅ |

#### DoneTool (`tools/done.py`)

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RD-1 | Dynamic schema generatie op basis van done_variables | ✅ |
| RD-2 | Validatie: summary aanwezig, required variables ingevuld, types correct | ✅ |
| RD-3 | `required_summary_status` check (summary moet minimaal 1 keyword bevatten) | ✅ |
| RD-4 | `completion_preconditions` check (required tool calls gedaan, unless-voorwaarden) | ✅ |

#### EventEmitter (`events.py`)

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RE-1 | Events in-memory opgeslagen in volgorde | ✅ |
| RE-2 | Real-time callbacks op elke `emit()` | ✅ |
| RE-3 | Callback exceptions worden gevangen, andere callbacks blijven draaien | ✅ |

#### Compat Layer (`compat.py`)

Brug tussen Druppie backend en agent_runtime.

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| RC-1 | `adapt_llm()`: wrapped oude `BaseLLM.achat()` naar nieuwe async callable | ✅ |
| RC-2 | `DruppieToolProvider`: implementeert `ToolProvider` protocol, routeert tool calls naar juiste MCP server | ✅ |
| RC-3 | `create_event_persister()`: event callback → DB writes (ToolCall records, agent run updates) | ✅ |
| RC-4 | `old_definition_to_new()`: converteert oude Pydantic `AgentDefinition` naar nieuwe dataclass | ✅ |
| RC-5 | `SubagentsMCPConnection`: wrapped SubagentsMCP als MCPConnection | ✅ |

---

### 2. AgentV2 Facade (`druppie/agents/runtime_v2.py`)

De nieuwe Agent class die alle agents via agent_runtime draait. De orchestrator importeert dit als `from druppie.agents.runtime_v2 import AgentV2 as Agent` op 6 locaties.

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| V2-1 | Zelfde public API als oude `Agent` class (`run()`, `list_agents()`, etc.) | ✅ |
| V2-2 | Intern: gebruikt `AgentLoop` uit `agent_runtime/loop.py` via `compat.py` adapters | ✅ |
| V2-3 | Alle 6 orchestrator call sites gebruiken `AgentV2` (lines 465, 709, 806, 941, 1012, 1198) | ✅ |
| V2-4 | Message reconstructie uit DB voor pause/resume werkt | ✅ |
| V2-5 | Prompt building met tool instructions, project context, language injection | ✅ |

---

### 3. Sandbox Infrastructure (`druppie/mcp-servers/module-coding/`)

#### Sandbox Container Lifecycle (`v1/tools.py`, 2762 regels)

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| SB-1 | Per-session per-git_scope container: `druppie-{session[:12]}-{git_scope}` | ✅ |
| SB-2 | Eerste tool call → container created + repo cloned. Volgende calls → bestaande container hergebruikt | ✅ |
| SB-3 | Container resources: 12GB memory, 4 CPUs, 32768 pids limit, 512MB tmpfs | ✅ |
| SB-4 | Sysbox runtime voor Docker-in-Docker (Docker 20.10.24 + Compose v5.1.4 in sandbox) | ✅ |
| SB-5 | Dependency cache volume gedeeld tussen alle sandboxen (`sandbox_dep_cache` voor pip/npm/uv) | ✅ |
| SB-6 | Container destroyed bij: parent done(), error, cancel (`_destroy_all_for_session()`) | ✅ |
| SB-7 | Dode container detectie: als container niet meer draait bij `_resolve_container()`, wordt nieuwe aangemaakt | ✅ |

#### Git Security

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| SG-1 | Git credentials alleen gebruikt bij clone, daarna gestript (remote URL zonder credentials) | ✅ |
| SG-2 | `push_changes`: git bundle extractie op host, push vanuit host (credentials nooit in container) | ✅ |
| SG-3 | `create_pr`: PR aangemaakt via Gitea API vanuit host, niet vanuit sandbox | ✅ |
| SG-4 | Bash tool blokkeert gevaarlijke git commands (`git push`, `git credential`, etc.) | ✅ |

#### Netwerkisolatie (3 tiers)

Toegevoegd vanwege data_analyst agent die data-access MCP nodig had. Geconfigureerd in YAML per agent.

| # | Tier | Config | Beschrijving |
|---|------|--------|-------------|
| SN-1 | Geen netwerk | `networks: []` | Standaard. Alleen interne sandbox communicatie. Explorer agent. |
| SN-2 | Modules | `networks: [modules]` | Toegang tot Druppie MCP modules (data-access, filesearch). data_analyst. |
| SN-3 | Internet | `networks: [internet]` | Volledig internet voor npm/pip install, git clone. developer, deployer. |
| SN-4 | Beide | `networks: [internet, modules]` | core_builder_subagent. |

**Mechanisme**: Container start met alleen `SANDBOX_NETWORK`. Extra netwerken geconnect via `docker network connect` op basis van `agent_networks` parameter uit agent YAML.

#### MCP Tools beschikbaar in sandbox

| Tool | Beschrijving | Status |
|------|-------------|--------|
| `read_file` | Lees bestand uit sandbox container | ✅ |
| `write_file` | Schrijf bestand naar sandbox container | ✅ |
| `edit_file` | Targeted edits op bestand in container (search/replace) | ✅ |
| `bash` | Shell command uitvoeren in container (timeout, output capture, live streaming) | ✅ |
| `grep` | Regex search in container | ✅ |
| `find` / `ls` | Bestanden zoeken/oplijsten | ✅ |
| `run_tests` | Auto-detect test framework (pytest/vitest/jest), run tests, parse output | ✅ |
| `push_changes` | Git bundle extractie + push naar Gitea/GitHub | ✅ |
| `create_pr` | Pull request aanmaken op Gitea/GitHub | ✅ |
| `get_git_status` | Git status van workspace | ✅ |
| `make_design` | Functioneel/technisch design document schrijven met Mermaid validatie | ✅ |
| `install_dependencies` | npm install / pip install in sandbox | ✅ |
| `detect_test_framework` | Auto-detect pytest/vitest/jest | ✅ |

#### Sandbox Management API (`server.py`)

| Endpoint | Beschrijving | Status |
|----------|-------------|--------|
| `POST /sandbox/cleanup/{session_id}` | Destroy alle containers voor een sessie | ✅ |
| `POST /sandbox/cleanup/{session_id}/{git_scope}` | Destroy specifieke container | ✅ |
| `GET /sandbox/status` | Overzicht actieve containers + warm pool | ✅ |

---

### 4. Agent Definities & Hiërarchie

#### Algemene Agents (`definitions/general/`)

| Agent | Role | MCPs | Subagents | Git Scope |
|-------|------|------|-----------|-----------|
| router | primary | web (search, fetch) | — | — |
| planner | primary | — | — | — |
| business_analyst | primary | coding (make_design, bash, push_changes) | — | current_project |
| architect | primary | coding (make_design, bash, push_changes, read_file, grep) | — | current_project |
| summarizer | primary | — | — | — |

#### Coding Agents — Project (`definitions/coding/project/`)

| Agent | Role | Subagents | MCPs (coding tools) | Networks |
|-------|------|-----------|---------------------|----------|
| **ultimate_dev** | primary | explorer, builder_planner, test_builder, developer, test_executor, reviewer, deployer | — (orchestrator only) | — |
| explorer | subagent | — | read_file, grep, find, ls | — |
| builder_planner | subagent | explorer | read_file, write_file, edit_file, bash, grep, find, ls, push_changes, create_pr, get_git_status | — |
| test_builder | subagent | explorer | read_file, write_file, edit_file, bash, grep, find, ls, run_tests, push_changes, create_pr, get_git_status | — |
| developer | subagent | explorer | read_file, write_file, edit_file, bash, grep, find, ls, run_tests, push_changes, create_pr, get_git_status | — |
| test_executor | subagent | explorer | read_file, bash, grep, find, ls, run_tests, push_changes | — |
| reviewer | subagent | explorer | read_file, bash, grep, find, ls | — |
| deployer | subagent | explorer | read_file, bash, grep, find, ls | — |

Alle coding agents delen `git: current_project` — zelfde sandbox container binnen een sessie.

#### Coding Agents — Core (`definitions/coding/core/`)

| Agent | Role | Subagents | MCPs (coding tools) | Networks |
|-------|------|-----------|---------------------|----------|
| **ultimate_dev_core** | primary | core_explorer, core_builder_subagent | — (orchestrator only) | — |
| core_explorer | subagent | core_explorer (recursief!) | read_file, bash, grep, find, ls | — |
| core_builder_subagent | subagent | — | read_file, write_file, edit_file, bash, grep, find, ls, run_tests, push_changes, create_pr, get_git_status | [internet] |

`core_builder_subagent` is de enige agent met `networks: [internet]` — nodig om dependencies te installeren bij core platform changes.

#### Ultimate Dev TDD Pipeline Flow

```
ultimate_dev (orchestrator)
  │
  ├── 1. explorer → leest design docs, rapporteert bevindingen
  │
  ├── 2. builder_planner → maakt builder_plan.md
  │     └── kan explorer subagent spawnen voor onderzoek
  │
  ├── 3. test_builder → genereert tests (TDD Red Phase)
  │     └── kan explorer subagent spawnen
  │
  ├── 4. developer → implementeert code (TDD Green Phase)
  │     └── kan explorer subagent spawnen
  │
  ├── 5. test_executor → draait tests, rapporteert PASS/FAIL
  │     └── kan explorer subagent spawnen
  │
  ├── [als FAIL] → terug naar 4 (developer) met failure details
  │                 max 3 retries per stage
  │
  ├── 6. reviewer → code review, APPROVE of REJECT
  │     └── kan explorer subagent spawnen
  │
  ├── [als REJECT] → terug naar 4 (developer) met feedback
  │
  ├── 7. deployer → Docker build + deploy
  │     └── kan explorer subagent spawnen
  │
  ├── [als DEPLOY FAIL] → terug naar 4 (developer) met error logs
  │
  └── 8. done() met samenvatting
```

#### Ultimate Dev Core Flow

```
ultimate_dev_core (orchestrator)
  │
  ├── 1. core_explorer → leest Druppie core codebase + design docs
  │     └── kan zichzelf recursief spawnen (depth 10) voor parallel onderzoek
  │
  ├── 2. core_builder_subagent → implementeert core wijzigingen
  │     └── maakt branch core/<desc> van colab-dev
  │     └── draait pytest, ruff, black
  │     └── pusht + opent PR
  │
  ├── 3. core_explorer → verifieert implementatie
  │
  └── 4. done() met PR URL
```

---

### 5. Developer Page (`frontend/src/pages/DeveloperPage.jsx`)

Standalone pagina voor agent testing buiten de standaard pipeline om.

| # | Acceptatiecriterium | Status |
|---|---------------------|--------|
| DP-1 | Project selectie dropdown (alle Gitea projecten) | ✅ |
| DP-2 | Agent selectie dropdown (alle agents met primary/both role) | ✅ |
| DP-3 | Task prompt textarea | ✅ |
| DP-4 | Execute button → `POST /agent-test/execute` | ✅ |
| DP-5 | Backend: maakt session + agent_run, draait agent in background task | ✅ |
| DP-6 | Frontend pollet status tot voltooiing | ✅ |
| DP-7 | Status badges: completed, failed, running, pending, cancelled | ✅ |
| DP-8 | Agent details: role, git scope, MCP config, subagents | ✅ |
| DP-9 | Role-based toegang (admin/developer) | ✅ |

---

### 6. Test Infrastructuur

| # | Wat | Locatie | Status |
|---|-----|---------|--------|
| T-1 | Agent runtime unit tests (9 test files) | `druppie/tests/agent_runtime/` | ✅ |
| T-2 | Sandbox MCP tests | `druppie/tests/mcp_servers/test_sandbox.py` | ✅ |
| T-3 | Orchestrator subagent tests | `druppie/tests/execution/test_orchestrator_subagents.py` | ✅ |
| T-4 | Evaluation/testing framework (replay executor, bounded orchestrator, judges) | `druppie/testing/` | ✅ |
| T-5 | Setup tests voor E2E flows | `testing/tools/` | ✅ |

---

## Wat er nog moet gebeuren

### 1. Core in de sandbox

Coding agents moeten de Druppie core kunnen installeren en testen in hun sandbox.

| # | Eis |
|---|-----|
| C1 | Sandbox heeft Druppie core dependencies beschikbaar (installatie via pip/npm vanuit repo of cache) |
| C2 | Agent kan tests draaien tegen de core in de sandbox (unit tests + Playwright) |
| C3 | Agent kan zelf verifiëren of wijzigingen werken (build + test slagen) |

### 2. Gespecialiseerde coding agents

| # | Eis |
|---|-----|
| A1 | `backend_builder` — Python/FastAPI/SQLAlchemy specialist |
| A2 | `frontend_builder` — React/Vite specialist |
| A3 | `db_builder` — database schema/migraties specialist |
| A4 | coding_planner kiest de juiste builder(s) op basis van het plan |
| A5 | Parallelle builders aan verschillende files in 1 sandbox |
| A6 | Planner genereert contracts/interfaces zodat builders consistent blijven |

### 3. Betere builder planner

| # | Eis |
|---|-----|
| P1 | Planner onderzoekt codebase (patterns, dependencies, data model) voor het plan |
| P2 | Minimaal 2 proposals met verschillende aanpak, elk met pros/cons/impact/effort |
| P3 | Vraagt developer toestemming voor uitvoeren |
| P4 | Plan bevat code conventions, test strategie, file-level change approach |

### 4. Foutherstel verbeteren

| # | Eis |
|---|-----|
| F1 | Sandbox crash → automatische container recreatie, agent blijft draaien |
| F2 | Build/test fail → max 3 retries met fail rapport terug naar parent |
| F3 | Geen stille crashes. Alle errors zichtbaar in events |

### 5. E2E — Vergunningzoeker

| # | Eis |
|---|-----|
| E1 | `docker compose build` slaagt |
| E2 | App bereikbaar op HTTP port |
| E3 | Functionele endpoints werken zoals gespecificeerd |
| E4 | Minimaal 1 test slaagt |
| E5 | Agent stopt/crasht niet tijdens executie |
