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

    return {
        "type": chart_type,
        "title": title or "",
        "x_label": x_label,
        "y_label": y_label,
        "data": points,
    }


def build_multi_series_chart_spec(
    data: list[dict],
    chart_type: ChartType,
    x_column: str,
    series: list[str],
    title: str = "",
    x_label: str | None = None,
    y_label: str | None = None,
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

    return {
        "type": chart_type,
        "title": title or "",
        "x_label": x_label,
        "y_label": y_label,
        "series": [{"key": s, "label": s} for s in series],
        "data": points,
    }


def spec_to_markdown(spec: dict) -> str:
    """Wrap a chart spec in a ```chart fenced code block, ready for chat."""
    return "```chart\n" + json.dumps(spec, ensure_ascii=False) + "\n```"


SUPPORTED_AGGREGATIONS: tuple[str, ...] = ("count", "sum", "avg", "min", "max")


def aggregate_rows(
    data: list[dict],
    x_column: str,
    y_column: str | None,
    aggregation: str,
    top_n: int | None = None,
) -> tuple[list[dict], str]:
    """Group rows by `x_column` and aggregate over `y_column` (single series).

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
