# @status draft|active|superseded
# @superseded_by <filename-or-empty>
# @adr <ADR filename this spec implements>
# @prd <PRD filename this spec implements>

# Spec (executable Gherkin) TEMPLATE.
# Copy this to docs/specs/<NNN-feature-name>.feature and fill it in.
#
# Traceability: the @prd / @adr tags below link this behaviour back to the PRD and ADR that
# motivated it. Keep the paths pointing at real files.
#
# LATER (PBI 9744 — afdwingen): the behave runner + Python step definitions in docs/specs/steps/
# (incl. environment.py) and the `behave` dependency are set up in PBI 9744. This template is the
# skeleton only — the scenarios below are not yet executable until that harness exists.

@prd docs/prds/NNN-<feature-name>.md
@adr docs/adrs/NNN-<feature-name>.md
Feature: <feature name>
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: <happy path name>
    Given <precondition>
    When <action>
    Then <expected observable outcome>
    And <additional outcome>

  # Add more Scenario / Scenario Outline blocks as needed. Phrase Given/When/Then in concrete,
  # checkable state (e.g. "Given 3 parallel subagents, When the user retries B, Then only B resets").
