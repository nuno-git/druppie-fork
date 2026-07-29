# @status active
# @superseded_by
# @adr
# @prd docs/prds/028-batch-delete.md

# Spec (executable Gherkin) for batch delete of sessions and projects.
#
# Traceability: the @prd tag links this behaviour back to the PRD that motivated it.
#
# LATER (PBI 9744 — afdwingen): the behave runner + Python step definitions in docs/specs/steps/
# (incl. environment.py) and the `behave` dependency are set up in PBI 9744. This template is the
# skeleton only — the scenarios below are not yet executable until that harness exists.

@prd docs/prds/028-batch-delete.md
Feature: Batch delete sessions and projects
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Enter selection mode shows checkboxes on all sessions
    Given the session sidebar displays 5 sessions
    When the user clicks the selection mode toggle
    Then each session row shows a checkbox
    And the delete button is hidden (no items selected yet)

  Scenario: Select individual sessions shows delete count
    Given the session sidebar is in selection mode with 5 sessions
    When the user checks 3 sessions
    Then the delete button shows "Delete (3)"
    And the button is enabled

  Scenario: Select all checks every session and shows "Delete all"
    Given the session sidebar is in selection mode with 5 sessions
    When the user clicks "Select all"
    Then all 5 session checkboxes are checked
    And the delete button shows "Delete all"

  Scenario: Deselect all hides the delete button
    Given the session sidebar is in selection mode with 3 sessions checked
    When the user unchecks all 3 sessions
    Then the delete button is hidden

  Scenario: Confirm batch delete removes selected sessions and refreshes sidebar
    Given the session sidebar is in selection mode with 5 sessions
    And the user has checked 2 sessions
    When the user clicks "Delete (2)"
    And the user confirms the dialog
    Then a DELETE request is sent with the 2 session IDs in the request body
    And the sidebar refreshes showing 3 sessions
    And selection mode exits

  Scenario: Cancel batch delete exits selection mode without deleting
    Given the session sidebar is in selection mode with 5 sessions
    And the user has checked 2 sessions
    When the user clicks "Delete (2)"
    And the user cancels the dialog
    Then no DELETE request is sent
    And selection mode exits
    And all 5 sessions remain visible in the sidebar

  Scenario: Empty state hides selection mode toggle
    Given the session sidebar shows no sessions
    Then the selection mode toggle is not visible

  Scenario: Batch delete with no IDs deletes all user sessions
    Given the authenticated user has 5 sessions
    When a DELETE request is sent to the sessions endpoint with an empty body
    Then all 5 sessions are deleted
    And the response status is 200

  Scenario: Same selection and delete flow applies to projects page
    Given the projects page displays 4 projects
    When the user clicks the selection mode toggle
    Then each project row shows a checkbox
    When the user checks all 4 projects
    And the user clicks "Delete all"
    And the user confirms the dialog
    Then a DELETE request is sent with all 4 project IDs
    And the projects page refreshes showing 0 projects

  Scenario: Selection mode toggle enters and exits cleanly
    Given the session sidebar displays 5 sessions
    When the user clicks the selection mode toggle
    Then checkboxes appear on all sessions
    When the user clicks the selection mode toggle again
    Then all checkboxes are removed
    And no sessions are selected
    And the delete button is hidden
