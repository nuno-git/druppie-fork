---
id: "020"
title: Data Access MCP architecture
status: accepted
date: 2026-07-16
deciders:
  - architect
  - backend-team
supersedes: null
superseded_by: null
linked_prd: docs/prds/009-data-access-mcp.md
linked_research: null
---

> **Where this fits:** This ADR records the architectural decision behind the unified Data Access
> MCP and is also the **single source of truth for its technical contract** (configuration format,
> tool catalog, adapter architecture, security boundaries, operational notes). The testable
> acceptance behaviour lives in [`docs/specs/021-data-access-mcp.feature`](../specs/021-data-access-mcp.feature);
> the product framing (problem, user journey, scope) lives in
> [`docs/prds/009-data-access-mcp.md`](../prds/009-data-access-mcp.md).

## Context

Agents (Business Analyst, Data Analyst) and generated applications need to read, query, and
download data from heterogeneous enterprise sources — Azure Data Lake, Azure SQL (Synapse
serverless) — and the chart-rendering workflow needs to aggregate that data without pulling whole
tables into the model context.

Before this decision, data access lived in a standalone `module-azure-datalake` MCP that only spoke
to one source type, exposed an ad-hoc tool surface, and had no place to hang a second adapter. Any
agent that needed SQL or any non-Azure-Data-Lake source would have had to write its own integration
code, duplicating auth logic, security boundaries, and connection management — with inconsistent
security per agent.

The forces in play:

- Multiple, growing source types (Azure Data Lake key/public, Azure SQL connection-string, an
  interim Azure SQL OBO path), each with its own auth model.
- A central platform responsibility for read-only enforcement, workspace-bound downloads,
  injection guards on filter expressions, and per-role tool scoping.
- An existing platform convention that MCP servers are referenced by agents as
  `<server>_<tool>`, parsed by `druppie/agents/loop.py::_parse_tool_name` splitting on the first
  underscore.
- A chart-rendering pipeline (`ChartBlock.jsx` + `recharts`) already present in the frontend that
  could display inline charts if the data layer produced a small, aggregated spec.

## Decision

Build one unified, **adapter-based** MCP — `data-access` — that fronts every supported source type
through a single tool set, and standardise how sources are declared, addressed, and secured.

1. **Adapter-based MCP with a unified tool interface.** One server exposes
   `list_sources`, `test_connection`, `list_available_data`, `get_schema`, `read_data`,
   `execute_query`, `download_data`, `create_chart`, and `create_chart_from_source`. A `BaseAdapter`
   contract is implemented per source type (`AzureDataLakeAdapter`, `AzureSQLAdapter`, …); the
   dispatcher selects the adapter from the `source_id` the agent passes in. Adding a source type
   means adding an adapter, not a new MCP.
2. **Multi-source declaration via `DATA_SOURCE_1` … `DATA_SOURCE_9` env vars.** Operators register
   sources in `.env`; the MCP loads them at container startup (`v1/module.py::_load_data_sources`).
   `<source_id>` is the handle agents pass to every other tool.
3. **Colon-delimited config string with `split(":", 2)` parsing.** Each entry is
   `type:name:config_blob`. Only the leading `type` and `name` are split off; the remaining
   `config_blob` keeps every internal colon so an ODBC connection string
   (`Server=tcp:host,1433;…`) survives intact.
4. **Supported source types.**
   - `azure-datalake:<source_id>:<account_name>:<storage_key>` (key auth)
   - `azure-datalake:<source_id>:<account_name>` (public)
   - `azure-sql:<source_id>:<odbc_connection_string>` (connection string, incl. service-principal)
   - `azure-sql-obo:<source_id>:<tenant_id>:<client_id>:<client_secret>:<scope>:<server>:<database>`
     (interim — see [Azure SQL setup](#azure-sql-setup-synapse-serverless))
5. **MCP id `data-access` with a single-word platform alias.** Tools are referenced as
   `dataaccess:<tool_name>`. The alias is single-word because
   `druppie/agents/loop.py::_parse_tool_name` splits the LLM-facing `<server>_<tool>` form on the
   first underscore; a multi-underscore alias would misroute.
6. **Container `druppie-module-data-access` on port `9010`.** Source lives at
   `druppie/mcp-servers/module-data-access/`; health endpoint at `GET http://localhost:9010/health`.
7. **Centralised security model:** read-only SQL principals (`db_datareader` only), workspace-bound
   downloads with a path-traversal guard, `filter_expr` treated as a WHERE-clause fragment with an
   injection guard run before any connection is opened, and per-role tool scoping. Details in
   [Security boundaries](#security-boundaries).
8. **Inline charts aggregate server-side, never in model context.** `create_chart` /
   `create_chart_from_source` push `GROUP BY` into the database for SQL sources and read the file
   in full for Data Lake sources; only a small JSON chart spec (~hundreds of bytes) returns to the
   agent. See [Visualization](#visualization).

## Consequences

- (+) One place to add a new source type (a new adapter), instead of per-agent integration code.
- (+) One place to enforce read-only access, workspace-bound downloads, injection guards, and
  role-scoped tool access — security is consistent by construction.
- (+) Chart aggregation stays server-side, so large tables cannot blow up the model context window.
- (+) The single-word `dataaccess` alias keeps the existing `_parse_tool_name` routing rule intact.
- (−) Source configuration is read once at container startup; changes require
  `docker compose up -d --force-recreate --no-deps module-data-access`, **not** a plain `restart`.
  This is a known operational footgun (see [Operational notes](#operational-notes)).
- (−) The colon-delimited config format is hand-rolled; a malformed entry is rejected at load time
  but the format is not self-documenting (no schema, no validator beyond the loader).
- (−) `azure-sql-obo` is **interim**: it runs an OAuth `client_credentials` grant against one
  shared service identity, not a true per-user on-behalf-of exchange. True OBO is a follow-up
  (PRD 009, Open Question Q1).
- (−) For Data Lake, `create_chart_from_source` reads the whole file into MCP-server memory before
  aggregating — fine at ~hundreds of thousands of rows, a pressure point at multi-GB (tracked in
  `docs/BACKLOG.md` → *Visualization — Performance & Scale*).
- (−) No OBO token caching: Azure SQL OBO adapters obtain a fresh token per call. Acceptable
  today; any change to that is a security-sensitive diff.

---

# Technical contract

The remainder of this ADR is the full technical reference for the Data Access MCP. It is the
authoritative source for config format, tool semantics, adapter behaviour, security boundaries,
testing, and operational notes.

## Configuration

Data sources are declared via `DATA_SOURCE_1` … `DATA_SOURCE_9` in `.env`. Each entry is a
colon-delimited string `type:name:config_blob`. Only the leading `type` and `name` are split off
(`split(":", 2)`); the remaining `config_blob` keeps every internal colon, so an ODBC connection
string (`Server=tcp:host,1433;…`) survives intact. The MCP loads them at container startup (see
`v1/module.py::_load_data_sources`); changes require a
`docker compose up -d --force-recreate --no-deps module-data-access` — a plain `restart` does **not**
re-read `.env`.

| Source type | Format |
|---|---|
| Azure Data Lake (key) | `azure-datalake:<source_id>:<account_name>:<storage_key>` |
| Azure Data Lake (public) | `azure-datalake:<source_id>:<account_name>` |
| Azure SQL (connection string) | `azure-sql:<source_id>:<odbc_connection_string>` |
| Azure SQL (OBO token — interim) | `azure-sql-obo:<source_id>:<tenant_id>:<client_id>:<client_secret>:<scope>:<server>:<database>` |

`<source_id>` is the handle agents pass back to every other tool.

> **Auth status.** `azure-datalake` (key / public) and `azure-sql` (connection string, incl.
> service-principal auth) are supported and tested. `azure-sql-obo` is **interim**: it currently
> runs an OAuth `client_credentials` grant (one shared service identity), not a true per-user
> on-behalf-of exchange — true OBO is a separate follow-up.

Examples:

```dotenv
DATA_SOURCE_1=azure-datalake:dlspublichhrhhskexp01:dlspublichhrhhskexp01:<base64-storage-key>
DATA_SOURCE_3=azure-sql:synapsedwh:Driver={ODBC Driver 18 for SQL Server};Server=<ws>-ondemand.sql.azuresynapse.net;Database=<db>;Authentication=ActiveDirectoryServicePrincipal;UID=<client-id>;PWD=<client-secret>;Encrypt=yes;TrustServerCertificate=no;
```

## Azure SQL setup (Synapse serverless)

The `azure-sql` source type connects through `pyodbc` + the Microsoft **ODBC Driver 18** (installed
in the MCP image — see `Dockerfile`). Steps to provision a serverless endpoint and a service
principal for it:

1. **Synapse workspace.** Create an Azure Synapse Analytics workspace (or reuse one). The
   *serverless* SQL pool is built in; its endpoint is
   `<workspace-name>-ondemand.sql.azuresynapse.net`.
2. **Service principal.** In Microsoft Entra ID, register an application, then create a client
   secret. Record the **tenant id**, **client (app) id**, and **secret value**.
3. **Database + grant.** In the serverless pool create a database, then grant the service principal
   read access:
   ```sql
   -- run on the serverless endpoint, master context
   CREATE LOGIN [<sp-display-name>] FROM EXTERNAL PROVIDER;
   -- run in the target database
   CREATE USER  [<sp-display-name>] FROM LOGIN [<sp-display-name>];
   ALTER ROLE   db_datareader ADD MEMBER [<sp-display-name>];
   ```
   Grant **`db_datareader` only** — read-only is also what bounds the `filter_expr` injection
   surface (see [Security boundaries](#security-boundaries)).
4. **Storage access.** If the serverless pool reads lake data via `OPENROWSET` / external tables,
   give the service principal **Storage Blob Data Reader** on the backing ADLS account.
5. **Firewall.** On the Synapse workspace, allow the Druppie host's IP (or enable "Allow Azure
   services").
6. **Configure the source.** Add to `.env` (single line):
   ```dotenv
   DATA_SOURCE_3=azure-sql:synapsedwh:Driver={ODBC Driver 18 for SQL Server};Server=<ws>-ondemand.sql.azuresynapse.net;Database=<db>;Authentication=ActiveDirectoryServicePrincipal;UID=<client-id>;PWD=<client-secret>;Encrypt=yes;TrustServerCertificate=no;
   ```
   `Authentication=ActiveDirectoryServicePrincipal` lets ODBC Driver 18 do the token exchange — no
   manual token code runs for this path. Recreate the container
   (`docker compose up -d --force-recreate --no-deps module-data-access`) and confirm the startup
   log shows `Loaded data source: synapsedwh (azure-sql)`.

## Tools

All tools return `{"success": <bool>, ...}` JSON. On failure the response includes
`"error": "<message>"` and the framework stores the full body so tests can assert on it.

| Tool | Args | Success shape |
|---|---|---|
| `list_sources` | — | `{success, sources: [{source_id, source_type, name, auth_type}], count}` |
| `test_connection` | `source_id` | `{success, message, source_info}` |
| `list_available_data` | `source_id`, `path?`, `recursive?` | `{success, data_items: [{item_id, name, type, metadata}], count, level, container?, path?}` |
| `get_schema` | `source_id`, `data_id` | `{success, schema: {columns: [{name, type}], metadata}}` |
| `read_data` | `source_id`, `data_id`, `filter_expr?`, `limit?`, `offset?` | `{success, data: [...], row_count, columns, metadata}` |
| `execute_query` | `source_id`, `query`, `limit?` | `{success, data: [...], row_count, columns, warnings, metadata}` |
| `download_data` | `source_id`, `data_id`, `destination`, `session_id*`, `project_id*` | `{success, destination, size_bytes}` |
| `create_chart` | `data`, `chart_type`, `x_column`, `y_column`, `title?`, `x_label?`, `y_label?` | `{success, spec, markdown}` |
| `create_chart_from_source` | `source_id`, `data_id`, `chart_type`, `x_column`, `y_column?`, `series_column?`, `aggregation?`, `filter_expr?`, `top_n?`, `max_series?`, `read_limit?`, `title?`, `x_label?`, `y_label?` | `{success, spec, markdown, category_count, full_dataset, aggregated_in, rows_scanned?, series_count?}` |

`*` `session_id` and `project_id` on `download_data` are auto-injected by the backend from the
active session — agents do not supply them.

The last two tools (`create_chart`, `create_chart_from_source`) render charts inline in the chat —
see [Visualization](#visualization).

### Agent access

| Agent | Tools | Rationale |
|---|---|---|
| `business_analyst` | `list_sources`, `test_connection`, `list_available_data`, `get_schema`, `read_data` | Answers general_chat data-discovery questions ("which data is available?") and gathers data context during `create_project` / `update_project` requirements work. Read-only — no `download_data`, BA does not write files into the workspace. |
| `data_analyst` | `list_sources`, `test_connection`, `list_available_data`, `get_schema`, `read_data`, `execute_query`, `create_chart`, `create_chart_from_source` | Answers data questions and **renders charts inline in chat**. Uses discovery tools to locate a dataset, then `create_chart_from_source` to visualize it. Read-only — no `download_data`. |

Other agents have no access yet. `download_data` is intentionally unassigned until a workflow needs
the bytes on disk (Developer / Test Builder when consuming sample data, most likely).

### Tool semantics

`list_available_data` semantics differ per source:
- Azure Data Lake: empty path → containers; container path → files (recursive walks subdirectories).
- Azure SQL: empty path → tables; schema path → table list filtered.

`read_data` filter syntax:
- Azure SQL: a SQL `WHERE`-clause **fragment** only (e.g. `Status = 'open' AND Year >= 2020`).
  Statement terminators, comment markers and stored-procedure calls are rejected — see
  [Security boundaries](#security-boundaries).
- Azure Data Lake: pandas `DataFrame.query()` expression.

`execute_query` (Azure SQL only):
- Accepts a **single** read-only statement that must start with `SELECT` or `WITH` (CTE). DML/DDL
  verbs, comments, batch separators (`GO`), stored-proc calls and additional `;` separators are
  rejected before the query reaches the database. The configured `db_datareader` principal is the
  real hard line; this validator just makes the contract explicit.
- Same 1000-row default cap as `read_data`. The cap is enforced by fetching one extra row from the
  cursor — if the query produced more, `metadata.truncated` is `true` and `warnings[]` says so.
  Paginate via `ORDER BY ... OFFSET ... ROWS FETCH NEXT ... ROWS ONLY` in the query itself.
- For file-based sources (Azure Data Lake) the tool returns a clear "unsupported" error — use
  `read_data` instead.

## Adapter architecture

The MCP is organised around one dispatch layer and N adapters:

- **Dispatcher** (`v1/tools.py`) — receives the agent tool call, looks up the `source_id` in the
  in-memory source registry, routes the call to the matching adapter, and applies cross-cutting
  guards (workspace escape guard on `download_data`, see
  [Security boundaries](#security-boundaries)).
- **`BaseAdapter`** — defines the contract every adapter implements: connection lifecycle,
  `list_available_data`, `get_schema`, `read_data`, `download_data`, and (for SQL adapters)
  `execute_query`. Adapters translate the unified tool args into source-specific calls.
- **Per-source adapters:**
  - `AzureDataLakeAdapter` — connects with `azure-storage-blob` (key or anonymous), reads CSVs via
    `pandas` with BOM/malformed-row robustness (see [CSV robustness](#csv-robustness)).
  - `AzureSQLAdapter` — connects through `pyodbc` + ODBC Driver 18, validates `filter_expr` /
    `execute_query` SQL before opening a connection, caps unbounded reads.
  - `azure-sql-obo` variant — same SQL surface but obtains an OAuth token per call instead of
    using a static connection string (interim; see
    [Azure SQL setup](#azure-sql-setup-synapse-serverless)).

Adding a source type is a new adapter + a new `type:` prefix in the config table; no dispatcher or
tool-surface change is required.

## Visualization

`create_chart` and `create_chart_from_source` turn data into a chart that renders **inline in the
chat**. The design principle: the LLM decides *what* to plot (chart type, columns, aggregation);
the data is aggregated server-side and **never enters the model context**. Only a small JSON spec
travels back.

### Data flow

```
agent picks type + columns
        │
        ▼
create_chart_from_source ──► SQL source:  GROUP BY pushed into the database
        │                    Data Lake:   whole file read into MCP memory, aggregated
        ▼
{spec, markdown}  ◄── only the aggregated result (~hundreds of bytes)
        │
        ▼
agent embeds the `markdown` (a ```chart fenced block) in hitl_ask_question
        │
        ▼
frontend ChartBlock.jsx parses the spec → renders with recharts
```

No file is written for a chart — Data Lake blobs are read into memory (`io.BytesIO`) and discarded;
SQL aggregation happens in the database. The only persisted artifact is the spec itself, stored in
the chat `messages` row, which is what lets the chart re-render on session reload.

### The chart spec

A small JSON object wrapped in a ` ```chart ` fenced code block:

```json
{
  "type": "bar",
  "title": "Assets per category",
  "x_label": "Category",
  "y_label": "count",
  "data": [{"x": "Afsluiter", "y": 9230}, {"x": "Elektromotor", "y": 3624}]
}
```

Multi-series specs additionally carry a `series` array, and `data` rows are flat
(`{x, <series_key>: value, ...}`).

### Chart types

13 types in three families (which columns each needs):

| Family | Types | Columns |
|---|---|---|
| XY | `bar`, `line`, `area`, `horizontal_bar`, `scatter` | `x_column` + `y_column` |
| Proportion | `pie`, `donut`, `treemap`, `funnel` | `x_column` (name) + `y_column` (value) |
| Multi-series | `stacked_bar`, `grouped_bar`, `stacked_area`, `multi_line` | `x_column` + `y_column` + `series_column` |

### `create_chart` vs `create_chart_from_source`

- **`create_chart`** charts **inline values** the agent already holds (e.g. the user typed
  "chart A=10, B=25"). Single-series + proportion types only.
- **`create_chart_from_source`** reads + aggregates a configured source. Use this for any real
  dataset. Key behaviors:
  - **Full-dataset aggregation.** SQL sources push `GROUP BY` into the database
    (`build_sql_aggregation_query`, `aggregated_in: "database"`); Data Lake files are read in full
    and aggregated server-side (`aggregated_in: "server"`). `read_limit` defaults to `None` (no
    cap) — set it only to deliberately sample a very large Data Lake file. The response carries
    `full_dataset` (false if a cap truncated the read) and, for the server path, `rows_scanned`.
  - **`aggregation`**: `count` (default, ignores `y_column`) or `sum`/`avg`/`min`/`max` over
    `y_column`.
  - **`series_column`** is required for multi-series types; it is the second grouping dimension
    (each distinct value becomes a series). Capped by `max_series` (default 10); categories capped
    by `top_n` (default 20).
  - On invalid input returns `{success: false, error}` (unsupported chart_type, missing column,
    non-numeric `y` values, empty result).

> **Aggregation correctness.** Early versions aggregated over a row-capped read, which silently
> skewed charts of large tables (a 279k-row source was charted from its first 5000 rows). The
> current full-dataset behavior — DB pushdown for SQL, full-file read for Data Lake — fixes this;
> `full_dataset` signals when a result is nonetheless a sample.

### Frontend rendering

The chat renders assistant / HITL message text through `react-markdown` with custom code-block
handlers (the same mechanism that renders ` ```mermaid ` via `MermaidBlock`).
`frontend/src/components/ChartBlock.jsx` is registered for the `chart` language in
`frontend/src/components/chat/ChatHelpers.jsx`: it parses the spec, validates it, and renders the
matching `recharts` component inside a `ResponsiveContainer`, falling back to an inline error card
if the spec is malformed.

## Azure SQL row caps

`read_data` against Azure SQL caps unbounded reads so an agent cannot pull a whole Synapse table
into the LLM context:

- With no `limit`, the result is capped at **1000 rows**; `metadata.capped` is `true` and
  `warnings[]` says so. Pass an explicit `limit` to read more.
- `download_data` streams the full table to CSV in 5000-row batches (no in-memory materialisation)
  with a hard **1,000,000-row** ceiling; if hit, the CSV is truncated and `warnings[]` reports it.

## CSV robustness

`read_data` and `get_schema` against CSV files in Azure Data Lake:

- Open with `encoding="utf-8-sig"` so any UTF-8 BOM in the file is stripped — without this the
  first column name comes back as `﻿<name>` and `df["<name>"]` lookups fail.
- Read with `on_bad_lines="skip"` so rows whose field count does not match the header are dropped
  instead of failing the whole call. Real-world exports often have unquoted commas in free-text
  columns (e.g. Dutch descriptions in `Asset_Omschrijving`); this is a data quality bug at source,
  not in the adapter.
- The number of skipped rows is reported in two places on the success response:
  `warnings: ["Skipped N malformed row(s) …"]` (so an agent surfaces it to the user) and
  `metadata.skipped_rows: N` (machine readable). Both are present even when zero rows were skipped
  (warnings list is empty, count is `0`).

## Security boundaries

- **Workspace escape guard** (`v1/tools.py:148-156`). `download_data` resolves `destination`
  against `/workspaces/default/<project_id>/<session_id>/` and returns
  `{success: false, error: "Invalid destination path: ... escapes the workspace directory"}` if
  the resolved path is outside that root. The guard fires before the adapter is touched, so it
  does not depend on the source being reachable. Pinned by
  `testing/tools/data-access-download-data-path-traversal.yaml`.
- **`filter_expr` is a WHERE-clause fragment, not arbitrary SQL.** The Azure SQL adapter rejects a
  `filter_expr` containing statement terminators (`;`), comment markers (`--`, `/*`), batch
  separators (`GO`) or stored-procedure calls (`xp_`, `sp_`, `EXEC`) before it is appended to the
  query (`AzureSQLAdapter._validate_filter`). Defence in depth — the configured SQL principal
  should also be `db_datareader` only, which bounds anything that slips through to read-only.
- **`execute_query` is read-only by contract.** A single statement that must start with `SELECT`
  or `WITH`; DML/DDL verbs, comments, batch separators, stored-proc calls and additional `;`
  separators are rejected before the query reaches the database.
- **No OBO token caching.** Azure SQL OBO adapters obtain a fresh token per call. There is no
  persistence layer or in-memory cache. Reviewers should treat any change to that behavior as a
  security-sensitive diff.
- **Secrets in `.env`.** Storage keys and client secrets live only in the process environment;
  they are not stored in the database or surfaced to agents. `list_sources` returns `auth_type`
  (`key`, `connection_string`, `obo`) but not the credential itself.
- **Per-role tool scoping.** `business_analyst` and `data_analyst` get read-only tool sets;
  neither has `download_data`. See [Agent access](#agent-access).

## Health check

- `GET http://localhost:9010/health` returns 200 once the MCP HTTP server is up.
- The healthcheck returns 200 **even when no sources load**; it only proves the process is
  reachable. To confirm a source actually parsed, check
  `docker logs druppie-module-data-access | grep "Loaded data source"`.

## Testing

The MCP is covered by 16 YAML tool tests in `testing/tools/data-access-*.yaml`. Run them via the
evaluations endpoint (admin token required):

```bash
curl -X POST http://localhost:8500/api/evaluations/run-tests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_names": ["data-access-list-sources-shape", ...], "execute": true, "judge": false}'
```

### Env-agnostic (7)

These run without any configured source and exercise the shape and error contracts.

| Test | What it pins |
|---|---|
| `data-access-list-sources-shape` | `list_sources` returns `{success, sources, count}` even when no sources are configured. |
| `data-access-test-connection-unknown-source` | `test_connection` against a bogus `source_id` returns `{success: false, error}`. |
| `data-access-list-available-data-unknown-source` | Same for `list_available_data`. |
| `data-access-get-schema-unknown-source` | Same for `get_schema`. |
| `data-access-read-data-unknown-source` | Same for `read_data`. |
| `data-access-download-data-unknown-source` | Same for `download_data`. |
| `data-access-download-data-path-traversal` | `destination: "../escape.csv"` is rejected before any adapter call, with the literal `"Invalid destination path"` / `"escapes the workspace"` message. |

### Live (6, tagged `live`)

These depend on `DATA_SOURCE_1` pointing at the `dlspublichhrhhskexp01` Azure Data Lake account,
with the seeded `dwhpublic/HHR/` content present.

| Test | What it pins |
|---|---|
| `data-access-test-connection-success` | Connection succeeds against the configured source. |
| `data-access-list-available-data-containers` | Root listing returns `dwhpublic` with `level: containers`. |
| `data-access-list-available-data-files` | Recursive listing inside `dwhpublic/HHR` returns the seeded CSV files. |
| `data-access-get-schema-csv` | Schema for `VW_HHR_Fudura_MeteringPoints.csv` exposes `meteringPointId`, `channelId`, etc. |
| `data-access-read-data-with-limit` | `limit: 2` returns 2 rows with `"limited": true` and the column metadata. |
| `data-access-download-data-success` | The CSV lands in `/workspaces/default/<project_id>/<session_id>/data/metering-points.csv` with non-zero `size_bytes`. |

### Azure SQL (3, tagged `live` + `azure-sql`)

These need an `azure-sql` source named `synapsedwh` configured via `DATA_SOURCE_N` (see
[Azure SQL setup](#azure-sql-setup-synapse-serverless)). `data-access-sql-filter-rejected` passes
even if the endpoint is unreachable — the filter guard runs before the connection is opened.

| Test | What it pins |
|---|---|
| `data-access-sql-test-connection` | `test_connection` actually reaches the SQL endpoint and runs `SELECT 1`. |
| `data-access-sql-list-tables` | `list_available_data` enumerates tables from `INFORMATION_SCHEMA.TABLES`. |
| `data-access-sql-filter-rejected` | `read_data` rejects a `filter_expr` containing `;` with a `WHERE-clause` error. |
| `data-access-sql-execute-query` | `execute_query` runs a `SELECT` and returns rows. |
| `data-access-sql-execute-query-rejected` | `execute_query` rejects a non-SELECT statement with a `SELECT or WITH` error. |

All assertions use `{matches: "\"success\"\\s*:\\s*(true|false)"}` so they remain robust to JSON
whitespace.

## Operational notes

- `list_sources` returning `count: 0` after a config change almost always means the container was
  restarted instead of recreated. Use
  `docker compose up -d --force-recreate --no-deps module-data-access`.
- The healthcheck (`/health`) returns 200 even when no sources load; check
  `docker logs druppie-module-data-access | grep "Loaded data source"` to confirm a source actually
  parsed.
- `injection_value_is_none from_path=project.id` in backend logs during a `download_data` call
  means the session was started outside of a project context (e.g. via the tool-test harness); the
  destination still resolves but `<project_id>` becomes the string `None` in the path.

<!-- LATER (PBI 9744 — afdwingen): hoe deze beslissing wordt afgedwongen wordt in PBI 9744
     onderzocht en hier toegevoegd. -->
