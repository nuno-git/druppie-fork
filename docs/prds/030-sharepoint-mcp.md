---
id: "030"
title: "SharePoint MCP Server"
status: implemented
author: sjoerd
date: 2026-07-21
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/035-sharepoint-mcp-architecture.md"]
linked_research: []
linked_specs: []
linked_workitem: "https://dev.azure.com/MSF-WBS/AI-platform/_workitems/edit/9254"
---

# PRD 030: SharePoint MCP Server

## Problem

Agents cannot access documents stored in SharePoint. Users frequently reference SharePoint files during conversations (data dictionaries, policy documents, project specs) but agents have no way to browse or read them. This forces users to manually copy-paste content from SharePoint into the chat, breaking the conversational flow and losing document context (source, version, path).

The data analyst agent can discover datasets in Azure Data Lake and SQL, but SharePoint — where most organizational documents live — is a blind spot. Without access, agents cannot answer questions like "what does the data dictionary say about this field?" or "find the project charter on SharePoint."

## Goal

An MCP server that provides read-only access to SharePoint sites via Microsoft Graph API, using delegated (OBO) authentication so agents read as the logged-in user. Agents can discover sites, browse folder structures, search for files, and read text content — all scoped to the user's existing SharePoint permissions.

**Definition of done:** A data analyst agent can discover available SharePoint sites, get a folder-level overview of a site, find a specific file by keyword, and read its text content — all through natural language, without the user having to leave the chat or copy-paste content.

## User Journey

1. User asks "What documents do we have on SharePoint about the data platform?"
2. Data analyst agent calls `list_sites` to discover accessible SharePoint sites.
3. System returns sites filtered by the server-side allowlist.
4. Agent calls `list_all_files` on the relevant site to get a folder-level summary.
5. System returns folder paths with file counts, sizes, and type breakdown.
6. Agent calls `search_files` with keyword "data platform" to find relevant documents.
7. System returns matching files with names, paths, and metadata.
8. Agent calls `read_file` on a text-based file (CSV, JSON, markdown).
9. System returns the file content inline.
10. Agent summarizes the document content for the user.
11. For Office files (docx, xlsx), agent shares the `web_url` so the user can view in browser.

## Constraints

- Read-only access only. No file creation, upload, modification, or deletion.
- OBO (On-Behalf-Of) authentication: agents access SharePoint as the logged-in user, not as a service principal. Requires Entra ID brokering.
- Site allowlist (`SHAREPOINT_ALLOWED_SITES`) restricts which sites agents can access, regardless of user permissions. Three modes: `all`, empty (block all), or semicolon-separated site URLs.
- Graph site IDs contain commas (`hostname,guid1,guid2`), so the allowlist delimiter must be semicolons.
- Text content is returned inline only for text-based files. Binary/Office files return metadata with a `web_url` for browser viewing.
- The `list_all_files` tool returns folder-level summaries (not individual files) to avoid overflowing agent context on large drives.
- App Registration requires delegated permissions: `Files.Read.All` and `Sites.Read.All`.

## Out of Scope

- Write operations (upload, create, modify, delete files).
- SharePoint Lists or other non-file content.
- OneDrive personal drives (only SharePoint sites).
- Inline rendering of Office documents (docx, xlsx, pptx) — agents share the web_url instead.
- Per-user allowlists (the site allowlist is server-wide).
- Delta sync / incremental updates (the delta endpoint is used for full tree enumeration, not change tracking).

## Open Questions

None blocking — architectural decisions are captured in ADR 035.

## Linked Documents

- ADR 035: `docs/adrs/035-sharepoint-mcp-architecture.md` — Architecture decisions (OBO auth, URL-based allowlist, folder-summary approach, env var conventions)
