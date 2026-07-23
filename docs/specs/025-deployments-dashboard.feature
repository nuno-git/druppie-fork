# @status active
# @superseded_by
# @adr
# @prd docs/prds/027-deployments-dashboard.md

# Spec (executable Gherkin) for the Deployments Dashboard.
#
# Traceability: the @prd tag links this behaviour back to PRD 027.

@prd docs/prds/027-deployments-dashboard.md
Feature: Deployments Dashboard
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: User with running deployments sees correct stats row counts
    Given the user has 5 deployed applications: 3 Running, 1 Stopped, 1 Unhealthy
    When the user opens the Deployments dashboard at /deployments
    Then the stats row shows Total: 5
    And the stats row shows Running: 3
    And the stats row shows Stopped: 1
    And the stats row shows Unhealthy: 1

  Scenario: Search filter by app name filters the table
    Given the user has deployments named "api-gateway", "auth-service", "data-pipeline", and "notification-service"
    When the user types "auth" in the search field
    Then the table shows only "auth-service"
    And "api-gateway", "data-pipeline", and "notification-service" are hidden

  Scenario: Click start button on stopped app transitions to Running
    Given the user has a stopped deployment named "api-gateway"
    When the user clicks the start button on "api-gateway"
    Then the system sends a start request for "api-gateway"
    And the status chip transitions to Running
    And the stats row Running count increments by 1
    And the stats row Stopped count decrements by 1

  Scenario: Click stop button on running app transitions to Stopped
    Given the user has a running deployment named "auth-service"
    When the user clicks the stop button on "auth-service"
    Then the system sends a stop request for "auth-service"
    And the status chip transitions to Stopped
    And the stats row Stopped count increments by 1
    And the stats row Running count decrements by 1

  Scenario: Click restart button restarts the app with temporary transitioning state
    Given the user has a running deployment named "data-pipeline"
    When the user clicks the restart button on "data-pipeline"
    Then the system sends a restart request for "data-pipeline"
    And the status chip shows "Transitioning" during the restart
    And after the restart completes, the status chip returns to "Running"
    And the stats row Running count remains unchanged

  Scenario: Click logs button opens logs drawer with last 300 lines
    Given the user has a running deployment named "api-gateway"
    When the user clicks the logs button on "api-gateway"
    Then a terminal-style drawer opens from the bottom of the page
    And the drawer displays the last 300 lines of "api-gateway" logs
    And the drawer has a refresh button
    And the drawer has a close button

  Scenario: Empty state shows message when user has no deployments
    Given the user has no deployed applications
    When the user opens the Deployments dashboard at /deployments
    Then the stats row shows Total: 0, Running: 0, Stopped: 0, Unhealthy: 0
    And the table area displays "No deployments found"
    And no action buttons are shown

  Scenario: Stats row updates on polling interval
    Given the user has a running deployment named "api-gateway"
    And the Deployments dashboard is open
    When 5 seconds elapse
    Then the system polls for updated deployment statuses
    And the stats row reflects the latest counts
    And the table rows reflect the latest status chips

  Scenario: User only sees their own deployments
    Given user A has deployments "app-alpha" and "app-beta"
    And user B has deployments "app-gamma" and "app-delta"
    When user A opens the Deployments dashboard
    Then user A sees only "app-alpha" and "app-beta" in the table
    And "app-gamma" and "app-delta" are not visible to user A

  Scenario: Logs drawer refresh button fetches latest logs
    Given the logs drawer is open for deployment "api-gateway"
    And the drawer displays 300 lines of logs
    When the user clicks the refresh button in the logs drawer
    Then the system fetches the latest logs for "api-gateway"
    And the drawer updates to show the most recent 300 lines
