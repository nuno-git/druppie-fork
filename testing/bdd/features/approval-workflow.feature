@prd docs/prds/approval-system.md
@adr docs/adrs/003-tool-only-communication.md
Feature: Tool Approval Workflow
  Agents execute tools that require human approval before proceeding.
  Users with the required role can approve or reject, and the agent
  resumes or retries accordingly.

  Background:
    Given the API is running
    And a test database is available

  Scenario: Architect approves technical design
    Given a project exists with id "proj-001"
    And an agent produces a technical design requiring "architect" approval
    When the architect approves the pending approval
    Then the approval status is "approved"
    And the agent workflow resumes in the background
    And the tool executes and the file is committed

  Scenario: Developer approves Docker build
    Given a project exists with id "proj-002"
    And an agent requests a Docker build requiring "developer" approval
    When the developer approves the pending approval
    Then the approval status is "approved"
    And the container starts successfully

  Scenario: Rejection sends feedback to agent
    Given a pending approval exists with id "appr-001" requiring "architect" role
    When the architect rejects it with reason "Needs more security review"
    Then the approval status is "rejected"
    And the rejection reason is "Needs more security review"
    And the agent workflow resumes in the background
    And the agent can retry with a different approach

  Scenario: Role-based authorization denied
    Given a pending approval exists with id "appr-002" requiring "architect" role
    And the current user has role "developer"
    When the user tries to approve the approval
    Then the response status code is 403
    And the approval status remains "pending"
