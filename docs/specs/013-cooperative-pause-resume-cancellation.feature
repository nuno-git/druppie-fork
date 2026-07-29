# @status active
# @superseded_by
# @adr docs/adrs/013-cooperative-pause-resume-cancellation.md
# @prd docs/prds/011-session-lifecycle-management.md
@adr docs/adrs/013-cooperative-pause-resume-cancellation.md
@prd docs/prds/011-session-lifecycle-management.md
Feature: Cooperative Pause, Resume, and Cancellation
  # The "why" (problem, goal, motivation) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: User-initiated stop sets the session status to paused
    Given a session whose status is "active"
    When the user calls POST /api/chat/{session_id}/cancel
    Then the session status is set to "paused" in the database
    And the Continue button becomes visible in the UI

  Scenario: The agent stops at the next checkpoint, not mid-call
    Given an agent loop currently inside an LLM call when a stop is requested
    When the in-flight LLM call and tool execution complete
    Then the loop halts at the next checkpoint between LLM iterations
    And no in-flight call is interrupted mid-execution

  Scenario: The orchestrator checks status before each agent run and after each completes
    Given a session with multiple pending agent runs and status "paused"
    When the orchestrator reaches the next checkpoint
    Then it stops executing further agent runs
    And no additional agent run is started

  Scenario: Resume reconstructs state from the DB and continues
    Given a paused session with persisted LlmCall and ToolCall records
    When the user calls POST /api/sessions/{session_id}/resume
    Then a background task calls reconstruct_from_db to rebuild the conversation
    And the agent loop continues from the iteration where it paused
    And after the current agent completes the orchestrator continues remaining pending runs

  Scenario: Automatic pause on a tool requiring approval
    Given an agent that calls a tool requiring approval
    When the ToolExecutor processes that tool call
    Then an Approval record is created and the agent run is marked paused_tool
    And the orchestrator stops executing further agents until the approval is resolved
    When the approval is approved and resume_after_approval runs
    Then the agent continues the paused tool and then the loop

  Scenario: Automatic pause on a HITL question
    Given an agent that calls a HITL question tool
    When the ToolExecutor processes that tool call
    Then a Question record is created and the agent run is marked paused_hitl
    When the user answers and resume_after_answer runs
    Then the answer is saved to the tool call result and the agent loop continues

  Scenario: Zombie session recovery marks orphaned active sessions as paused on startup
    Given sessions in "active" status when the server previously stopped
    When the backend starts up
    Then each orphaned active session is marked "paused"
    And the user can resume each via the Continue button

  Scenario: cancelled status is internal-only and never set by user actions
    Given a new plan created by the planner that supersedes previously pending agent runs
    When the planner records the new plan
    Then the superseded pending runs are marked cancelled
    But a user calling the cancel endpoint never produces a cancelled session
