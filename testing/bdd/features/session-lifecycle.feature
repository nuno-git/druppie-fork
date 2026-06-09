Feature: Session Lifecycle Management
  Sessions track the full lifecycle of an agent conversation including
  pause, resume, and crash recovery.

  Background:
    Given the API is running
    And a test database is available

  Scenario: User stops active session
    Given an active session exists with id "sess-001"
    When the user sends a stop request for the session
    Then the session status becomes "paused"
    And the session can be resumed later

  Scenario: Resume paused session
    Given a paused session exists with id "sess-002"
    And the session has agent state saved
    When the user sends a resume request for the session
    Then the session status becomes "active"
    And the agent continues from where it left off

  Scenario: Zombie session recovery on server restart
    Given sessions "sess-zombie-1" and "sess-zombie-2" were active at server shutdown
    When the server starts up
    Then those sessions are marked as "paused_crashed"
    And the user can manually resume them via the resume endpoint
