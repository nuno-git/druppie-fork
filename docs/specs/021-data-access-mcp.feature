# @status active
# @superseded_by
# @adr
# @prd docs/prds/009-data-access-mcp.md
# Source reference: docs/guides/data-access-mcp-contract.md (full technical contract; behavioral layer superseded by this spec)

@prd docs/prds/009-data-access-mcp.md
Feature: Data Access MCP
  # The Data Access MCP lets agents read and download data from heterogeneous
  # sources (Azure Data Lake, Azure SQL) through a single adapter-based tool set.
  # Full technical detail — tool catalog, config format, security boundaries —
  # lives in docs/guides/data-access-mcp-contract.md. This spec holds only the
  # acceptance Scenarios below.

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

  Scenario: list_available_data semantics differ per source type
    Given an Azure Data Lake source
    When list_available_data is called with an empty path
    Then it returns the containers
    When list_available_data is called with a container path
    Then it returns the files and a recursive flag walks subdirectories
    Given an Azure SQL source
    When list_available_data is called with an empty path
    Then it returns the tables from INFORMATION_SCHEMA.TABLES

  Scenario: read_data caps unbounded Azure SQL reads
    Given an Azure SQL source and a read_data call with no explicit limit
    When the underlying result exceeds 1000 rows
    Then the returned data is capped at 1000 rows
    And metadata.capped is true and warnings[] reports the cap
    When an explicit limit is passed
    Then up to that many rows are returned without the default cap

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

  Scenario: create_chart_from_source aggregates without loading the dataset into model context
    Given a create_chart_from_source call against an Azure SQL source
    When the chart is built
    Then GROUP BY aggregation is pushed into the database and aggregated_in is "database"
    Given a create_chart_from_source call against an Azure Data Lake source
    When the chart is built
    Then the file is read in full and aggregated server-side, with aggregated_in "server"
    And only the aggregated chart spec returns to the agent
    And when a read cap truncated the source, the response reports full_dataset as false

  Scenario: Agent access to tools is scoped per role
    Given the business_analyst agent
    Then it may use list_sources, test_connection, list_available_data, get_schema, and read_data
    But it may not use download_data
    Given the data_analyst agent
    Then it may additionally use execute_query, create_chart, and create_chart_from_source
    But it may not use download_data
