# BDD feature TEMPLATE (Gherkin).
# Copy this to testing/bdd/features/<feature-name>.feature and fill it in.
#
# Traceability: the @prd / @adr tags below link this behaviour back to the PRD and ADR that
# motivated it. Keep the paths pointing at real files.
#
# LATER (Story #3 — afdwingen): the behave runner + Python step definitions in testing/bdd/steps/
# (incl. environment.py) and the `behave` dependency are set up in Story #3. This template is the
# skeleton only — the scenarios below are not yet executable until that harness exists.

@prd docs/prds/NNN-<feature-name>.md
@adr docs/adrs/NNN-<feature-name>.md
Feature: <feature name>
  In order to <business value>
  As a <role>
  I want <capability>

  Scenario: <happy path name>
    Given <precondition>
    When <action>
    Then <expected observable outcome>
    And <additional outcome>

  # Add more Scenario / Scenario Outline blocks as needed. Phrase Given/When/Then in concrete,
  # checkable state (e.g. "Given 3 parallel subagents, When the user retries B, Then only B resets").
