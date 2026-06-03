---
name: llm-orchestration-standard
description: >
  This skill should be used by the builder_planner when a technical design
  describes an in-app LLM workflow (chain, evaluation loop, single agent
  with tools, durable workflow, or multi-agent). It defines the ONE
  platform standard for how Druppie-generated apps build in-app LLM logic —
  one baseline, one agent library, one access-pattern default — plus the
  decision for WHERE the code lives. It turns the architect's pattern +
  agency decision into a concrete, standardised implementation plan.
---

# LLM Orchestration — Platform Standard (Builder Planner — HOW)

The architect has already decided the WHAT: the workflow pattern (#1–#6),
the agency level (LLM + UI / single agent / multi-agent), and where the
capability should live. This skill is the builder_planner's HOW: turn that
into a concrete plan using **one** standard, so every generated app is
built the same way and stays easy to maintain, review, and understand.

The goal is standardisation, not a framework beauty contest. There is one
default way to build in-app agents. Deviating from it requires an explicit,
written justification in the build plan.

## The one standard

| Architect's agency decision | Standard implementation | Access to the LLM |
|---|---|---|
| **LLM + UI baseline** (patterns #1–#2) | **Plain Python** — a direct call plus a UI gate (Approve/Reject/edit). No framework. | `module-llm.chat` |
| **Sequential chain / evaluation loop** (#2–#3) | **Plain Python** — explicit functions/steps, a `for`-loop for evaluation. No framework. | `module-llm.chat` |
| **Single agent + tools** (#4) | **Pydantic-AI** — one typed agent, tools as typed functions, ReAct-style loop. *(Proposed standard — confirm with the platform team.)* | Direct provider SDK *(until module-llm exposes tool-use — see v2 handoff)* |
| **Durable / multi-agent** (#5–#6) | **Escalation — not pre-blessed.** Requires a deliberate platform decision before building; do not silently pick a new framework per project. Flag it and get the standard set first. | n/a |

Two libraries cover the overwhelming majority of in-app work: **plain
Python** for everything linear, **Pydantic-AI** for the single agent with
tools. Anything beyond (durable execution, genuine multi-agent) is rare
and must be standardised deliberately — not chosen ad hoc.

## Access pattern — default to the platform building block

- **Default: `module-llm.chat`.** Prefer the platform module for
  governance, consistency, audit, and provider/data sovereignty. It fits
  every plain-Python pattern (#1–#3).
- **Direct provider SDK only when required.** `module-llm.chat` is today
  single prompt → single answer (no tool-use, streaming, structured
  output, or multi-turn history). A single agent with tools (#4) therefore
  needs a direct SDK *today*. State this in the build plan with the reason.
- **This boundary will move.** If `module-llm` grows tool-use / structured
  output / multi-turn (the v2 handoff in the research doc), Pydantic-AI and
  friends can run through the platform module and the default widens. Treat
  the access-pattern as "module-llm unless it can't yet do it."

## Where the code lives (confirm the architect's placement)

The architect named a placement; the builder_planner confirms it and plans
the build accordingly:

1. **In the app (project-local)** — implement directly in the generated
   app. One-off, project-specific logic.
2. **Extend the project template** — add the pattern as a reusable,
   pre-defined example in the template. Recurs across projects but needs
   per-project adaptability and lives best close to the app.
3. **Evolve a module** — recurring + benefits from centralisation; grow an
   existing module (e.g. `module-llm`). This is a core-update build path,
   not project-local code.
4. **New module** — fundamentally distinct or broadly reusable capability.

If the architect's placement looks wrong from the build side (e.g. clear
cross-project reuse routed as project-local code), raise it rather than
silently building a one-off.

## Three worked examples

1. **Klacht-trieerder** — classify → validate → draft → quality-check.
   Pattern #2 (sequential chain). Agency: LLM + UI baseline (a human
   approves the draft). Standard: **plain Python** functions, one
   `module-llm.chat` call per step, a UI gate before send. Placement:
   in-app.
2. **Permit-checker** — an LLM that, given an application, decides which
   validation tools to run (rules lookup, zoning check, document fetch).
   Pattern #4 (single agent + tools). Standard: **Pydantic-AI**, tools as
   typed functions, direct provider SDK. Placement: in-app (project-local
   tools), unless the validation tools recur → extend the template.
3. **Ticket summariser** — one prompt → one answer shown to an agent.
   Pattern #1 (single-shot). Agency: LLM + UI. Standard: **plain Python**,
   a single `module-llm.chat` call. No framework, no agent.

## What to put in the build plan

- Library: plain Python **or** Pydantic-AI (or a flagged escalation).
- Access pattern: `module-llm.chat` **or** direct SDK + the one-line reason.
- Code placement: which of the four paths, matching the TD.
- Workflow NFRs the TD set (latency budget, LLM-failure fallback, retry
  policy, max agent iterations) — wire them into the plan.

## Anti-patterns

- **A different framework per project.** The point is one standard; per-app
  framework choices make the fleet unmaintainable.
- **A heavy framework for linear control flow** — LangGraph for a
  `for`-loop. Plain Python is the standard for #1–#3.
- **A custom durable state machine** for a genuine pattern #5 — escalate
  and standardise instead of rebuilding a checkpointer badly.
- **Routing an agent framework through `module-llm.chat`** today — you pay
  the framework cost for a fraction of the value; either use the direct SDK
  or stay on plain Python until module-llm v2 lands.

## References

- The architect's WHAT-side skill (pattern + agency + placement):
  `llm-orchestration-in-apps`.
- Research foundation, the full considered-alternatives survey, the
  module-llm capability gap, and the module-llm v2 handoff:
  [`docs/LLM-orchestration/llm-orchestration-in-apps.md`](../../../docs/LLM-orchestration/llm-orchestration-in-apps.md)
- `module-llm` interface (current `chat` tool):
  [`druppie/mcp-servers/module-llm/v1/tools.py`](../../mcp-servers/module-llm/v1/tools.py)
