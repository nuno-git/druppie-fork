# @status active
# @superseded_by
# @adr 008-data-modeling-policy.md
@adr docs/adrs/008-data-modeling-policy.md
Feature: Data-modeling policy
  # The "why" (problem, goal, user journey) lives in the linked ADR (@adr).
  # This ADR supersedes the old "NO JSON/JSONB columns" policy from TECHNICAL.md §4.1
  # and CLAUDE.md. This spec holds only the acceptance Scenarios below.

  Scenario: Queryable data is stored in typed columns
    Given a new field that will be filtered, indexed, joined, or constrained
    When the field is modeled in a SQLAlchemy model
    Then the field is a typed, normalized column
    But the field is not embedded inside a JSON/JSONB column

  Scenario: Raw LLM API response is stored in a JSON column
    Given a raw LLM API request or response payload to persist for debugging or replay
    When the payload is stored
    Then the payload is written to a JSON/JSONB column
    And the payload is kept verbatim without normalization into relational tables

  Scenario: JSON column is accessed through a Pydantic model
    Given a JSON/JSONB column that holds an opaque payload
    When the column is read or written
    Then the value is serialized or deserialized via a Pydantic model
    But the value is never accessed through raw dict indexing

  Scenario: Schema changes do not use database migrations
    Given a change to a SQLAlchemy model
    When the change is applied
    Then no migration script is generated
    And the database is reset using the reset-db or reset-hard profile

  Scenario: Old blanket "no JSON" policy no longer applies
    Given the previous policy stating "NO JSON/JSONB columns"
    When a raw LLM payload must be persisted
    Then the JSON/JSONB column is permitted under this ADR
    And the old policy from TECHNICAL.md §4.1 and CLAUDE.md is superseded
