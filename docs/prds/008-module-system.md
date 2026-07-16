---
id: "008"
title: "Module System"
status: implemented
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: ["docs/research/003-module-convention.md"]
linked_specs: ["docs/specs/020-module-contract.feature"]
---

# PRD 008: Module System

## Problem

The platform needs to support capabilities beyond its core agent pipeline — OCR, data access, translation, ArchiMate generation, and more. Without a module system, each capability would be tightly coupled to the backend: adding a tool means modifying core code, deployment is monolithic, and versioning is all-or-nothing. Generated applications also need access to the same tools at runtime, but with different auth context than agents.

## Goal

Containerized MCP servers ("modules") that expose tools via the standard MCP protocol, are independently versioned (multiple major versions coexist via path-based routing), independently deployable, and callable by both Druppie agents (build-time, session context) and generated applications (runtime, app context). Each module manages its own storage, authenticates its own requests, and reports usage back to the caller.

**Definition of done:** A module author can create a `module-<name>/` directory with `MODULE.yaml` + versioned subdirectories, containerize it, and have it immediately discoverable by agents via `list_druppie_modules` and callable by applications via the SDK — with no core code changes.

## User Journey

1. Module author creates `druppie/mcp-servers/module-<name>/` with `MODULE.yaml` (id, latest_version, versions), `server.py` (root router), and `vN/` directories (one per major version).
2. Each `vN/tools.py` defines MCP tools via FastMCP `@mcp.tool()` decorators — this is the single source of truth for the tool contract.
3. Module is containerized via its `Dockerfile` and deployed as a Docker Compose service.
4. On startup, `mcp_config.yaml` registers the module container URL. The ToolRegistry discovers tools via MCP `tools/list`.
5. Agents (Architect, BA) discover available modules via the `list_druppie_modules` builtin — receiving module id, versions, tool schemas.
6. Agents invoke module tools. Standard arguments (`user_id`, `session_id` XOR `app_id`, `project_id`) are injected by the orchestrator.
7. Module authenticates the request via Keycloak JWT validation (`auth.py`), executes the tool, and returns `_meta` with usage info.
8. Caller (core or SDK) records usage (`module_usage` table or POST `/api/usage`).
9. When a breaking change is needed, a new `v2/` directory is added; `v1/` remains untouched; both serve simultaneously at `/v1/mcp` and `/v2/mcp`.

## Constraints

- Modules never connect to Druppie's PostgreSQL — they manage their own storage (own database or stateless).
- Druppie context (user_id, session_id, project_id) is received via injected MCP parameters, not by querying Druppie tables.
- Authentication is self-service: each module validates Keycloak JWTs against the JWKS endpoint. No API gateway proxy.
- Cross-version database changes are additive only: every new column has a DEFAULT; no DROP, RENAME, or ALTER TYPE.
- `user_id` is always required; exactly one of `session_id` / `app_id` must be set (agents set session_id, apps set app_id).
- MCP server categories bound reachability: `core` (agents only), `module` (apps only), `both` (agents + apps).

## Out of Scope

- Module marketplace or registry UI (modules are code, configured via `mcp_config.yaml`).
- Hot-reload of module definitions (requires container restart).
- Automatic module scaffolding from a template (manual directory creation).
- Cross-module orchestration (if a tool mainly calls other modules, it belongs in the application layer or as a skill).

## Open Questions

None: feature is implemented and in production.

## Linked Documents

- **Research:** Research 003 (`docs/research/003-module-convention.md`) — Module Convention design rationale
- **Specs:** `docs/specs/020-module-contract.feature` — Module contract acceptance scenarios
- **Technical reference:** `docs/guides/module-contract.md` — Full technical contract (MODULE.yaml structure, version system, SDK, auth, usage tracking, RBAC, DB tables)
