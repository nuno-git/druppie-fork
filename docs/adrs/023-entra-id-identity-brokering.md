---
id: "023"
title: Entra ID identity brokering via Keycloak with OBO token exchange
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/024-entra-id-integration.md
linked_research: null
---

# ADR 023: Entra ID identity brokering via Keycloak with OBO token exchange

## Context

PR #294 implemented Entra ID identity brokering through Keycloak with on-behalf-of (OBO) token exchange. The PR spans 26 commits across 49 files and delivers the full auth flow: login, token exchange, scoped Azure access, and security hardening.

Before this decision, Druppie had no Entra ID integration. Users authenticated only through local Keycloak accounts. Azure data sources (Azure SQL, Azure Data Lake, Azure DevOps) were accessed through shared service principals or connection strings, not through the user's own identity. ADR 020 called the `azure-sql-obo` source type "interim" and flagged true per-user OBO as a follow-up. This PR delivers that follow-up.

The forces in play:

- **Delegated access.** Users need to access Azure Synapse SQL and Azure DevOps through their own Entra ID identity, not a shared service principal. This means per-user scoped tokens, not a single client_credentials grant.
- **Keycloak as the identity hub.** Druppie already uses Keycloak for local authentication. Adding Entra ID as an identity provider keeps the auth surface in one place rather than introducing a second auth path.
- **OBO token exchange.** The Keycloak broker token must be exchanged for service-specific tokens (Microsoft Graph, Azure SQL, Azure DevOps) without exposing the user's credentials to every downstream service.
- **Security review.** A dedicated security review of the implementation found 25 findings, all of which were fixed before merge. The accepted risks and backlogged items are documented below.
- **Session state management.** The OBO flow introduces an authorization popup that pauses the session. The session state machine needed a new state to represent this.

## Decision

### 1. Keycloak as Entra ID identity broker (not direct Entra auth)

Entra ID is configured as an **identity provider** in the Druppie Keycloak realm. Users authenticate through Keycloak's IdP-initiated login flow, not directly against Microsoft Entra ID. Keycloak handles the initial token exchange, session management, and IdP role mapping.

Why not direct Entra auth? Keycloak already manages Druppie's local user accounts, roles, and session lifecycle. Adding Entra ID as an IdP keeps all auth logic in one place, reuses the existing session infrastructure, and avoids maintaining a separate Entra auth path with its own token handling, logout, and session management.

### 2. Microsoft-brokered users are separate Keycloak accounts (no auto-linking)

When a user logs in through the Entra ID IdP, Keycloak creates a **new, separate** user account linked to the Microsoft identity. This account is distinct from any local Keycloak account the same person might have. There is no automatic account linking or SSO unification.

This is a deliberate choice: auto-linking would require matching on email or another identifier, which introduces account takeover risk if the IdP's email claim is not authoritative. Separate accounts keep the security boundary clear. Unification is deferred (see Consequences).

### 3. IdP role mapper grants the 'developer' role

A Keycloak IdP role mapper assigns the `developer` role (with its `read-token` composite) to every user who authenticates through the Entra ID IdP. This gives all Microsoft-brokered users the same baseline permissions. Finer-grained role assignment per Entra group or attribute is deferred.

### 4. OBO token exchange: broker token to scoped Azure tokens

The Keycloak broker token (obtained during IdP login) is exchanged for service-specific access tokens using the OAuth 2.0 On-Behalf-Of flow. Three token scopes are supported:

- **Microsoft Graph** (`https://graph.microsoft.com/.default`) — used for profile avatar fetch and user info.
- **Azure SQL** (configurable per source via `entra_scope` in `mcp_config.yaml`) — used for OBO-authenticated SQL queries.
- **Azure DevOps** (`https://app.vssps.visualstudio.com/.default`) — used for DevOps API access.

The exchange happens in the backend (`druppie/entra/`), not in the MCP server. The MCP server receives a pre-exchanged token scoped to its specific resource.

### 5. User-scoped tokens are memory-only, per-request lifetime

Tokens obtained through OBO exchange are held in memory for the duration of a single request and discarded immediately after. They are never written to the database, never cached to disk, and never serialized. Each request that needs a scoped token triggers a fresh OBO exchange.

This is a security-by-design choice: tokens are the most sensitive credential in the system. Not persisting them limits the blast radius of a database compromise or disk read.

### 6. Session state machine extended with `paused_entra_auth`

The session lifecycle (ADR 011) gains a new state: `paused_entra_auth`. When a user's session needs Entra ID authorization (e.g., the broker token has expired or a new scope is needed), the session transitions to `paused_entra_auth`. The frontend detects this state and shows an authorization popup. After the user completes the auth flow, the session auto-resumes to its previous active state.

### 7. Email allowlist gates login

The `ENTRA_ALLOWED_EMAILS` environment variable controls which Microsoft accounts can log in through the Entra ID IdP. It is a comma-separated list of email addresses. If the email from the Entra ID token is not in the list, the login is rejected at the Keycloak IdP level.

This is a blunt instrument (see Consequences) but provides a hard access control gate during the initial rollout.

### 8. Config-driven audience validation from `entra_scope`

Each Azure data source that supports OBO auth declares its required token scope in `mcp_config.yaml` under the `entra_scope` key. When the backend exchanges a broker token for a scoped token, it validates that the requested scope matches a known, configured scope. Unknown scopes are rejected before the exchange is attempted.

### 9. Token expiry tracking with 60s margin

The backend tracks token expiry for all OBO-exchanged tokens. If a token's remaining lifetime falls below 60 seconds, it is treated as expired and a fresh exchange is triggered. This prevents edge-case failures where a token expires between the exchange and the downstream call.

### 10. Accepted risks

Three risks were identified during the security review and accepted or backlogged:

| Risk | Status | Rationale |
|------|--------|-----------|
| `storeToken` + `offline_access` scopes requested from Entra ID | **Accepted** | Required for the OBO flow to obtain refresh tokens. The refresh token is stored in the Keycloak user session (not in Druppie's database). |
| TLS certificate validation on Azure SQL connections | **Backlogged** | The ODBC driver's `TrustServerCertificate` setting is configurable. Proper CA-signed cert provisioning is tracked as a follow-up. |
| JWT signature verification on Entra tokens | **Mitigated by TLS to KC broker** | Druppie does not verify Entra JWT signatures directly. Instead, all Entra tokens are obtained through the Keycloak broker over TLS. Keycloak verifies the IdP token; Druppie trusts Keycloak. |

### 11. Supersedes the "interim" status in ADR 020

ADR 020 documented `azure-sql-obo` as an interim solution using a shared `client_credentials` grant. This ADR and the accompanying PR #294 replace that interim path with true per-user OBO token exchange. The `azure-sql-obo` source type in ADR 020 is now superseded by the OBO flow described here.

## Consequences

Positive:

- **True OBO delegation.** Users access Azure resources through their own identity, not a shared service principal. Audit logs show the actual user, not a generic principal.
- **User-scoped Azure access.** Each user gets tokens scoped to their own permissions in Azure. No more shared credentials.
- **Security reviewed.** 25 findings from the dedicated security review were fixed before merge. The implementation has been through a structured security audit.
- **Single auth surface.** Keycloak remains the sole identity provider. Entra ID is an IdP behind Keycloak, not a parallel auth path.
- **Memory-only tokens.** No token persistence means no token leakage through database compromise.
- **Session-aware auth.** The `paused_entra_auth` state gives users a clear, resumable authorization flow without losing session context.

Negative:

- **Separate Keycloak accounts.** Users who have both a local Druppie account and an Entra ID login end up with two separate Keycloak accounts. No SSO unification means they may need to log in twice or manage two profiles.
- **Memory-only tokens, no persistence for long-running tasks.** Tokens are discarded after each request. Long-running agent tasks that need sustained Azure access must re-authenticate on each tool call, which adds latency and may fail if the broker token has expired.
- **Email allowlist is blunt.** The `ENTRA_ALLOWED_EMAILS` gate is a static list. Adding or removing users requires a deployment change. There is no integration with Entra ID groups or dynamic membership.
- **Keycloak broker is additional infrastructure dependency.** The OBO flow depends on the Keycloak broker being available and correctly configured. If Keycloak is down, Entra ID login is unavailable even if Microsoft Entra ID itself is reachable.
- **Token exchange latency.** Each OBO exchange adds a network round-trip to Microsoft Entra ID. For latency-sensitive operations (e.g., interactive SQL queries), this overhead is noticeable.
