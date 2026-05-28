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
from typing import Literal

from fastmcp import FastMCP
from .charts import (
    MULTI_SERIES_TYPES,
    aggregate_multi_series,
    aggregate_rows,
    build_chart_spec,
    build_multi_series_chart_spec,
    spec_to_markdown,
)
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


@mcp.tool()
async def create_chart(
    data: list[dict],
    chart_type: Literal[
        "bar", "line", "area", "horizontal_bar", "scatter",
        "pie", "donut", "treemap", "funnel",
    ],
    x_column: str,
    y_column: str,
    title: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
) -> dict:
    """Produce a chart spec the chat UI can render inline.

    Use this AFTER pulling data with read_data() or execute_query() to
    visualize the result. Prefer execute_query when an aggregation is needed
    (e.g. GROUP BY) so the database does the work and the chart input stays
    small.

    The returned `markdown` field is a ready-to-embed fenced code block.
    Include it verbatim in your next user-facing message (e.g. inside
    hitl_ask_question) — the chat UI will render the chart inline.

    Args:
        data: List of row dicts, as returned by read_data/execute_query.
        chart_type: One of "bar", "line", "pie", "scatter".
        x_column: Column name to use for the x-axis (or pie slice name).
        y_column: Column name to use for the y-axis (or pie slice value).
        title: Optional chart title.
        x_label: Optional x-axis label (ignored for pie).
        y_label: Optional y-axis label (ignored for pie).

    Returns:
        On success: {"success": True, "spec": <chart spec>, "markdown": "```chart..."}.
        On failure: {"success": False, "error": "<reason>"}.
    """
    try:
        spec = build_chart_spec(
            data=data,
            chart_type=chart_type,
            x_column=x_column,
            y_column=y_column,
            title=title,
            x_label=x_label,
            y_label=y_label,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "spec": spec,
        "markdown": spec_to_markdown(spec),
    }


@mcp.tool()
async def create_chart_from_source(
    source_id: str,
    data_id: str,
    chart_type: Literal[
        "bar", "line", "area", "horizontal_bar", "scatter",
        "pie", "donut", "treemap", "funnel",
        "stacked_bar", "grouped_bar", "stacked_area", "multi_line",
    ],
    x_column: str,
    y_column: str | None = None,
    series_column: str | None = None,
    aggregation: Literal["count", "sum", "avg", "min", "max"] = "count",
    filter_expr: str | None = None,
    top_n: int | None = 20,
    max_series: int | None = 10,
    read_limit: int = 5000,
    title: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
) -> dict:
    """Build a chart spec by reading + aggregating data SERVER-SIDE.

    Use this for charting data that lives in a configured source (Azure SQL
    table or Azure Data Lake file). The raw rows NEVER enter the conversation
    — the data is read inside this MCP server, aggregated, and only the small
    per-category summary + chart spec is returned to you.

    PREFER THIS over read_data + create_chart for any non-trivial dataset.
    Calling read_data with many rows pulls megabytes of JSON into your
    context and will overflow the LLM. This tool keeps your context small.

    Chart type families and required columns:
      - Single-series (x/y axes):       bar | line | area | horizontal_bar | scatter
        → set x_column + y_column (or aggregation="count" for y)
      - Proportions (name/value):       pie | donut | treemap | funnel
        → set x_column (becomes slice name) + y_column / aggregation="count"
      - Multi-series breakdowns:        stacked_bar | grouped_bar | stacked_area | multi_line
        → ALSO set series_column (a second grouping column, e.g. "year")

    Aggregation semantics:
      - "count":          count rows per group (y_column ignored)
      - "sum"/"avg"/...:  aggregate y_column values grouped by x_column
                          (and series_column for multi-series)

    Args:
        source_id:     Source ID from list_sources()
        data_id:       Table name (SQL) or file path (Data Lake)
        chart_type:    See families above
        x_column:      Primary grouping column (becomes x / pie name)
        y_column:      Numeric column to aggregate (required unless aggregation="count")
        series_column: Second grouping column — REQUIRED for multi-series chart types,
                       ignored otherwise. Each unique value becomes a series.
        aggregation:   count | sum | avg | min | max
        filter_expr:   Optional pre-aggregation filter
        top_n:         Keep only top N x_column values by total aggregated value (default 20)
        max_series:    For multi-series only — cap the number of series kept (default 10)
        read_limit:    Hard cap on rows fetched from source (default 5000)
        title:         Optional chart title
        x_label:       Optional x-axis label
        y_label:       Optional y-axis label

    Returns:
        On success: {"success": True, "spec": ..., "markdown": "```chart...",
                     "row_count_read": int, "category_count": int,
                     "series_count": int (multi-series only)}.
        On failure: {"success": False, "error": "<reason>"}.
    """
    normalized_filter = filter_expr
    if normalized_filter is not None and normalized_filter.strip().lower() in ("", "null", "none"):
        normalized_filter = None
    if series_column is not None and series_column.strip().lower() in ("", "null", "none"):
        series_column = None

    is_multi = chart_type in MULTI_SERIES_TYPES
    if is_multi and not series_column:
        return {
            "success": False,
            "error": f"chart_type={chart_type!r} requires series_column",
        }

    read_result = await module.read_data(
        source_id, data_id, filter_expr=normalized_filter, limit=read_limit
    )
    if not read_result.get("success"):
        return {
            "success": False,
            "error": f"read_data failed: {read_result.get('error', 'unknown error')}",
        }

    rows = read_result.get("data", [])
    if not isinstance(rows, list) or not rows:
        return {"success": False, "error": "source returned no rows"}

    default_title = title or (
        f"{aggregation}({y_column or '*'}) by {x_column}"
        + (f" / {series_column}" if is_multi else "")
    )
    default_y_label = y_label or (
        "count" if aggregation == "count" else f"{aggregation}({y_column})"
    )

    if is_multi:
        try:
            aggregated, series_keys = aggregate_multi_series(
                data=rows,
                x_column=x_column,
                series_column=series_column,  # type: ignore[arg-type]
                y_column=y_column,
                aggregation=aggregation,
                top_n=top_n,
                max_series=max_series,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        if not aggregated:
            return {
                "success": False,
                "error": "aggregation produced no rows (check x_column/series_column have non-null values)",
            }

        try:
            spec = build_multi_series_chart_spec(
                data=aggregated,
                chart_type=chart_type,
                x_column=x_column,
                series=series_keys,
                title=default_title,
                x_label=x_label or x_column,
                y_label=default_y_label,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        return {
            "success": True,
            "spec": spec,
            "markdown": spec_to_markdown(spec),
            "row_count_read": len(rows),
            "category_count": len(aggregated),
            "series_count": len(series_keys),
        }

    # Single-series path
    try:
        aggregated, agg_column = aggregate_rows(
            data=rows,
            x_column=x_column,
            y_column=y_column,
            aggregation=aggregation,
            top_n=top_n,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not aggregated:
        return {
            "success": False,
            "error": f"aggregation produced no rows (x_column={x_column!r} may be missing or all null)",
        }

    try:
        spec = build_chart_spec(
            data=aggregated,
            chart_type=chart_type,
            x_column=x_column,
            y_column=agg_column,
            title=default_title,
            x_label=x_label or x_column,
            y_label=default_y_label,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "spec": spec,
        "markdown": spec_to_markdown(spec),
        "row_count_read": len(rows),
        "category_count": len(aggregated),
    }