---
id: "037"
title: "Replace hard-delete retry with copy-and-supersede tracking"
status: accepted
date: 2026-07-29
deciders:
  - pieter
  - nuno
supersedes: null
superseded_by: null
linked_prd: "docs/prds/011-session-lifecycle-management.md"
linked_research: null
---

## Context

Druppie's retry mechanism used hard-delete. When a user retried an agent run, the original runs and their messages were permanently deleted from the database. This made session history non-reconstructable, violating DUTO V06 compliance requirements for archiving. Every retry was a destructive operation that erased evidence of what the system had previously done, making it impossible to audit or trace the full timeline of a session.

## Decision

Replace hard-delete retry with soft-delete using "superseded" tracking.

1. **Superseded timestamps and references:** On retry, old agent runs receive a `superseded_at` timestamp and a `superseded_by_run_id` foreign key pointing to the new replacement run.

2. **Copy creation:** New PENDING AgentRun copies are created via `create_superseding_copies()` rather than reusing or mutating the original runs.

3. **Pending work cancellation:** Pending Questions and Approvals on superseded runs are cancelled automatically when the run is superseded.

4. **Universal query filtering:** All runtime queries filter `superseded_at IS NULL` to exclude superseded runs from active processing. This applies to conversation history, sibling checks, resume, recovery, and planner summary context.

5. **Opt-in inspect view:** The frontend inspect view can include superseded runs by passing `?include_superseded=true`, giving developers and auditors visibility into the full retry timeline.

6. **Git force-push unchanged:** Git force-push behavior remains as-is. The compliance value comes from DB preservation, not git history.

## Consequences

**Positive:**
- Full session history is preserved. Every retry attempt is traceable, and no data is lost.
- DUTO V06 compliance for archiving is satisfied because the database retains all runs.
- The inspect view shows the complete timeline including previous attempts, supporting debugging and auditing.
- Superseded runs are invisible to active processing, so no stale data leaks into conversation history or planner context.

**Negative:**
- Every query that touches agent runs must include the `superseded_at IS NULL` filter. Forgetting this filter causes bugs where superseded data leaks into active processing (e.g., the planner summary leak where `get_completed_runs()` returned superseded runs, causing the planner to see stale context from prior retry attempts).
- The database grows with superseded records that are never cleaned up. This is acceptable for compliance, but may require a retention policy later.
- Retry logic is more complex than the old hard-delete approach: creating copies and marking superseded runs requires more careful orchestration than a simple delete.
