---
id: "002"
title: "LLM-Orchestratie binnen Gebouwde Apps — Platform Standaard & Onderbouwing"
status: complete
author: mk2023-land
date: 2026-06-01
outcome: null
---

# LLM-Orchestratie binnen Gebouwde Apps — Platform Standaard & Onderbouwing

> Status: platform-research, juni 2026.
> Onderbouwt twee skills:
> - `druppie/skills/llm-orchestration-in-apps/SKILL.md` (architect — WAT:
>   patroon, agency-niveau, plaatsing).
> - `druppie/skills/llm-orchestration-standard/SKILL.md` (builder_planner —
>   HOE: library, access-pattern, code-plaatsing).
>
> Dit is geen project-TD-research. Het doel is **één standaard** vast te
> leggen voor hoe Druppie-apps in-app LLM-logica bouwen — niet om per
> project tussen twaalf frameworks te kiezen. De framework-survey staat
> daarom achteraan als bewijslast (appendix), niet als keuzemenu.

## 1. Standaard in één pagina

Wanneer een door Druppie gegenereerde app **zelf** meerstaps-LLM-logica
bevat (niet een Druppie-agent aanroept, maar eigen LLM-stappen draait),
bouwen we dat op één manier. Standaardisatie wint van per-project
perfectionisme: het houdt een groeiende vloot van gegenereerde apps
beheerbaar, reviewbaar en snel te begrijpen.

| Agency-beslissing (architect) | Standaard-implementatie (builder_planner) | LLM-toegang |
|---|---|---|
| **LLM + UI** (patroon #1–#2) | **Plain Python** — directe call + UI-gate (Approve/Reject/edit). Geen framework. | `module-llm.chat` |
| **Sequential chain / evaluation loop** (#2–#3) | **Plain Python** — expliciete functies/stappen, `for`-loop voor evaluatie. Geen framework. | `module-llm.chat` |
| **Single agent + tools** (#4) | **Plain Python, core-stijl** — een kleine tool-loop gemodelleerd op de platform-agent-loop: tool calls, een **verplichte `done`-tool**, agents/tools in **YAML**, een max-iteratie-cap. Geen agent-framework. | Direct provider-SDK *(native tool-calling is nodig; module-llm.chat kan dat nog niet — zie §5)* |
| **Durable / multi-agent** (#5–#6) | **Escalatie — niet voorgebakken.** Vereist een bewuste platform-beslissing vóór bouwen; niet stilletjes per project een framework kiezen. | n.v.t. |

**Geen agent-framework.** Alles lineairs is plain Python; de single agent
met tools is een kleine core-stijl tool-loop (zie boven). Externe
agent-libraries (Pydantic-AI, LangGraph, CrewAI, …) brengen reële kosten
mee — version-churn, abstractie-lock-in, lastiger debuggen, grotere
supply-chain — en zijn niet de standaard. Durable execution en echte
multi-agent zijn zeldzaam en worden bewust gestandaardiseerd, niet ad hoc
gekozen. Een écht herbruikbare core-runtime vergt eerst de platform-loop
app-bruikbaar maken (toekomstwerk); tot dan is "core-stijl" *gemodelleerd
op* de core, per app met de hand geschreven.

**Default access-pattern:** `module-llm.chat`, tenzij het patroon iets
vereist dat de module vandaag niet kan (tool-use, streaming, structured
output, multi-turn) — dan direct SDK, met de reden in het plan. Die grens
schuift op zodra module-llm v2 landt (§5).

## 2. Scope — Druppie-agent vs in-app LLM-workflow

| Aspect | Druppie-agent | In-app LLM-workflow |
|--------|---------------|---------------------|
| Wie bouwt | Druppie-platformteam | Klant-applicatie |
| Code-locatie | `druppie/agents/definitions/*.yaml` + Orchestrator | Bínnen de gegenereerde app |
| Runtime | Druppie Orchestrator + ToolExecutor | Eigen control flow |
| Governance | Approvals, HITL, role-based MCP-permissies, audit | App regelt zelf logging/auth/errors |
| Tool-toegang | MCP-tools via tool_executor | Direct LLM-call (module-llm of provider) |
| Activatie | Planner scheduled hem | Endpoint of batch-job in de app |
| Skill | `module-convention` | `llm-orchestration-in-apps` + `-standard` |

Deze standaard geldt **alléén** voor de rechterkolom. Een nieuwe
Druppie-platformagent bouwen valt erbuiten.

## 3. Begrippenkader — workflow-patronen

Het patroon — niet het use-case-domein — bepaalt de structuur.

| # | Patroon | Voorbeeld | Karakteristiek |
|---|---------|-----------|----------------|
| 1 | **Single-shot** | "Vat dit ticket samen" | Eén prompt → één antwoord. Geen state, geen volgorde. |
| 2 | **Sequential chain** | draft → check → edit | Vaste volgorde, lineair, geen branching. |
| 3 | **Evaluation loop** | nightly gold-set scoring | `for sample in dataset: call → judge → log`. Metric-driven. |
| 4 | **Single agent + tools** | "vergunning-checker" met tools | Eén agent, meerdere tools, ReAct-loop. |
| 5 | **Stateful / durable** | meerdaagse approval-flow, HITL-pauze | Persistente state, pauze/resume, conditional branching. |
| 6 | **Multi-agent** | researcher + writer + reviewer | Meerdere agents met rollen, handoff of orchestrator-worker. |

> **2026-consensus** (Anthropic, Cognition, Shopify, MIT-studies): patroon
> #4 is het overlevende default-multi-step patroon. Multi-agent (#6) is in
> productie 58–285% duurder in tokens dan single-agent en degradeert 2–15%
> op SWE-bench Verified onder verkeerde toepassing. **Default = #4,
> escaleer naar #6 alleen bij gemeten capaciteits-saturatie.** Dit
> onderbouwt waarom de standaard bij de single agent (#4) stopt en
> multi-agent als bewuste escalatie behandelt.

## 4. De agency-hiërarchie (architect → WAT)

De architect lost de FD op tegen een **strikte volgorde** en stopt bij de
eerste regel die past. De uitkomst is een structurele beslissing
(geen-agent / single-agent / multi-agent), geen library.

1. **Simpelheid eerst.** Ontwerp de simpelste vorm die de FD bedient.
   Extra agency is een kost (latency, tokens, faalmodi, audit-oppervlak),
   geen feature.
2. **LLM + UI baseline.** Eén LLM-call gevolgd door een simpele
   mens-actie (Approve/Reject/edit) → **geen agent.** Patroon #1–#2.
3. **Single agent.** Meerdere distincte acties of tool-use voorbij
   generate-and-approve → **één agent met tools** (#4). Default-plafond
   voor niet-triviaal in-app werk.
4. **Multi-agent alleen op bewijs.** Escaleer naar #6 alleen bij gemeten
   single-agent-saturatie: informatievolume > één context-window, óf
   echt distincte, gelijktijdige expertisedomeinen. Noem het bewijs, of
   escaleer niet.

## 5. De kernvraag — module-llm uitbreiden of niet? (v2-handoff)

Vóór elke framework-vraag staat een structurele platformkeuze: **leeft de
LLM-abstractie in de modules of in de app?** Vandaag doet `module-llm` één
ding: `chat(prompt) → answer`. Daardoor moet een in-app agent (#4) nu een
direct provider-SDK gebruiken — buiten de platform-bouwsteen om, dus
zonder de governance/consistentie die `druppie.call("llm", …)` geeft.

### 5.1 Capability-gap van `module-llm.chat` vandaag

| Capability | `module-llm.chat` | Vereist voor |
|------------|-------------------|--------------|
| Streaming (token-stream) | ❌ | Agent-UX, streaming responses |
| Tool-use / function-calling | ❌ | Elke single-agent #4 (eigen core-stijl tool-loop) |
| Structured output (JSON-schema) | ❌ | Getypeerde agent-output, validatie |
| Multi-turn message history | ❌ | Alle meerstaps-agent-state |
| Vision (image inputs) | ❌ | Multimodale workflows |

### 5.2 Voorgestelde richting (handoff — niet in deze PR)

Brei `module-llm` uit tot een rijke in-app LLM-client zodat gegenereerde
apps op de platform-bouwsteen blijven i.p.v. elk hun eigen stack te
importeren. Concreet als v2-tools (analoog aan de RAG Story-A/B-splitsing):

- `module-llm.chat_multi_turn` — multi-turn history + system/context.
- `module-llm.chat_with_tools` — function-calling/tool-use loop.
- (optioneel) structured-output mode + streaming-events.

Effect: de single-agent-standaard (#4) kan dan via `module-llm` draaien
i.p.v. direct SDK, en de access-pattern-default verschuift naar "altijd
module-llm". **Dit is een platform-roadmap-item, geen onderdeel van deze
skill-PR.** De skills zijn bewust geschreven met "module-llm tenzij het
het nog niet kan", zodat ze automatisch meeschuiven als v2 landt.

> Open beslissing voor het team: groeit dit binnen `module-llm`, of wordt
> het een breder `module-agents`? Zie de code-plaatsing-strategie in de
> `llm-orchestration-standard` skill (paden 3–4).

## 6. Aanbeveling (samengevat)

* **Default 2026:** Plain Python + `module-llm.chat` voor #1–#3. Reik naar
  een framework alleen als het patroon expliciet voorbij lineair gaat én
  een direct SDK acceptabel is.
* **Eén agent-standaard:** plain Python, core-stijl voor #4 — een kleine
  tool-loop gemodelleerd op de platform-agent-loop (tool calls, verplichte
  `done`, YAML-agents, max-iteratie-cap). Geen agent-framework; niet
  twaalf opties — één.
* **Multi-agent/durable defensief:** behandel als escalatie die eerst een
  platform-standaard nodig heeft; bouw niet per project een eigen
  checkpointer of multi-agent-framework.
* **Geen TR-LLM-XX dump** in TD's: het patroon + de structurele
  beslissing horen in één compacte subsectie; de library hoort in het
  builder_plan.

### Waarom geen archetype-denken (zoals RAG LS/HS/B)?

Voor RAG werkt LS/HS/B omdat het quality-archetype direct numerieke
NFR-targets stuurt. Voor LLM-orchestratie ligt de structurele keuze in het
**workflow-patroon** (#1–#6), niet in een quality-archetype. De skills
positioneren daarom patronen, geen archetypes.

---

## Appendix A — Overwogen alternatieven (bewijslast)

> Deze survey onderbouwt *waarom* de standaard plain Python (core-stijl)
> is, zónder agent-framework. Het is bewust een appendix: een
> project-architect of builder_planner hoeft hier niet doorheen — de
> standaard in §1 is de uitkomst.

### Cross-framework vergelijking

| Framework | Status (2026) | Sweet spot | `module-llm`-fit | Verdict t.o.v. standaard |
|-----------|---------------|-----------|------------------|--------------------------|
| **Plain Python (core-stijl)** | stabiel | #1–#3 én de single agent #4 (eigen tool-loop) | ✅ native (chat); direct SDK voor native tool-use | **Standaard (baseline + agent)** |
| Pydantic-AI | V1 stable | getypeerde single agent + tools | ❌ (direct SDK) | Niet de standaard — geen framework |
| LangChain LCEL | 1.0 stable; legacy chains EOL dec-2026 | lineaire pipelines | ✅ lineair | Niet nodig naast plain Python |
| LangGraph | 1.0 LTS | durable stateful, complexe multi-agent | ❌ | Alleen bij bewezen #5-escalatie |
| DSPy | 3.x (alpha-label) | metric-driven multi-stage | ✅ uniek | Optioneel voor #3 met harde metric |
| LlamaIndex Workflows | 1.0 stable | event-driven multi-step | 🟡 deels | Alleen bij #5-escalatie |
| CrewAI | 1.x stable | role-based multi-agent | ❌ | Alleen bij bewezen #6 (Python-stack) |
| MAF | 1.0 GA apr-2026 | multi-agent op Microsoft/.NET | ❌ | Alleen bij bewezen #6 (MS-stack) |
| Claude Agent SDK | 0.x (alpha) | app = autonome Anthropic-agent | ❌ | Alleen Anthropic-native, vendor-lock |
| AutoGen | **maintenance** | — | ❌ | Niet kiezen voor greenfield |
| Semantic Kernel | opgevolgd door MAF | bestaande SK-codebases | ❌ | Niet voor nieuw werk |
| Mirascope | 2.x, kleine community | anti-framework single calls | 🟡 | Plain Python is meestal beter |

### Waarom plain Python de baseline is
De industrie-consensus 2026 ("We ditched LangChain", roborhythms,
LangChain-1.0-upgrade-lessen) is dat ~80% van in-app LLM-werk lineair is en
geen framework nodig heeft; een framework toevoegen "voor later" is een
anti-pattern. Plain Python + `module-llm.chat` is daarom de nulmeting.

### Waarom geen agent-framework, maar een eigen core-stijl loop
Een single agent met tools (#4) heeft een tool-loop nodig, maar dat is
een kleine, expliciete loop — geen reden om een externe agent-library te
importeren. Het platform heeft het patroon al in de core
(`druppie/agents/loop.py`: tool calls, verplichte `done`, YAML-agents);
apps modelleren dáárop. Eén standaard voorkomt dat elke app een andere
agent-library kiest, en vermijdt de kosten van frameworks (version-churn,
abstractie-lock-in, lastiger debuggen, supply-chain). Multi-agent
(CrewAI/MAF) en durable engines (LangGraph) worden bewust níét
voorgebakken, conform de 2026-consensus dat premature multi-agent duurder
en slechter is.

## Appendix B — Bronnen (selectie)

### Frameworks
* LangChain / LangGraph 1.0 GA — <https://blog.langchain.com/langchain-langgraph-1dot0/>
* Pydantic-AI — <https://ai.pydantic.dev/>, <https://github.com/pydantic/pydantic-ai>
* DSPy — <https://dspy.ai/>, <https://github.com/stanfordnlp/dspy>
* CrewAI — <https://docs.crewai.com/>, <https://github.com/crewAIInc/crewAI>
* AutoGen (maintenance) — <https://github.com/microsoft/autogen>
* Microsoft Agent Framework — <https://learn.microsoft.com/en-us/agent-framework/>
* Claude Agent SDK — <https://code.claude.com/docs/en/agent-sdk/overview>
* LlamaIndex Workflows — <https://www.llamaindex.ai/blog/announcing-workflows-1-0-a-lightweight-framework-for-agentic-systems>

### Industrie-analyses 2026
* Anthropic engineering — Effective harnesses for long-running agents — <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
* "How I Built an AI Orchestration Engine Without LangChain in 2026" — <https://www.roborhythms.com/how-to-build-ai-orchestration-without-langchain-2026/>
* Databricks DSPy + JetBlue case study — <https://www.databricks.com/blog/optimizing-databricks-llm-pipelines-dspy>
* Multi-agent benchmark — <https://dev.to/ottoaria/multi-agent-ai-in-2026-build-production-systems-with-crewai-langgraph-autogen-5e40>
* "We ditched LangChain" — <https://medium.com/@larklaflamme/we-ditched-langchain-heres-what-we-built-instead-and-why-it-s-better-for-serious-ai-research-292d4265dde8>

### Gerelateerde platformdocs
* `druppie/mcp-servers/module-llm/v1/tools.py` — huidige `module-llm.chat` interface
* `druppie/skills/technical-design-format/SKILL.md` — TD-format
* `druppie/skills/technical-research-format/SKILL.md` — research-format
