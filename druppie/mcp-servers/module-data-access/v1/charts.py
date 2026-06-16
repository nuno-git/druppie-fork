"""Chart-spec builder for the data-access MCP server.

Pure-Python helper that turns tabular data plus a chart configuration into a
small JSON spec the chat UI can render via the `ChartBlock` React component.

Kept separate from `tools.py` so the spec logic is easy to unit-test without
needing the FastMCP runtime.

Three families of chart types share three data shapes:

  XY_TYPES        — {x, y} rows (bar, line, area, horizontal_bar, scatter)
  NAME_VALUE_TYPES — {name, value} rows (pie, donut, treemap, funnel)
  MULTI_SERIES_TYPES — {x, <series_key>: value, ...} rows + spec.series list
                       (stacked_bar, grouped_bar, stacked_area, multi_line)
"""

from __future__ import annotations

import json
import re
from typing import Any

ChartType = str

XY_TYPES: tuple[ChartType, ...] = ("bar", "line", "area", "horizontal_bar", "scatter")
NAME_VALUE_TYPES: tuple[ChartType, ...] = ("pie", "donut", "treemap", "funnel")
MULTI_SERIES_TYPES: tuple[ChartType, ...] = (
    "stacked_bar",
    "grouped_bar",
    "stacked_area",
    "multi_line",
)
SUPPORTED_CHART_TYPES: tuple[ChartType, ...] = XY_TYPES + NAME_VALUE_TYPES + MULTI_SERIES_TYPES

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DATE_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$"
    r"|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"
    r"|^\d{4}[-/]Q[1-4]$"
    r"|^Q[1-4][-/ ]\d{4}$"
)

_LABEL_ABBREVIATIONS: dict[str, str] = {
    "avg": "Average",
    "cnt": "Count",
    "num": "Number",
    "pct": "Percentage",
    "qty": "Quantity",
    "amt": "Amount",
    "desc": "Description",
    "id": "ID",
}


def is_temporal(values: list) -> bool:
    """Return True if the majority of non-None values look like years or dates."""
    candidates = [v for v in values if v is not None]
    if not candidates:
        return False
    hits = sum(
        1
        for v in candidates
        if (isinstance(v, (int, float)) and 1900 <= v <= 2100)
        or (isinstance(v, str) and (_YEAR_RE.match(v) or _DATE_RE.match(v)))
    )
    return hits >= len(candidates) * 0.6


def humanize_label(column_name: str | None) -> str:
    """Turn a technical column name into a readable chart label.

    "total_revenue" → "Total Revenue", "avg" → "Average".
    """
    if not column_name:
        return ""
    parts = re.split(r"[_\s]+", column_name.strip())
    result = []
    for p in parts:
        low = p.lower()
        if low in _LABEL_ABBREVIATIONS:
            result.append(_LABEL_ABBREVIATIONS[low])
        else:
            result.append(p.capitalize())
    return " ".join(result)


def infer_number_format(data: list[dict], value_key: str) -> str | None:
    """Return "compact" if values are large enough to benefit from K/M formatting."""
    values = []
    for row in data:
        v = row.get(value_key)
        if isinstance(v, (int, float)):
            values.append(abs(v))
    if not values:
        return None
    return "compact" if max(values) >= 10_000 else None


def recommend_chart_type(
    data: list[dict],
    x_column: str,
    y_column: str | None,
    series_column: str | None,
    aggregation: str,
) -> ChartType:
    """Deterministic chart type recommendation based on data shape."""
    x_values = [row.get(x_column) for row in data if row.get(x_column) is not None]
    n_categories = len(set(str(v) for v in x_values))

    if series_column:
        if is_temporal(x_values):
            return "multi_line"
        return "stacked_bar"

    if is_temporal(x_values):
        return "line"

    max_label_len = max((len(str(v)) for v in x_values), default=0)

    if max_label_len > 20:
        return "horizontal_bar"
    if n_categories <= 6 and aggregation in ("count", "sum"):
        return "pie"
    if n_categories > 15:
        return "treemap"
    return "bar"


def _coerce_number(value: Any, *, column: str) -> float:
    """Coerce a cell value to float, raising ValueError with column context."""
    if value is None:
        raise ValueError(f"column '{column}' contains a null value")
    if isinstance(value, bool):
        raise ValueError(f"column '{column}' contains a boolean, expected a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(
                f"column '{column}' contains a non-numeric string: {value!r}"
            ) from exc
    raise ValueError(
        f"column '{column}' contains an unsupported type: {type(value).__name__}"
    )


def build_chart_spec(
    data: list[dict],
    chart_type: ChartType,
    x_column: str,
    y_column: str,
    title: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
    number_format: str | None = None,
) -> dict:
    """Build a validated single-series chart spec.

    For multi-series charts use `build_multi_series_chart_spec` instead.
    """
    if chart_type in MULTI_SERIES_TYPES:
        raise ValueError(
            f"chart_type {chart_type!r} is multi-series; "
            f"use build_multi_series_chart_spec()"
        )
    if chart_type not in SUPPORTED_CHART_TYPES:
        raise ValueError(
            f"unsupported chart_type {chart_type!r}; "
            f"expected one of {', '.join(SUPPORTED_CHART_TYPES)}"
        )
    if not isinstance(data, list) or not data:
        raise ValueError("'data' must be a non-empty list of row dicts")
    if not x_column or not y_column:
        raise ValueError("'x_column' and 'y_column' are required")

    first_row = data[0]
    if not isinstance(first_row, dict):
        raise ValueError("each row in 'data' must be a dict")
    if x_column not in first_row:
        raise ValueError(f"x_column {x_column!r} is not present in the data rows")
    if y_column not in first_row:
        raise ValueError(f"y_column {y_column!r} is not present in the data rows")

    points: list[dict] = []
    for row in data:
        if chart_type in NAME_VALUE_TYPES:
            points.append(
                {
                    "name": str(row[x_column]),
                    "value": _coerce_number(row[y_column], column=y_column),
                }
            )
        elif chart_type == "scatter":
            points.append(
                {
                    "x": _coerce_number(row[x_column], column=x_column),
                    "y": _coerce_number(row[y_column], column=y_column),
                }
            )
        else:  # bar, line, area, horizontal_bar — categorical/ordered x, numeric y
            x_val = row[x_column]
            points.append(
                {
                    "x": x_val if isinstance(x_val, (int, float)) else str(x_val),
                    "y": _coerce_number(row[y_column], column=y_column),
                }
            )

    spec = {
        "type": chart_type,
        "title": title or "",
        "x_label": x_label,
        "y_label": y_label,
        "data": points,
    }
    if number_format:
        spec["number_format"] = number_format
    return spec


def build_multi_series_chart_spec(
    data: list[dict],
    chart_type: ChartType,
    x_column: str,
    series: list[str],
    title: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
    number_format: str | None = None,
) -> dict:
    """Build a validated multi-series chart spec.

    `data` rows look like `{x_column: <category>, <series[0]>: <num>, ...}`.
    The resulting spec normalizes `x_column` to "x" so the frontend can use
    a single `dataKey="x"` across chart types.
    """
    if chart_type not in MULTI_SERIES_TYPES:
        raise ValueError(
            f"chart_type {chart_type!r} is not a multi-series type; "
            f"expected one of {', '.join(MULTI_SERIES_TYPES)}"
        )
    if not isinstance(data, list) or not data:
        raise ValueError("'data' must be a non-empty list of row dicts")
    if not x_column:
        raise ValueError("'x_column' is required")
    if not series:
        raise ValueError("'series' must be a non-empty list of column names")

    first_row = data[0]
    if not isinstance(first_row, dict):
        raise ValueError("each row in 'data' must be a dict")
    if x_column not in first_row:
        raise ValueError(f"x_column {x_column!r} is not present in the data rows")
    # Series columns may be missing from some rows — the loop below fills with 0.
    # We only require that at least ONE series value appears somewhere in the data,
    # otherwise the chart would be empty and meaningless.
    if not any(s in row for row in data for s in series):
        raise ValueError("none of the series columns are present in any data row")

    points: list[dict] = []
    for row in data:
        out: dict[str, Any] = {}
        x_val = row[x_column]
        out["x"] = x_val if isinstance(x_val, (int, float)) else str(x_val)
        for s in series:
            value = row.get(s)
            if value is None:
                out[s] = 0.0
            else:
                try:
                    out[s] = _coerce_number(value, column=s)
                except ValueError:
                    out[s] = 0.0
        points.append(out)

    spec = {
        "type": chart_type,
        "title": title or "",
        "x_label": x_label,
        "y_label": y_label,
        "series": [{"key": s, "label": s} for s in series],
        "data": points,
    }
    if number_format:
        spec["number_format"] = number_format
    return spec


def spec_to_markdown(spec: dict) -> str:
    """Wrap a chart spec in a ```chart fenced code block, ready for chat."""
    return "```chart\n" + json.dumps(spec, ensure_ascii=False) + "\n```"


def _quote_ident(ident: str) -> str:
    """Quote a T-SQL identifier with brackets, escaping embedded ]."""
    return "[" + str(ident).replace("]", "]]") + "]"


def build_sql_aggregation_query(
    data_id: str,
    x_column: str,
    y_column: str | None,
    aggregation: str,
    series_column: str | None = None,
    filter_expr: str | None = None,
    top_n: int | None = None,
    sort_by: str = "value",
) -> str:
    """Build a GROUP BY aggregation query for a SQL source.

    Pushes the aggregation into the database so it runs over the FULL table
    and returns only the small grouped result (no row-cap truncation).

    `data_id` is "schema.table" (or just "table"). Output columns are
    aliased to `x`/`y` (single-series) or `x`/`s`/`y` (multi-series) so the
    caller can build the spec without knowing the original column names.
    """
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise ValueError(
            f"unsupported aggregation {aggregation!r}; "
            f"expected one of {', '.join(SUPPORTED_AGGREGATIONS)}"
        )
    if aggregation != "count" and not y_column:
        raise ValueError(f"aggregation={aggregation!r} requires y_column")
    if not x_column:
        raise ValueError("x_column is required")

    if "." in data_id:
        schema, table = data_id.split(".", 1)
        table_ref = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    else:
        table_ref = _quote_ident(data_id)

    if aggregation == "count":
        agg_expr = "COUNT(*)"
    else:
        fn = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}[aggregation]
        agg_expr = f"{fn}({_quote_ident(y_column)})"

    where = f" WHERE {filter_expr}" if filter_expr else ""

    if series_column:
        # Multi-series: group by both dimensions; caller pivots + trims.
        return (
            f"SELECT {_quote_ident(x_column)} AS x, "
            f"{_quote_ident(series_column)} AS s, {agg_expr} AS y "
            f"FROM {table_ref}{where} "
            f"GROUP BY {_quote_ident(x_column)}, {_quote_ident(series_column)}"
        )

    top = f"TOP {int(top_n)} " if top_n else ""
    order = f"{_quote_ident(x_column)} ASC" if sort_by == "label" else f"{agg_expr} DESC"
    return (
        f"SELECT {top}{_quote_ident(x_column)} AS x, {agg_expr} AS y "
        f"FROM {table_ref}{where} "
        f"GROUP BY {_quote_ident(x_column)} "
        f"ORDER BY {order}"
    )


SUPPORTED_AGGREGATIONS: tuple[str, ...] = ("count", "sum", "avg", "min", "max")


def aggregate_rows(
    data: list[dict],
    x_column: str,
    y_column: str | None,
    aggregation: str,
    top_n: int | None = None,
    sort_by: str = "value",
) -> tuple[list[dict], str]:
    """Group rows by `x_column` and aggregate over `y_column` (single series).

    sort_by: "value" (descending by aggregated value), "label" (ascending by
    x_column — natural order for chronological/alphabetical data).

    Returns `(rows, agg_column_name)` — see module docstring for shape.
    """
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise ValueError(
            f"unsupported aggregation {aggregation!r}; "
            f"expected one of {', '.join(SUPPORTED_AGGREGATIONS)}"
        )
    if not isinstance(data, list):
        raise ValueError("'data' must be a list of row dicts")
    if not x_column:
        raise ValueError("'x_column' is required")
    if aggregation != "count" and not y_column:
        raise ValueError(f"aggregation={aggregation!r} requires y_column")

    if aggregation == "count":
        counts: dict = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            key = row.get(x_column)
            if key is None:
                continue
            counts[key] = counts.get(key, 0) + 1
        result = [{x_column: k, "count": v} for k, v in counts.items()]
        agg_column = "count"
    else:
        buckets: dict = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            x = row.get(x_column)
            y = row.get(y_column)
            if x is None or y is None:
                continue
            if isinstance(y, bool):
                continue
            if isinstance(y, (int, float)):
                y_num = float(y)
            elif isinstance(y, str):
                try:
                    y_num = float(y)
                except ValueError:
                    continue
            else:
                continue
            buckets.setdefault(x, []).append(y_num)
        result = []
        for x, ys in buckets.items():
            if not ys:
                continue
            if aggregation == "sum":
                agg = sum(ys)
            elif aggregation == "avg":
                agg = sum(ys) / len(ys)
            elif aggregation == "min":
                agg = min(ys)
            else:  # max
                agg = max(ys)
            result.append({x_column: x, y_column: agg})
        agg_column = y_column  # type: ignore[assignment]

    if sort_by == "label":
        result.sort(key=lambda r: str(r[x_column]))
    else:
        result.sort(key=lambda r: r[agg_column], reverse=True)
    if top_n is not None and top_n > 0:
        result = result[:top_n]
    return result, agg_column


def aggregate_multi_series(
    data: list[dict],
    x_column: str,
    series_column: str,
    y_column: str | None,
    aggregation: str,
    top_n: int | None = None,
    max_series: int | None = 10,
    sort_by: str = "value",
) -> tuple[list[dict], list[str]]:
    """Pivot-aggregate rows for a multi-series chart.

    Groups by (x_column, series_column) pair and applies `aggregation`.
    Returns `(rows, series_keys)` where each row is
    `{x_column: <x_value>, <series_value_1>: <agg>, <series_value_2>: <agg>, ...}`.

    `top_n` keeps the top N x_column values by total aggregated value.
    `max_series` keeps the top N series_column values; remaining are dropped.
    Missing (x, series) pairs in the output get 0 to keep the data shape rectangular.
    """
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise ValueError(
            f"unsupported aggregation {aggregation!r}; "
            f"expected one of {', '.join(SUPPORTED_AGGREGATIONS)}"
        )
    if not isinstance(data, list):
        raise ValueError("'data' must be a list of row dicts")
    if not x_column or not series_column:
        raise ValueError("'x_column' and 'series_column' are required")
    if aggregation != "count" and not y_column:
        raise ValueError(f"aggregation={aggregation!r} requires y_column")

    # bucket[(x, s)] = list of y values  (or count via len)
    buckets: dict[tuple, list[float]] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        x = row.get(x_column)
        s = row.get(series_column)
        if x is None or s is None:
            continue
        if aggregation == "count":
            buckets.setdefault((x, s), []).append(1.0)
            continue
        y = row.get(y_column)
        if y is None or isinstance(y, bool):
            continue
        if isinstance(y, (int, float)):
            y_num = float(y)
        elif isinstance(y, str):
            try:
                y_num = float(y)
            except ValueError:
                continue
        else:
            continue
        buckets.setdefault((x, s), []).append(y_num)

    def _apply(values: list[float]) -> float:
        if aggregation == "count":
            return float(len(values))
        if aggregation == "sum":
            return sum(values)
        if aggregation == "avg":
            return sum(values) / len(values)
        if aggregation == "min":
            return min(values)
        return max(values)  # max

    # Aggregate each (x, s) pair.
    agg: dict[tuple, float] = {(x, s): _apply(vs) for (x, s), vs in buckets.items() if vs}

    # Compute x totals and series totals for top_n trimming.
    x_totals: dict = {}
    s_totals: dict = {}
    for (x, s), v in agg.items():
        x_totals[x] = x_totals.get(x, 0.0) + v
        s_totals[s] = s_totals.get(s, 0.0) + v

    if sort_by == "label":
        x_order = sorted(x_totals.items(), key=lambda kv: str(kv[0]))
    else:
        x_order = sorted(x_totals.items(), key=lambda kv: kv[1], reverse=True)
    if top_n is not None and top_n > 0:
        x_order = x_order[:top_n]
    kept_x = [x for x, _ in x_order]

    s_order = sorted(s_totals.items(), key=lambda kv: kv[1], reverse=True)
    if max_series is not None and max_series > 0:
        s_order = s_order[:max_series]
    series_keys = [str(s) for s, _ in s_order]

    rows: list[dict] = []
    for x in kept_x:
        row: dict[str, Any] = {x_column: x}
        for s, s_str in zip([s for s, _ in s_order], series_keys):
            row[s_str] = agg.get((x, s), 0.0)
        rows.append(row)

    return rows, series_keys
