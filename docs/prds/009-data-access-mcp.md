---
id: "009"
title: "Data Access MCP"
status: implemented
author: nuno
date: 2026-07-16
supersedes: null
superseded_by: null
linked_adrs: []
linked_research: []
linked_specs: ["testing/specs/features/data-access-mcp.feature"]
---

# PRD 009: Data Access MCP

## Problem

Agents (Business Analyst, Data Analyst) and generated applications need to read, query, and download data from heterogeneous enterprise sources — Azure Data Lake, Azure SQL (Synapse serverless) — without each building bespoke integration code. Without a unified data access layer, every agent that needs data writes its own adapter, duplicating auth logic, security boundaries, and connection management. Security is inconsistent and per-agent.

## Goal

A single MCP server with an adapter-based architecture that provides a unified tool set (`list_sources`, `test_connection`, `list_available_data`, `get_schema`, `read_data`, `execute_query`, `download_data`, `create_chart_from_source`) across all supported source types. Security boundaries are enforced centrally: read-only database access, workspace-bound downloads, injection guards on filter expressions, and per-role tool scoping.

**Definition of done:** An operator configures data sources via `DATA_SOURCE_N` env vars, and agents can immediately discover, browse, read, query, and chart from those sources through a single consistent tool set — with secrets never exposed and downloads never escaping the workspace.

## User Journey

1. Operator configures data sources in `.env` as `DATA_SOURCE_N=type:name:config_blob` (Azure Data Lake, Azure SQL, etc.) and recreates the container.
2. Agent calls `list_sources` → receives source catalog (id, type, name, auth_type) with no secrets exposed.
3. Agent calls `test_connection` to verify a source is reachable.
4. Agent calls `list_available_data` → receives containers/files (Data Lake) or tables (SQL).
5. Agent calls `get_schema` → receives column definitions for a table or file.
6. Agent calls `read_data` → receives rows (SQL capped at 1000 by default; file-based reads stream).
7. For SQL sources, agent calls `execute_query` with a SELECT/WITH statement → receives query results.
8. Agent calls `download_data` → CSV is streamed in 5000-row batches to the workspace (hard 1M-row ceiling, workspace escape guard).
9. Agent calls `create_chart_from_source` → aggregation pushed to DB (SQL) or done server-side (Data Lake); only the chart spec (~hundreds of bytes) returns to the agent context.

## Constraints

- **Read-only:** Azure SQL connections use `db_datareader` role only. DML, DDL, stored procedure calls, and batch separators are rejected before reaching the adapter.
- **Workspace-bound downloads:** `download_data` resolves destinations against `/workspaces/default/<project_id>/<session_id>/`; path traversal (`../`) is rejected.
- **Injection surface:** `filter_expr` is treated as a WHERE-clause fragment — statement terminators (`;`), comment markers (`--`, `/*`), batch separators (`GO`), and stored-procedure prefixes (`xp_`, `sp_`, `EXEC`) are rejected.
- **Row ceilings:** `read_data` caps at 1000 rows for Azure SQL (configurable); `download_data` hard ceiling at 1,000,000 rows.
- **Secret isolation:** `list_sources` returns `auth_type` but never the credential. Secrets live only in environment variables.
- **Per-role tool scoping:** Business Analyst gets read-only tools (no `download_data`); Data Analyst additionally gets `execute_query` and chart tools (no `download_data`).
- **Container restart required:** Source configuration changes need `docker compose up -d --force-recreate --no-deps`, not a plain restart.

## Out of Scope

- Write operations (INSERT, UPDATE, DELETE) — sources are read-only.
- Real-time streaming / change data capture.
- Non-Azure sources (Postgres, MySQL, S3) — adapter framework supports adding them, but none are implemented yet.
- True per-user on-behalf-of (OBO) authentication for Azure SQL — current `azure-sql-obo` runs a shared service identity (`client_credentials` grant), not a per-user token exchange.

## Open Questions

- **Q1: When will true OBO authentication land for Azure SQL?**
  - Option A: Keep shared service principal (simpler, current).
  - Option B: Implement per-user token exchange via Keycloak token broker (richer audit trail, more complex).
  - Owner: architect.

## Linked Documents

- **Specs:** `testing/specs/features/data-access-mcp.feature` — Data Access MCP acceptance scenarios
- **Technical reference:** `docs/reference/mcp/data-access.md` — Full technical contract (tool catalog, config format, security boundaries, adapter details)
