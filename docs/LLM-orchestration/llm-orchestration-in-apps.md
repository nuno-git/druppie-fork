# LLM-Orchestratie binnen Gebouwde Apps — Platform Onderzoek

> Status: platform-research, juni 2026.
> Onderbouwt de skill `druppie/skills/llm-orchestration-in-apps/SKILL.md`.
> Niet bedoeld als project-TD-research. Een project-architect leest de
> skill (samenvatting + keuzewijzer); dit document is de
> evidence-base waarop die skill rust.

## Inleiding

### Onderwerp

Wanneer Druppie een applicatie voor een klant bouwt, kan die applicatie
zélf één of meerdere LLM-aanroepen bevatten — niet als Druppie-agent in
de platform-stack, maar als component binnen de gegenereerde app
(beleidsdraft-assistent, klacht-trieerder, vergunning-checker, …).

Dit onderzoek vergelijkt de relevante LLM-orchestratie-frameworks voor
2026 — LangGraph, LangChain LCEL, Pydantic-AI, DSPy, Mirascope, CrewAI,
AutoGen, Semantic Kernel, Microsoft Agent Framework, Claude Agent SDK,
LlamaIndex Workflows — plus "plain Python" als nulmeting, met als doel
de architect een onderbouwde keuze te kunnen laten maken.

### Onderzoeksvraag

Welke LLM-orchestratie-keuze (framework of geen-framework) past het best
bij welk **workflow-patroon** binnen door Druppie gegenereerde
applicaties, gegeven de huidige `module-llm.chat`-bouwsteen en de
platform-architectuur?

### Uitgangspunten

* **Scope = in-app workflows**, géén Druppie-agents. Druppie's eigen
  agent-stack (Orchestrator + YAML agent-definities + governance) valt
  buiten dit onderzoek; daar gelden andere conventies
  (`module-convention` skill, agent-definitie-patterns).
* **Bouwsteen `module-llm.chat`** is vandaag een MCP-tool met één
  prompt → één antwoord, backed door Z.AI GLM of DeepInfra. Geen
  streaming, geen tool-use, geen structured output, geen multi-turn
  message history.
* **Alternatief access-pattern** = de gebouwde app praat direct met
  een provider via een OpenAI-compatible HTTP-endpoint of een
  vendor-SDK (Anthropic, OpenAI, Azure Foundry, lokaal vLLM/Ollama).
  Provider-keuze is platform-config, geen skill-business.
* **Druppie-conventies**: hergebruik vóór maatwerk (principe 11),
  observability via OpenTelemetry, type-safety waar haalbaar, geen
  fundamenteel platform-lock-in zonder concrete trigger.
* **Niet in scope**: prompt-engineering best practices, evaluatie-tooling
  voor specifieke modellen, fine-tuning, GPU-infrastructuur.

### Begrippenkader — workflow-patronen

Voor de keuzewijzer onderscheiden we zes patronen. Het patroon — niet
het use-case-domein — bepaalt welk framework past.

| # | Patroon | Voorbeeld | Karakteristiek |
|---|---------|-----------|----------------|
| 1 | **Single-shot** | "Vat dit ticket samen" | Eén prompt → één antwoord. Geen state, geen volgorde. |
| 2 | **Sequential chain** | draft → check → edit | Vaste volgorde van stappen, lineair, geen branching. |
| 3 | **Evaluation loop** | nightly digest scoring, gold-set runs | `for sample in dataset: call → judge → log`. Metric-driven. |
| 4 | **Single agent + tools** | "vergunning-checker" met tools | Eén agent, meerdere tools, ReAct-style loop, mogelijk meerdere iteraties. |
| 5 | **Stateful / durable workflow** | meerdaagse approval-flow, HITL-pauze | Persistente state, pauze/resume, branching met conditional logic. |
| 6 | **Multi-agent** | researcher + writer + reviewer | Meerdere agents met rollen of taken, handoff of orchestrator-worker. |

> **2026-consensus** (Anthropic, Cognition, Shopify, MIT-studies): patroon
> 4 is het overlevende default-multi-step patroon. Multi-agent (#6) is
> in productie 58–285% duurder in tokens dan single-agent en degradeert
> 2–15% op SWE-bench Verified onder verkeerde toepassing. **Default = #4,
> escaleer naar #6 alleen bij gemeten capaciteits-saturatie.**

## Overwogen Benaderingen

We beschouwen vier framework-clusters plus de plain-Python nulmeting.

### Cluster 1 — Graph / Imperative

#### Plain Python (nulmeting)

* **Beschrijving:** `module-llm.chat` (of provider-SDK) in functies, met
  if/else, for-loops, asyncio, Pydantic voor validatie. Geen
  framework-abstractie.
* **Hergebruik:** `module-llm` (via MCP-bridge) of LiteLLM voor
  provider-portabiliteit zonder framework-commitment.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | ++ | Geen leercurve, geen abstractielaag |
  | Herbruikbaarheid | + | Geen lock-in; rechtstreeks met platform-bouwstenen |
  | Operationele kosten | ++ | Geen framework-overhead in tokens of ms |
  | Risico | + | Bij groei richting durable/multi-agent: zelf herbouwen wat LangGraph al heeft |
  | Fit met principes | ++ | "Standaard voor maatwerk" — gebruikt platform-bouwsteen direct |
  | `module-llm.chat`-fit | ++ | Native — design-point |

* **Wanneer geschikt:** Patronen #1, #2, #3, en simpele varianten van
  #4 (1–2 tools, ≤5 staten). De industrie-default 2026 voor productie
  die niet expliciet een framework nodig heeft. Documented "we ditched
  LangChain" pattern (Apr–May 2026, meerdere case studies).

#### LangChain LCEL (zonder LangGraph)

* **Beschrijving:** Declaratieve compositie via pipe-operator —
  `prompt | model | parser`. Sinds 1.0 GA (22 okt 2025) is de
  agent-loop verhuisd naar LangGraph; "LangChain zonder LangGraph"
  betekent in 2026 effectief **alleen LCEL-chains**. Legacy chains
  (`AgentExecutor`, `LLMChain`) zitten in `langchain-classic` en zijn
  EOL december 2026.
* **Hergebruik:** Brede provider-matrix (Anthropic, OpenAI, Azure,
  Bedrock, Ollama, vLLM, OpenAI-compatible), uitgebreide
  output-parsers, retrievers, prompt-templates.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | +/- | LCEL is elegant; pipe-debugging is opaak |
  | Herbruikbaarheid | + | Brede provider-pool; standaard prompt-templates |
  | Operationele kosten | - | ~10ms framework-overhead per call; abstraction tax |
  | Risico | - | Geschiedenis van breaking changes; "we ripped out LangChain" pattern in 2026 |
  | Fit met principes | +/- | Brengt afhankelijkheidsgraaf binnen; volg dezelfde patronen tussen apps |
  | `module-llm.chat`-fit | + | Lineaire chains werken; geen tool-use/streaming nodig |

* **Wanneer geschikt:** Patroon #2 (lineaire pipeline) wanneer het team
  LangChain al kent en de output-parsers concreet waarde toevoegen.
  Voor andere patronen: ga door naar LangGraph (zegt de officiële
  documentatie sinds 1.0).

#### LangGraph

* **Beschrijving:** Graph-based runtime — nodes + edges + TypedDict
  state + checkpointing. Eerste 1.0 LTS GA 22 oktober 2025 (geen
  breaking changes tot 2.0). Native multi-agent patterns: Supervisor,
  Swarm, Hierarchical. Productie-gebruikers: Uber, JP Morgan,
  BlackRock, Cisco, LinkedIn, Klarna, Replit.
* **Hergebruik:** LangChain provider-matrix; Postgres-checkpointer;
  LangSmith-tracing native + OpenTelemetry export.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | -- | Steile leercurve; meerdere abstracties (StateGraph, ToolNode, create_agent) |
  | Herbruikbaarheid | + | Patronen herbruikbaar; ecosysteem volwassen |
  | Operationele kosten | - | ~14ms framework-overhead; ~2.4K extra token-overhead per workflow |
  | Risico | + | LTS-commitment, brede productie-adoptie |
  | Fit met principes | +/- | Zware lock-in; observability uitstekend |
  | `module-llm.chat`-fit | -- | Verliest 80% van waarde: tool-use, streaming, structured output, agentic loops vallen weg |

* **Wanneer geschikt:** Patronen #5 (stateful/durable) en zware
  varianten van #6 (multi-agent met persistentie/HITL/multi-day runs).
  Vereist direct provider-SDK; via `module-llm.chat` is het overkill.

#### Cluster-uitspraak

| Patroon | Aanbevolen | Notitie |
|---------|-----------|---------|
| #1 single-shot | Plain Python | Framework is altijd overhead hier |
| #2 sequential | Plain Python óf LangChain LCEL | LCEL alleen als team het al heeft |
| #3 evaluation loop | Plain Python | Het is letterlijk een `for`-loop |
| #5 stateful durable | LangGraph | Vereist direct SDK; vermijd via module-llm |
| #6 zware multi-agent | LangGraph | Vereist direct SDK |

### Cluster 2 — Type-safe / Programmatic

#### Pydantic-AI

* **Beschrijving:** Type-safe agent-loop met Pydantic-gevalideerde
  inputs en outputs. V1 stabiel sinds september 2025; V2 in beta
  (mei 2026). Durable execution via DBOS (Postgres) of Temporal.
  Native A2A multi-agent protocol. Productie-gebruikers: Datalayer,
  Overjoy (verving LangChain), Lema AI, Boosted.ai (50k+ workflows/dag),
  MindsDB.
* **Hergebruik:** LiteLLMProvider out-of-the-box (100+ providers
  inclusief vLLM/Ollama/Foundry); Pydantic Logfire als first-party
  observability.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | + | Eén abstractie (Agent), Pythonisch |
  | Herbruikbaarheid | + | Brede provider-matrix; A2A protocol |
  | Operationele kosten | + | Lichter dan LangGraph; Logfire kostbewust |
  | Risico | + | V1 LTS sinds sept 2025; V2 migration path disciplined |
  | Fit met principes | ++ | Pydantic + FastAPI fit Druppie-stack perfect |
  | `module-llm.chat`-fit | -- | Vereist function-calling + JSON-mode voor `output_type`; degradeert tot wrapper |

* **Wanneer geschikt:** Patroon #4 (single agent + tools) en lichte #6
  (A2A multi-agent). De default voor type-safe Python agent-loops in
  2026 — mits direct SDK beschikbaar.

#### DSPy

* **Beschrijving:** Declaratief + offline optimizer. Schrijf Signatures
  en Modules, een compile-step (MIPROv2, GEPA, SIMBA, GRPO) zoekt over
  prompt/few-shot/weight-space om een metric te maximaliseren. Stanford
  NLP / Databricks-backed. v3.2.1 mei 2026. Productie: JetBlue (2× sneller
  RAG-deploy), Shopify, Dropbox, Moody's, AWS, Sephora, VMware, Cursor,
  Mistral.
* **Hergebruik:** Via LiteLLM óf via custom `BaseLM` met capability-flags.
  MLflow 3.0 native tracing.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | - | Signatures/Optimizers/Adapters; expliciete leercurve |
  | Herbruikbaarheid | + | Optimizers herbruikbaar; metrics blijven van toepassing bij modelwissel |
  | Operationele kosten | +/- | Compile-step kost minuten tot uren in tokens; runtime is goedkoop |
  | Risico | - | PyPI "Alpha"-label ondanks productie-gebruik; 2.x→3.x bracht breaking changes |
  | Fit met principes | + | Optimizer-paradigm past "meten, niet gokken"-mindset |
  | `module-llm.chat`-fit | **++** | Uniek: subclass `BaseLM`, `supports_function_calling=False`, tekst-adapters doen de rest |

* **Wanneer geschikt:** Patroon #3 (evaluation loop) en multi-stage
  pipelines met een meetbare metric. **Het enige framework dat
  structureel goed op `module-llm.chat` past** — DSPy gaat ervan uit
  dat de LM een completion-box is.

#### Mirascope

* **Beschrijving:** "Anti-framework" Pydantic-native LLM-SDK met
  decorator-API. Geen graph-DSL, geen state-machine. v2.4.0 maart
  2026. Klein (~1.5k stars) maar actief; commercieel platform Lilypad
  als observability-SaaS.
* **Hergebruik:** Brede provider-pool; LiteLLM als meta-provider;
  Logfire/Langfuse integratie.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | + | Decorator-API; geen agent-loop verplicht |
  | Herbruikbaarheid | +/- | Klein ecosysteem; minder productie-cases |
  | Operationele kosten | + | Dunne laag; nauwelijks overhead |
  | Risico | - | Klein team, 1.5k stars, productie-track record dun |
  | Fit met principes | + | Pydantic-native; weinig magie |
  | `module-llm.chat`-fit | - | Bare `@llm.call` werkt, maar structured output / tools / streaming vallen weg |

* **Wanneer geschikt:** Patronen #1/#2 wanneer het team expliciet
  géén framework wil maar wel Pydantic-ergonomie. Pydantic-AI is
  bijna altijd de betere keuze tenzij anti-framework-positie een
  expliciete eis is.

#### Cluster-uitspraak

| Patroon | Aanbevolen | Notitie |
|---------|-----------|---------|
| #3 evaluation loop (metric-driven) | DSPy | Enige met offline optimizer; werkt via module-llm |
| #4 single agent + tools (typed) | Pydantic-AI | Default; vereist direct SDK |
| structured output zonder agent-loop | Mirascope of Pydantic-AI | Beide werken; PA bredere community |

### Cluster 3 — Multi-agent

> **Belangrijke 2026-context.** Microsoft heeft AutoGen + Semantic
> Kernel geconsolideerd tot **Microsoft Agent Framework (MAF) 1.0**
> (GA 3 april 2026). AutoGen is in maintenance-mode (alleen security
> + bugfix); SK krijgt onderhoud maar geen nieuwe investering. Voor
> greenfield werk in 2026 is AutoGen een footgun.

#### CrewAI

* **Beschrijving:** Role-based multi-agent ("Crews") + event-driven
  workflows ("Flows"). Onafhankelijk van LangChain. 52.6k stars,
  v1.14.6 mei 2026. Powers "12M+ daily agent executions in productie"
  (marketing-claim). Gebruikers: Docusign, Piracanjuba.
* **Hergebruik:** LiteLLM onder de motorkap; YAML-driven agent-config;
  ingebouwde memory (ChromaDB/LanceDB) — let op: lokaal storage werkt
  niet transparant in multi-instance deploys.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | + | YAML-config; lage on-ramp |
  | Herbruikbaarheid | + | Patroon (researcher/writer/reviewer) herbruikbaar tussen apps |
  | Operationele kosten | - | ~18% token-overhead vs LangGraph; debugging opaak bij 5+ agents |
  | Risico | + | Productie-adoptie, MIT, actief onderhoud |
  | Fit met principes | + | Helder rol-decompositie-model; memory-backend opt-in |
  | `module-llm.chat`-fit | - | Tool-use + structured output zijn load-bearing; degradeert sterk |

* **Wanneer geschikt:** Patroon #6 wanneer de taak natuurlijk in 2–5
  rollen ontbindt en het team rapid-prototyping waardeert. **De enige
  serieuze niet-Microsoft optie voor role-based multi-agent.**

#### AutoGen (vermelding ter completeness)

* **Status 2026:** Maintenance-only. v0.7.5 sept 2025 was de laatste
  feature-release; backlog van 533 open issues groeit zonder triage.
  Microsoft wijst greenfield projecten naar MAF.
* **Verdict:** **Niet aanbevelen voor nieuw werk.** Alleen relevant
  als de klant een bestaande AutoGen-codebase heeft, met
  migratie-plan richting MAF in 2026.

#### Semantic Kernel

* **Beschrijving:** Microsoft's enterprise plugin/agent-orchestratie
  SDK (C#, Python, Java). Sterk in .NET; banner zegt expliciet
  "Semantic Kernel is now Microsoft Agent Framework". Productie:
  KPMG, Fujitsu.
* **Hergebruik:** Brede provider-matrix; Azure-integratie first-class.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | - | Kernel/Plugin/ChatHistory/Connector-lagen; learning curve |
  | Herbruikbaarheid | + | Plugin-as-tool-paradigm, brede provider-pool |
  | Operationele kosten | +/- | Geen specifieke overhead-metric, .NET DI is overhead bij Python-gebruik |
  | Risico | - | Officieel "opgevolgd" door MAF; greenfield-investering verdampt |
  | Fit met principes | + | Sterk type-safety op C#; .NET-shops zijn de sweet spot |
  | `module-llm.chat`-fit | - | Plugin-calling vereist tool-use bij provider; degradeert |

* **Wanneer geschikt:** Bestaande SK-codebases, .NET/Java enterprise.
  Voor greenfield Druppie-apps: vrijwel altijd MAF de betere keuze.

#### Microsoft Agent Framework (MAF) — opvolger

* **Beschrijving:** GA 3 april 2026. Same DI/Kernel-ergonomie als SK,
  plus AutoGen's multi-agent patronen (Magentic-One, GroupChat,
  Sequential, Concurrent, Handoff). Native MCP + A2A protocol. DevUI
  browser-debugger. OpenTelemetry-native.
* **Hergebruik:** Foundry/Azure-integratie first-party;
  IChatClient-abstractie maakt provider-swap één regel.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | - | Erft SK-lagen + AutoGen-patterns |
  | Herbruikbaarheid | + | MCP + A2A native; foundry/azure first-party |
  | Operationele kosten | +/- | Onbekend lange-termijn productie-profiel (jong product) |
  | Risico | +/- | Jong (GA april 2026); 10.9k stars; "early adopter"-fase |
  | Fit met principes | + | Microsoft long-term commitment helder; sterk type-safety |
  | `module-llm.chat`-fit | - | Tool-use + multi-turn vereist |

* **Wanneer geschikt:** Patroon #6 wanneer de klant op Azure
  Foundry / .NET-stack zit. Vermijd voor andere stacks tenzij er een
  expliciete reden is.

#### Cluster-uitspraak

| Patroon | Aanbevolen | Notitie |
|---------|-----------|---------|
| #6 multi-agent, Python | CrewAI | Default voor niet-Microsoft stacks |
| #6 multi-agent, Microsoft/.NET | MAF | Niet AutoGen, niet SK voor greenfield |
| #6 multi-agent op `module-llm.chat` | **geen framework — herontwerp naar #4** | Industrie-consensus: vermijd premature multi-agent |

### Cluster 4 — Provider-native / Lightweight

#### Claude Agent SDK

* **Beschrijving:** Anthropic's officiële agent-loop SDK; embedt dezelfde
  loop, ingebouwde tools (Read/Write/Edit/Bash/Glob/Grep/WebSearch/...)
  en context-management die Claude Code aandrijven. Python v0.2.87
  (mei 2026). Hard gekoppeld aan Anthropic.
* **Hergebruik:** Anthropic API, Bedrock, Vertex, Azure Foundry — allemaal
  Anthropic-modellen. Andere providers alleen via translating gateways
  (Bifrost, LiteLLM, Portkey) en die zijn fragiel.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | + | Eén `query()`-call; subagents via `Agent`-tool |
  | Herbruikbaarheid | -- | Vendor-lock op Anthropic |
  | Operationele kosten | +/- | Streaming-only; Anthropic-pricing |
  | Risico | - | Python-PyPI status nog "Alpha"; 15 juni 2026 billing/model-cutover |
  | Fit met principes | -- | Tegen "standaard voor maatwerk" als de app niet Anthropic-native is |
  | `module-llm.chat`-fit | -- | Onmogelijk — spreekt Anthropic Messages API, niet module-llm |

* **Wanneer geschikt:** Wanneer de applicatie **ís** een Anthropic-agent
  (Claude Code-stijl autonomous coder/operator) en provider-lock-in
  acceptabel is. Niet de keuze voor generieke in-app workflows op
  Druppie-stack.

#### LlamaIndex Workflows

* **Beschrijving:** Event-driven async-first step-compositie. `@step`
  async-functies, `Event`-subclasses, typed `Context`. Workflows 1.0
  GA mid-2025; standalone `llama-index-workflows` package, MIT.
  Pythonischer dan LangGraph; ~6ms framework-overhead vs ~14ms; ~1.6K
  token-overhead vs ~2.4K.
* **Hergebruik:** Brede provider-pool (~300 integration packages);
  `FunctionAgent` (vereist function-calling) en `ReActAgent`
  (prompt-based, geen function-calling nodig). `AgentWorkflow` voor
  multi-agent met handoff.
* **Voor- en nadelen:**

  | Aspect | Score | Toelichting |
  |--------|-------|-------------|
  | Complexiteit | +/- | Event-routing is impliciet; debuggen vraagt instrumentatie |
  | Herbruikbaarheid | + | Provider-portabel; LlamaCloud/AgentCore-deploy beschikbaar |
  | Operationele kosten | + | Lichtste framework-overhead in z'n klasse |
  | Risico | + | 1.0-stabilisatie, MIT, actief 100+ commits/90 dagen |
  | Fit met principes | + | Pydantic-native; OpenTelemetry first-class |
  | `module-llm.chat`-fit | **+** | Plain `@step` + `ReActAgent` werken; `FunctionAgent`/multi-agent vereist direct SDK |

* **Wanneer geschikt:** Patronen #2, #3, #5 en lichte #6 wanneer
  provider-portabiliteit + observability + Pydantic-typing belangrijk
  zijn. **Het enige multi-step framework dat een werkbaar pad biedt
  via `module-llm.chat`** (mits men bij ReAct-style agents blijft).

#### Cluster-uitspraak

| Patroon | Aanbevolen | Notitie |
|---------|-----------|---------|
| Anthropic-native autonomous agent | Claude Agent SDK | Alleen als app = Anthropic-agent |
| #2 / #3 / #5 met provider-portabiliteit | LlamaIndex Workflows | Lichter dan LangGraph; werkt deels via module-llm |
| Multi-agent (lichte) | LlamaIndex AgentWorkflow | Voor zwaardere durable workflows: LangGraph |

## Druppie-specifieke Lens

### `module-llm.chat`-compatibiliteits-matrix

Dit is de bepalende as voor de keuze, en is uniek voor Druppie:

| Framework | Werkt op `module-llm.chat`? | Verlies bij gebruik | Aanbeveling |
|-----------|----------------------------|---------------------|-------------|
| **Plain Python** | ✅ Native | Niets — design-point | Gebruik |
| **DSPy** | ✅ Native (uniek) | Niets — paradigma sluit aan | Gebruik voor #3 |
| **LangChain LCEL** | ✅ Lineair OK | Tool-use, structured output via function-calling | Gebruik voor #2 |
| **LlamaIndex Workflows** | 🟡 Deels | `FunctionAgent` + multi-agent vallen weg; `ReActAgent` werkt | Gebruik voor #2/#3/#5 met ReAct |
| **Mirascope** | 🟡 Bare-only | Structured output, tools, streaming | Direct SDK |
| **LangGraph** | ❌ Niet zinnig | 80% van waarde (tool-use, streaming, agentic loops) | Direct SDK of vermijd |
| **Pydantic-AI** | ❌ Niet zinnig | Typed agent loop, A2A, structured output | Direct SDK |
| **CrewAI** | ❌ Niet zinnig | Tool-use, structured output, streaming chunks | Direct SDK |
| **AutoGen / SK / MAF** | ❌ Niet zinnig | Tool-use, multi-turn, plugin-calling | Direct SDK |
| **Claude Agent SDK** | ❌ Onmogelijk | Spreekt Anthropic Messages API, niet module-llm | Direct Anthropic |

**Gevolg voor de skill:** De keuze is niet eerst "welk framework", maar
eerst "hoe komen we aan de LLM?". Als de app door `module-llm.chat`
moet, valt de helft van de kandidaten af.

### Scheidslijn Druppie-agent vs in-app LLM-workflow

| Aspect | Druppie-agent | In-app LLM-workflow |
|--------|---------------|---------------------|
| Wie bouwt | Druppie-platformteam | Klant-applicatie |
| Code-locatie | `druppie/agents/definitions/*.yaml` + Orchestrator | Bínnen de gegenereerde app |
| Runtime | Druppie Orchestrator + ToolExecutor | Eigen control flow + framework-keuze |
| Governance | Approvals, HITL, role-based MCP permissies, audit | App regelt zelf logging/auth/errors |
| Tool-toegang | MCP-tools via tool_executor | Direct LLM-call (module-llm of provider) |
| Activatie | Planner scheduled hem | Endpoint of batch-job in de app |
| Skill-trigger | `module-convention` | **`llm-orchestration-in-apps` (deze)** |

**De skill geldt alléén voor de rechter kolom.** Een nieuwe Druppie-agent
bouwen is geen scope van deze skill.

### Capability-gap analyse `module-llm`

Wat zou `module-llm` moeten bieden om elke framework-keuze structureel
te dragen?

| Capability | `module-llm.chat` vandaag | Vereist voor |
|------------|--------------------------|--------------|
| Streaming (token-stream) | ❌ | LangGraph (UX), Claude SDK, Pydantic-AI streaming, CrewAI streaming |
| Tool-use / function-calling | ❌ | Pydantic-AI, LangGraph, CrewAI, MAF, Claude SDK, LlamaIndex `FunctionAgent` |
| Structured output (JSON-schema/mode) | ❌ | Pydantic-AI `output_type`, CrewAI `output_pydantic` |
| Multi-turn message history | ❌ | Alle agent-frameworks (essentieel voor multi-step state) |
| Vision (image inputs) | ❌ | Multimodal agents |
| Async streaming events | ❌ | AutoGen actor-model, LangGraph token streaming |

→ **Strategische optie:** `module-llm` uitbreiden tot een rijke "in-app
LLM client" met deze capabilities. Dat opent Pydantic-AI / LangGraph
/ MAF / CrewAI / LlamaIndex `FunctionAgent` voor in-app gebruik via
de platform-bouwsteen. **Maar:** dit is een platform-roadmap-beslissing,
geen skill-beslissing. De skill blijft daarom agnostisch: zegt wat
elk framework vereist, laat de architect kiezen tussen "via module-llm
(beperkt)" en "direct SDK (vol)".

## Cross-framework Comparison Matrix

| Framework | Stars (2026) | Status | Paradigma | Multi-agent | Type-safety | OTel | `module-llm`-fit |
|-----------|--------------|--------|-----------|-------------|-------------|------|------------------|
| Plain Python | n.v.t. | stabiel | imperatief | manueel | Pydantic direct | DIY | ✅ native |
| LangChain LCEL | 138k | 1.0 stable | pipe-chains | nee | Pydantic-parsers | + | ✅ lineair |
| LangGraph | 33.6k | 1.0 LTS | graph + state | native | TypedDict | ++ (LangSmith) | ❌ |
| Pydantic-AI | 17.4k | V1 stable | agent-loop | A2A | Pydantic ++ | ++ (Logfire) | ❌ |
| DSPy | 34.8k | 3.x (alpha-label) | declaratief + optimizer | compositie | type-hints | ++ (MLflow) | ✅ **uniek** |
| Mirascope | 1.5k | 2.x | decorator-API | compositie | Pydantic + | + (Logfire/Langfuse) | 🟡 |
| CrewAI | 52.6k | 1.x | role-based + flows | native | Pydantic + | ++ | ❌ |
| AutoGen | 58.6k | **maintenance** | actor-model | native | Pydantic | ++ | ❌ |
| Semantic Kernel | 28k | "opgevolgd" | kernel+plugins | sub-module | Pydantic/.NET ++ | ++ | ❌ |
| MAF | 10.9k | 1.0 GA apr 2026 | kernel + AutoGen-patterns | native | Pydantic/.NET ++ | ++ | ❌ |
| Claude Agent SDK | 7.1k Py + 1.5k TS | 0.2/0.3 (alpha) | Claude-loop | hierarchisch | TypedDict | + (opt-in) | ❌ |
| LlamaIndex Workflows | 386 (sep.) + 49.8k (umbrella) | 1.0 stable | event-driven | AgentWorkflow | Pydantic ++ | ++ (Phoenix/LlamaTrace) | 🟡 |

## Beslissingsgids per patroon

> Lees deze tabel met `module-llm.chat` (default vandaag) als eerste
> overweging. "Vereist direct SDK" betekent: framework werkt structureel
> niet via `module-llm.chat`; provider-keuze is dan een aparte
> beslissing in de TD.

| Patroon | Voorbeeld | Default (via module-llm) | Alternatief (direct SDK) | Vermijd |
|---------|-----------|--------------------------|-------------------------|---------|
| #1 single-shot | "Vat ticket samen" | Plain Python | — | Elke framework |
| #2 sequential | draft → check → edit | Plain Python | LangChain LCEL | LangGraph (overkill) |
| #3 evaluation loop | nightly gold-set, metric-driven | DSPy | DSPy + direct SDK | LangGraph (overkill) |
| #4 single agent + tools | "vergunning-checker" | **niet werkbaar** — vereist tool-use | Pydantic-AI (default) | CrewAI multi-agent (premature) |
| #5 stateful durable | meerdaagse approval-flow | **niet werkbaar** — vereist persistente state + tool-use | LangGraph (durable) of LlamaIndex Workflows (lichter) | Plain Python (herbouwt LangGraph slecht) |
| #6 multi-agent | researcher + writer + reviewer | **niet werkbaar** + sterk afgeraden voor v1 | CrewAI (Python) / MAF (Microsoft) | AutoGen (maintenance), SK greenfield |

### Q8 — Archetype-denken (zoals RAG LS/HS/B)?

**Verdict: nee, niet voor LLM-orchestratie.** Voor RAG werkt LS/HS/B
omdat het quality-archetype direct numerieke NFR-targets stuurt
(faithfulness, citation precision, hallucinatie). Voor LLM-orchestratie
ligt de structurele keuze in het **workflow-patroon** (#1–#6), niet in
een quality-archetype. Een chat-bot kan #1 én #4 zijn; een nightly
digest kan #3 zijn ongeacht latency-strakheid. De skill positioneert
daarom patronen, geen archetypes.

## Aanbeveling

* **Default-positie voor in-app LLM-workflows in 2026:** Plain Python +
  `module-llm.chat`. Reach for a framework alleen als het workflow-patroon
  expliciet voorbij lineair gaat (patroon #5 of #6) **én** een direct
  SDK acceptabel is.

* **Pattern → framework mapping voor de skill** (kort):
  1. Single-shot of evaluation loop → **Plain Python** (DSPy als er een
     meetbare quality-metric is en optimalisatie waarde toevoegt).
  2. Sequential chain → **Plain Python** (LCEL alleen als al in gebruik).
  3. Single agent + tools → **Pydantic-AI** (default) + direct SDK.
  4. Stateful durable workflow → **LlamaIndex Workflows** (lichter) of
     **LangGraph** (zwaarder, durable execution) + direct SDK.
  5. Multi-agent (genuine specialisatie + capacity-saturatie aangetoond)
     → **CrewAI** (Python-stack) of **MAF** (Microsoft-stack) +
     direct SDK.
  6. Anthropic-only autonomous agent → **Claude Agent SDK**.

* **`module-llm.chat` vs direct SDK** is een per-project keuze met
  trade-off: governance/consistentie/data-soevereiniteit (via module-llm)
  versus framework-features (via direct SDK). De skill verplicht niets,
  legt de keuze expliciet voor.

* **Multi-agent-defensief**: de skill duwt actief richting patroon #4
  (single agent + tools) tenzij de FD expliciet rolverdeling, parallel
  verification of context-window saturation noemt. 2026-consensus is
  helder: orchestrator-worker is het overlevende multi-agent patroon,
  en premature multi-agent is een industrie-anti-pattern.

### Afgeleide beslissingen voor TDs

In een TD die deze skill toepast, hoort kort vermeld:

1. Welk **patroon** (#1–#6) past op de in-app LLM-workflow.
2. Welk **framework** (of plain Python) is gekozen + één-regel
   onderbouwing.
3. **Access-pattern** (via `module-llm.chat` of direct SDK) + reden.
4. **Eventuele NFRs** specifiek voor deze workflow (latency-budget,
   fallback bij LLM-failure, retry-policy, max-iteraties bij agent-loop).
5. **Open evaluatie**: hoe weten we of deze keuze klopte (metric +
   bron).

Geen TR-LLM-XX dump van twaalf rijen — compact en project-specifiek.

### Open vragen / aannames

* **Platform-roadmap:** wordt `module-llm` uitgebreid (streaming,
  tool-use, structured output)? Zo ja, verandert de
  `module-llm`-compatibiliteits-tabel structureel en kunnen
  Pydantic-AI / LangGraph / MAF voortaan via de platform-bouwsteen.
  Skill is bewust agnostisch op dit punt — herzien bij elke
  `module-llm`-versie-bump.
* **Provider-strategie:** Z.AI/DeepInfra (vandaag) versus Foundry
  versus lokaal vLLM/Ollama is platform-config; de skill is
  provider-agnostisch.
* **DSPy alpha-label:** PyPI staat nog op "Development Status: 3 -
  Alpha" ondanks productie-gebruik bij JetBlue/Shopify/Databricks.
  Geen blocker; wel een notitie in de skill.
* **MAF-volwassenheid:** GA april 2026, jong product. Voor
  Microsoft-stacks aanbevolen boven SK/AutoGen, maar realistische
  productie-track-record komt pas H2 2026.

## Bronnen (selectie)

### Frameworks
* LangChain / LangGraph 1.0 GA — <https://blog.langchain.com/langchain-langgraph-1dot0/>
* LangGraph docs — <https://github.com/langchain-ai/langgraph>
* Pydantic-AI — <https://ai.pydantic.dev/>, <https://github.com/pydantic/pydantic-ai>
* DSPy — <https://dspy.ai/>, <https://github.com/stanfordnlp/dspy>
* Mirascope — <https://mirascope.com/>, <https://github.com/Mirascope/mirascope>
* CrewAI — <https://docs.crewai.com/>, <https://github.com/crewAIInc/crewAI>
* AutoGen (maintenance) — <https://github.com/microsoft/autogen>
* Semantic Kernel — <https://learn.microsoft.com/en-us/semantic-kernel/>
* Microsoft Agent Framework — <https://learn.microsoft.com/en-us/agent-framework/>
* Claude Agent SDK — <https://code.claude.com/docs/en/agent-sdk/overview>
* LlamaIndex Workflows — <https://www.llamaindex.ai/blog/announcing-workflows-1-0-a-lightweight-framework-for-agentic-systems>

### Industrie-analyses 2026
* "How I Built an AI Orchestration Engine Without LangChain in 2026" — <https://www.roborhythms.com/how-to-build-ai-orchestration-without-langchain-2026/>
* Anthropic engineering — Effective harnesses for long-running agents — <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
* Databricks DSPy + JetBlue case study — <https://www.databricks.com/blog/optimizing-databricks-llm-pipelines-dspy>
* Multi-agent benchmark — <https://dev.to/ottoaria/multi-agent-ai-in-2026-build-production-systems-with-crewai-langgraph-autogen-5e40>
* Alice Labs 2026 framework ranking — <https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026>
* "Lessons learnt from upgrading to LangChain 1.0 in production" — <https://towardsdatascience.com/lessons-learnt-from-upgrading-to-langchain-1-0-in-production/>
* "We ditched LangChain" — <https://medium.com/@larklaflamme/we-ditched-langchain-heres-what-we-built-instead-and-why-it-s-better-for-serious-ai-research-292d4265dde8>

### Gerelateerde platformdocs
* `docs/CODEBASE_STRUCTURE.md` — Druppie agent-stack en LangGraph-runtime
* `druppie/mcp-servers/module-llm/v1/tools.py` — huidige `module-llm.chat` interface
* `druppie/skills/technical-design-format/SKILL.md` — TD-format
* `druppie/skills/technical-research-format/SKILL.md` — research-format
