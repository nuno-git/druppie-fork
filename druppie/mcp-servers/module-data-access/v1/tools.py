"""Data Access v1 — MCP Tool Definitions.

Unified interface for accessing data from multiple sources:
- Azure Data Lake (key-based or public)
- Azure SQL (connection string or OBO token)
- Future sources via adapter pattern

IMPORTANT: OBO tokens are fetched fresh per request - NEVER cached or stored.
"""

import logging
import os
from pathlib import Path

from fastmcp import FastMCP
from .module import DataAccessModule

logger = logging.getLogger("dataaccess-mcp")

MODULE_ID = "dataaccess"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Data Access v1",
    version=MODULE_VERSION,
    instructions="Unified data access for Azure Data Lake and Azure SQL. Read and download data from multiple sources through a single interface.",
)

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
module = DataAccessModule()


@mcp.tool()
async def list_sources() -> dict:
    """List all configured data sources.

    Call this FIRST to discover available sources. Use the returned
    'source_id' in all other tools.

    Returns:
        Dict with list of sources (source_id, source_type, name, auth_type).
    """
    return module.list_sources()


@mcp.tool()
async def test_connection(source_id: str) -> dict:
    """Test connection to a data source.

    Args:
        source_id: Source ID from list_sources()

    Returns:
        Dict with connection status.
    """
    return await module.test_connection(source_id)


@mcp.tool()
async def list_available_data(
    source_id: str,
    path: str = "",
    recursive: bool = False,
) -> dict:
    """List available data in a source.

    For Azure Data Lake: returns containers or files
    For Azure SQL: returns tables

    Args:
        source_id: Source ID from list_sources()
        path: Optional path/namespace (container for datalake, schema for SQL)
        recursive: List recursively (datalake only)

    Returns:
        Dict with list of data_items (item_id, name, type, metadata).
    """
    return await module.list_available_data(source_id, path, recursive)


@mcp.tool()
async def get_schema(
    source_id: str,
    data_id: str,
) -> dict:
    """Get schema/metadata for a specific data item.

    Returns column names, types, and other metadata without reading data.

    Args:
        source_id: Source ID from list_sources()
        data_id: Data item ID (table name or file path) from list_available_data()

    Returns:
        Dict with schema information (columns, metadata).
    """
    return await module.get_schema(source_id, data_id)


@mcp.tool()
async def read_data(
    source_id: str,
    data_id: str,
    filter_expr: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """Read data from a source.

    For Azure SQL: filters are SQL WHERE clauses
    For Azure Data Lake: filters are pandas query expressions
    No row limit unless explicitly specified via 'limit'.

    Args:
        source_id: Source ID from list_sources()
        data_id: Data item ID from list_available_data()
        filter_expr: Optional filter (SQL WHERE or pandas query)
        limit: Optional maximum rows to return
        offset: Optional offset for pagination

    Returns:
        Dict with data records, row_count, columns, and metadata.
    """
    return await module.read_data(source_id, data_id, filter_expr, limit, offset)


@mcp.tool()
async def execute_query(
    source_id: str,
    query: str,
    limit: int | None = None,
) -> dict:
    """Run a free-form read-only SQL query against a SQL data source.

    Only supported for SQL sources (e.g. azure-sql). The query must be a
    single SELECT or WITH (CTE) statement — DML/DDL, comments, batch
    separators and stored-procedure calls are rejected. Results are capped
    at 1000 rows by default; pass an explicit 'limit' to read more, or
    paginate via ORDER BY/OFFSET in the query itself.

    For file-based sources (Azure Data Lake) this returns a clear
    'unsupported' error — use read_data instead.

    Args:
        source_id: Source ID from list_sources()
        query: Read-only SELECT or WITH statement
        limit: Optional maximum rows to return

    Returns:
        Dict with data records, row_count, columns, warnings and metadata.
    """
    return await module.execute_query(source_id, query, limit)


@mcp.tool()
async def download_data(
    source_id: str,
    data_id: str,
    destination: str,
    session_id: str = "",
    project_id: str = "",
) -> dict:
    """Download data from a source to the workspace.

    Args:
        source_id: Source ID from list_sources()
        data_id: Data item ID from list_available_data()
        destination: Destination path relative to workspace (e.g., data/myfile.csv)
        session_id: Session ID (auto-injected by backend)
        project_id: Project ID (auto-injected by backend)

    Returns:
        Dict with download result (destination, row_count/size).
    """
    workspace_dir = WORKSPACE_ROOT / "default" / project_id / session_id
    destination_path = (workspace_dir / destination).resolve()

    try:
        destination_path.relative_to(workspace_dir.resolve())
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid destination path: '{destination}' escapes the workspace directory",
        }

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    return await module.download_data(source_id, data_id, str(destination_path))