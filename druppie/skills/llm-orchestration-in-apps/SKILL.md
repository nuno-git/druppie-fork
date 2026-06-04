---
name: llm-orchestration-in-apps
description: >
  This skill should be used by the architect when a functional design
  describes multi-step LLM logic INSIDE a generated application — chains,
  evaluation loops, agents with tools, stateful/durable workflows, or
  multi-agent systems. It helps the architect decide the WHAT: which
  workflow pattern applies and how much agency the problem actually
  needs. It does NOT name frameworks or libraries — that HOW-decision
  belongs to the builder_planner (see the `llm-orchestration-standard`
  skill) — and it does NOT re-derive capability placement, which is the
  architect's standard reuse decision framework applied to any capability.
---

# LLM Orchestration in Built Apps (Architect — WHAT)

When a Druppie-built application contains its **own** LLM workflow — not
just calling out to a Druppie agent, but running multi-step LLM logic
inside the app — the architect must decide **how much agency the problem
needs**. The architect names the *pattern* and the *structural shape*;
the builder_planner later picks the concrete library from the platform
standard. Where the capability lives (in-app / extend a module / new
module) is **not** decided here — it is the architect's standard reuse
decision framework, applied to this capability like any other.

This keeps the role boundary intact: the architect decides WHAT and WHY,
**never** names concrete frameworks or libraries in the TD.

## Scope (one line)

This skill is for an in-app LLM workflow (the app runs its own LLM logic);
it is **not** for building a new Druppie platform agent — that is
`module-convention`.

## When to invoke this skill

Trigger on these signals in the FD:
- **Chains**: "draft → check → edit", "extract → classify → enrich"
- **Evaluation loops**: nightly digest scoring, gold-set runs, iterative
  quality checks
- **Agentic patterns**: the app gives an LLM tools and lets it decide what
  to call (search, fetch, validate, persist)
- **Stateful workflows**: multi-day approval flows, HITL pauses, resumable
  state machines
- **Multi-agent**: explicit role decomposition (researcher + writer +
  reviewer), parallel verification, agent handoffs

**Do not invoke** for:
- A single LLM call ("summarise this ticket") — no orchestration decision
  to make; the app just calls `module-llm.chat`.
- RAG-only workflows — use the `rag-patterns` skill instead.
- New Druppie platform agents — use `module-convention` instead.

## Step 1 — Name the workflow pattern

The pattern — not the use-case domain — drives every downstream decision.

| # | Pattern | Example | Characteristic |
|---|---------|---------|----------------|
| 1 | Single-shot | "Summarise this ticket" | One prompt → one answer. No state, no order. |
| 2 | Sequential chain | draft → check → edit | Fixed step order, linear, no branching. |
| 3 | Evaluation loop | nightly gold-set scoring | `for sample in dataset: call → judge → log`. Metric-driven. |
| 4 | Single agent + tools | "permit-checker" with validation tools | One agent, multiple tools, ReAct-style loop. |
| 5 | Stateful / durable | multi-day approval flow with HITL pause | Persistent state, pause/resume, conditional branching. |
| 6 | Multi-agent | researcher + writer + reviewer | Multiple agents with roles, handoff or orchestrator-worker. |

State which pattern the FD matches in **one sentence**.

## Step 2 — The agency decision hierarchy

Standardisation beats per-project cleverness: the architect must resolve
the requirements against this hierarchy **in order** and stop at the first
rule that fits. The output is a *structural* decision (no-agent /
single-agent / multi-agent), not a library.

- **Rule 1 — Simplicity first.** Always design the simplest shape that
  satisfies the FD. Added agency is a cost (latency, tokens, failure
  modes, audit surface), not a feature. Justify any escalation explicitly.
- **Rule 2 — The "LLM + UI" baseline.** If the task is one LLM call
  followed by a simple human action (Approve / Reject / edit), **do not
  use an agent.** This is a direct LLM call plus a UI gate — patterns
  #1–#2. Most "AI features" land here.
- **Rule 3 — Introduce a single agent.** If the task needs multiple
  distinct actions or tool use beyond generate-and-approve — the LLM must
  decide *which* steps/tools to run — use **one agent with tools**
  (pattern #4). This is the default ceiling for non-trivial in-app work.
- **Rule 4 — Scale to multi-agent only on evidence.** Escalate to multiple
  agents (pattern #6) only when the FD shows **measured** single-agent
  saturation: the information volume exceeds a single context window, OR
  the problem genuinely needs distinct, concurrent domains of expertise.
  Premature multi-agent is an industry anti-pattern (higher cost, worse
  quality on benchmarks). Name the saturation evidence, or do not escalate.

> These rules are the starting hierarchy. Extend them with concrete,
> project-grounded thresholds as the platform learns — but keep them a
> *strict order*, not a menu.

## Capability placement is not an LLM decision

Where the capability lives — in-app, extend an existing module, or a new
module — is **not** specific to LLM workflows. It is the architect's
standard **reuse decision framework**, applied to an LLM capability
exactly as to any other (OCR, RAG, data-access, …). Do not re-derive an
LLM-flavoured version here: run the same generic placement decision the
architect makes for every capability, and state the outcome in one
sentence in the TD. For "extend a module" / "new module" the architect
flags the platform need (e.g. the module-llm v2 handoff) without
designing the module's internals.

## What to write in the TD (compact — WHAT only)

Keep this to one subsection in the architectural solution. Include:

1. **Workflow pattern** — which of #1–#6, in one sentence.
2. **Agency decision** — no-agent (LLM + UI) / single agent / multi-agent,
   with the rule that decided it and (for multi-agent) the saturation
   evidence.
3. **Workflow-specific NFRs** — only when they actually drive design:
   end-to-end latency budget, fallback on LLM failure, retry policy, max
   iterations for an agent loop.
4. **Evaluation hook** — how the team will know the choice was right (one
   sentence — metric + source).

Capability placement (in-app / extend a module / new module) is recorded
in the TD's general modules/reuse section via the architect's standard
reuse decision framework — not restated as an LLM-specific item here.

**Do not** name a framework or library, and **do not** produce a
multi-row TR-LLM-XX requirements dump. The concrete library and the
access-pattern (`module-llm` vs direct SDK) are the builder_planner's
call, made against the platform standard.

## Anti-patterns to catch in a design

- **Reaching for an agent when LLM + UI suffices** (Rule 2 violated) — a
  generate-and-approve feature does not need an agentic loop.
- **Multi-agent for a problem that fits one context window** with 1–2
  tools — escalation without saturation evidence (Rule 4 violated).
- **Naming a framework in the FD/TD** — that pre-empts the builder_planner
  and breaks the architect's role boundary.
- **Re-inventing a durable state machine** ("we'll just persist to
  Postgres between steps") for a genuine pattern #5 — flag the durability
  requirement; let the builder_planner pick the standard tool.

## References

- The platform standard the builder_planner applies (library + code
  placement): `llm-orchestration-standard` skill.
- Research foundation, the module-llm capability gap, and the module-llm
  v2 handoff:
  [`docs/LLM-orchestration/llm-orchestration-in-apps.md`](../../../docs/LLM-orchestration/llm-orchestration-in-apps.md)
- `module-llm` interface (current `chat` tool):
  [`druppie/mcp-servers/module-llm/v1/tools.py`](../../mcp-servers/module-llm/v1/tools.py)
- Druppie agent stack (contrast — *not* in scope for this skill):
  [`druppie/execution/orchestrator.py`](../../execution/orchestrator.py)
