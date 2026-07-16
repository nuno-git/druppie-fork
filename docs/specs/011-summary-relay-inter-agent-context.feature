# @status active
# @superseded_by
# @adr docs/adrs/011-summary-relay-inter-agent-context.md
@adr docs/adrs/011-summary-relay-inter-agent-context.md
Feature: Summary Relay as Sole Inter-Agent Context
  # The "why" (problem, goal, motivation) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Relay accumulates each completed agent's summary on done()
    Given a session with 2 completed agent runs that each called builtin:done
    When the next pending agent run is prepared for execution
    Then its planned_prompt begins with a "PREVIOUS AGENT SUMMARY:" header
    And the summary contains an "Agent <role>:" line for each completed run
    And the lines appear in completed_at order

  Scenario: Only "Agent <role>:" lines are relayed, not full summaries
    Given a completed agent run whose done() summary contains prose outside the "Agent <role>:" pattern
    When the next pending agent run is prepared
    Then only the lines matching the "Agent <role>:" pattern appear in the relayed summary
    And the non-matching prose is excluded

  Scenario: Duplicate summary lines are deduplicated across runs
    Given two completed agent runs whose done() summaries share an identical "Agent <role>:" line
    When the next pending agent run is prepared
    Then that shared line appears exactly once in the relayed summary

  Scenario: The current agent's own new lines are merged with prior accumulated lines
    Given one completed agent run and a current agent calling done() with a new "Agent <role>:" line
    When the relay accumulates
    Then the relayed summary contains both the prior run's lines and the current run's new line
    And lines the current agent repeated from the prior set are not duplicated

  Scenario: Agents never receive another agent's full conversation history
    Given a completed agent run that made several LLM calls and tool calls
    When the next pending agent run is prepared
    Then the next agent's context contains no raw tool-call results from the prior run
    And no raw LLM message content from the prior run

  Scenario: Accumulation is per-session and never resets across workflow phases
    Given a session where the planner re-evaluated and created new pending runs after earlier runs completed
    When a later pending agent run is prepared
    Then its relayed summary still includes the "Agent <role>:" lines from the earlier completed runs

  Scenario: A new session starts with no accumulated summaries
    Given a brand-new session with no completed agent runs
    When the first pending agent run is prepared
    Then its planned_prompt contains no "PREVIOUS AGENT SUMMARY:" block

  Scenario: Relayed summaries are persisted and auditable
    Given a completed agent run that called done()
    When the relay reads its summary
    Then the summary is read from the done tool-call result JSON persisted on that run
    And the tool call has tool_name "done" and status "completed"
