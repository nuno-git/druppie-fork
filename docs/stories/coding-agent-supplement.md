# Coding Agent Improvement — Aanvullende Eisen

> Dit bestand bevat aanvullende eisen bovenop de bestaande story in `docs/stories/coding-agent-improvement.md` (Fase 3: Native coding agents in Druppie's runtime). Het overkoepelende doel blijft: de coding agent moet de vergunningzoeker applicatie end-to-end kunnen bouwen.

---

## Wat er al werkt (samengevat)

| Onderdeel | Status |
|-----------|--------|
| `agent_runtime/` library met AgentLoop, done() enforcement, subagents | ✅ Klaar |
| AgentV2 facade die alle agents via nieuwe runtime draait | ✅ Klaar |
| Sandbox containers (Docker/Kata, per git_scope, git bundle extractie, geen credentials) | ✅ Klaar |
| Subagent spawning (inline, parent wacht, child done() destroyet container niet) | ✅ Klaar |
| Warm pool voor sandbox containers | ✅ Klaar |
| Developer page (project + agent + prompt → execute) | ✅ Klaar |
| Netwerkisolatie van sandbox per agent via YAML (`networks: [internet, modules, ...]`) | ✅ Klaar |

---

## Wat er nog moet gebeuren

### 1. Core in de sandbox

Coding agents moeten de Druppie core kunnen installeren in hun sandbox om te verifiëren of hun code werkt.

| # | Eis |
|---|-----|
| C1 | Sandbox heeft Druppie core dependencies beschikbaar (installatie via pip/npm vanuit repo of cache) |
| C2 | Agent kan tests draaien tegen de core in de sandbox zowel unit tests als playwright |
| C3 | Agent kan zelf verifiëren of wijzigingen werken (build + test slagen) |

### 2. Gespecialiseerde coding agents

In plaats van één generieke developer krijg je agents met diepgaande kennis van hun laag.

| # | Eis |
|---|-----|
| A1 | `backend_builder` — Python/FastAPI/SQLAlchemy specialist |
| A2 | `frontend_builder` — React/Vite specialist |
| A3 | `db_builder` — database schema/migraties specialist |
| A4 | coding_planner kiest de juiste builder(s) op basis van het plan |
| A5 | Parallelle builders werken aan verschillende files in 1 sandbox |
| A6 | Planner genereert contracts/interfaces zodat builders consistent blijven |

### 3. Betere builder planner

| # | Eis |
|---|-----|
| P1 | Planner onderzoekt codebase (patterns, dependencies, data model) voor het plan |
| P2 | Minimaal 2 proposals met verschillende aanpak, elk met pros/cons/impact/effort |
| P3 | Vraagt developer toestemming voor uitvoeren |
| P4 | Plan bevat code conventions, test strategie, file-level change approach |

### 4. Sandbox lifecycle

| # | Eis |
|---|-----|
| L1 | Container start bij eerste tool call, stopt bij parent done()/error/cancel |
| L2 | Subagent done() destroyet container niet |
| L3 | HITL pause → container stop. Resume → herstart met warm pool |

### 5. Foutherstel

| # | Eis |
|---|-----|
| F1 | Tool error → retry 3x. Sandbox crash → nieuwe container, agent blijft draaien |
| F2 | LLM fail → retry 3x met backoff |
| F3 | Subagent fail → parent beslist: retry/skip/abort |
| F4 | Build/test fail → max 3 retries, daarna fail rapport |
| F5 | Geen stille crashes. Alle errors zichtbaar in events |

### 6. Developer Page

| # | Eis |
|---|-----|
| D1 | Alleen admin/developer rollen hebben toegang |
| D2 | Live status + events + tool calls zichtbaar na execute |

### 7. E2E — Vergunningzoeker

De coding agent bouwt autonoom de vergunningzoeker applicatie.

| # | Eis |
|---|-----|
| E1 | `docker compose build` slaagt |
| E2 | App bereikbaar op HTTP port (`curl localhost: