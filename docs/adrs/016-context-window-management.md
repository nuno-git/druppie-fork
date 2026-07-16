---
id: "016"
title: Adopt a context window management strategy for agent sessions
status: proposed
date: 2026-07-16
deciders:
  - Nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

## Context

Long agent sessions accumulate context without any limit, and there is no
strategy — summarization, truncation, or sliding window — for conversations that
approach or exceed the LLM context window. This is most likely to be hit on
complex `update_project` workflows with many tool-calling iterations, and on the
`data_analyst` agent which runs on a small-context (`cheap`) profile with a long
system prompt.

Two reinforcing problems are documented in `docs/BACKLOG.md`:

1. **No Context Window Management.** Messages accumulate for the whole session
   lifetime with no compaction. Once the window is full the agent run fails or
   degrades, and there is no recovery path.
2. **Unbounded Summary Accumulation Across Agents.** The summary relay
   (`druppie/agents/builtin_tools.py:628-684`,
   `druppie/repositories/execution_repository.py:149-175`) accumulates
   `"Agent <role>: ..."` lines from *every* completed agent run and prepends
   them to the next agent's prompt. This never resets — it grows for the entire
   session, across all planner re-evaluations and workflow iterations. In a
   session with multiple design loops (BA ↔ Architect) and execution loops
   (Developer ↔ Deployer), plus a planner that re-runs several times, the
   prepended summary keeps expanding and competes with the agent's own prompt
   and tool-call history for context space.

A related force is **large file uploads**: extracted attachment text (up to
50,000 chars) is returned in full by the `read_attachment` builtin tool, and
combined with prompt + tool history it can overflow the window. There is no
per-attachment token estimate, no session-level context budget, and no
chunked/paginated reading today.

The net effect: a single unbounded resource (the prompt context) is fed from
several unbounded sources (messages, relayed summaries, attachments), with no
measurement, no budget, and no compaction. Today the only "guardrail" is the
50K-char extraction cap on attachments.

## Decision

Adopt a multi-layer context window management strategy. Treat the available
context as a **budgeted resource**, measured and enforced in the Python runtime
rather than hoped-for by the LLM.

- **Token counting & budget.** Introduce token counting (rough char/4 heuristic
  or `tiktoken`) and a per-session context budget that tracks how the window is
  spent — prompt vs. relayed summary vs. tool history vs. attachments. Surface
  this budget so agents and the planner can reason about it.
- **Tiered summarization of the relayed summary.** Keep recent agent outputs in
  full detail and compress older ones with LLM-generated summaries instead of
  appending raw `"Agent <role>: ..."` lines forever. Cap the summary section at a
  fixed token budget and compress when exceeded. Optionally reset accumulation
  at each planner re-evaluation so each "phase" starts bounded.
- **Sliding window for tool/message history.** Bound the message + tool-call
  history kept in-context; evict the oldest entries (with summary retention) once
  the history section exceeds its share of the budget.
- **Attachment guardrails.** Add a per-attachment token estimate at upload time,
  a per-session total-attachment size limit/warning, and pagination
  (`offset`/`limit`) plus an optional `summarize_attachment` tool in
  `read_attachment` so agents can read large files incrementally rather than in
  one shot.

The exact thresholds (budget size, how many recent agents stay full-detail,
whether to reset per planner pass) are to be settled when this ADR moves to
`accepted`; the commitment here is the shape: measure, budget, compress.

## Consequences

Positive:
- Agents stop failing/degrading on long sessions; behavior on complex
  `update_project` and long `data_analyst` sessions becomes predictable.
- Cost and latency become controllable — compaction runs only when a budget is
  hit, not on every turn.
- Relayed summaries stay useful instead of ballooning, so later agents still
  get relevant context rather than a wall of accumulated lines.
- Aligns with the large-attachment guardrail work already partially scoped in
  the backlog.

Negative:
- Compaction can lose information; badly-tuned summarization may degrade agent
  quality. Requires validation that summarized context still performs.
- Adds LLM calls for summarization (latency + cost) and runtime complexity to
  track budgets and evict history.
- New state to maintain (per-session budget, summary tiers); more surface area
  to test.

Before this ADR can move to `accepted`:
- Prototype token counting and confirm counts across all providers (LiteLLM).
- Decide the budget split (prompt / summary / history / attachments) and the
  tier thresholds.
- Decide between tiered summarization vs. plain sliding window vs. per-planner
  reset, and validate summary quality does not regress agent outcomes on a long
  session E2E.

## Alternatives Considered

- **Status quo (do nothing).** Rejected — long sessions already fail or degrade;
  this is the problem being solved.
- **Hard truncation (drop oldest context, no summarization).** Simplest, but
  loses information abruptly and can drop exactly the context a later agent
  needs (e.g. an early BA decision). Rejected as the sole mechanism; acceptable
  only as a last-resort fallback when budgets are exhausted.
- **Pure sliding window (keep last N agents/messages).** Simpler than tiered
  summarization, but discards older detail wholesale. Useful as a component,
  insufficient on its own for sessions where early context stays relevant.
- **LLM-generated compression of everything older than the last turn.** Highest
  quality retention, but adds the most latency/cost and complexity. Adopted in
  the tiered form (compress older tiers only) rather than compressing all
  history.
- **Per-planner-reset only (start each phase fresh).** Bounds growth cheaply
  but can throw away cross-phase context that the planner itself needs. Kept as
  an *optional* reset, not the primary mechanism.
