---
id: "035"
title: "Use OBO auth, URL allowlist, and folder summaries for SharePoint MCP"
status: accepted
date: 2026-07-21
deciders:
  - sjoerd
supersedes: null
superseded_by: null
linked_prd: "docs/prds/030-sharepoint-mcp.md"
linked_research: null
---

## Context

The platform needs read-only access to SharePoint documents for agents (data analyst, product owner). Key design questions: how to authenticate, how to restrict site access, and how to handle large drives without overflowing agent context.

The existing Entra ID brokering infrastructure provides OBO tokens scoped to the logged-in user. The Azure DevOps MCP uses a service principal, but SharePoint access should respect the user's own permissions (different users see different sites/files). The `ENTRA_ALLOWED_EMAILS` env var already controls which Entra accounts can use the platform, using a semicolon-separated format.

Graph API site IDs contain commas (`hostname,guid1,guid2`), which rules out comma-separated config values. A naive `list_all_files` tool that returns every file on a drive can produce thousands of items, exceeding the agent's context window.

## Decision

**Authentication:** Use delegated (OBO) authentication. Tokens are passed per-request from the orchestration layer via declarative parameter injection (`user_token` from `user.entra_token`, marked `hidden: true`). Tokens are never stored by the module. This reuses the existing Entra broker flow and ensures agents can only access what the user can access in SharePoint.

**Site allowlist:** Use `SHAREPOINT_ALLOWED_SITES` with the same three-mode convention as `ENTRA_ALLOWED_EMAILS`: `all` (no filtering), empty/unset (block all, fail-closed default), or semicolon-separated site URLs. Filtering is enforced server-side on all operations by comparing the Graph site's `webUrl` against the allowlist. Verified site IDs are cached in-memory to avoid redundant Graph lookups; the cache stores URL-allowlist decisions (server-wide config), not per-user authorization (which is enforced by Graph via the OBO token on every call).

**Folder summaries:** The `list_all_files` tool uses the Graph delta endpoint to enumerate the full drive tree, then aggregates into per-folder statistics (file count, total size, file type breakdown) instead of returning individual files. This scales to drives of any size — the response is proportional to the number of folders, not files. Agents use this to orient, then drill into specific folders with `list_files` or find files with `search_files`.

## Consequences

**Positive:**
- Agents read as the user — no over-privileged service principal, no credential management per user.
- Site allowlist gives platform operators control independent of SharePoint permissions.
- Folder summaries keep agent context small regardless of drive size, enabling a reliable orient → target → read workflow.
- Semicolon delimiter and three-mode convention are consistent with `ENTRA_ALLOWED_EMAILS`, reducing configuration surprises.

**Negative:**
- OBO tokens require the Entra broker to be configured and the user to have linked their Microsoft account. If either is missing, SharePoint tools are unavailable (graceful degradation, not an error).
- The URL-based allowlist requires the admin to know SharePoint site URLs. Graph site IDs would be more precise but are opaque and contain commas.
- Folder summaries add a server-side aggregation step. For very large drives, the delta call itself may take several seconds (paginated). This is still faster than the agent making N sequential `list_files` calls.
- The in-memory verified-IDs cache resets on container restart. This is acceptable because the cache is purely an optimization — every operation still checks the user's access via the OBO token at the Graph API level.
