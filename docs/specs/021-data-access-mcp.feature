# @status active
# @superseded_by
# @adr docs/adrs/020-data-access-mcp.md
# @prd docs/prds/009-data-access-mcp.md
# Technical contract (tool catalog, config format, adapter architecture, security
# boundaries, operational notes): docs/adrs/020-data-access-mcp.md

@adr docs/adrs/020-data-access-mcp.md
@prd docs/prds/009-data-access-mcp.md
Feature: Data Access MCP
  # The Data Access MCP lets agents read and download data from heterogeneous
  # sources (Azure Data Lake, Azure SQL) through a single adapter-based tool set.
  # Full technical detail lives in docs/adrs/020-data-access-mcp.md. This spec
  # holds only the acceptance Scenarios below.

  # ─────────────────────────────────────────────────────────────────────────
  # Source configuration
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: DATA_SOURCE_N entries are parsed with split(":", 2) so config blobs keep internal colons
    Given an env entry DATA_SOURCE_3=azure-sql:synapsedwh:Driver={...};Server=tcp:host,1433;...
    When the MCP loads data sources at container startup via _load_data_sources
    Then the leading type is "azure-sql" and the name is "synapsedwh"
    And the remaining config_blob is the full ODBC connection string, with every internal colon preserved
    And the source is registered under the source_id "synapsedwh"

  Scenario: DATA_SOURCE_1 through DATA_SOURCE_9 are honoured; 10 and above are ignored
    Given DATA_SOURCE_1..DATA_SOURCE_9 each declare a distinct source
    When the MCP loads sources at startup
    Then all nine sources are registered and list_sources reports count: 9
    Given an additional DATA_SOURCE_10 entry
    Then it is not loaded and list_sources count remains 9

  Scenario: Config changes require a container recreate, not a plain restart
    Given the data-access MCP is running with one configured source
    When the operator edits .env to add a second DATA_SOURCE_N and runs docker compose restart
    Then the new source is NOT loaded and list_sources count is unchanged
    When the operator instead runs docker compose up -d --force-recreate --no-deps module-data-access
    Then the new source is loaded and list_sources count increases
    And the startup log contains "Loaded data source: <source_id> (<type>)"

  Scenario: A malformed DATA_SOURCE_N entry is rejected at load time
    Given a DATA_SOURCE_N entry missing the type or name component
    When the MCP loads sources at startup
    Then the malformed entry is skipped (not registered)
    And other valid entries still load
    And the startup log reports the rejected entry

  # ─────────────────────────────────────────────────────────────────────────
  # Adapter selection
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: The correct adapter is selected per source type
    Given a registered azure-datalake source "lake1"
    When an agent calls read_data with source_id "lake1"
    Then the AzureDataLakeAdapter handles the call
    Given a registered azure-sql source "synapsedwh"
    When an agent calls read_data with source_id "synapsedwh"
    Then the AzureSQLAdapter handles the call

  Scenario: list_sources exposes the source type and auth type per source
    Given one azure-datalake source with key auth and one azure-sql source with connection_string auth
    When an agent calls list_sources
    Then each entry carries source_type matching its adapter (azure-datalake or azure-sql)
    And each entry carries auth_type ("key", "public", "connection_string", or "obo")

  # ─────────────────────────────────────────────────────────────────────────
  # list_sources / secrets
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: list_sources returns configured sources without exposing secrets
    Given the data-access MCP is running on port 9010
    When an agent calls list_sources
    Then the response shape is {success, sources, count}
    And when no DATA_SOURCE_N entry is configured, sources is empty and count is 0
    And every source entry exposes source_id, source_type, name, and auth_type only
    But the response never contains the storage key, client secret, or ODBC connection string

  Scenario: Tools reject an unknown source_id
    Given the data-access MCP with a configured source "synapsedwh"
    When an agent calls test_connection, list_available_data, get_schema, read_data, or download_data with a bogus source_id
    Then each tool returns {success: false, error: <message>}

  # ─────────────────────────────────────────────────────────────────────────
  # test_connection
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: test_connection succeeds against a reachable source and fails on connection error
    Given a configured source whose endpoint is up
    When an agent calls test_connection with that source_id
    Then the response is {success: true, message, source_info}
    Given a configured source whose endpoint is unreachable (bad credentials, network, firewall)
    When an agent calls test_connection with that source_id
    Then the response is {success: false, error: <message>} and the error describes the connection failure

  # ─────────────────────────────────────────────────────────────────────────
  # list_available_data
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: list_available_data semantics differ per source type
    Given an Azure Data Lake source
    When list_available_data is called with an empty path
    Then it returns the containers
    When list_available_data is called with a container path
    Then it returns the files and a recursive flag walks subdirectories
    Given an Azure SQL source
    When list_available_data is called with an empty path
    Then it returns the tables from INFORMATION_SCHEMA.TABLES

  # ─────────────────────────────────────────────────────────────────────────
  # read_data
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: read_data returns rows with column metadata
    Given a configured source and a known data_id
    When an agent calls read_data with that source_id and data_id
    Then the response shape is {success, data, row_count, columns, metadata}
    And data is a list of row objects whose keys match the columns list
    And row_count equals len(data)

  Scenario: read_data caps unbounded Azure SQL reads
    Given an Azure SQL source and a read_data call with no explicit limit
    When the underlying result exceeds 1000 rows
    Then the returned data is capped at 1000 rows
    And metadata.capped is true and warnings[] reports the cap
    When an explicit limit is passed
    Then up to that many rows are returned without the default cap

  Scenario: read_data CSV robustness for Azure Data Lake files
    Given a CSV file in Azure Data Lake with a UTF-8 BOM and malformed rows
    When read_data or get_schema reads it
    Then the file is opened with utf-8-sig so the BOM is stripped from the first column name
    And malformed rows (field count != header count) are skipped rather than failing the call
    And metadata.skipped_rows reports the count of skipped rows
    And warnings[] contains a "Skipped N malformed row(s)" message when N > 0

  # ─────────────────────────────────────────────────────────────────────────
  # execute_query
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: execute_query accepts only read-only SELECT or WITH on Azure SQL
    Given an Azure SQL source
    When execute_query is called with a single statement starting with SELECT or WITH
    Then it runs and returns {success, data, row_count, columns, warnings, metadata}
    When execute_query is called with a DML/DDL verb, a comment, a batch separator (GO), a stored-proc call, or an extra ; separator
    Then it is rejected with a "SELECT or WITH" error before the query reaches the database
    Given a file-based Azure Data Lake source
    When execute_query is called
    Then it returns an "unsupported" error directing the caller to use read_data

  Scenario: filter_expr is a WHERE-clause fragment, not arbitrary SQL
    Given an Azure SQL source and a read_data call
    When filter_expr contains a statement terminator (;), a comment marker (-- or /*), a batch separator (GO), or a stored-procedure call (xp_, sp_, EXEC)
    Then the Azure SQL adapter rejects it with a WHERE-clause error
    And the rejection happens before any database connection is opened
    And the configured db_datareader principal bounds any remaining surface to read-only

  # ─────────────────────────────────────────────────────────────────────────
  # download_data
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: download_data enforces the workspace escape guard
    Given a download_data call with destination "../escape.csv"
    When the destination is resolved against /workspaces/default/<project_id>/<session_id>/
    Then the resolved path is detected as outside that workspace root
    And the call returns {success: false} with a message containing "Invalid destination path" and "escapes the workspace"
    And the guard fires before the source adapter is touched, regardless of source reachability

  Scenario: download_data streams the full table with a hard row ceiling
    Given a download_data call against a large Azure SQL table
    When the CSV is produced
    Then it is streamed in 5000-row batches without full in-memory materialization
    And if the 1,000,000-row ceiling is hit, the CSV is truncated and warnings[] reports the truncation

  Scenario: download_data returns the workspace-relative destination path and size
    Given a successful download_data call
    Then the response shape is {success: true, destination, size_bytes}
    And destination is the resolved path under /workspaces/default/<project_id>/<session_id>/
    And size_bytes is greater than zero
    And session_id and project_id were auto-injected by the backend, not supplied by the agent

  # ─────────────────────────────────────────────────────────────────────────
  # Visualization
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: create_chart_from_source aggregates without loading the dataset into model context
    Given a create_chart_from_source call against an Azure SQL source
    When the chart is built
    Then GROUP BY aggregation is pushed into the database and aggregated_in is "database"
    Given a create_chart_from_source call against an Azure Data Lake source
    When the chart is built
    Then the file is read in full and aggregated server-side, with aggregated_in "server"
    And only the aggregated chart spec returns to the agent
    And when a read cap truncated the source, the response reports full_dataset as false

  Scenario: create_chart_from_source rejects invalid chart input
    Given a create_chart_from_source call with an unsupported chart_type
    Then it returns {success: false, error}
    Given a call with a missing column, non-numeric y_column values for a sum/avg aggregation, or an empty result
    Then it returns {success: false, error}

  Scenario: chart specs render inline in chat via a ```chart fenced block
    Given a successful create_chart or create_chart_from_source call
    Then the response carries a spec JSON object and a markdown field
    And the markdown is a ```chart fenced code block containing the spec
    And ChartBlock.jsx parses the spec and renders the chart inline; no file is written for a chart

  # ─────────────────────────────────────────────────────────────────────────
  # Agent access
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: Agent access to tools is scoped per role
    Given the business_analyst agent
    Then it may use list_sources, test_connection, list_available_data, get_schema, and read_data
    But it may not use download_data
    Given the data_analyst agent
    Then it may additionally use execute_query, create_chart, and create_chart_from_source
    But it may not use download_data

  # ─────────────────────────────────────────────────────────────────────────
  # Health & operations
  # ─────────────────────────────────────────────────────────────────────────

  Scenario: /health returns 200 independent of source configuration
    Given the data-access MCP process is up on port 9010
    When GET /health is called
    Then it returns HTTP 200
    And this holds even when zero sources are configured
    But a 200 does not prove any source parsed — that must be confirmed via "Loaded data source" in docker logs
