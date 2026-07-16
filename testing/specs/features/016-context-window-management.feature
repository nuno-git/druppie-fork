# @status draft
# @superseded_by
# @adr 016-context-window-management.md

@adr docs/adrs/016-context-window-management.md
Feature: Context Window Management
  # The "why" (problem, goal) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.
  # Status draft: the ADR is `proposed` and not yet implemented; these scenarios
  # describe the intended behaviour once context is managed as a budgeted resource.

  Scenario: Long session does not overflow the context window
    Given an update_project session with many tool-calling iterations
    When the accumulated context approaches the model's context window limit
    Then older context is compacted within the session budget
    And the agent run continues without exceeding the window

  Scenario: Relayed summary is bounded across agents
    Given a session with multiple design loops and execution loops
    And a planner that re-evaluates several times
    When the summary relay assembles the prepended "Agent <role>: ..." section
    Then the section stays within a fixed token budget
    And older agent outputs are compressed instead of appended verbatim forever

  Scenario: Recent agent outputs keep full detail while older ones are compressed
    Given a session where several agents have completed in sequence
    When the relayed summary is built for the next agent
    Then the most recent agent outputs are included in full detail
    And older agent outputs are represented as compressed summaries

  Scenario: Session context budget tracks where the window is spent
    Given a session with a prompt, tool history, relayed summary, and attachments
    When the runtime builds the next agent prompt
    Then it tracks token usage per section
    And the per-section usage is available to the planner and agent

  Scenario: Large attachment is read incrementally instead of in one shot
    Given an uploaded attachment whose extracted text is large
    When an agent reads the attachment
    Then it can read the attachment with offset and limit parameters
    And a per-attachment token estimate is recorded at upload time

  Scenario: Total attachment size is guarded per session
    Given a session with several uploaded attachments
    When the total attachment size approaches the session attachment limit
    Then a warning or hard limit is enforced
    And the agent is prevented from overflowing the window with attachment text

  Scenario: Compaction preserves the information later agents need
    Given a long session where an early BA decision is relevant to a later agent
    When the context is compacted under the budget
    Then the early BA decision remains available to the later agent
    And the agent does not regress compared to the unbounded behavior
