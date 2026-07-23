---
id: "016"
title: "Sub-Agent Spawning & Step Injection"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: []
---

# PRD 016: Sub-Agent Spawning & Step Injection

## Problem

Only the Planner agent can create new agent runs (via `make_plan`). Other agents cannot delegate subtasks, request clarifications from other agents, or inject follow-up work. This limits the pipeline's flexibility — a Developer that discovers an architecture issue cannot ask the Architect without going through the full planning cycle.

## Goal

Allow any agent to inject new agent runs directly after itself in the execution sequence, and to spawn sub-agents for subtask delegation. This works like `make_plan` but inserts steps immediately after the current agent rather than replacing the full plan.

## User Journey

1. Developer agent discovers it needs an architecture clarification.
2. Developer calls a new `inject_step` builtin with agent=architect, prompt="Clarify X".
3. Architect run is inserted immediately after the Developer in the execution sequence.
4. Developer pauses, Architect runs, returns summary.
5. Developer resumes with the Architect's answer in its context.
6. Tester finds failures, injects a Developer fix run + a re-test, creating a mini-loop.

## Constraints

- Sequence numbering must handle injections into an existing run list without breaking ordering.
- Conflict resolution needed when multiple agents try to inject simultaneously.
- Infinite loop prevention: agent A spawns B which spawns A — needs a depth/cycle limit.
- Injected agents must respect the same approval gates as planned agents.

## Out of Scope

- Parallel sub-agent execution (injected runs are sequential).
- Cross-session agent spawning.

## Open Questions

- **Q1: How to prevent infinite spawn loops?**
  - Option A: Hard depth limit (max 5 levels of injection per session).
  - Option B: Token/cost budget limit (stop spawning when budget exhausted).
  - Option C: Both.
  - Owner: architect.

## Linked Documents

- Source: `docs/BACKLOG.md` — "Agents Should Be Able to Spawn Sub-Agents and Inject Next Steps"
