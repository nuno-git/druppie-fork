---
id: "014"
title: Atomic-Claim Cron Scheduling
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

The cron pipeline (`druppie/jobs/`) lets administrators schedule recurring agent runs via YAML
definitions. In production the backend runs as **multiple instances** for availability. Every
instance's `JobScheduler._check_jobs()` polls for due jobs on the same schedule, so two or more
instances can race to trigger the same scheduled slot and produce duplicate runs.

The forces at play:

- **Exactly-once triggering.** A scheduled job must fire at most once per scheduled time, regardless
  of how many backend instances are polling.
- **No external dependencies.** The platform already depends on PostgreSQL; adding a separate lock
  service (Redis, etcd) increases operational surface area for a problem Postgres can solve.
- **Simplicity & auditability.** The claim mechanism should be a single, inspectable operation whose
  winner is obvious from the data, not a distributed-lock dance with leases and renewals.
- **Clock skew tolerance.** The mechanism should rely on database atomicity, not on wall-clock
  agreement between instances.

A normal "read-then-write" sequence (check if due, then insert a run) is not safe under concurrency:
two instances can both read "due" and both insert. The decision is to make the check and the write a
single atomic step.

## Decision

Scheduled agent runs use an **atomic-claim pattern** to prevent duplicate execution in multi-instance
deployments. **A database row serves as the lock.**

Concretely:

- `JobRepository.claim_job_trigger()` issues a single `UPDATE ... WHERE last_triggered_at <
  scheduled_time` against the `job_definitions` row (a compare-and-swap on the row). Because the
  `UPDATE` is atomic at the row level, exactly one of the racing instances updates the row (and
  returns it); the others update zero rows and lose the claim.
- The winning instance then inserts a `job_runs` row and hands it to
  `Orchestrator.execute_pending_runs()`. The losing instances simply see the claim fail and skip.
- The claim is a plain SQL row update — no advisory locks, no lease renewal, no external lock
  service. The `last_triggered_at` column on the `job_definitions` row *is* the lock state, and it is
  directly inspectable.
- Supporting decisions carried over from the same section: `JobDefinitionList` is **not** paginated
  (definitions are bounded YAML config, typically < 50), while `JobRunList` **is** paginated (runs
  accumulate indefinitely). Job YAML files are validated at load time
  (`JobService.load_definitions_from_yaml()`): required fields, cron syntax (via `croniter`), and
  agent existence are checked before any DB insertion; invalid files are logged and skipped entirely.

## Consequences

Positive:

- **Exactly-once triggering under contention.** Row-level atomicity guarantees a single winner per
  scheduled slot, even with many instances racing.
- **No new infrastructure.** It reuses the existing Postgres dependency — no Redis/etcd to operate or
  back up.
- **Self-documenting lock.** The lock state is a normal column (`last_triggered_at`); anyone can query
  who/when a job last fired.
- **Fail-safe by construction.** A crashed winner either committed the `UPDATE` (job recorded as
  triggered) or did not (claim is still available for the next poll).

Negative:

- **DB is a single point of contention.** All instances contend on the same rows; very high job
  frequency could cause row-level lock contention.
- **No cross-cluster coordination.** The guarantee holds only within one shared database. Two
  deployments pointing different backends at the same DB would still race (out of scope by design).
- **Lease-less.** If the winning instance crashes *after* claiming but *before* inserting the run,
  the slot is marked triggered and the run is lost until the next scheduled time.

## Alternatives Considered

- **External distributed lock (Redis / etcd).** Rejected: it adds a mandatory new stateful service
  for a problem the existing database already solves, increasing operational and failure-surface
  cost.
- **Leader election (single scheduler instance).** Rejected: it reduces availability (the scheduler
  stops entirely if the leader is down) and adds the complexity of leader election on top of the
  pool of backend instances.
- **Postgres advisory locks (`pg_advisory_lock`).** Considered: they are session-scoped and do not
  survive a crash cleanly, and they are less self-documenting than a `last_triggered_at` column. The
  row-based `UPDATE ... WHERE` compare-and-swap is simpler and its state is directly inspectable.
- **Read-then-write (check due, then insert).** Rejected: it is a classic check-then-act race that
  produces duplicate runs under concurrency — exactly the problem being solved.
