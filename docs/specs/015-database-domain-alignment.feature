# @status draft
# @superseded_by
# @adr 015-database-domain-alignment.md

@adr docs/adrs/015-database-domain-alignment.md
Feature: Database-Domain Alignment
  # The "why" (problem, goal) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.
  # Status draft: the ADR is `proposed` and not yet implemented; these scenarios
  # describe the intended behaviour once the schema is aligned with the domain.

  Scenario: Timeline ordering is driven by a shared session-level sequence counter
    Given a session with interleaved messages and agent runs
    And two events share an identical timestamp
    When the session timeline is read
    Then the events are ordered by the shared session-level sequence counter
    And the identical timestamps do not change the order

  Scenario: Timeline is the database source of truth, not derived at read time
    Given a session has messages and agent runs stored across their respective tables
    When the repository loads the SessionDetail
    Then the timeline is returned in the order recorded by the schema
    And the repository does not sort the timeline by timestamp in application code

  Scenario: Events of different types interleave correctly in the unified timeline
    Given a session where a message occurs between two agent runs
    When the session timeline is read
    Then the message appears between those two agent runs in sequence order
    And each TimelineEntry preserves its entry type

  Scenario: Schema stays fully relational
    Given the aligned schema for timeline events
    When the tables are inspected
    Then no JSON or JSONB columns are used for timeline structure
    And ordering is stored as explicit relational columns

  Scenario: Repositories become thin mappers after the audit
    Given every repository in druppie/repositories/ has been audited
    When a repository assembles a domain model from the database
    Then it maps columns directly to domain fields
    And it performs no structural reordering or re-derivation at read time

  Scenario: Schema reset is the rollout path
    Given the project rule that no database migrations are written
    When the aligned schema is deployed
    Then the database is reset rather than incrementally migrated
    And existing sessions are not carried forward
