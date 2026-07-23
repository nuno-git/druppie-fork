# @status active
# @superseded_by
# @adr docs/adrs/014-atomic-claim-cron-scheduling.md
@adr docs/adrs/014-atomic-claim-cron-scheduling.md
Feature: Atomic-Claim Cron Scheduling
  # The "why" (problem, goal, motivation) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: A single instance claims a due scheduled slot exactly once
    Given one backend instance and a job whose scheduled time is now due
    When the JobScheduler polls and JobRepository.claim_job_trigger runs
    Then exactly one job_runs row is inserted for that scheduled time
    And the job_definitions last_triggered_at is advanced to the scheduled time

  Scenario: Two racing instances do not produce duplicate runs
    Given two backend instances polling the same due job at the same time
    When both call JobRepository.claim_job_trigger concurrently
    Then the claim is an atomic UPDATE ... WHERE last_triggered_at < scheduled_time
    And exactly one instance wins the claim and inserts a job_runs row
    And the losing instance updates zero rows and skips

  Scenario: The claim is a compare-and-swap on the job_definitions row
    Given a job_definitions row with a last_triggered_at value
    When claim_job_trigger executes
    Then it issues UPDATE job_definitions SET last_triggered_at = scheduled_time WHERE last_triggered_at < scheduled_time
    And the affected row is returned only to the winning instance

  Scenario: A slot already claimed is not re-triggered by a later poll
    Given a job whose last_triggered_at already equals or exceeds the scheduled time
    When any instance polls and attempts to claim it
    Then the WHERE clause matches zero rows
    And no job_runs row is inserted

  Scenario: A crashed winner does not double-fire on the next poll within the same slot
    Given an instance that won the claim but crashed before inserting the run
    When the next scheduled time for that job becomes due
    Then the claim for the new scheduled time succeeds normally
    And the missed earlier slot is not retried

  Scenario: Job definitions are validated at load time before DB insertion
    Given a job YAML file missing a required field
    When JobService.load_definitions_from_yaml loads it
    Then the file is logged and skipped entirely
    And no broken job_definitions row is inserted
    Given a job YAML with invalid cron syntax
    When it is loaded
    Then croniter rejects it and the file is skipped
    Given a job YAML referencing a non-existent agent
    When it is loaded
    Then the filesystem check fails and the file is skipped

  Scenario: JobDefinitionList is not paginated while JobRunList is
    Given a deployment with many job definitions and accumulating job runs
    When the definitions endpoint is called
    Then all definitions are returned without pagination
    When the runs endpoint is called
    Then the runs are paginated
