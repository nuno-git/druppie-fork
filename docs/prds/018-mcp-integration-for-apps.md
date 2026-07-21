---
id: "018"
title: "MCP Server Integration for Generated Applications"
status: draft
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: ["docs/research/003-module-convention.md"]
linked_specs: []
---

# PRD 018: MCP Server Integration for Generated Applications

## Problem

The Developer agent writes standalone applications with no standardized way to consume Druppie's own MCP servers (coding, docker, web, file search, data access). Each generated app that needs these capabilities builds its own bespoke integration, resulting in inconsistency and duplicated effort.

## Goal

A skill (prompt/template) that teaches the Developer agent how to integrate Druppie's core MCP servers into generated applications following a standardized pattern. The skill auto-updates with the currently available MCP servers and tools so the Developer always has an up-to-date view.

## User Journey

1. Developer agent receives a requirement: "The app should read data from Azure SQL."
2. Developer invokes the MCP integration skill.
3. Skill returns the current catalog of available MCP servers + integration patterns.
4. Developer writes code that connects to the data-access MCP via the SDK.
5. Generated app can call data-access tools at runtime through the standard SDK path.

## Constraints

- Depends on MCP versioning (stable API contracts for core MCP servers).
- Depends on the skills system (already implemented).
- Skill content must dynamically reflect available MCP servers (not hardcoded).
- Integration pattern must work for both agents (session context) and apps (app context).

## Out of Scope

- Custom MCP servers per generated app (apps use Druppie's existing MCP servers).
- MCP server auto-discovery at app runtime (compile-time skill is sufficient).

## Open Questions

None blocking — depends on MCP versioning landing first.

## Linked Documents

- Research: Research 003 (`docs/research/003-module-convention.md`) — Module Convention
- PRD: PRD 008 (`docs/prds/008-module-system.md`) — Module System
- Source: `docs/BACKLOG.md` — "Skill: MCP Server Integration for Generated Applications"
