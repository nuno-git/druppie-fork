---
id: "022"
title: Platform Orchestration — Router + Planner Pattern with Subagents for Fast Iteration
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: docs/research/004-agent-runtime.md
---

## Context

Druppie is a spec-driven AI platform for the Dutch Water Authorities (Waterschappen).
Its mission: enable fast software iteration by letting AI agents write, test, and deploy
code autonomously, with human oversight at key gates. The platform needs an orchestration
pattern that scales from simple chat to full project creation while maintaining safety and
auditability.

The origin repo vision (sjhoeksma/druppie) defines three planes:

- **Control Plane (Hersenen)** — orchestration, planning, intent classification
- **Execution Plane (Handen)** — agent execution, tool calls, sandboxed coding
- **Runtime Plane (Resultaat)** — deployed applications, data access, monitoring

The core philosophy: "Alles is een Spec" — everything from infrastructure to agent
behavior is a spec file. Human-in-the-Loop at critical decisions, Secure by Design, and
full traceability are non-negotiable. The "Vaarkaart" vision calls for 21 waterschappen
operating as one concern, with data-driven water management and rapid digital innovation.
Key principles: "Leren, Experimenteren en Verbeteren" — a natural process, not a rigid
project.

Before this decision, Druppie had no unified orchestration layer. Agents ran in isolation
with no routing, no planning, and no mechanism to chain them into coherent workflows.
Each new capability required bespoke wiring. The forces at play:

- **Intent diversity.** Users arrive with different needs: a casual question ("what data
  do you have?"), a project request ("build a water quality dashboard"), or an update
  ("add a new chart to the existing dashboard"). Each needs a different pipeline.
- **Pipeline complexity.** A full project creation involves business analysis,
  architecture, development (frontend, backend, database), testing, documentation, and
  deployment. That is 6-10 specialized agents in sequence, each with its own tools and
  sandbox.
- **Reactive planning.** The platform cannot predict upfront how many iterations a
  project needs. It must plan one step at a time, re-evaluate after each agent completes,
  and adapt based on real output.
- **Parallel speed.** Within a single pipeline step, multiple agents can work in parallel
  (e.g., frontend and backend developers). The platform must support fan-out without
  sacrificing coordination.
- **Safety and auditability.** Every agent run must be traceable, every completion must
  be validated, and the system must fail closed when an agent does not meet its contract.
- **Context continuity.** Each agent starts fresh. The platform must relay what prior
  agents decided and produced without blowing the context window.

## Decision

Adopt a three-layer orchestration pattern: **Router → Planner → Subagents**, implemented
in `druppie/execution/orchestrator.py`, `druppie/agents/builtin_tools.py`, and
`druppie/agent_runtime/`.

### Layer 1: Router — Intent Classification

The Router (`druppie/agents/definitions/general/router.yaml`) is the entry point. It
classifies user intent into exactly one of three categories:

- `create_project` — the user wants a new application built from scratch
- `update_project` — the user wants to modify an existing project
- `general_chat` — the user has a question, no project work needed

The Router runs at temperature 0.1 with a cheap LLM profile for fast, deterministic
classification. It has one mandatory builtin tool: `set_intent()`. The Router **must**
call `set_intent()` before it calls `done()`. It never answers the user directly — it
classifies and exits.

`set_intent()` (`druppie/agents/builtin_tools.py`, line 446-684) does the heavy lifting:

- For `create_project`: creates a Project record, provisions a Gitea repository, and
  pushes the project template.
- For `update_project`: links the existing project to the current session.
- For `general_chat`: sets the session intent so downstream agents know the scope.

Critically, `set_intent()` calls `_update_planner_prompt()` (line 708), which injects
`INTENT:`, `PROJECT_ID:`, and other context into the Planner's system prompt. The Router
does not plan — it classifies and seeds.

### Layer 2: Planner — Reactive Step-by-Step Planning

The Planner (`druppie/agents/definitions/general/planner.yaml`) operates in two modes:

1. **Initial Planning.** Reads the injected INTENT context from `set_intent()` and
   creates a plan of exactly 2 steps: a working agent run followed by a planner
   re-evaluation. This forces the Planner to check real output before continuing.

2. **Re-evaluation.** Reads accumulated agent summaries from all completed runs, decides
   the next step based on status signals (success, failure, partial completion), and
   creates the next working agent.

The Planner has one mandatory builtin tool: `make_plan()`. It must call `make_plan()`
before `done()`. The Planner never executes work — it decides what work to do next.

Mandatory sequences are defined in code (lines 398-408):

- `create_project`: BA → architect → dev_orchestrator → documenter → deployer →
  summarizer
- `update_project`: developer(branch) → BA → architect → dev_orchestrator → documenter →
  deployer(preview) → developer(merge) → deployer(final) → summarizer

The Planner plans **one working agent at a time**, not a full DAG. This is intentional:
it allows reactive planning based on real output rather than assumptions. A safety limit
of 30 planner iterations prevents runaway loops, after which the orchestrator forces
finalization.

`make_plan()` (`builtin_tools.py`, line 763-888) creates `AgentRun` records with
`status='pending'` and cancels any stale pending runs from a previous plan iteration.

### Layer 3: Subagents — Parallel Execution Within a Step

When an agent definition declares `subagents`, the runtime creates a
`SubagentsMCPConnection` (`runtime_v2.py`, line 380-548) that spawns all children in
parallel via `asyncio.gather` (`agent_runtime/subagents.py`, line 112-361). Each child
runs its own `AgentLoop.run()` with its own `LoopConfig`.

Key properties:

- **Parallel fan-out.** All subagents of a parent run concurrently. The Dev Orchestrator
  (`dev_orchestrator.yaml`) spawns explorer, builder_planner, test_builder, developer,
  frontend_developer, backend_developer, database_developer, test_executor, reviewer, and
  deployer in rapid sequence.
- **Depth limit.** `max_subagent_depth` defaults to 10, preventing runaway nesting.
- **Parent chain walking.** When a subagent completes, the orchestrator patches the
  parent's `subagents()` tool call with results and resumes the parent
  (`orchestrator.py`, line 1253-1324).
- **TDD pipeline.** The Dev Orchestrator follows PLAN → TEST (Red) → IMPLEMENT (Green) →
  VERIFY → REVIEW → DEPLOY, with loop-back on failure (max 3 retries) and expert gates
  for plan approval.

### The Mechanical Gate: done() Enforcement

No agent can finish without passing `done()` validation
(`agent_runtime/tools/done.py` and `agent_runtime/loop.py`). The gate has three stages:

1. **Schema validation.** The `done` tool call must match the expected schema.
2. **Summary status keywords.** The summary must contain required keywords (e.g.,
   "completed", "failed").
3. **Precondition checks.** The tool call history is inspected to verify that mandatory
   tools were called (e.g., `set_intent()` for Router, `make_plan()` for Planner).

Auto-done triggers after N retries: enforcement (3), truncation (5), compaction limit,
context overflow, or max turns. When context overflows, only the `done()` tool is
offered — the agent cannot continue.

### How This Enables Fast Iteration for Rijnland

1. **No-code to code pipeline.** Router classifies intent, Planner creates a plan, agents
   build. A user says "I want a water quality dashboard" and Druppie builds it.
2. **Human at key gates only.** Approval only at critical points (BA design approval,
   architect TD approval, deploy to production). Everything else is autonomous.
3. **Subagents for parallel speed.** Dev Orchestrator spawns explorer, planner, developer,
   tester, reviewer in rapid sequence. Context compaction prevents window overflow.
4. **Agent-near-truth.** Agents run in the same sandbox where their code will eventually
   run. They can test and verify, not assume.
5. **Summary relay.** Each agent's summary feeds into the next via the summary relay
   mechanism (ADR 011). No context loss between agents. Planner re-evaluates based on
   real output, not assumptions.
6. **Fail-closed validation.** `done()` will not succeed unless required tools were called
   and the summary contains required keywords. No silent failures.

### The Generieke Platformvisie

Druppie is more than a chatbot. It is an autonomous AI workforce that manages the full
lifecycle of digital solutions:

- From vraagarticulatie (requirements elicitation) and ontwerp (design)
- To toetsing aan wetgeving (compliance with AVG, BIO, NIS2, AI Act)
- To bouw, uitrol, en beheer (build, deploy, and manage)
- Everything traceable, explainable, and with human control at critical moments

The platform democratizes software creation: anyone in the organization can have a secure
application built without writing code. The business describes what they need in natural
language. Druppie translates to code.

## Consequences

Positive:

- **Reactive planning.** The Planner plans one agent at a time and re-evaluates after
  each completion. This adapts to real output instead of following a rigid DAG.
- **Parallel subagent execution.** Within a single pipeline step, subagents run
  concurrently via `asyncio.gather`, reducing wall-clock time for multi-agent steps.
- **done() as a mechanical gate.** No agent can silently fail or skip mandatory steps.
  The three-stage validation (schema, keywords, preconditions) ensures contract
  compliance.
- **Summary relay for context continuity.** Each agent's summary feeds into the next
  (ADR 011). The Planner re-evaluates based on real output, not assumptions.
- **Router classifies without answering.** The Router never responds to the user. It
  classifies intent and seeds the Planner, keeping the classification layer fast and
  focused.
- **Fail-closed validation.** If an agent does not call its mandatory tools or its
  summary lacks required keywords, `done()` rejects the completion. No silent failures.
- **Scalable from chat to project.** The same three-layer pattern handles `general_chat`
  (Router → Planner → single agent) and `create_project` (Router → Planner → 6-10 agent
  pipeline). The architecture does not change, only the plan length.

Negative:

- **Sequential top-level agent execution.** The Planner runs one working agent at a
  time. There is no parallel execution at the top level — only within a single step via
  subagents. Long pipelines (e.g., `create_project`) are inherently serial.
- **Planner is a single point of failure.** If the Planner produces a bad plan or
  misinterprets agent summaries, the entire pipeline derails. Recovery depends on the
  Planner's own re-evaluation loop.
- **30-iteration safety limit.** The hard cap of 30 planner iterations may prematurely
  end complex projects that legitimately need more steps. The limit is a blunt
  instrument.
- **Subagent depth limit of 10.** Deeply nested agent hierarchies (subagents of
  subagents of subagents) are capped. This prevents runaway nesting but also limits
  complex hierarchical workflows.
- **No DAG-based planning.** The Planner produces linear sequences, not directed acyclic
  graphs. Workflows that could benefit from parallel independent tracks (e.g., frontend
  and backend development) must use subagents within a single step rather than parallel
  top-level agents.
