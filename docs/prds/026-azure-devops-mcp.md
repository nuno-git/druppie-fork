---
id: "026"
title: "Azure DevOps MCP Server"
status: approved
author: nuno
date: 2026-07-17
supersedes: null
superseded_by: null
linked_adrs: ["docs/adrs/027-azure-devops-mcp-architecture.md"]
linked_research: []
linked_specs: []
linked_workitem: null
---

# PRD 026: Azure DevOps MCP Server

## Problem

Agents cannot access Azure DevOps backlogs. Product owners, business analysts, and developers need to read, create, and update work items, manage board columns, and add comments — all through natural language agent interaction. Without this, every backlog operation requires a manual trip to the Azure DevOps web UI, breaking the agent-driven workflow.

The backlog is the single source of truth for what the team is working on. An agent that cannot see or change the backlog cannot plan, prioritize, or report progress. The gap forces users to context-switch between Druppie and Azure DevOps, undermining the promise of a unified AI workforce.

## Goal

An MCP server that provides read and write access to Azure DevOps backlogs, with HITL approval gating for all mutation operations. Agents can query backlogs, inspect work item details, create and update work items, manage board columns, and read or add comments — all through a consistent tool interface. Write operations require explicit human approval before reaching Azure DevOps.

**Definition of done:** A product owner agent can query the backlog, create a new user story, move it to the correct board column, and add a comment — all through natural language, with each write operation gated by human approval.

## User Journey

1. User asks "What's in the current sprint backlog?"
2. Product owner agent calls `query_backlog` with sprint filter.
3. System returns work items with ID, title, state, assigned to, and tags.
4. User asks "Create a new user story for login SSO."
5. Agent calls `create_work_item` with title and type.
6. System pauses — HITL approval prompt appears.
7. User approves the creation.
8. Work item is created in Azure DevOps.
9. Agent confirms with the new work item ID and URL.
10. User asks "Move it to In Progress and add a note."
11. Agent calls `update_work_item` with the board column change.
12. System pauses — HITL approval prompt appears.
13. User approves.
14. Agent calls `add_work_item_comment` with the note.
15. System pauses — HITL approval prompt appears.
16. User approves.
17. Agent confirms the update.

## Constraints

- Single-project scoping: each MCP connection is bound to exactly one Azure DevOps project. No cross-project access.
- All write operations (create, update, add comment, change board column) require HITL approval. Read operations are unrestricted.
- Authentication via service principal (PAT or managed identity). No per-user credential management.
- WIQL queries must escape user-provided strings to prevent injection.
- The `board_column` field must be managed alongside `state` — multiple board columns can share the same state, so setting state alone does not reliably control board position.
- Must support Azure Foundry Claude auto-detection for Entra ID users.

## Out of Scope

- Multi-project access (each connection is single-project).
- Sprint planning automation (creating sprints, assigning capacity).
- Test plan management (test cases, test suites, test runs).
- Pipeline access (builds, releases, artifacts).
- Wiki access (Azure DevOps wiki pages).
- Per-user OBO authentication (shared service principal only for now).

## Open Questions

None blocking — all architectural decisions are captured in ADR 027.

## Linked Documents

- ADR 027: `docs/adrs/027-azure-devops-mcp-architecture.md` — Architecture decisions (single-project scoping, HITL gating, board_column vs state, WIQL escaping, product owner agent)
