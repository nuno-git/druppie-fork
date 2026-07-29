---
id: "015"
title: Align database schema with domain models
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

The database schema and the domain models have diverged. The intended data flow is
`Repository → Domain Model → Service → API Route`, with the domain layer using a
Summary/Detail pattern (`SessionSummary`, `SessionDetail`, etc.). In practice the
database no longer mirrors that shape: the repositories bridge the gap by
assembling domain objects from raw queries at read time, and that translation is
fragile and implicit.

The clearest symptom is **timeline ordering**. `SessionDetail` exposes a single
unified `timeline` — a sorted list of `TimelineEntry`, each entry being either a
`Message` or an `AgentRunDetail`. At the database level, however, messages and
agent runs live in two separate tables with no shared ordering. The repository
reconstructs the timeline by sorting rows on their timestamps. That is fragile:
if two events share a timestamp, or a timestamp is wrong, the ordering is wrong.
Both tables already carry a `sequence_number` column, but **no shared
session-level counter drives them**, so the columns are not actually a reliable
ordering authority today.

This is one of the open items in `docs/BACKLOG.md` ("Database Schema Does Not
Match Domain Models") and compounds the project's "no JSON/JSONB columns" rule —
structure that should be relational is instead being re-derived in application
code. The result is a database that is *not* the source of truth for ordering
and structure; the source of truth is whatever the repository code computes at
query time.

Constraints:
- Project rule: **no database migrations** — SQLAlchemy models are updated
  directly and the DB is reset (`docker compose --profile reset-db`). Any change
  therefore has no incremental migration path; it ships as a schema reset.
- Project rule: **no JSON/JSONB columns** — everything must be normalized into
  proper relational tables.

## Decision

Make the database the source of truth for ordering and structure so the
repositories become thin readers rather than re-assemblers. Concretely:

- Introduce a **shared session-level sequence counter** that assigns a monotonic
  order to every event (message or agent run) within a session, and make that
  counter — not a timestamp — the authoritative `timeline` ordering key.
- Prefer a **dedicated `timeline_entries` table** that explicitly records the
  ordered stream of events per session (type discriminator + foreign key to the
  concrete row), rather than continuing to UNION two unrelated tables at read
  time. Both existing `sequence_number` columns then back-reference this single
  counter.
- **Audit every repository** in `druppie/repositories/` for database-to-domain
  translation that is currently done in code, and move that structural logic
  into the schema where it belongs.
- Keep all new structure **fully normalized** (no JSON/JSONB), consistent with
  the existing rule.

The detailed shape (single counter on existing tables vs. a `timeline_entries`
table) is to be settled as part of moving this ADR from `proposed` to
`accepted`; the commitment here is the direction: the schema must mirror the
domain.

## Consequences

Positive:
- The database becomes the authoritative source for ordering and structure;
  queries return correctly ordered data without application-level sorting.
- Repositories shrink to thin mappers — less implicit, less fragile translation
  code, fewer ordering bugs.
- `SessionDetail.timeline` is derived from a real, queryable relation instead of
  a UNION + sort, which makes pagination, filtering and auditing easier.
- Aligns the codebase with its own data-flow contract and the no-JSON/JSONB
  rule.

Negative:
- Touches `druppie/db/models/`, `druppie/domain/`, and every repository — a
  broad, cross-cutting change.
- Because there are no migrations, the change ships as a **schema reset**
  (`reset-db` / `reset-hard`); existing sessions are not carried forward. Any
  data-loss path must be explicitly accepted before this is approved.
- Risk of regressions in timeline rendering if the audit misses a translation
  site; requires a full repository-by-repository pass.

Before this ADR can move to `accepted`:
- Complete the repository audit and enumerate every translation site.
- Decide between sequence-counter-on-existing-tables and a dedicated
  `timeline_entries` table (recommend the latter for cleanliness).
- Confirm the reset-based rollout is acceptable and define the test plan that
  proves timeline ordering is correct end-to-end.

## Alternatives Considered

- **Status quo (repositories keep bridging at read time).** Rejected — the
  backlog already flags this as fragile; ordering bugs are latent and the
  translation code keeps growing.
- **Sort on timestamp only (no sequence counter).** Rejected — timestamps can
  collide or be incorrect, which is exactly the failure mode today.
- **Sequence counter added to the two existing tables, no `timeline_entries`
  table.** Lighter change, but keeps the UNION-of-two-tables read pattern and
  leaves the structural mismatch in place. Kept as the fallback option if the
  dedicated table proves too disruptive.
- **Single-table inheritance / polymorphic events table.** Considered and
  rejected — it conflates unrelated event shapes into one wide table and fights
  the normalized relational model the project has chosen.
