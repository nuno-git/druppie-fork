---
id: "024"
title: Entra ID Integration (Azure Entra ID identity brokering via Keycloak)
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs:
  - docs/adrs/023-entra-id-identity-brokering.md
linked_research: []
linked_specs:
  - docs/specs/022-entra-id-authorization.feature
linked_workitem: null
---

# PRD 024: Entra ID Integration

> **Where this fits:** The PRD is the START of the spec-driven pipeline. Everything flows
> from here: PRD -> Research (optional, only when unclear) -> ADR (decision) -> Spec (verification)
> -> Implementation. The PRD describes the PROBLEM and the GOAL from the user's perspective.
> It does NOT contain technical decisions (that's ADRs) or executable tests (that's Specs).

## Problem

Users of Druppie need delegated access to Azure resources through their own Entra ID identity. Currently, all Azure data access (Azure Synapse SQL, Azure Data Lake, Azure DevOps) goes through shared service principals or static connection strings. This means:

- Audit logs show a generic service principal, not the actual user who performed the query.
- Users cannot access Azure resources that are scoped to their individual Entra ID permissions.
- The platform cannot enforce per-user access control on Azure data sources.
- ADR 020's `azure-sql-obo` source type uses a shared `client_credentials` grant, which was explicitly documented as "interim" with true per-user OBO as a follow-up.

Without this feature, Druppie cannot operate in environments where Azure resource access must be tied to the authenticated user's identity rather than a shared credential.

## Goal

End-to-end Entra ID integration via Keycloak identity brokering with OBO token exchange. Users authenticate through their own Microsoft Entra ID account (brokered through Keycloak), and the platform exchanges the broker token for scoped access tokens to Microsoft Graph, Azure SQL, and Azure DevOps. All token handling is memory-only with no persistence. The session state machine handles the authorization popup flow gracefully.

## User Journey

1. User navigates to Druppie login and selects "Sign in with Microsoft".
2. User authenticates through Microsoft Entra ID (email, password, MFA).
3. Keycloak creates a brokered account linked to the Microsoft identity and assigns the `developer` role.
4. If the user's email is not in the `ENTRA_ALLOWED_EMAILS` allowlist, login is rejected.
5. User lands in Druppie with their Microsoft identity. The session is active.
6. User asks an agent to query Azure Synapse SQL. The agent calls a data-access tool.
7. Backend detects the user has an Entra ID identity, performs OBO token exchange for the Azure SQL scope, and passes the scoped token to the data-access MCP.
8. The query runs under the user's identity. Results return to the agent.
9. User asks the agent to list Azure DevOps pipelines. Same OBO flow for the Azure DevOps scope.
10. User's profile avatar is fetched from Microsoft Graph and cached on disk (24h TTL).
11. When the broker token approaches expiry (within 60s margin), the session transitions to `paused_entra_auth` and the frontend shows an authorization popup.
12. User re-authenticates through the popup. The session auto-resumes.

## Constraints

- Must use Keycloak as the identity broker (not direct Entra auth) to keep all auth in one place.
- Tokens must be memory-only, never persisted to the database.
- Email allowlist must gate login at the IdP level.
- Session state machine must handle the `paused_entra_auth` state with auto-resume.
- Token expiry must be tracked with a 60s safety margin.
- All 25 security review findings must be fixed before the feature ships.
- The implementation must supersede the "interim" `azure-sql-obo` path from ADR 020.

## Out of Scope

- Auto-linking of local Keycloak accounts with Microsoft-brokered accounts (deferred to a follow-up).
- TLS certificate provisioning for Azure SQL connections (backlogged).
- JWT signature verification on Entra tokens (mitigated by TLS to Keycloak broker).
- Dynamic Entra ID group-based role assignment (email allowlist only for now).
- Token persistence for long-running agent tasks (memory-only by design).
- Multiple IdP support (Entra ID only for now).

## Open Questions

None. All architectural decisions were resolved during implementation and are recorded in ADR 023.

## Linked Documents

- **ADRs:** docs/adrs/023-entra-id-identity-brokering.md
- **Research:** None
- **Specs / Feature files:** docs/specs/022-entra-id-authorization.feature
