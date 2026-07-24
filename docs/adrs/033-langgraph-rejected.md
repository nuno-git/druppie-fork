---
id: "033"
title: "Reject LangGraph for agent flow due to excessive customization overhead"
status: deprecated
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: "004"
linked_prd: null
linked_research: docs/research/002-llm-orchestration-in-apps.md
---

# ADR 033: Reject LangGraph for agent flow due to excessive customization overhead

## Context

After the pi_agent was rejected, LangGraph was adopted as the main agent flow
and used for roughly four months (January-May 2026). Key commits: `ba9c84b4`
(StateGraph), `0db781c5` (HITL via `interrupt()`).

LangGraph provided a structured StateGraph API with built-in HITL support
via `interrupt()`, and a growing Python ecosystem.

## Decision

**Reject LangGraph.** While it worked for basic agent flows, Druppie's
governance requirements demanded customizations that eventually rewired
most of LangGraph:

- `done()` enforcement as a mechanical gate (not prompt-only)
- Summary relay for inter-agent context continuity
- Recursive subagent spawning with parallel execution
- Context compaction via LLM summarization with token calibration
- Sandbox lifecycle management (create, warm, destroy per agent)
- Cooperative pause/resume/cancellation with Postgres LISTEN/NOTIFY

At the point where every LangGraph primitive was wrapped or bypassed,
the abstraction had become a hindrance. The LangGraph layer was a thin
wrapper over custom code with no remaining value. The decision was made
to drop the abstraction and build the runtime ourselves.

This was consistent with the broader framework survey (Research 002),
which concluded that "Plain Python (core-stijl)" is the standard and that
external agent libraries bring version churn, abstraction lock-in, harder
debugging, and a larger supply chain.

## Consequences

**Positive.** The LangGraph phase confirmed exactly which capabilities the
runtime needed to own directly: done() enforcement, subagent spawning,
context compaction, sandbox lifecycle, and pause/resume. These became the
core features of the `agent_runtime/` library.

**Negative.** Four months of LangGraph integration was discarded. The
LangGraph HITL model (`interrupt()`) differed from Druppie's approval gate
model, adding migration complexity.
