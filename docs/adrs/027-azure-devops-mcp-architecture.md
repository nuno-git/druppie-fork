---
id: "027"
title: "Azure DevOps MCP Server Architecture"
status: accepted
date: 2026-07-17
deciders:
  - nuno
supersedes: null
superseded_by: null
linked_prd: docs/prds/026-azure-devops-mcp.md
linked_research: null
---

# ADR 027: Azure DevOps MCP Server Architecture

## Context

Druppie agents need to interact with Azure DevOps backlogs — reading work items, creating and updating them, managing board columns, and adding comments. The backlog is the team's single source of truth for what to build, and agents that cannot see or change it cannot plan, prioritize, or report progress.

The forces at play:

- **Security boundary.** Azure DevOps contains sensitive project data (user stories, bugs, epics, feature requests). Write access must be gated. Read access should be open so agents can discover and report without friction.
- **Project isolation.** Each Azure DevOps project is a separate trust boundary. An agent scoped to one project must not accidentally read or write another project's data.
- **Authentication model.** Agents run unattended. Per-user credential management (each agent logging in as a different user) does not scale. A shared service principal with scoped permissions is the practical choice.
- **Board column semantics.** Azure DevOps Kanban boards allow multiple columns to share the same work item state (e.g., "In Progress" and "In Review" both map to "Committed"). Setting `state` alone does not reliably move an item to the correct board column. The board column is stored in a team-specific WEF (Work Item Extensibility Framework) field like `WEF_ABC123_Kanban.Column`.
- **Injection risk.** WIQL (Work Item Query Language) is a SQL-like query language. User-provided strings in WIQL queries must be escaped to prevent injection attacks.
- **Agent routing.** Backlog queries are a natural fit for the product owner role. The planner must route backlog-related requests to the right agent.
- **Azure Foundry integration.** When running on Azure Foundry with Claude, Entra ID users should be auto-detected for seamless authentication.

PRs #248 and #249 implemented the Azure DevOps MCP server in four commits:

1. **Read-only backlog access** (`7808d79f`): `query_backlog`, `get_work_item`, `search_work_items` tools with single-project isolation.
2. **Write operations with HITL** (`b24661e8`): `create_work_item`, `update_work_item` tools gated by human approval.
3. **Comment tools** (`2dff240b`): `get_work_item_comments`, `add_work_item_comment` tools, with `add_work_item_comment` HITL-gated.
4. **board_column fix** (`d8bae0bb`, `157ed671`): `board_column` parameter on `update_work_item` that discovers and patches the team-specific WEF Kanban.Column field. State and board_column cannot both be set in the same call — they conflict because board_column automatically updates the state.

## Decision

Adopt the following architecture for the Azure DevOps MCP server (`druppie/mcp-servers/module-azuredevops/`):

### Single-Project Scoping

Each MCP connection is bound to exactly one Azure DevOps project. The project is configured at connection time via environment variables (`AZURE_DEVOPS_ORG`, `AZURE_DEVOPS_PROJECT`). All API calls are scoped to that project. This isolates access and prevents cross-project leakage. A second project requires a separate MCP server instance.

### Service Principal Authentication

Authentication uses a shared service principal via Azure DevOps PAT (Personal Access Token) or managed identity. The PAT is configured as `AZURE_DEVOPS_PAT` in the environment. This avoids per-user credential management and provides consistent auth for all agents. On Azure Foundry with Claude, Entra ID users are auto-detected for seamless authentication.

### HITL Gating for All Write Operations

All mutation operations require human approval before reaching Azure DevOps:

- `create_work_item` — HITL gate
- `update_work_item` — HITL gate
- `add_work_item_comment` — HITL gate
- `change_board_column` (via `update_work_item`) — HITL gate

Read operations (`query_backlog`, `get_work_item`, `search_work_items`, `get_work_item_comments`) are unrestricted. The HITL gate is implemented at the tool level in `tools.py` using Druppie's existing approval workflow (PRD 010, ADR 010).

### board_column Managed Alongside state

The `board_column` parameter on `update_work_item` discovers the team-specific WEF Kanban.Column field by querying the board metadata and patches it directly. This ensures board moves work as expected from the Kanban board perspective. State and board_column cannot both be set in the same call — they conflict because board_column automatically updates the state. The tool rejects calls that set both.

### WIQL Escaping Strategy

All user-provided strings in WIQL queries are escaped to prevent injection. String literals are wrapped in single quotes with internal single quotes doubled (WIQL escaping convention). Numeric and identifier fields are validated against expected types before inclusion. The escaping is applied in the client layer (`client.py`) before the query reaches the Azure DevOps API.

### Product Owner Agent

A new product owner agent (`druppie/agents/definitions/product_owner.yaml`) is wired with the Azure DevOps MCP tools. The planner routes backlog-related queries to this agent based on intent classification. The agent has access to all Azure DevOps tools (read and write) and relies on the HITL gate for mutation operations.

### Azure Foundry Claude Auto-Detection

When running on Azure Foundry with Claude, the MCP server auto-detects Entra ID users and uses their identity for authentication. This is configured via `AZURE_FOUNDRY_ENABLED` and related environment variables. When auto-detection is active, the PAT is used as a fallback for non-Entra-ID operations.

## Consequences

**Positive.** Natural language backlog management — agents can query, create, update, and comment on work items without leaving the Druppie interface. HITL gates prevent unauthorized mutations: every write operation requires explicit human approval, matching Druppie's governance model. Single-project isolation prevents accidental cross-project data access. Escape-safe queries protect against WIQL injection. The product owner agent gives backlog operations a natural home in the planner routing. The board_column fix ensures Kanban board moves work correctly even when multiple columns share the same state.

**Negative.** Single-project only — cross-project views (e.g., "show me all open bugs across all projects") require separate MCP server instances or a separate integration. PAT rotation is manual — there is no automated credential rotation for the service principal. No sprint or planning support — sprint management, capacity planning, and velocity tracking are out of scope. New agent to maintain — the product owner agent adds to the agent catalog and requires ongoing maintenance. State and board_column cannot be set together — callers must choose one or the other, which may require two sequential calls for some workflows.
