# @status active
# @superseded_by
# @adr 010-layered-approval-model.md
# @prd docs/prds/010-approval-workflow-system.md
@adr docs/adrs/010-layered-approval-model.md
@prd docs/prds/010-approval-workflow-system.md
Feature: Layered approval model
  # The "why" (problem, goal, user journey) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Tool with a global default approval requirement pauses for a human
    Given a tool whose global default in mcp_config.yaml requires approval
    And a required_role of "developer" for that tool
    When an agent invokes the tool
    Then the ToolExecutor creates an Approval record linked to the ToolCall
    And the agent run pauses with status "waiting_approval"
    And the tool does not execute until an approval is granted

  Scenario: Tool with no global approval requirement runs freely
    Given a tool whose global default requires no approval
    And no per-agent override for that tool
    When an agent invokes the tool
    Then the tool executes immediately
    And no Approval record is created

  Scenario: Per-agent override tightens a freely-running tool to require approval
    Given a tool whose global default requires no approval
    And an agent YAML with an approval_overrides entry that sets requires_approval to true
    When that agent invokes the tool
    Then the effective rule requires approval
    And the ToolExecutor creates an Approval record and pauses the run

  Scenario: Per-agent override sets the required approving role
    Given an agent YAML with an approval_overrides entry for coding:write_file
    And the override sets required_role to "architect"
    When that agent invokes coding:write_file
    Then the Approval record requires a user with the "architect" role

  Scenario: Approval is only accepted from a user with the required role
    Given a pending Approval with required_role "architect"
    When a user without the "architect" role attempts to approve
    Then the approval is rejected
    When a user with the "architect" role approves
    Then the Approval is granted
    And the agent run resumes and the tool executes

  Scenario: Effective rule is the global default overridden by the agent entry
    Given a global default for a tool
    And a per-agent approval_overrides entry for the same tool
    When the ToolExecutor computes the effective rule for that agent and tool
    Then the per-agent override takes precedence over the global default
    And the resolution requires no code change in the ToolExecutor
