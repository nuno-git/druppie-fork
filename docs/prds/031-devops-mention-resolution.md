---
id: "031"
title: "Azure DevOps @mention resolution in comments and descriptions"
status: implemented
author: sjoerd
date: 2026-07-27
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/036-devops-mention-resolution.md"]
linked_research: []
linked_specs: []
linked_workitem: "https://dev.azure.com/MSF-WBS/AI-platform/_workitems/edit/9974"
---

# PRD 031: Azure DevOps @mention resolution in comments and descriptions

## Problem

When agents write `@Display Name` in work item comments or descriptions via the Azure DevOps MCP, it appears as plain text -- no notification is sent. Azure DevOps requires a specific HTML format with the user's identity GUID for working mentions. This breaks team workflows where agents tag people for review.

## Goal

Automatically resolve `@Display Name` patterns to Azure DevOps identity GUIDs and replace with the HTML mention format that triggers notifications. Works transparently -- agents don't need to change how they write mentions.

## User Journey

1. Agent calls `add_work_item_comment` with text containing `@Noordam, Pieter please review`
2. MCP server detects the `@Name` pattern via regex
3. Server resolves "Noordam, Pieter" to identity GUID via the Identity Picker API
4. Plain-text mention is replaced with `<a href="#" data-vss-mention="version:2.0,{GUID}">@Noordam, Pieter</a>`
5. Comment is posted -- Pieter receives a notification in Azure DevOps

## Constraints

- Regex-based detection: matches `@Lastname, Firstname` (comma format) and `@Firstname Lastname` (space format, uppercase-only trailing words)
- Identity Picker API (POST to `vssps.dev.azure.com`) used for resolution
- In-memory cache with 1-hour TTL; caches misses to avoid repeated API calls
- Graceful degradation: unresolved mentions stay as plain text
- Applied in three paths: `add_work_item_comment`, `create_work_item` (description), `update_work_item` (description)

## Out of Scope

- Mentions in titles (titles are plain text, no HTML support)
- Auto-completing partial names (the regex captures the full pattern as-is)
- Multi-word lowercase name particles like "van der" in space format (use comma format instead)

## Open Questions

None blocking -- architectural decisions are captured in ADR 036.

## Linked Documents

- ADR 036: `docs/adrs/036-devops-mention-resolution.md` -- Architecture decisions (regex detection, Identity Picker API, in-memory cache, call sites)
