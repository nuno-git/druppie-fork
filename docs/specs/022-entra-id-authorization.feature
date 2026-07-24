# @status active
# @superseded_by
# @adr docs/adrs/023-entra-id-identity-brokering.md
# @prd docs/prds/024-entra-id-integration.md

# Spec (executable Gherkin) for Entra ID identity brokering via Keycloak with OBO token exchange.
#
# Traceability: the @prd / @adr tags below link this behaviour back to the PRD and ADR that
# motivated it.
#
# LATER (PBI 9744 — afdwingen): the behave runner + Python step definitions in docs/specs/steps/
# (incl. environment.py) and the `behave` dependency are set up in PBI 9744. This template is the
# skeleton only — the scenarios below are not yet executable until that harness exists.

@prd docs/prds/024-entra-id-integration.md
@adr docs/adrs/023-entra-id-identity-brokering.md
Feature: Entra ID Authorization
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  # ─────────────────────────────────────────────────────────────────────────
  # Login flow
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Entra ID login with allowlisted email creates a session and data source queries work
    Given the user's email "user@example.com" is in the ENTRA_ALLOWED_EMAILS list
    When the user authenticates through the "Sign in with Microsoft" flow
    Then Keycloak creates a brokered account linked to the Microsoft identity
    And the brokered account is assigned the "developer" role
    And the user lands on the Druppie dashboard with an active session
    When the user asks an agent to query an Azure SQL data source
    Then the backend performs an OBO token exchange for the Azure SQL scope
    And the query executes under the user's identity
    And results are returned to the agent

  Scenario: Entra ID login with non-allowlisted email is rejected
    Given the user's email "unknown@external.com" is NOT in the ENTRA_ALLOWED_EMAILS list
    When the user authenticates through the "Sign in with Microsoft" flow
    Then the login is rejected at the Keycloak IdP level
    And the user sees an access denied message
    And no Druppie session is created

  # ─────────────────────────────────────────────────────────────────────────
  # Local account isolation
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Local Keycloak account without Entra ID works normally for non-Azure features
    Given the user has a local Keycloak account (no Entra ID link)
    When the user logs in with their local credentials
    Then all non-Azure features work normally
    And the user can create projects, run agents, and view dashboards
    When the user attempts to query an Azure SQL data source that requires OBO auth
    Then the request fails with an "Entra ID not linked" error
    And the user is prompted to link their Entra ID account

  # ─────────────────────────────────────────────────────────────────────────
  # Session state machine
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: paused_entra_auth session state triggers authorization popup and auto-resumes
    Given the user has an active session with an Entra ID identity
    When the broker token approaches expiry (within 60s margin)
    Then the session transitions to "paused_entra_auth" state
    And the frontend displays an authorization popup
    When the user completes the re-authentication flow
    Then the session auto-resumes to its previous active state
    And subsequent Azure queries succeed with a fresh token

  # ─────────────────────────────────────────────────────────────────────────
  # Token expiry
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Token expiry within margin triggers forced re-auth
    Given the user has an active OBO-exchanged token for Azure SQL
    When the token's remaining lifetime falls below 60 seconds
    Then the backend treats the token as expired
    And a fresh OBO exchange is triggered before the downstream call
    And the downstream call succeeds with the new token
    When the broker token itself has expired and cannot be refreshed
    Then the session transitions to "paused_entra_auth"
    And the user must re-authenticate through the authorization popup

  # ─────────────────────────────────────────────────────────────────────────
  # Avatar fetch
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Avatar fetch from Microsoft Graph is cached on disk with 24h TTL
    Given the user has an active Entra ID session
    When the frontend requests the user's profile avatar
    Then the backend performs an OBO exchange for the Microsoft Graph scope
    And fetches the avatar photo from Graph API
    And the avatar is cached to disk
    When the avatar is requested again within 24 hours
    Then the cached copy is served without a new Graph API call
    When the avatar is requested after 24 hours
    Then a fresh copy is fetched from Graph API and the cache is updated

  # ─────────────────────────────────────────────────────────────────────────
  # Connected Services page
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Connected Services page shows Entra link status for Azure DevOps and Azure SQL
    Given the user has an active Entra ID session
    When the user navigates to the Connected Services page
    Then the page shows the user's Entra ID identity (email, tenant)
    And for each configured Azure SQL source with OBO auth, the page shows "Connected via Entra ID"
    And for Azure DevOps, the page shows "Connected via Entra ID"
    Given the user has no Entra ID session
    When the user navigates to the Connected Services page
    Then the page shows "Not connected" for Entra ID
    And provides a "Sign in with Microsoft" button
