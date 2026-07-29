---
id: "036"
title: "Use regex detection and Identity Picker API for @mention resolution"
status: accepted
date: 2026-07-27
deciders:
  - sjoerd
supersedes: null
superseded_by: null
linked_prd: "docs/prds/031-devops-mention-resolution.md"
linked_research: null
---

## Context

Azure DevOps requires `<a href="#" data-vss-mention="version:2.0,{GUID}">@Name</a>` HTML for working mentions. The MCP module passes text through unchanged. We need to detect mention patterns, resolve names to GUIDs, and replace before posting.

## Decision

1. **Regex-based detection:** `_MENTION_RE` matches `@Lastname, Firstname` (comma branch) and `@Firstname Lastname` (space branch with uppercase-only trailing words to avoid capturing prose). Trade-off: multi-word lowercase particles like "van der" need comma format.

2. **Identity Picker API** (POST `vssps.dev.azure.com/_apis/identitypicker/identities`): used over the older GET Identities API because it is more reliable, returns richer data, and matches what the DevOps web UI uses. The `localId` field provides the GUID needed for mentions.

3. **In-memory cache:** 1-hour TTL, caches both hits and misses. Resets on container restart. Same pattern as other MCP modules.

4. **Null-localId filtering:** Some Azure AD identities (e.g. admin accounts) have no `localId`. The resolution logic filters these out and prefers identities with a valid GUID.

5. **Three call sites:** `add_work_item_comment` (text), `create_work_item` (description), `update_work_item` (description). Titles are not processed (plain text only in DevOps).

6. **New `resolve_user` tool:** Exposes identity lookup for agents to verify names before mentioning. Read-only, no approval required.

## Consequences

**Positive:**
- Mentions work transparently, agents don't need to know about GUIDs, cached lookups are fast.
- Graceful degradation: unresolved mentions remain as plain text rather than causing errors.
- The `resolve_user` tool gives agents a way to verify names before writing mentions.

**Negative:**
- Regex cannot perfectly distinguish names from prose in all cases (mitigated by uppercase-only trailing words and API validation).
- The `vssps` subdomain derivation assumes modern `dev.azure.com` URL format (legacy `visualstudio.com` URLs would need adjustment).
- In-memory cache resets on container restart. This is acceptable because the cache is purely an optimization -- every resolution still calls the Identity Picker API on cache miss.
