@prd docs/prds/004-agent-runtime.md
@adr docs/adrs/004-agent-runtime.md
Feature: Native Agent Runtime
  # Acceptance criteria for the agent runtime library.

  Scenario: Agent completes after calling done() with required variables
    Given an agent defined with done_variables "plan" and "scope"
    When the agent calls the done tool with values for plan and scope
    Then the agent run completes with status "completed"
    And the output variables are stored on the run

  Scenario: Agent cannot complete without calling done()
    Given an agent defined with done_variables "plan"
    When the agent stops calling tools without invoking done
    Then the agent run does not complete
    And the loop continues until done is called or the turn limit is hit

  Scenario: Subagent spawning creates a child agent run
    Given a parent agent with the subagents tool available
    When the parent calls subagents with a target agent id and prompt
    Then a child agent run is created with parent_run_id set
    And the parent waits until the child run finishes

  Scenario: Context compaction triggers when context exceeds threshold
    Given an agent run with a context token count above the compaction threshold
    When the next turn begins
    Then the prior turns are summarized by the LLM
    And the compacted summary replaces the older messages

  Scenario: Cancellation propagates to running agent loop
    Given an agent run that is currently executing
    When a cancellation request is issued for the run
    Then the loop stops after the current tool call finishes
    And the run status is set to "cancelled"

  Scenario: Tool call routes through MCP server based on agent YAML config
    Given an agent YAML defining mcps from the module-coding server
    When the agent requests a tool provided by module-coding
    Then the ToolExecutor dispatches the call to the module-coding MCP server
    And the result is returned to the agent loop

  Scenario: Agent pauses for human-in-the-loop approval and resumes after approval
    Given an agent that invokes a tool requiring approval
    When the tool call is detected as gated
    Then the run suspends with status "pending_approval"
    When the approver approves the request
    Then the run resumes and the tool executes

  Scenario: Per-agent sandbox created based on git_scope property
    Given an agent YAML with git_scope set to "feature/foo"
    When the agent run starts
    Then the module-coding server provisions a sandbox container for that scope
    And the agent MCP tool calls execute inside that sandbox
