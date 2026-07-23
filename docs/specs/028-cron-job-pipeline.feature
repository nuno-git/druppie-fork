# @status active
# @superseded_by
# @adr docs/adrs/014-atomic-claim-cron-scheduling.md
# @prd docs/prds/013-scheduled-jobs.md

# Spec (executable Gherkin) for the Cron Job Pipeline (PR #230).
#
# Traceability: the @prd tag links this behaviour back to PRD 013.
# Spec 014 covers the atomic-claim mechanism; this spec covers the
# user-facing pipeline behaviour (UI, approval gates, history, validation).

@prd docs/prds/013-scheduled-jobs.md
@adr docs/adrs/014-atomic-claim-cron-scheduling.md
Feature: Cron Job Pipeline
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Admin views /tasks page and sees all defined cron jobs with status
    Given the admin user is authenticated
    And there are 3 job definitions: "nightly-summary", "weekly-review", and "deployment-window"
    When the admin navigates to /tasks
    Then the page displays all 3 job definitions
    And each job shows its name, schedule, last run time, and enabled/disabled status
    And each job has a "Run Now" button

  Scenario: Non-admin views /tasks page and is denied access
    Given a user with role "developer" is authenticated
    When the user navigates to /tasks
    Then the response is 403 Forbidden
    And the page displays an "Access Denied" message

  Scenario: Admin triggers manual job run and it executes
    Given the admin is on the /tasks page
    And a job definition "nightly-summary" exists with status "enabled"
    When the admin clicks "Run Now" on "nightly-summary"
    Then a new job run is created with trigger type "manual"
    And the job run appears in the Job Runs section with status "Pending"
    And the job transitions to "Running" within 5 seconds
    And the job eventually reaches "Completed" or "Failed"

  Scenario: Cron job triggers on schedule automatically
    Given a job definition "weekly-review" with schedule "0 8 * * 1"
    And the current time is Monday 08:00:00
    When the scheduler polls and the slot is due
    Then a new job run is created with trigger type "scheduled"
    And the job run appears in the Job Runs section with status "Pending"

  Scenario: Job with approval gate pauses for human approval
    Given a job definition "deployment-window" with approval_required: true and required_role: "admin"
    When the job triggers on schedule
    Then the job run status is "Pending" with sub-status "waiting_approval"
    And the job does not start executing
    When an admin user approves the run
    Then the job run status transitions to "Running"
    And the agent executes the configured prompt

  Scenario: Job with approval gate is rejected on decline
    Given a job definition "deployment-window" with approval_required: true
    And the job run is in "waiting_approval" status
    When an admin user declines the run
    Then the job run status transitions to "Rejected"
    And the agent never executes
    And the run history shows "Rejected" with the declining user's identity

  Scenario: Job run history shows status lifecycle
    Given a job definition "nightly-summary" with multiple runs
    When the admin views the job run history
    Then each run shows a status badge
    And the status transitions follow: Pending -> Running -> Completed
    Or the status transitions follow: Pending -> Running -> Failed
    Or the status transitions follow: Pending -> Rejected
    And each run shows its trigger type (scheduled or manual)
    And each run shows its start time and duration

  Scenario: Disabled jobs do not trigger on schedule
    Given a job definition "nightly-summary" with enabled: false
    When the scheduler polls for due jobs
    Then the scheduler skips "nightly-summary"
    And no job run is created for "nightly-summary"
    When an admin toggles the job to enabled
    And the next scheduled time becomes due
    Then the scheduler triggers the job normally

  Scenario: Invalid job YAML is rejected at startup with error
    Given a job YAML file with a missing "agent_id" field
    When JobService.load_definitions_from_yaml runs on startup
    Then the file is logged with a validation error
    And the file is skipped entirely
    And no job_definitions row is inserted for that file
    Given a job YAML with an invalid cron expression "99 99 * * *"
    When it is loaded
    Then croniter rejects the expression
    And the file is skipped with a logged error

  Scenario: Run history pagination loads older runs on scroll
    Given a job definition with 35 historical runs
    When the admin opens the job run history
    Then the first page shows 20 runs
    When the admin scrolls to the bottom of the list
    Then the next 15 runs load automatically
    And all 35 runs are visible after the second page loads
