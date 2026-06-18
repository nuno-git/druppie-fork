"""Unit tests for the dataaccess MCP chart-spec builder.

`charts.py` lives in `druppie/mcp-servers/module-data-access/v1/`, which is a
standalone service tree (the directory name uses a dash, so it is not a Python
package importable from the main `druppie` package). We load the module
directly by path to keep the test free of any sys.path / package shenanigans.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_CHARTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "mcp-servers"
    / "module-data-access"
    / "v1"
    / "charts.py"
)

_spec = importlib.util.spec_from_file_location("dataaccess_charts", _CHARTS_PATH)
charts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(charts)


# ---------------------------------------------------------------------------
# Happy paths — one per chart type
# ---------------------------------------------------------------------------


def test_bar_chart_projects_x_y_pairs():
    data = [
        {"category": "A", "amount": 10},
        {"category": "B", "amount": 25},
        {"category": "C", "amount": 7},
    ]
    spec = charts.build_chart_spec(
        data=data,
        chart_type="bar",
        x_column="category",
        y_column="amount",
        title="Sales by category",
        y_label="Amount (USD)",
    )
    assert spec["type"] == "bar"
    assert spec["title"] == "Sales by category"
    assert spec["y_label"] == "Amount (USD)"
    assert spec["data"] == [
        {"x": "A", "y": 10.0},
        {"x": "B", "y": 25.0},
        {"x": "C", "y": 7.0},
    ]


def test_line_chart_coerces_numeric_strings():
    data = [
        {"month": "2025-01", "revenue": "1200"},
        {"month": "2025-02", "revenue": "1500.5"},
    ]
    spec = charts.build_chart_spec(
        data=data, chart_type="line", x_column="month", y_column="revenue"
    )
    assert spec["type"] == "line"
    assert spec["data"][0] == {"x": "2025-01", "y": 1200.0}
    assert spec["data"][1] == {"x": "2025-02", "y": 1500.5}


def test_pie_chart_uses_name_value_shape():
    data = [
        {"segment": "Enterprise", "share": 0.6},
        {"segment": "SMB", "share": 0.4},
    ]
    spec = charts.build_chart_spec(
        data=data, chart_type="pie", x_column="segment", y_column="share"
    )
    assert spec["data"] == [
        {"name": "Enterprise", "value": 0.6},
        {"name": "SMB", "value": 0.4},
    ]


def test_scatter_chart_requires_numeric_x_and_y():
    data = [
        {"height": 170, "weight": 65},
        {"height": 180, "weight": 80},
    ]
    spec = charts.build_chart_spec(
        data=data, chart_type="scatter", x_column="height", y_column="weight"
    )
    assert spec["data"] == [
        {"x": 170.0, "y": 65.0},
        {"x": 180.0, "y": 80.0},
    ]


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


def test_rejects_unsupported_chart_type():
    with pytest.raises(ValueError, match="unsupported chart_type"):
        charts.build_chart_spec(
            data=[{"a": 1, "b": 2}],
            chart_type="histogram",
            x_column="a",
            y_column="b",
        )


def test_rejects_empty_data():
    with pytest.raises(ValueError, match="non-empty list"):
        charts.build_chart_spec(
            data=[], chart_type="bar", x_column="a", y_column="b"
        )


def test_rejects_missing_x_column():
    with pytest.raises(ValueError, match="x_column 'foo' is not present"):
        charts.build_chart_spec(
            data=[{"bar": 1, "baz": 2}],
            chart_type="bar",
            x_column="foo",
            y_column="baz",
        )


def test_rejects_missing_y_column():
    with pytest.raises(ValueError, match="y_column 'foo' is not present"):
        charts.build_chart_spec(
            data=[{"bar": 1, "baz": 2}],
            chart_type="bar",
            x_column="bar",
            y_column="foo",
        )


def test_rejects_non_numeric_y_value():
    with pytest.raises(ValueError, match="non-numeric string"):
        charts.build_chart_spec(
            data=[{"x": "A", "y": "not a number"}],
            chart_type="bar",
            x_column="x",
            y_column="y",
        )


def test_rejects_null_y_value():
    with pytest.raises(ValueError, match="null value"):
        charts.build_chart_spec(
            data=[{"x": "A", "y": None}],
            chart_type="bar",
            x_column="x",
            y_column="y",
        )


def test_rejects_scatter_with_non_numeric_x():
    with pytest.raises(ValueError, match="non-numeric string"):
        charts.build_chart_spec(
            data=[{"x": "A", "y": 1}],
            chart_type="scatter",
            x_column="x",
            y_column="y",
        )


# ---------------------------------------------------------------------------
# Markdown round-trip
# ---------------------------------------------------------------------------


def test_spec_to_markdown_round_trips_via_json():
    spec = charts.build_chart_spec(
        data=[{"category": "A", "amount": 10}],
        chart_type="bar",
        x_column="category",
        y_column="amount",
        title="Sales",
    )
    md = charts.spec_to_markdown(spec)
    assert md.startswith("```chart\n")
    assert md.endswith("\n```")
    body = md[len("```chart\n") : -len("\n```")]
    assert json.loads(body) == spec


# ---------------------------------------------------------------------------
# aggregate_rows
# ---------------------------------------------------------------------------


def test_aggregate_count_groups_by_x_column():
    data = [
        {"category": "A"},
        {"category": "B"},
        {"category": "A"},
        {"category": "C"},
        {"category": "A"},
    ]
    result, agg_column = charts.aggregate_rows(
        data, x_column="category", y_column=None, aggregation="count"
    )
    assert agg_column == "count"
    # sorted descending by count
    assert result == [
        {"category": "A", "count": 3},
        {"category": "B", "count": 1},
        {"category": "C", "count": 1},
    ]


def test_aggregate_sum_combines_y_values():
    data = [
        {"region": "EU", "revenue": 100},
        {"region": "US", "revenue": 250},
        {"region": "EU", "revenue": 150},
    ]
    result, agg_column = charts.aggregate_rows(
        data, x_column="region", y_column="revenue", aggregation="sum"
    )
    assert agg_column == "revenue"
    assert result == [
        {"region": "EU", "revenue": 250.0},
        {"region": "US", "revenue": 250.0},
    ]


def test_aggregate_avg_handles_numeric_strings():
    data = [
        {"team": "Red", "score": "10"},
        {"team": "Red", "score": "20"},
        {"team": "Blue", "score": "15"},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="team", y_column="score", aggregation="avg"
    )
    by_team = {row["team"]: row["score"] for row in result}
    assert by_team == {"Red": 15.0, "Blue": 15.0}


def test_aggregate_top_n_trims_results():
    data = [{"k": "a"}, {"k": "b"}, {"k": "c"}, {"k": "d"}, {"k": "a"}, {"k": "a"}]
    result, _ = charts.aggregate_rows(
        data, x_column="k", y_column=None, aggregation="count", top_n=2
    )
    assert len(result) == 2
    assert result[0] == {"k": "a", "count": 3}


def test_aggregate_skips_null_keys_and_values():
    data = [
        {"x": "A", "y": 10},
        {"x": None, "y": 5},
        {"x": "B", "y": None},
        {"x": "A", "y": 20},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="x", y_column="y", aggregation="sum"
    )
    assert result == [{"x": "A", "y": 30.0}]


def test_aggregate_rejects_unsupported_aggregation():
    with pytest.raises(ValueError, match="unsupported aggregation"):
        charts.aggregate_rows(
            [{"a": 1}], x_column="a", y_column=None, aggregation="median"
        )


def test_aggregate_requires_y_column_for_non_count():
    with pytest.raises(ValueError, match="requires y_column"):
        charts.aggregate_rows(
            [{"a": 1}], x_column="a", y_column=None, aggregation="sum"
        )


def test_aggregate_min_max():
    data = [
        {"k": "A", "v": 10},
        {"k": "A", "v": 30},
        {"k": "B", "v": 20},
    ]
    min_result, _ = charts.aggregate_rows(
        data, x_column="k", y_column="v", aggregation="min"
    )
    max_result, _ = charts.aggregate_rows(
        data, x_column="k", y_column="v", aggregation="max"
    )
    assert {r["k"]: r["v"] for r in min_result} == {"A": 10.0, "B": 20.0}
    assert {r["k"]: r["v"] for r in max_result} == {"A": 30.0, "B": 20.0}


# ---------------------------------------------------------------------------
# New chart types — single-series variants
# ---------------------------------------------------------------------------


def test_horizontal_bar_uses_xy_shape():
    spec = charts.build_chart_spec(
        data=[{"cat": "A long category name", "val": 5}, {"cat": "B", "val": 10}],
        chart_type="horizontal_bar",
        x_column="cat",
        y_column="val",
    )
    assert spec["type"] == "horizontal_bar"
    assert spec["data"][0] == {"x": "A long category name", "y": 5.0}


def test_area_chart_uses_xy_shape():
    spec = charts.build_chart_spec(
        data=[{"t": 1, "v": 10}, {"t": 2, "v": 20}],
        chart_type="area",
        x_column="t",
        y_column="v",
    )
    assert spec["type"] == "area"
    assert spec["data"][0] == {"x": 1, "y": 10.0}


def test_donut_uses_name_value_shape():
    spec = charts.build_chart_spec(
        data=[{"seg": "Enterprise", "share": 0.6}],
        chart_type="donut",
        x_column="seg",
        y_column="share",
    )
    assert spec["data"] == [{"name": "Enterprise", "value": 0.6}]


def test_treemap_uses_name_value_shape():
    spec = charts.build_chart_spec(
        data=[{"cat": "A", "v": 100}, {"cat": "B", "v": 50}],
        chart_type="treemap",
        x_column="cat",
        y_column="v",
    )
    assert spec["data"] == [{"name": "A", "value": 100.0}, {"name": "B", "value": 50.0}]


def test_funnel_uses_name_value_shape():
    spec = charts.build_chart_spec(
        data=[{"stage": "Visited", "n": 1000}, {"stage": "Signup", "n": 200}],
        chart_type="funnel",
        x_column="stage",
        y_column="n",
    )
    assert spec["data"] == [
        {"name": "Visited", "value": 1000.0},
        {"name": "Signup", "value": 200.0},
    ]


def test_build_chart_spec_rejects_multi_series_types():
    with pytest.raises(ValueError, match="multi-series"):
        charts.build_chart_spec(
            data=[{"x": "A", "y": 1}],
            chart_type="stacked_bar",
            x_column="x",
            y_column="y",
        )


# ---------------------------------------------------------------------------
# Multi-series chart spec
# ---------------------------------------------------------------------------


def test_multi_series_stacked_bar_normalizes_x_key():
    data = [
        {"category": "A", "Q1": 10, "Q2": 15},
        {"category": "B", "Q1": 5, "Q2": 8},
    ]
    spec = charts.build_multi_series_chart_spec(
        data=data,
        chart_type="stacked_bar",
        x_column="category",
        series=["Q1", "Q2"],
        title="Sales by quarter",
    )
    assert spec["type"] == "stacked_bar"
    assert spec["series"] == [{"key": "Q1", "label": "Q1"}, {"key": "Q2", "label": "Q2"}]
    # x normalized to "x", series keys retained
    assert spec["data"] == [
        {"x": "A", "Q1": 10.0, "Q2": 15.0},
        {"x": "B", "Q1": 5.0, "Q2": 8.0},
    ]


def test_multi_series_fills_missing_series_with_zero():
    data = [{"category": "A", "Q1": 10}]  # Q2 missing
    spec = charts.build_multi_series_chart_spec(
        data=data,
        chart_type="grouped_bar",
        x_column="category",
        series=["Q1", "Q2"],
    )
    # Q2 absent in the row → defaulted to 0
    assert spec["data"][0] == {"x": "A", "Q1": 10.0, "Q2": 0.0}


def test_multi_series_rejects_single_series_type():
    with pytest.raises(ValueError, match="not a multi-series type"):
        charts.build_multi_series_chart_spec(
            data=[{"x": "A", "Q1": 1}],
            chart_type="bar",
            x_column="x",
            series=["Q1"],
        )


def test_multi_series_rejects_empty_series():
    with pytest.raises(ValueError, match="non-empty list"):
        charts.build_multi_series_chart_spec(
            data=[{"x": "A"}],
            chart_type="stacked_bar",
            x_column="x",
            series=[],
        )


# ---------------------------------------------------------------------------
# aggregate_multi_series
# ---------------------------------------------------------------------------


def test_aggregate_multi_series_count_pivot():
    data = [
        {"category": "A", "year": 2024},
        {"category": "A", "year": 2024},
        {"category": "A", "year": 2025},
        {"category": "B", "year": 2024},
        {"category": "B", "year": 2025},
        {"category": "B", "year": 2025},
    ]
    rows, series_keys = charts.aggregate_multi_series(
        data,
        x_column="category",
        series_column="year",
        y_column=None,
        aggregation="count",
    )
    # series totals: 2024=3, 2025=3 → both kept, order tied
    assert set(series_keys) == {"2024", "2025"}
    by_cat = {r["category"]: {k: r[k] for k in series_keys} for r in rows}
    assert by_cat == {"A": {"2024": 2.0, "2025": 1.0}, "B": {"2024": 1.0, "2025": 2.0}}


def test_aggregate_multi_series_sum_with_y_column():
    data = [
        {"region": "EU", "product": "X", "revenue": 100},
        {"region": "EU", "product": "Y", "revenue": 200},
        {"region": "US", "product": "X", "revenue": 50},
        {"region": "US", "product": "Y", "revenue": 80},
    ]
    rows, series_keys = charts.aggregate_multi_series(
        data,
        x_column="region",
        series_column="product",
        y_column="revenue",
        aggregation="sum",
    )
    # Y total: 280, X total: 150 → series sorted desc
    assert series_keys == ["Y", "X"]
    eu = next(r for r in rows if r["region"] == "EU")
    assert eu["X"] == 100.0
    assert eu["Y"] == 200.0


def test_aggregate_multi_series_caps_with_max_series():
    data = [
        {"x": "A", "s": "1"},
        {"x": "A", "s": "2"},
        {"x": "A", "s": "3"},
        {"x": "A", "s": "1"},
        {"x": "A", "s": "1"},
    ]
    rows, series_keys = charts.aggregate_multi_series(
        data,
        x_column="x",
        series_column="s",
        y_column=None,
        aggregation="count",
        max_series=2,
    )
    # top-2 series by total: 1 (3 rows), then 2 or 3 (1 each)
    assert series_keys[0] == "1"
    assert len(series_keys) == 2
    assert "3" not in rows[0] or rows[0].get("3", 0) == 0


def test_aggregate_multi_series_requires_y_for_non_count():
    with pytest.raises(ValueError, match="requires y_column"):
        charts.aggregate_multi_series(
            [{"x": "A", "s": "1"}],
            x_column="x",
            series_column="s",
            y_column=None,
            aggregation="sum",
        )


# ---------------------------------------------------------------------------
# build_sql_aggregation_query — full-dataset GROUP BY pushdown
# ---------------------------------------------------------------------------


def test_sql_query_count_single_series():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.users",
        x_column="country",
        y_column=None,
        aggregation="count",
        top_n=20,
    )
    assert q == (
        "SELECT TOP 20 [country] AS x, COUNT(*) AS y "
        "FROM [dbo].[users] "
        "GROUP BY [country] "
        "ORDER BY COUNT(*) DESC"
    )


def test_sql_query_sum_with_y_column():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.sales",
        x_column="region",
        y_column="amount",
        aggregation="sum",
        top_n=10,
    )
    assert q == (
        "SELECT TOP 10 [region] AS x, SUM([amount]) AS y "
        "FROM [dbo].[sales] "
        "GROUP BY [region] "
        "ORDER BY SUM([amount]) DESC"
    )


def test_sql_query_with_filter():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.sales",
        x_column="region",
        y_column=None,
        aggregation="count",
        filter_expr="year = 2025",
        top_n=5,
    )
    assert "WHERE year = 2025" in q
    assert "GROUP BY [region]" in q


def test_sql_query_multi_series_no_top():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.sales",
        x_column="region",
        y_column="revenue",
        aggregation="sum",
        series_column="product",
        top_n=20,  # ignored for multi-series (caller pivots)
    )
    assert q == (
        "SELECT [region] AS x, [product] AS s, SUM([revenue]) AS y "
        "FROM [dbo].[sales] "
        "GROUP BY [region], [product]"
    )
    assert "TOP" not in q


def test_sql_query_table_without_schema():
    q = charts.build_sql_aggregation_query(
        data_id="users",
        x_column="country",
        y_column=None,
        aggregation="count",
        top_n=10,
    )
    assert "FROM [users]" in q


def test_sql_query_escapes_bracket_in_identifier():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.weird",
        x_column="col]name",
        y_column=None,
        aggregation="count",
    )
    # ] doubled to ]] inside the brackets
    assert "[col]]name]" in q


def test_sql_query_rejects_bad_aggregation():
    with pytest.raises(ValueError, match="unsupported aggregation"):
        charts.build_sql_aggregation_query(
            data_id="dbo.t", x_column="a", y_column="b", aggregation="median"
        )


def test_sql_query_requires_y_for_non_count():
    with pytest.raises(ValueError, match="requires y_column"):
        charts.build_sql_aggregation_query(
            data_id="dbo.t", x_column="a", y_column=None, aggregation="avg"
        )


# ---------------------------------------------------------------------------
# is_temporal
# ---------------------------------------------------------------------------


def test_is_temporal_detects_years():
    assert charts.is_temporal([2019, 2020, 2021, 2022]) is True


def test_is_temporal_detects_year_strings():
    assert charts.is_temporal(["2019", "2020", "2021"]) is True


def test_is_temporal_detects_date_strings():
    assert charts.is_temporal(["2024-01-15", "2024-02-20", "2024-03-10"]) is True


def test_is_temporal_detects_quarter_strings():
    assert charts.is_temporal(["2024-Q1", "2024-Q2", "2024-Q3"]) is True


def test_is_temporal_rejects_categories():
    assert charts.is_temporal(["Noord", "Zuid", "Oost", "West"]) is False


def test_is_temporal_rejects_numbers_outside_year_range():
    assert charts.is_temporal([50000, 60000, 70000]) is False


def test_is_temporal_handles_empty():
    assert charts.is_temporal([]) is False


# ---------------------------------------------------------------------------
# humanize_label
# ---------------------------------------------------------------------------


def test_humanize_label_snake_case():
    assert charts.humanize_label("total_revenue") == "Total Revenue"


def test_humanize_label_abbreviations():
    assert charts.humanize_label("avg") == "Average"
    assert charts.humanize_label("cnt") == "Count"


def test_humanize_label_empty():
    assert charts.humanize_label(None) == ""
    assert charts.humanize_label("") == ""


# ---------------------------------------------------------------------------
# infer_number_format
# ---------------------------------------------------------------------------


def test_infer_number_format_compact_for_large():
    data = [{"v": 50_000}, {"v": 120_000}]
    assert charts.infer_number_format(data, "v") == "compact"


def test_infer_number_format_none_for_small():
    data = [{"v": 50}, {"v": 120}]
    assert charts.infer_number_format(data, "v") is None


def test_infer_number_format_empty():
    assert charts.infer_number_format([], "v") is None


# ---------------------------------------------------------------------------
# recommend_chart_type
# ---------------------------------------------------------------------------


def test_recommend_temporal_data():
    data = [{"year": 2020, "v": 10}, {"year": 2021, "v": 20}, {"year": 2022, "v": 30}]
    assert charts.recommend_chart_type(data, "year", "v", None, "sum") == "line"


def test_recommend_few_categories():
    data = [{"s": "A", "v": 1}, {"s": "B", "v": 2}, {"s": "C", "v": 3}]
    assert charts.recommend_chart_type(data, "s", "v", None, "count") == "pie"


def test_recommend_long_labels():
    data = [
        {"cat": "Informatievoorziening en automatisering", "v": 10},
        {"cat": "Short", "v": 20},
    ]
    assert charts.recommend_chart_type(data, "cat", "v", None, "sum") == "horizontal_bar"


def test_recommend_many_categories():
    data = [{"cat": f"cat_{i}", "v": i} for i in range(20)]
    assert charts.recommend_chart_type(data, "cat", "v", None, "sum") == "treemap"


def test_recommend_with_series():
    data = [{"region": "EU", "product": "X", "v": 10}]
    assert charts.recommend_chart_type(data, "region", "v", "product", "sum") == "stacked_bar"


def test_recommend_temporal_with_series():
    data = [{"year": 2020, "product": "X", "v": 10}]
    assert charts.recommend_chart_type(data, "year", "v", "product", "sum") == "multi_line"


# ---------------------------------------------------------------------------
# sort_by in aggregation
# ---------------------------------------------------------------------------


def test_aggregate_rows_sort_by_label():
    data = [
        {"year": "2022", "v": 10},
        {"year": "2020", "v": 30},
        {"year": "2021", "v": 20},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="year", y_column="v", aggregation="sum", sort_by="label"
    )
    assert [r["year"] for r in result] == ["2020", "2021", "2022"]


def test_aggregate_rows_sort_by_value():
    data = [
        {"year": "2020", "v": 10},
        {"year": "2022", "v": 30},
        {"year": "2021", "v": 20},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="year", y_column="v", aggregation="sum", sort_by="value"
    )
    assert [r["year"] for r in result] == ["2022", "2021", "2020"]


def test_aggregate_multi_series_sort_by_label():
    data = [
        {"year": "2022", "s": "A", "v": 10},
        {"year": "2020", "s": "A", "v": 30},
        {"year": "2021", "s": "A", "v": 20},
    ]
    rows, _ = charts.aggregate_multi_series(
        data, x_column="year", series_column="s",
        y_column="v", aggregation="sum", sort_by="label",
    )
    assert [r["year"] for r in rows] == ["2020", "2021", "2022"]


# ---------------------------------------------------------------------------
# number_format in spec
# ---------------------------------------------------------------------------


def test_build_chart_spec_includes_number_format():
    data = [{"x": "A", "y": 50_000}]
    spec = charts.build_chart_spec(
        data=data, chart_type="bar", x_column="x", y_column="y",
        number_format="compact",
    )
    assert spec["number_format"] == "compact"


def test_build_chart_spec_omits_number_format_when_none():
    data = [{"x": "A", "y": 50}]
    spec = charts.build_chart_spec(
        data=data, chart_type="bar", x_column="x", y_column="y",
    )
    assert "number_format" not in spec


def test_build_multi_series_spec_includes_number_format():
    data = [{"cat": "A", "Q1": 50_000, "Q2": 60_000}]
    spec = charts.build_multi_series_chart_spec(
        data=data, chart_type="stacked_bar", x_column="cat",
        series=["Q1", "Q2"], number_format="compact",
    )
    assert spec["number_format"] == "compact"


# ---------------------------------------------------------------------------
# SQL sort_by
# ---------------------------------------------------------------------------


def test_sql_query_sort_by_label():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.sales",
        x_column="year",
        y_column="revenue",
        aggregation="sum",
        sort_by="label",
    )
    assert "ORDER BY [year] ASC" in q


def test_sql_query_sort_by_value_default():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.sales",
        x_column="region",
        y_column="revenue",
        aggregation="sum",
    )
    assert "ORDER BY SUM([revenue]) DESC" in q


# ---------------------------------------------------------------------------
# is_temporal — edge cases
# ---------------------------------------------------------------------------


def test_is_temporal_mixed_with_nones():
    """None values are skipped; majority of non-None decides."""
    assert charts.is_temporal([2020, None, 2021, None, 2022]) is True


def test_is_temporal_below_threshold():
    """Less than 60% temporal → False."""
    assert charts.is_temporal([2020, "cat_a", "cat_b", "cat_c", "cat_d"]) is False


def test_is_temporal_exactly_at_threshold():
    """Exactly 60% temporal → True."""
    values = [2020, 2021, 2022, "cat_a", "cat_b"]
    assert charts.is_temporal(values) is True


def test_is_temporal_date_formats():
    """Various date formats: DD/MM/YYYY and Q notation."""
    assert charts.is_temporal(["15/01/2024", "20/02/2024"]) is True
    assert charts.is_temporal(["Q1 2024", "Q2 2024", "Q3 2024"]) is True


def test_is_temporal_all_none():
    assert charts.is_temporal([None, None, None]) is False


# ---------------------------------------------------------------------------
# humanize_label — additional cases
# ---------------------------------------------------------------------------


def test_humanize_label_compound_abbreviations():
    assert charts.humanize_label("avg_amt") == "Average Amount"


def test_humanize_label_single_word():
    assert charts.humanize_label("revenue") == "Revenue"


def test_humanize_label_already_readable():
    assert charts.humanize_label("Total Revenue") == "Total Revenue"


# ---------------------------------------------------------------------------
# recommend_chart_type — default bar fallback
# ---------------------------------------------------------------------------


def test_recommend_default_bar():
    """Non-temporal, 7-15 categories with sum → bar."""
    data = [{"cat": f"cat_{i}", "v": i} for i in range(10)]
    assert charts.recommend_chart_type(data, "cat", "v", None, "sum") == "bar"


def test_recommend_pie_only_for_count_or_sum():
    """Few categories with avg aggregation → bar (not pie)."""
    data = [{"s": "A", "v": 1}, {"s": "B", "v": 2}, {"s": "C", "v": 3}]
    assert charts.recommend_chart_type(data, "s", "v", None, "avg") == "bar"


# ---------------------------------------------------------------------------
# aggregate_rows — sort_by actually differentiates
# ---------------------------------------------------------------------------


def test_aggregate_rows_sort_by_value_descending():
    """Verify value sort is descending (not coincidentally matching label order)."""
    data = [
        {"cat": "Alpha", "v": 5},
        {"cat": "Beta", "v": 30},
        {"cat": "Gamma", "v": 15},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="cat", y_column="v", aggregation="sum", sort_by="value"
    )
    assert [r["cat"] for r in result] == ["Beta", "Gamma", "Alpha"]


def test_aggregate_rows_sort_by_label_ascending():
    """Verify label sort is ascending alphabetical."""
    data = [
        {"cat": "Zebra", "v": 30},
        {"cat": "Apple", "v": 5},
        {"cat": "Mango", "v": 15},
    ]
    result, _ = charts.aggregate_rows(
        data, x_column="cat", y_column="v", aggregation="sum", sort_by="label"
    )
    assert [r["cat"] for r in result] == ["Apple", "Mango", "Zebra"]


# ---------------------------------------------------------------------------
# infer_number_format — edge cases
# ---------------------------------------------------------------------------


def test_infer_number_format_negative_large():
    data = [{"v": -50_000}, {"v": 120_000}]
    assert charts.infer_number_format(data, "v") == "compact"


def test_infer_number_format_mixed_types():
    """Non-numeric values are skipped."""
    data = [{"v": "not a number"}, {"v": 50_000}]
    assert charts.infer_number_format(data, "v") == "compact"


def test_infer_number_format_missing_key():
    """Rows without the value key are skipped."""
    data = [{"other": 50_000}]
    assert charts.infer_number_format(data, "v") is None


# ---------------------------------------------------------------------------
# build_sql_aggregation_query — sort_by integration
# ---------------------------------------------------------------------------


def test_sql_query_sort_by_label_with_count():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.events",
        x_column="year",
        y_column=None,
        aggregation="count",
        sort_by="label",
    )
    assert "ORDER BY [year] ASC" in q


def test_sql_query_sort_by_value_with_count():
    q = charts.build_sql_aggregation_query(
        data_id="dbo.events",
        x_column="year",
        y_column=None,
        aggregation="count",
        sort_by="value",
    )
    assert "ORDER BY COUNT(*) DESC" in q


# ---------------------------------------------------------------------------
# number_format propagation in multi-series
# ---------------------------------------------------------------------------


def test_build_multi_series_spec_omits_number_format_when_none():
    data = [{"cat": "A", "Q1": 50, "Q2": 60}]
    spec = charts.build_multi_series_chart_spec(
        data=data, chart_type="stacked_bar", x_column="cat",
        series=["Q1", "Q2"],
    )
    assert "number_format" not in spec


# ---------------------------------------------------------------------------
# aggregate_multi_series — sort_by value
# ---------------------------------------------------------------------------


def test_aggregate_multi_series_sort_by_value():
    data = [
        {"cat": "Alpha", "s": "A", "v": 5},
        {"cat": "Gamma", "s": "A", "v": 30},
        {"cat": "Beta", "s": "A", "v": 15},
    ]
    rows, _ = charts.aggregate_multi_series(
        data, x_column="cat", series_column="s",
        y_column="v", aggregation="sum", sort_by="value",
    )
    assert [r["cat"] for r in rows] == ["Gamma", "Beta", "Alpha"]
