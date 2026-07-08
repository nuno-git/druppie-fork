---
id: "002"
title: Prohibit JSON and JSONB database columns
status: accepted
date: 2026-06-09
deciders:
  - architect
  - developer
superseded_by: null
enforcement:
  lint_rules:
    - ruff-custom
  ci_checks:
    - check-no-json-columns
linked_prd: null
linked_research: null
---

## Context

PostgreSQL offers JSON and JSONB column types that allow storing unstructured or semi-structured data alongside relational data. While convenient for rapid prototyping, JSON columns create several long-term problems:

- **No schema enforcement**: Any shape of data can be stored, leading to silent data corruption when application expectations diverge from actual stored data.
- **Poor queryability**: Complex JSON path queries are harder to write, slower to execute, and harder to index than standard relational queries.
- **Migration difficulty**: Refactoring JSON blobs into proper tables is high-risk and error-prone once production data exists in various shapes.
- **Type safety loss**: ORM models and Pydantic validation cannot effectively guard JSON column contents at the database layer.

We experienced these issues firsthand during early prototyping where configuration data was stored in JSONB columns. Querying, validating, and evolving that data became a significant source of bugs.

## Decision

All data must be normalized into proper relational tables. JSON and JSONB column types are prohibited in all SQLAlchemy models.

**Rules:**

1. No column in any `druppie/db/models/` file may use `sqlalchemy.types.JSON` or `sqlalchemy.dialects.postgresql.JSONB`.
2. Every piece of data that needs persistence gets its own table with properly typed columns and foreign key relationships.
3. When data has a one-to-many relationship with a parent entity, create a separate table with a foreign key — do not store it as a JSON array.

**Known exception:** Raw API request bodies may be stored as JSON in a debugging/log table for troubleshooting purposes. This is explicitly temporary and must not be used for query business logic. These columns should be marked with a comment: `# TEMPORARY: JSON for debugging only — do not query in business logic`.

## Consequences

**Positive:**

- Full type safety from database to application through Pydantic domain models.
- Straightforward queries using standard SQL joins and filters.
- Schema changes are explicit via model updates and tracked through the reset-DB workflow.
- Data integrity enforced by foreign keys and column constraints.

**Negative:**

- More tables and joins for data that could theoretically fit in a single JSON column.
- Schema changes require updating SQLAlchemy models and resetting the database (no migrations).
- Slightly more boilerplate for new features that need multiple related entities.

## Compliance

Compliance is verified through:

1. **ruff custom rule / CI check**: A CI script scans `druppie/db/models/` for any usage of `JSON` or `JSONB` column types and fails if found.
2. **Code review**: Reviewers reject any PR that introduces a JSON/JSONB column without a documented exception.
3. **Model audit**: Periodic review of all SQLAlchemy models to ensure no untyped columns exist.

## Enforcement

When a JSON column is detected:

1. **CI failure**: The `check-no-json-columns` job fails, blocking the PR.
2. **Remediation**: The developer must normalize the data into proper relational tables.
3. **Exception process**: If a genuine need for JSON storage arises (e.g., storing arbitrary third-party API responses), it requires architect approval and must be documented as a known exception in the model file with a `# TEMPORARY` comment.
