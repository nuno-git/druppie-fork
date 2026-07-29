---
id: "008"
title: "Data-modeling policy: typed columns preferred, JSON for raw LLM responses"
status: accepted
date: 2026-07-16
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: null
linked_research: null
---

# ADR 008: Data-modeling policy: typed columns preferred, JSON for raw LLM responses

## Context

> **This ADR supersedes the previous data-modeling policy** documented in
> `docs/TECHNICAL.md` §4.1 ("No JSON/JSONB columns — all data is normalized into
> proper relational tables") and restated in `CLAUDE.md`
> ("NO JSON/JSONB columns — Normalize everything into proper relational tables").
> That blanket prohibition is **no longer in effect**; the rules below replace it.

The old policy forbade JSON/JSONB columns entirely. In practice that was too
rigid: the platform needs to store **raw LLM API responses** (request/response
payloads for debugging, replay, and audit) which are inherently unstructured,
deeply nested, and schema-unstable across providers. Forcing those blobs into
relational tables produced wide, sparse, hard-to-maintain schemas for data that is
almost never queried by field.

At the same time, most data *is* queryable (statuses, foreign keys, timestamps,
role assignments) and belongs in typed, indexed, normalized columns. The team also
works without database migrations: SQLAlchemy models are edited directly and the
database is reset via the `reset-db` / `reset-hard` profiles.

The forces at play:

- Raw LLM payloads are write-once, read-for-debugging, and never filtered by
  individual fields — a perfect fit for an opaque JSON column.
- Queryable data (e.g. `ApprovalStatus`, `AgentRunStatus`, role assignments) must
  stay typed, validatable, and indexable.
- Bare `dict` access to JSON columns is brittle (typos, `KeyError`s, no schema
  evolution signal); the codebase already standardizes on Pydantic for the API
  contract.

## Decision

Adopt a two-track data-modeling policy:

1. **Prefer typed, normalized columns** for all queryable data. Anything that will
   ever be filtered, indexed, joined, or constrained goes in a proper typed column
   or relational table — never in a JSON blob.
2. **JSON/JSONB columns are permitted** for storing raw LLM API responses and
   similar opaque, unstructured payloads (e.g. cached provider responses). These
   columns are treated as write-once, read-for-debugging blobs.
3. **Access JSON columns typesafely.** Serialize and deserialize JSON columns with
   Pydantic models — never reach into them via raw `dict` indexing. This keeps
   schema changes visible and gives validation on read/write.
4. **No database migrations.** Continue to update SQLAlchemy models directly and
   reset the database with the `reset-db` profile (soft reset, keeps users) or
   `reset-hard` (full wipe). This policy is unchanged from the old one.

## Consequences

Positive:

- Raw LLM responses are preserved verbatim without contorting them into awkward
  relational shapes.
- Queryable data stays indexable, validatable, and easy to reason about.
- Pydantic-typed JSON access turns silent `KeyError`s into explicit schema drift
  and gives the same validation guarantees as the rest of the domain layer.

Negative:

- Two storage strategies to reason about; reviewers must judge, per new field,
  whether it is queryable (typed column) or opaque (JSON).
- Risk of "JSON creep" — teams gradually stuffing queryable fields into a JSON
  column. This must be caught in review.
- Each JSON column carries an extra Pydantic model to maintain alongside the
  SQLAlchemy column.

## Alternatives Considered

- **Strict normalization only (the old policy: no JSON at all).** Rejected: it
  forced provider-specific, deeply nested LLM payloads into wide sparse tables
  with high maintenance cost for debugging-only data.
- **Free-form JSON everywhere.** Rejected: loses queryability, indexing, and
  validation for data (statuses, roles, relationships) that genuinely belongs in
  typed columns.
- **Introduce Alembic migrations.** Rejected for now: the no-migration / reset-db
  workflow remains faster for this project's current stage; the reset profiles are
  sufficient and keep schema changes trivially reversible.
