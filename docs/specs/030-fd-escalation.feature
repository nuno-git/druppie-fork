# @status active
# @superseded_by
# @adr docs/adrs/038-fd-escalation-via-expert-hitl.md
# @prd docs/prds/032-fd-escalation.md

@prd docs/prds/032-fd-escalation.md
@adr docs/adrs/038-fd-escalation-via-expert-hitl.md
Feature: FD Escalation via expert HITL tools

  Scenario: Escalation triggers after threshold consecutive DESIGN_FEEDBACK rejections
    Given an architect agent definition with escalation_threshold set to 3
    And a session where the architect has returned DESIGN_FEEDBACK 3 times
    When the BA completes its revision and the planner runs
    Then the planner calls ask_expert_multiple_choice_question with expert_role="business_analyst"
    And the question includes the 4 standard escalation choices

  Scenario: Orchestrator overrides planner prompt when threshold reached
    Given a session with fd_rejection_count >= escalation_threshold
    When the BA agent completes
    Then the orchestrator overwrites the pending planner's planned_prompt with an escalation override
    And the override instructs the planner to call ask_expert_multiple_choice_question only

  Scenario: Expert selects Iterate
    Given an escalation question is pending for the business_analyst expert
    When the expert selects "Iterate" and adds a comment
    Then the planner routes to the BA with the expert's comment as primary directive
    And the planner re-escalates after the BA completes instead of routing to the architect

  Scenario: Expert selects Ready
    Given an escalation question is pending for the business_analyst expert
    When the expert selects "Ready" and adds a comment
    Then the planner routes to the architect with an override prompt
    And the override includes the expert's comment

  Scenario: Expert selects Escalate
    Given an escalation question is pending for the business_analyst expert
    When the expert selects "Escalate"
    Then the planner calls ask_expert_multiple_choice_question with expert_role="architect"
    And the architect expert question includes the BA expert's comment

  Scenario: Expert selects Terminate
    Given an escalation question is pending for the business_analyst expert
    When the expert selects "Terminate" and adds a reason
    Then the planner calls terminate_session with the expert's reason
    And the session status becomes TERMINATED
    And all pending agent runs are cancelled

  Scenario: terminate_session sets session to TERMINATED
    Given a session with pending agent runs
    When terminate_session is called with a reason
    Then the session status is set to "terminated"
    And all pending runs are cancelled
    And the tool returns status "terminated" with the reason

  Scenario: Escalation card shows 3-state rendering in the UI
    Given an escalation question appears in a session timeline
    When the question is unanswered
    Then the card shows amber styling with "Awaiting decision" text
    When the expert submits an answer
    Then the card shows blue styling with "Processing your decision" text
    When the answer is persisted
    Then the card shows gray styling with "Answered by" text

  Scenario: Escalation card shows documents under review
    Given an escalation question appears in a session with surfaced files from prior agent runs
    Then the escalation card shows a "Documents under review" section
    And each document is clickable to preview its content

  Scenario: Single-select enforcement on escalation choices
    Given an escalation question with 4 choices
    When the expert selects one choice and then selects another
    Then only the second choice remains selected
