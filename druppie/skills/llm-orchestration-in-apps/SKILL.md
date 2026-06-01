---
name: llm-orchestration-in-apps
description: >
  This skill should be used when designing an application that contains
  multi-step LLM workflows inside the built app itself — chains,
  evaluation loops, agents with tools, stateful/durable workflows, or
  multi-agent systems. It positions in-app LLM workflows as a legitimate
  building block (distinct from Druppie's own agent stack) and provides
  a decision-guide between plain Python, LangGraph, Pydantic-AI, DSPy,
  CrewAI, MAF, Claude Agent SDK, and LlamaIndex Workflows.
---

# LLM Orchestration in Built Apps

When a Druppie-built application contains its **own** LLM workflow —
not just calling out to a Druppie-agent, but running multi-step LLM
logic inside the app — the architect needs an explicit framework
choice. Without that choice, the team falls back to "use what we
know" and either over-engineers (LangGraph for a `for`-loop) or
under-engineers (Python spaghetti for what wants to be an agent).

## Scope — Druppie-agent vs in-app LLM-workflow

| Aspect | Druppie-agent | In-app LLM-workflow |
|---|---|---|
| Who builds | Druppie platform team | The customer application |
| Code location | `druppie/agents/definitions/*.yaml` + Orchestrator | Inside the generated app |
| Runtime | Druppie Orchestrator + ToolExecutor | App's own control flow + framework choice |
| Governance | Approvals, HITL, role-based MCP permissions, audit | App handles its own logging/auth/errors |
| Tool access | MCP-tools via tool_executor | Direct LLM-call (`module-llm.chat` or provider SDK) |
| Activation | Scheduled by the planner | Called by an app endpoint or batch job |
| Skill triggers | `module-convention` skill | **This skill** |

**This skill applies only to the right column.** If the user is asking
for a new Druppie agent (a new platform role like "summarizer-agent"),
that is a different design — use `module-convention` instead.

## When to invoke this skill

Trigger on these signals in the FD:
- **Chains**: "draft → check → edit", "extract → classify → enrich"
- **Evaluation loops**: nightly digest scoring, gold-set runs,
  iterative quality checks
- **Agentic patterns**: the app gives an LLM tools and lets it decide
  what to call (search, fetch, validate, persist)
- **Stateful workflows**: multi-day approval flows, HITL pauses,
  resumable state machines
- **Multi-agent**: explicit role decomposition (researcher + writer +
  reviewer), parallel verification, agent handoffs

**Do not invoke** for:
- A single LLM call ("summarise this ticket") — no framework choice
  to make; just call `module-llm.chat`.
- RAG-only workflows — use the `rag-patterns` skill instead.
- New Druppie agents — use `module-convention` instead.

## Workflow patterns

The pattern — not the use-case domain — determines the framework.

| # | Pattern | Example | Characteristic |
|---|---------|---------|----------------|
| 1 | Single-shot | "Summarise this ticket" | One prompt → one answer. No state, no order. |
| 2 | Sequential chain | draft → check → edit | Fixed step order, linear, no branching. |
| 3 | Evaluation loop | nightly gold-set scoring | `for sample in dataset: call → judge → log`. Metric-driven. |
| 4 | Single agent + tools | "permit-checker" with validation tools | One agent, multiple tools, ReAct-style loop. |
| 5 | Stateful / durable | multi-day approval flow with HITL pause | Persistent state, pause/resume, conditional branching. |
| 6 | Multi-agent | researcher + writer + reviewer | Multiple agents with roles, handoff or orchestrator-worker. |

**2026 consensus:** pattern #4 is the surviving default for multi-step
work. Multi-agent (#6) costs 58–285% more tokens in production and
degrades quality on benchmarks when applied prematurely. **Default to
#4; escalate to #6 only with measured single-agent saturation.**

## The defining axis — `module-llm.chat` vs direct SDK

Today's `module-llm.chat` is **single prompt → single answer**, no
streaming, no tool-use, no structured output, no multi-turn history.
This makes the access-pattern decision structural — not all frameworks
work through it.

| Framework | Works on `module-llm.chat`? | What you lose |
|-----------|----------------------------|---------------|
| Plain Python | ✅ Native | Nothing — design point |
| DSPy | ✅ Native (unique) | Nothing — paradigm fits |
| LangChain LCEL | ✅ Linear only | Tool-use, structured output |
| LlamaIndex Workflows | 🟡 Partial | `FunctionAgent`/multi-agent need SDK; `ReActAgent` + `@step` work |
| LangGraph / Pydantic-AI / CrewAI / MAF | ❌ | ~80% of the value (agentic loop, streaming, tool-use) |
| Claude Agent SDK | ❌ | Wire-format incompatible — speaks Anthropic Messages API |

**Implication:** decide first **how the app reaches an LLM**, then pick
the framework. State this choice explicitly in the TD with the reason
(governance/consistency via `module-llm`, framework features via
direct SDK).

## Decision guide — pattern → framework

| Pattern | Default (via `module-llm`) | Alternative (direct SDK) | Avoid |
|---------|----------------------------|--------------------------|-------|
| #1 single-shot | **Plain Python** | — | Any framework (overhead) |
| #2 sequential | **Plain Python** | LangChain LCEL (only if already in use) | LangGraph (overkill) |
| #3 evaluation loop | **Plain Python** (DSPy if a quality metric drives the design) | DSPy + direct SDK | LangGraph (overkill) |
| #4 single agent + tools | not feasible — requires tool-use | **Pydantic-AI** (default) | CrewAI/MAF (premature multi-agent) |
| #5 stateful durable | not feasible — requires persistent state + tool-use | **LlamaIndex Workflows** (light) or **LangGraph** (heavy, durable execution) | Plain Python (rebuilds LangGraph badly) |
| #6 multi-agent (justified) | not feasible + strongly discouraged for v1 | **CrewAI** (Python stack) or **MAF** (Microsoft/.NET stack) | AutoGen (maintenance), Semantic Kernel (greenfield) |
| Anthropic-native autonomous | — | **Claude Agent SDK** | Anywhere a portable provider matters |

## Stop — do not reinvent the orchestrator

If the workflow shape calls for a framework, use one of the choices
above instead of building a half-baked custom state-machine. The 80-line
"plain Python orchestrator" is a defended position **for patterns #1–#3
and simple variants of #4**, not for genuine durable agentic workflows.

Equally: if the workflow is one prompt → one answer, do **not** reach
for LangGraph "because we may need it later." Add the framework when
the workflow actually grows past linear control flow.

## Framework picks at a glance

| Framework | Sweet spot | Status (2026) |
|-----------|------------|---------------|
| **Plain Python** | Patterns #1–#3; simple #4 | Always available; industry default for the 80% case |
| **LangChain LCEL** | Linear pipelines with output parsers | 1.0 stable; legacy chains EOL Dec 2026 |
| **LangGraph** | Durable stateful workflows; complex multi-agent | 1.0 LTS; production-proven |
| **Pydantic-AI** | Type-safe single agent with tools | V1 stable; V2 beta (H2 2026) |
| **DSPy** | Metric-driven multi-stage pipelines | 3.x; PyPI still flags "Alpha" despite production use |
| **CrewAI** | Role-based multi-agent (non-Microsoft) | 1.x stable |
| **MAF** | Multi-agent on Microsoft/.NET/Foundry | 1.0 GA April 2026 |
| **Claude Agent SDK** | App = autonomous Anthropic agent | 0.x; Python still alpha-labelled |
| **LlamaIndex Workflows** | Event-driven multi-step with provider portability | 1.0 stable; lighter than LangGraph |
| **AutoGen** | — | **Maintenance only; do not pick for greenfield** |
| **Semantic Kernel** | Existing SK codebases only | Officially superseded by MAF for new work |
| **Mirascope** | Anti-framework Pydantic ergonomics, single calls | Small community; Pydantic-AI is usually better |

## How to land this in a TD

Keep this **compact** — one subsection in the architectural solution,
not a takeover.

1. **Workflow pattern**: state which of #1–#6 the in-app LLM workflow
   matches, in one sentence.
2. **Framework choice**: framework (or plain Python) + one-line
   rationale tied to the pattern.
3. **Access pattern**: via `module-llm.chat` or direct SDK + reason
   (governance/consistency vs framework features).
4. **Workflow-specific NFRs** (only when they actually drive design):
   end-to-end latency budget, fallback on LLM failure, retry policy,
   max iterations for agent loops.
5. **Evaluation hook**: how will the team know the choice was right
   (one sentence — metric + source).

Do **not** produce a 12-row TR-LLM-XX dump in the Requirements table.
Keep LLM-orchestration specifics inside this subsection.

## Anti-patterns to catch in a design

- **"We use LangGraph"** without naming the pattern, the state shape,
  or why a `for`-loop wouldn't do. Under-specified — request the pattern
  and the durability requirement.
- **Multi-agent for a problem that fits in a single context window**
  with 1–2 tools. SWE-bench Verified shows degradation up to 19% on
  centralized multi-agent for tasks single-agent already saturates.
- **Routing LangGraph / Pydantic-AI / CrewAI through `module-llm.chat`**
  — you pay the framework cost for ~20% of the value. Either commit to
  a direct SDK or pick a framework that actually fits the chat-only
  contract (DSPy, LlamaIndex Workflows with `@step`+ReAct, plain Python).
- **Picking AutoGen for greenfield in 2026** — Microsoft moved investment
  to MAF; AutoGen receives only bug fixes.
- **Custom durable state machine** ("we'll just persist to Postgres
  between steps") when the workflow is genuinely #5 — you are rebuilding
  LangGraph's checkpointer. Pick the framework instead.
- **Claude Agent SDK as a generic LLM framework** — it's vendor-locked
  to Anthropic; only choose when the app is *meant* to be an Anthropic
  agent.

## References

- Research foundation with the full per-framework comparison, sources,
  and 2026 industry developments:
  [`docs/LLM-orchestration/llm-orchestration-in-apps.md`](../../../docs/LLM-orchestration/llm-orchestration-in-apps.md)
- `module-llm` interface (current `chat` tool):
  [`druppie/mcp-servers/module-llm/v1/tools.py`](../../mcp-servers/module-llm/v1/tools.py)
- Druppie agent stack (contrast — *not* in scope for this skill):
  [`druppie/execution/orchestrator.py`](../../execution/orchestrator.py)
