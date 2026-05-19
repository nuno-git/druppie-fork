# Data Access MCP

Unified, adapter-based MCP that lets agents read and download data from
heterogeneous sources (Azure Data Lake, Azure SQL) through a single set of
tools. Replaces the standalone `module-azure-datalake` MCP.

- Container: `druppie-module-data-access` (port `9010`)
- Source: `druppie/mcp-servers/module-data-access/`
- Health: `GET http://localhost:9010/health`
- MCP id: `data-access` (tools referenced as `dataaccess:<tool_name>` —
  the platform alias is single-word because
  `druppie/agents/loop.py::_parse_tool_name` splits the LLM-facing
  `<server>_<tool>` form on the first underscore; a multi-underscore alias
  would misroute)

## Configuration

Data sources are declared via `DATA_SOURCE_1` … `DATA_SOURCE_9` in `.env`.
Each entry is a single colon-delimited string: `type:name:config_parts...`.
The MCP loads them at container startup (see
`v1/module.py::_load_data_sources`); changes require a `docker compose up -d
--force-recreate --no-deps module-data-access` — a plain `restart` does not
re-read `.env`.

| Source type | Format |
|---|---|
| Azure Data Lake (key) | `azure-datalake:<source_id>:<account_name>:<storage_key>` |
| Azure Data Lake (public) | `azure-datalake:<source_id>:<account_name>` |
| Azure SQL (connection string) | `azure-sql:<source_id>:<connection_string>` |
| Azure SQL (OBO token) | `azure-sql-obo:<source_id>:<tenant_id>:<client_id>:<client_secret>:<scope>:<server>:<database>` |

`<source_id>` is the handle agents pass back to every other tool. OBO tokens
are fetched fresh per request and are **never** cached or persisted (see
`adapter/base.py`).

Example:

```dotenv
DATA_SOURCE_1=azure-datalake:dlspublichhrhhskexp01:dlspublichhrhhskexp01:<base64-storage-key>
```

## Tools

All tools return `{"success": <bool>, ...}` JSON. On failure the response
includes `"error": "<message>"` and the framework stores the full body so
tests can assert on it.

| Tool | Args | Success shape |
|---|---|---|
| `list_sources` | — | `{success, sources: [{source_id, source_type, name, auth_type}], count}` |
| `test_connection` | `source_id` | `{success, message, source_info}` |
| `list_available_data` | `source_id`, `path?`, `recursive?` | `{success, data_items: [{item_id, name, type, metadata}], count, level, container?, path?}` |
| `get_schema` | `source_id`, `data_id` | `{success, schema: {columns: [{name, type}], metadata}}` |
| `read_data` | `source_id`, `data_id`, `filter_expr?`, `limit?`, `offset?` | `{success, data: [...], row_count, columns, metadata}` |
| `download_data` | `source_id`, `data_id`, `destination`, `session_id*`, `project_id*` | `{success, destination, size_bytes}` |

`*` `session_id` and `project_id` on `download_data` are auto-injected by
the backend from the active session — agents do not supply them.

### Agent access

| Agent | Tools | Rationale |
|---|---|---|
| `business_analyst` | `list_sources`, `test_connection`, `list_available_data`, `get_schema`, `read_data` | Answers general_chat data-discovery questions ("which data is available?") and gathers data context during `create_project` / `update_project` requirements work. Read-only — no `download_data`, BA does not write files into the workspace. |

Other agents have no access yet. `download_data` is intentionally
unassigned until a workflow needs the bytes on disk (Developer / Test
Builder when consuming sample data, most likely).

`list_available_data` semantics differ per source:
- Azure Data Lake: empty path → containers; container path → files
  (recursive walks subdirectories).
- Azure SQL: empty path → tables; schema path → table list filtered.

`read_data` filter syntax:
- Azure SQL: SQL `WHERE` clause fragment.
- Azure Data Lake: pandas `DataFrame.query()` expression.

### CSV robustness

`read_data` and `get_schema` against CSV files in Azure Data Lake:

- Open with `encoding="utf-8-sig"` so any UTF-8 BOM in the file is
  stripped — without this the first column name comes back as
  `﻿<name>` and `df["<name>"]` lookups fail.
- Read with `on_bad_lines="skip"` so rows whose field count does not
  match the header are dropped instead of failing the whole call.
  Real-world exports often have unquoted commas in free-text columns
  (e.g. Dutch descriptions in `Asset_Omschrijving`); this is a data
  quality bug at source, not in the adapter.
- The number of skipped rows is reported in two places on the success
  response: `warnings: ["Skipped N malformed row(s) …"]` (so an agent
  surfaces it to the user) and `metadata.skipped_rows: N` (machine
  readable). Both are present even when zero rows were skipped
  (warnings list is empty, count is `0`).

## Security boundaries

- **Workspace escape guard** (`v1/tools.py:148-156`). `download_data`
  resolves `destination` against `/workspaces/default/<project_id>/<session_id>/`
  and returns `{success: false, error: "Invalid destination path: ... escapes
  the workspace directory"}` if the resolved path is outside that root. The
  guard fires before the adapter is touched, so it does not depend on the
  source being reachable. Pinned by
  `testing/tools/data-access-download-data-path-traversal.yaml`.
- **No OBO token caching**. Azure SQL OBO adapters obtain a fresh token per
  call. There is no persistence layer or in-memory cache. Reviewers should
  treat any change to that behavior as a security-sensitive diff.
- **Secrets in `.env`**. Storage keys and client secrets live only in the
  process environment; they are not stored in the database or surfaced to
  agents. `list_sources` returns `auth_type` (`key`, `connection-string`,
  `obo`) but not the credential itself.

## Testing

The MCP is covered by 13 YAML tool tests in `testing/tools/data-access-*.yaml`.
Run them via the evaluations endpoint (admin token required):

```bash
curl -X POST http://localhost:8500/api/evaluations/run-tests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_names": ["data-access-list-sources-shape", ...], "execute": true, "judge": false}'
```

### Env-agnostic (7)

These run without any configured source and exercise the shape and error
contracts.

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

These depend on `DATA_SOURCE_1` pointing at the `dlspublichhrhhskexp01`
Azure Data Lake account, with the seeded `dwhpublic/HHR/` content present.

| Test | What it pins |
|---|---|
| `data-access-test-connection-success` | Connection succeeds against the configured source. |
| `data-access-list-available-data-containers` | Root listing returns `dwhpublic` with `level: containers`. |
| `data-access-list-available-data-files` | Recursive listing inside `dwhpublic/HHR` returns the seeded CSV files. |
| `data-access-get-schema-csv` | Schema for `VW_HHR_Fudura_MeteringPoints.csv` exposes `meteringPointId`, `channelId`, etc. |
| `data-access-read-data-with-limit` | `limit: 2` returns 2 rows with `"limited": true` and the column metadata. |
| `data-access-download-data-success` | The CSV lands in `/workspaces/default/<project_id>/<session_id>/data/metering-points.csv` with non-zero `size_bytes`. |

All assertions use `{matches: "\"success\"\\s*:\\s*(true|false)"}` so they
remain robust to JSON whitespace.

## Operational notes

- `list_sources` returning `count: 0` after a config change almost always
  means the container was restarted instead of recreated. Use
  `docker compose up -d --force-recreate --no-deps module-data-access`.
- The healthcheck (`/health`) returns 200 even when no sources load; check
  `docker logs druppie-module-data-access | grep "Loaded data source"` to
  confirm a source actually parsed.
- `injection_value_is_none from_path=project.id` in backend logs during a
  `download_data` call means the session was started outside of a project
  context (e.g. via the tool-test harness); the destination still resolves
  but `<project_id>` becomes the string `None` in the path.
