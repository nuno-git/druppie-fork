---
id: "013"
title: "Scheduled Jobs"
status: approved
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/014-atomic-claim-cron-scheduling.md"]
linked_research: []
linked_specs: []
---

# PRD: Scheduled Jobs

## Problem

Many useful agent tasks are **recurring** rather than on-demand: a nightly
summary of platform activity, a periodic review of open work, a scheduled
deployment window. Without a scheduling capability, operators have two bad
options — manually trigger each run on a cadence, or build external cron that
calls the API. Both are duplicative and error-prone.

The problem is sharper in production, where the backend runs as **multiple
instances** for availability. If every instance is free to fire a due schedule,
two or more instances routinely race to trigger the same slot and produce
duplicate runs — wasted cost, duplicated side effects (e.g. two PRs, two
deploys), and confused audit history. A plain "check if due, then start a run"
sequence is unsafe under this concurrency: two instances can both read "due" and
both act.

On top of correctness, operators also need **control and visibility**: the
ability to gate a sensitive recurring job behind human approval, to disable a job
temporarily without deleting it, to see a clean history of what ran when, and to
trigger a job immediately outside its schedule for ad-hoc needs.

## Goal

Operators can define recurring agent runs as YAML **jobs** and trust the platform
to run them on schedule, exactly once, with full history and manual control.
Success looks like:

1. **Cron-based scheduling.** A job specifies a standard cron schedule (5- or
   6-field) for when to run, plus the agent to run and a natural-language prompt.
2. **Declarative job definitions.** Jobs live as YAML files and are auto-synced
   to the platform on startup — new files are created, updated files replace
   their previous values, removed files are deleted.
3. **Atomic execution guarantee.** A scheduled slot fires **at most once**, even
   when many backend instances are polling simultaneously. No duplicate runs.
4. **Approval gating.** A job can optionally pause at trigger time and require a
   human with a configured role to approve before the agent starts.
5. **Enable/disable.** A job can be disabled (visible but excluded from the
   scheduler) without being deleted.
6. **Run history and status tracking.** Every execution instance is recorded with
   status, trigger type, timestamps, and errors, and is linkable to its session.
7. **Manual trigger.** An admin can run a job immediately ("Run Now"), bypassing
   the cron schedule.
8. **Validation at load time.** Invalid job definitions (bad cron, missing
   fields, unknown agent) are rejected up front with clear errors, so no broken
   schedule can ever fire.

**Definition of done:** An operator can schedule a recurring agent run via a YAML
file, the platform runs it exactly once per scheduled slot across a multi-instance
deployment, the run appears in the job history with its status and session, an
admin can trigger it manually, an approval-gated job waits for the right role,
and an invalid definition is rejected at load with a logged error rather than
firing broken.

## User Journey

1. An operator writes a YAML file under `druppie/jobs/definitions/` with an `id`,
   display `name`, `schedule` (cron), `agent_id`, and `prompt`. Optionally they
   set `description`, `approval_required` + `required_role`, and `enabled`.
2. On startup, the platform validates each file — required fields, cron syntax,
   agent existence — and syncs valid definitions to the database. Invalid files
   are skipped entirely with a clear, logged error (no broken schedule is
   recorded).
3. The scheduler polls for due jobs. When a scheduled time arrives, it
   **atomically claims** that slot: across all backend instances, exactly one
   wins the claim and the others silently skip. The run is inserted exactly once.
4. The claimed run is handed to the orchestrator and the configured agent
   executes the prompt, just like any other agent run.
5. If the job is approval-gated, it pauses at trigger time and waits for a human
   with the `required_role` to approve before the agent starts.
6. The operator opens the Tasks page and sees every job definition alongside its
   latest run — status badge, trigger type (scheduled vs. manual), timestamps,
   any error, and a link into the run's session.
7. For an ad-hoc need, an admin clicks **Run Now** to trigger a job immediately,
   bypassing the cron schedule.
8. The operator reviews the paginated run history of any job for auditing —
   when it fired, whether it succeeded, and what session it produced.
9. To temporarily pause a job, the operator sets `enabled: false`; the job stays
   visible in the UI but is excluded from the scheduler until re-enabled.

## Constraints

- **Exactly-once triggering under contention.** A scheduled slot must fire at
  most once regardless of how many backend instances are polling — correctness
  cannot depend on wall-clock agreement between instances.
- **No new infrastructure.** The guarantee must reuse the platform's existing
  database dependency; introducing a separate lock service is out of the
  question for this problem.
- **Standard cron.** Schedules use standard cron expressions (via `croniter`),
  in 5- or 6-field form; bespoke schedule grammars are not introduced.
- **Jobs reference real agents.** The `agent_id` must resolve to an existing
  agent definition, validated at load time.
- **Definitions are bounded config, not growing history.** Job definitions are a
  small, bounded set (typically < 50) and are not paginated; run history, which
  accumulates indefinitely, is paginated.
- **Auditable lock state.** The mechanism that prevents duplicate runs must be
  inspectable directly from the data — an operator should be able to query when
  a job last fired without decoding leases or distributed-lock state.

## Out of Scope

- **UI authoring of job YAML.** Jobs are configuration-as-code (YAML files); an
  in-app editor is not part of this scope.
- **Cross-cluster coordination.** The exactly-once guarantee holds within a
  single shared database. Two separate deployments pointing different backends at
  the same DB would still race — explicitly out of scope by design.
- **Recovery of a lost slot.** If the winning instance crashes *after* claiming a
  slot but *before* inserting the run, that slot is marked triggered and the run
  is lost until the next scheduled time. Automatic recovery is not attempted.
- **Notifications and alerting.** Alerting on job failures or missed schedules is
  a separate concern.
- **DAG / dependency scheduling.** Jobs are independent cron entries; chaining
  one job's completion into another's trigger is not supported.

## Open Questions

- **Q1: How should job definitions be managed at runtime — YAML only, or also
  via UI?**
  - Option A: YAML only (config-as-code) — single source of truth, version
    controlled, but requires a restart/reload to change.
  - Option B: Add a UI enable/disable toggle on top of YAML — friendlier for
    ad-hoc pauses, introduces a second mutation path to keep consistent.
  - Owner: architect, deadline: 2026-08-30

- **Q2: How should a job behave if its target agent is later renamed or removed?**
  - Option A: Skip it at load (current) and re-validate on the next load cycle —
    silent, but the job quietly disappears from the schedule.
  - Option B: Surface it as an errored definition in the UI so the operator sees
    the dangling reference and can fix it.
  - Owner: architect, deadline: 2026-08-30

## Linked Documents

- **ADRs:** `docs/adrs/014-atomic-claim-cron-scheduling.md`
- **Research:** _(none)_
- **Specs / Feature files:** _(none yet)_
