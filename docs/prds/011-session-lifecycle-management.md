---
id: "011"
title: "Session Lifecycle Management"
status: approved
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/013-cooperative-pause-resume-cancellation.md"]
linked_research: []
linked_specs: []
---

# PRD: Session Lifecycle Management

> **Where this fits:** This PRD describes the **product** experience of
> controlling a session's life — start, pause, resume, cancel, and recover —
> from the user's perspective. The architectural decision (cooperative control
> via DB-backed status checkpoints, full reconstruction from persisted records,
> zombie recovery) lives in ADR 013. Session lifecycle is a part of the broader
> agent runtime described in PRD 004; this PRD narrows in on the user-facing
> state-control experience layered on top of it.

## Problem

A Druppie session is a long-lived, multi-agent LLM ↔ tool-calling pipeline.
From a user's point of view, today the experience breaks down in several ways:

- **No safe way to walk away.** Once a session is running, the user is stuck
  watching it. There is no clean "pause this and come back" — stopping risks
  losing the expensive LLM work already done, and resuming means starting over.
- **Stops are either dangerous or ignored.** A naive "kill the run" can corrupt
  in-flight work — half-written files, dangling approvals, an inconsistent
  conversation. A stop that does nothing until the whole pipeline finishes is
  not really a stop at all.
- **Gates feel like dead ends.** When a session pauses automatically for an
  approval or a HITL question, the user cannot tell whether the session is
  genuinely halted, still doing something in the background, or broken.
- **Crashes strand work.** If the server reboots mid-session, runs left in an
  "active" state sit there forever — the user thinks the session is running
  when nothing is happening, and there is no path back.
- **Status is opaque.** The difference between "actively working," "paused by
  me," "waiting on you," "done," and "failed" is not something the user can
  read at a glance, so they do not know what (if anything) they need to do.

What degrades without this feature: users cannot trust that a session is safely
stoppable and resumable, automatic gates feel like the system froze, and a
reboot silently abandons in-progress work.

## Goal

A session lifecycle that is **safe to interrupt, always resumable, and honestly
visible**. The user can start, stop, resume, and rely on automatic pausing at
gates, with no lost work and a status that always tells the truth. Done means:

1. **Cooperative stop.** A user can stop any running session; the current LLM
   call / tool execution finishes, then the session pauses cleanly at the next
   checkpoint. Stop never tears down in-flight state, and a stopped session is
   **always resumable** — nothing is discarded.
2. **Resume from where it left off.** Continuing a paused session rebuilds the
   full conversation from what was persisted and carries on exactly where it
   stopped, then runs any remaining pending agents.
3. **Automatic pause at gates.** When a session hits an approval, a HITL
   question, or a sandbox wait, it pauses by itself and shows a clear status so
   the user knows what it is waiting for — and resumes automatically once the
   gate is cleared.
4. **Crash recovery.** After a reboot or crash, sessions that were left
   "active" are detected and surfaced as **paused** (not stuck), so the user
   can simply resume them. No session is permanently stranded.
5. **Truthful status visibility.** The user can see, at a glance and with a
   consistent visual language, whether a session is `active`, `paused` (by them
   or recovered), `paused_approval`, `paused_hitl`, `paused_sandbox`,
   `completed`, or `failed` — and knows what action, if any, is theirs to take.
6. **Stop always available when it matters.** The Stop control stays available
   during active runs and during approval/HITL waits, so the user can always
   halt background work — not just when the session happens to be busy.

**Definition of done:** a user can stop a running session and resume it later
with all context intact (the conversation continues exactly where it paused),
automatic gates pause the session with a clear "waiting on you" status and
resume once resolved, and a simulated server crash leaves the session resumable
rather than stranded — all reflected accurately in the UI status.

## User Journey

1. A user starts a session (e.g. "create a todo app"). The session enters
   `active` and the multi-agent pipeline begins.
2. **User-initiated stop:** the user clicks **Stop**. The current step
   finishes, the session moves to `paused`, and the UI reflects it immediately.
   Nothing the agent already did is lost.
3. **Automatic pause (gate):** later, an agent calls a tool that needs approval
   (or asks a HITL question). The session moves to `paused_approval` (or
   `paused_hitl`) on its own, and the user sees a clear "waiting for approval"
   / "waiting for your answer" status. The Stop control remains available.
4. The user resolves the gate (approves, rejects, or answers). The session
   resumes automatically and continues from the exact step that paused.
5. **Resume after stop:** the user returns to a `paused` session and clicks
   **Continue**. The session rebuilds its state from the persisted history,
   continues the paused agent, and then proceeds through any remaining pending
   agents.
6. **Crash recovery:** the server reboots while a session was `active`. On
   restart, that session is automatically shown as `paused` (not "active but
   dead"). The user clicks Continue and picks up where they left off.
7. The session eventually reaches `completed` (all agents finished) or
   `failed` (an error occurred), and polling stops — the user is shown a
   terminal status.

## Constraints

- **Cooperative, never preemptive.** A stop takes effect only at the next
  checkpoint (between agent runs, or between LLM iterations). Up to one LLM
  iteration / tool execution may run after the user clicks Stop. Hard
  preemption that can corrupt in-flight work is explicitly out.
- **Durability is non-negotiable.** Every LLM call and tool result is
  persisted, so any pause (user stop, gate, or crash) is fully reconstructable.
  Stop must never discard work.
- **Stop is always resumable.** The user-facing Stop is a soft-stop that sets a
   resumable paused state. Destructive, non-resumable cancellation is not a
   user action.
- **`cancelled` is not a user action.** Internal-only cancellation (when a new
  plan supersedes old pending runs) is set by the planner, never by the user.
  Users only pause/resume.
- **Status must match reality.** The displayed status is the source of truth
  for what the session is doing; it must not show "active" when nothing is
  running (the zombie-recovery requirement exists precisely to enforce this).
- **Polling discipline.** Active sessions poll frequently (~500ms) for
  responsiveness; once a session completes, fails, or is paused, that
  high-frequency polling stops to avoid waste.

## Out of Scope

- **Hard preemption / guaranteed stop deadlines.** There is no wall-clock bound
  on how long the in-flight call takes to finish after Stop; that is an
  accepted trade-off of the cooperative model.
- **User-initiated destructive cancellation** (discard all work, no resume).
  Not a supported action; stop is always resumable.
- **Parallel multi-agent sessions.** The lifecycle model assumes sequential
  agent execution within a session; concurrent-agent scheduling is a separate
  concern.
- **The internal planner-driven `cancelled` flow** — surfaced here only to
  document that it is not user-facing; its behavior is owned by the planning
  subsystem.
- **The approval/HITL *content* experience** — what the cards show and how
  approve/reject works is owned by the Approval Workflow PRD (PRD 010). This
  PRD owns only the pause/resume/status behavior *around* those gates.

## Open Questions

- **Q1: How should the UI communicate stop latency honestly?**
  - Option A: Show a "stopping…" interim state until the checkpoint is reached,
    so the user knows the request is acknowledged but not yet effective.
  - Option B: Flip to "paused" immediately and let the in-flight step finish in
    the background. Snappier, but slightly misleading about what is running.
  - Owner: architect, deadline: 2026-08-15
- **Q2: Should zombie-recovered sessions notify the user, or just appear as
  paused?**
  - Option A: Silently surface as `paused` (minimal surprise, user resumes at
    will).
  - Option B: Badge / annotate them as "recovered after restart" so the user
    understands why a session they left running is now paused.
  - Owner: architect, deadline: 2026-08-15

## Linked Documents

- **ADRs:** `docs/adrs/013-cooperative-pause-resume-cancellation.md`
  (cooperative pause/resume/cancellation via DB-backed status checkpoints,
  full reconstruction from persisted records, zombie recovery).
- **Research:** _(none)_
- **Specs / Feature files:** _(none yet)_
- **Related PRDs:** **PRD 004 (Native Agent Runtime)** — session lifecycle is
  the user-facing state-control layer of the agent runtime described in PRD
  004; the runtime's pause/resume mechanics are what this PRD exposes to users.
  Also interacts with **PRD 010 (Approval Workflow System)**: an approval is
  one of the gates that pauses a session here.
- **Source references:** `docs/TECHNICAL.md` §8.9 (Pause and Resume);
  `docs/FEATURES.md` "Session Control" section.
