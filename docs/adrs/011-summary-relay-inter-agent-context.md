---
id: "011"
title: Summary Relay as Sole Inter-Agent Context
status: accepted
date: 2026-07-16
deciders:
  - Nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: docs/TECHNICAL.md
---

## Context

Druppie runs multi-agent pipelines (router → planner → architect → developer → …) where each
agent is an independent LLM loop with its own tool set. Those agents need some way to learn what
the agents before them decided and produced.

The forces at play:

- **Context budget.** Each agent already consumes a large system prompt plus tool schemas plus its
  own conversation. Passing the full raw transcript of every prior agent would blow up the context
  window within a few hops and push the per-call cost up sharply.
- **Decoupling.** Agents are specialised (BA elicits requirements, architect designs, builder
  codes). Letting one agent read another's internal tool-call chatter couples them to
  implementation details they should not care about.
- **Auditability.** Whatever crosses the boundary must be persisted and inspectable, both for the
  timeline UI and for debugging a broken hand-off.
- **Determinism.** The relay must run automatically as part of the platform — not rely on an agent
  choosing to share context.

Before this decision, the realistic alternatives were shared conversation history (full
passthrough) or free-form agent-to-agent messaging. Both were rejected for the reasons above.

## Decision

Agents communicate **only** through structured summary relays. There is no shared memory and no
direct message passing between agents. Each agent receives a structured summary of prior work —
never the full conversation history of the agents before it.

Mechanism (implemented in `druppie/agents/builtin_tools.py`, `druppie/repositories/execution_repository.py`,
and the `summary_relay` system prompt):

1. When an agent calls the `done()` builtin tool, the platform collects the `summary` field from the
   `done` tool-call result of every completed `AgentRun` in the session, ordered by `completed_at`.
2. From each stored summary it extracts only the lines matching the `"Agent <role>: ..."` pattern
   and deduplicates them across runs. This avoids re-copying the already-accumulated context each
   prior summary contains.
3. The current agent's own new lines are merged with the accumulated prior lines.
4. The combined text is prepended to the next pending agent run's `planned_prompt` in the database,
   under a `PREVIOUS AGENT SUMMARY:` header.

This is the **only** mechanism for inter-agent context passing. Agents declare the `summary_relay`
system prompt to learn how to read the incoming summary and how to format their own outgoing one
via `done()`.

Accumulation is **per-session and never resets** — every completed agent run contributes, regardless
of planner re-evaluations or workflow phase transitions. A new session starts with no accumulated
summaries. Summaries are persisted as `ToolCall` result JSON, so the relay is fully auditable.

## Consequences

Positive:

- **Bounded context per agent.** Each agent sees a compact summary rather than the entire upstream
  transcript, keeping token usage predictable across long pipelines.
- **Decoupled agents.** Agents depend only on the summary contract (the `"Agent <role>:"` line
  format), not on each other's tool-call internals, so they can evolve independently.
- **Auditable hand-off.** Every relayed summary is a persisted `done` tool-call result; the timeline
  and debug views show exactly what each agent received and emitted.
- **Automatic & deterministic.** The relay fires as part of `done()` handling — no agent can forget
  to share context.

Negative:

- **Information loss by design.** Only the `"Agent <role>:"` lines are relayed. Anything the prior
  agent did not put in its summary is invisible to downstream agents.
- **A weak summary breaks the chain.** If an agent writes a vague or missing summary, later agents
  (and the user) have no fallback to the raw prior conversation.
- **Line-based dedup heuristic.** Deduplication is by exact line match. A re-worded but semantically
  identical line is not detected, and a deliberately repeated line is dropped.

## Alternatives Considered

- **Shared conversation history (full passthrough).** Give every agent the complete transcript of all
  prior agents. Rejected: it causes unbounded context growth within a few hops, couples every agent
  to every other agent's tool-call format, and sharply increases per-call cost.
- **Free-form agent-to-agent messaging.** Let agents address messages to each other directly.
  Rejected: it introduces coordination complexity (who sends to whom, ordering, waiting), is
  non-deterministic (relies on an agent choosing to share), and is hard to audit compared with a
  single persisted `done` summary per agent.
