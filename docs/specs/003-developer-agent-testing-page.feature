@prd docs/prds/003-developer-agent-testing-page.md
@adr docs/adrs/003-developer-agent-testing-page.md
Feature: Developer/Agent Testing Page
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Execute a project-scoped agent
    Given the developer is on the Agent Test page
    And the developer selects an agent with git_scope "current_project"
    Then a project dropdown is displayed
    When the developer selects a project
    And the developer enters a prompt
    And the developer clicks Execute
    Then a session titled "Agent Test: {agent_id}" is created
    And the agent runs through the shared orchestrator
    And the run status is polled until terminal

  Scenario: Execute a core-scoped agent (no project needed)
    Given the developer is on the Agent Test page
    When the developer selects an agent with git_scope "update_core"
    Then the project dropdown is hidden
    And "Core update — no project needed" is displayed
    When the developer enters a prompt
    And the developer clicks Execute
    Then the agent runs against the Druppie core repository
    And no project_id is required

  Scenario: Project-scoped agent without project selection
    Given the developer selects an agent with git_scope "current_project"
    And the developer does not select a project
    Then the Execute button is disabled

  Scenario: Empty prompt
    Given the developer has selected an agent
    And the prompt text area is empty
    Then the Execute button is disabled

  Scenario: Successful execution
    Given the developer has executed an agent test
    When the agent completes successfully
    Then the run status shows "completed"
    And the run appears in the history panel

  Scenario: Failed execution
    Given the developer has executed an agent test
    When the agent encounters an error
    Then the run status shows "failed"
    And the error is visible in the run details

  Scenario: Open session from history
    Given a previous agent test run exists in the history panel
    When the developer clicks on it
    Then the full session opens in inspect mode in a new tab
