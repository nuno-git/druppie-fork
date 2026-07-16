---
id: "013"
title: Cooperative Pause, Resume, and Cancellation
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

Agent runs are long-lived LLM ↔ tool-calling loops. Users and operators must be able to stop a run,
resume it later, or have the platform recover it after a crash — all without corrupting the
conversation or losing work-in-progress.

The forces at play:

- **Safety of preemption.** An LLM call or a tool execution in flight cannot be safely interrupted
  mid-way — killing it can leave half-written files, dangling approvals, or an inconsistent DB state.
- **Durability.** Stopping a run must not discard the conversation. Everything done so far must be
  resumable.
- **Responsiveness vs. correctness.** Users expect a Stop button to take effect promptly, but the
  system must never tear down state to do so.
- **Crash recovery.** A server reboot should not strand runs in a permanently "active" state; users
  must be able to resume them.

The platform already has two natural pause points: between agent runs (in the orchestrator) and
between LLM iterations (in the agent loop). Polling a shared status flag at those points gives a
cooperative control channel without unsafe preemption.

## Decision

Agent execution supports cooperative pause, resume, and cancellation through a **control channel
backed by the session status in the database**. The agent and orchestrator check for control signals
at defined checkpoints; they never preempt a call in flight.

Checkpoints:

- The **orchestrator** polls the session status from the DB before each agent run and after each agent
  completes. If the status is `paused` or `cancelled`, it stops executing further runs.
- The **agent loop** polls the session status between LLM iterations (and the `agent_runtime`
  `CancellationToken` is checked each iteration). If a stop is requested, the loop finishes the
  current call/iteration and then halts cleanly.

Control flows:

- **User-initiated stop:** `POST /api/chat/{session_id}/cancel` sets `session.status = 'paused'`. The
  current LLM call / tool execution completes, then the loop halts at the next checkpoint. For
  sessions already paused for approval or HITL (no background task running), the change is immediate.
- **Resume:** `POST /api/sessions/{session_id}/resume` spawns a background task that calls
  `reconstruct_from_db()` (`druppie/agents/message_history.py`) to rebuild the full LLM conversation
  from `LlmCall` and `ToolCall` records, then continues the loop from the iteration where it paused.
  After the current agent completes, the orchestrator continues the remaining pending runs.
- **Automatic pause (approval / HITL):** when `ToolExecutor` hits a tool needing approval or a HITL
  question, it creates the `Approval`/`Question` record and the run pauses (`paused_tool` /
  `paused_hitl`); resume happens via `resume_after_approval()` / `resume_after_answer()`, again by
  reconstructing state from the DB.
- **Zombie recovery:** on startup, sessions found in `active` status (orphaned by a reboot/crash) are
  automatically marked `paused` so the user can resume them via Continue.

`cancelled` is **internal only** — set by the planner when a new plan supersedes old pending runs,
never by user actions.

The DB is the single source of truth: because every LLM call and tool result is persisted, the run
can always be reconstructed and resumed from where it stopped.

## Consequences

Positive:

- **No state corruption.** Stopping never interrupts a call in flight; the loop always lands on a
  clean, persisted checkpoint.
- **Full resumability.** `reconstruct_from_db()` rebuilds the conversation from persisted records, so
  a paused/crashed run continues exactly where it left off — across reboots.
- **Crash-safe.** Zombie recovery prevents orphaned `active` sessions after a server crash.
- **Uniform model.** User stops, approvals, HITL, and crashes all funnel through the same
  status-checkpoint mechanism.

Negative:

- **Stop latency.** A stop request takes effect only at the next checkpoint, so up to one LLM
  iteration (or one tool execution) may run after the user clicks Stop.
- **Polling overhead.** Each checkpoint reads the session status from the DB.
- **No hard deadline.** There is no guaranteed wall-clock bound on how long the in-flight call takes
  to finish after a stop is requested.

## Alternatives Considered

- **Hard preemption (kill the thread/process).** Rejected: it can corrupt in-flight tool side-effects
  (half-written files, dangling approvals) and loses any un-persisted state, making safe resume
  impossible.
- **OS signals / task cancellation tokens without DB status.** Rejected: in-process signals do not
  survive a reboot and do not give the orchestrator (which spans multiple agent runs) a shared,
  durable view of the desired state.
- **Non-resumable cancellation (discard on stop).** Rejected: it discards expensive LLM work and
  violates the durability requirement.
