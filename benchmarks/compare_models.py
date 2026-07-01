#!/usr/bin/env python3
"""Cross-model comparison matrix generator for in-cluster LLM benchmarks.

Reads N runner-output result JSON files (the exact schema produced by
``benchmarks/runner.py`` / ``benchmarks/reporter.py``) and emits a single
Markdown comparison matrix: one row per model, columns = high-signal,
directly-comparable metrics. Missing scenarios degrade gracefully to "--".

Pure stdlib only (json, argparse, glob, os, statistics) -- no external deps,
so it runs anywhere Python 3 does (including the stock python:3.12-slim image
used by the benchmark Job).

Usage:
  # explicit files
  python benchmarks/compare_models.py results-a.json results-b.json

  # every *.json in a folder
  python benchmarks/compare_models.py --dir benchmarks/results-incluster

  # files + folder, write to a file (also printed to stdout)
  python benchmarks/compare_models.py a.json --dir some/dir \
      --output benchmarks/results-incluster/COMPARISON-MATRIX.md

Result JSON schema this tool relies on (verified against real runner output,
e.g. benchmarks/results-incluster/results-qwen3.6-27b.json):

  {
    "timestamp": "...",
    "settings": {...},
    "models": [ {"display_name": "...", "model": "...", "parameters": "...",
                 "quantization": "...", "max_context": 131072, ...} ],
    "results": {
      "<category>": {                     # latency | generation |
        "<scenario_name>": {              # context_scaling | tool_overhead | stress
          "<model_display_name>": [       # list of per-run dicts
            {"total_latency_ms": float, "time_to_first_token_ms": float|null,
             "prompt_tokens": int, "completion_tokens": int, "total_tokens": int,
             "tokens_per_second": float, "prompt_eval_rate": float,
             "error": str|null},
            ...
          ]
        }
      }
    }
  }

Each result JSON usually holds ONE model (the in-cluster orchestrator runs one
model per Job), but this tool handles files with several models too: every
model in every file becomes its own matrix row.
"""

import argparse
import glob
import json
import os
import statistics
import sys

# ---------------------------------------------------------------------------
# Schema field names -- kept as constants so the reliance on the runner schema
# is explicit and easy to audit against a sample result JSON.
# ---------------------------------------------------------------------------
F_TTFT = "time_to_first_token_ms"
F_TPS = "tokens_per_second"
F_LATENCY = "total_latency_ms"
F_ERROR = "error"

CAT_LATENCY = "latency"
CAT_GENERATION = "generation"
CAT_CONTEXT = "context_scaling"
CAT_TOOLS = "tool_overhead"
CAT_STRESS = "stress"

# Representative scenarios used for the headline columns. If a given result
# file lacks one of these, the corresponding cell shows "--".
REPRESENTATIVE_LATENCY_SCENARIO = "latency-500"   # 500-token generation, cold-ish
CONTEXT_64K_SCENARIO = "context-64k"              # ~64k-token prompt TTFT
TOOLS_HI_SCENARIO = "tool-call-10-tools"
TOOLS_LO_SCENARIO = "tool-call-3-tools"
STRESS_SCENARIO = "repeated-50"

DASH = "--"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_files(paths, directory):
    """Resolve positional paths + optional --dir glob into a de-duplicated,
    ordered list of existing JSON file paths."""
    resolved = []
    seen = set()

    def add(p):
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isfile(ap):
            seen.add(ap)
            resolved.append(ap)

    for p in paths or []:
        add(p)
    if directory:
        for p in sorted(glob.glob(os.path.join(directory, "*.json"))):
            add(p)
    return resolved


def iter_models(doc):
    """Yield (model_meta_dict, results_dict) for every model in one result doc.

    ``results`` is filtered to just this model's per-scenario run lists so the
    metric helpers never have to re-key by display_name.
    """
    results = doc.get("results", {}) or {}
    for meta in doc.get("models", []) or []:
        name = meta.get("display_name") or meta.get("model") or "unknown"
        # Rebuild a per-model view: {category: {scenario: [run, ...]}}
        model_view = {}
        for category, scenarios in results.items():
            for scenario, per_model in scenarios.items():
                runs = per_model.get(name)
                if runs is not None:
                    model_view.setdefault(category, {})[scenario] = runs
        yield meta, model_view


# ---------------------------------------------------------------------------
# Metric helpers -- all tolerate missing scenarios / all-error runs and return
# None (rendered as "--") rather than raising.
# ---------------------------------------------------------------------------
def _ok_runs(runs):
    """Filter to runs that completed without an error."""
    return [r for r in (runs or []) if not r.get(F_ERROR)]


def _values(runs, field):
    """Non-null numeric values of ``field`` across successful runs."""
    out = []
    for r in _ok_runs(runs):
        v = r.get(field)
        if isinstance(v, (int, float)):
            out.append(v)
    return out


def _all_runs_of_category(model_view, category):
    """Flatten every run across all scenarios in a category."""
    flat = []
    for _scenario, runs in (model_view.get(category, {}) or {}).items():
        flat.extend(runs or [])
    return flat


def median_or_none(values):
    return statistics.median(values) if values else None


def median_ttft_ms(model_view):
    """Median TTFT across ALL latency + generation runs (streaming scenarios).

    context_scaling/latency/generation stream and report TTFT; tool_overhead
    does not (its TTFT is null), so it is excluded here.
    """
    runs = (
        _all_runs_of_category(model_view, CAT_LATENCY)
        + _all_runs_of_category(model_view, CAT_GENERATION)
        + _all_runs_of_category(model_view, CAT_CONTEXT)
    )
    return median_or_none(_values(runs, F_TTFT))


def median_decode_tps(model_view):
    """Median steady-state decode throughput (tok/s) over generation runs.

    Generation scenarios (fixed output sizes, tiny prompt) isolate decode
    speed best. Fall back to latency scenarios if generation is absent.
    """
    gen = _values(_all_runs_of_category(model_view, CAT_GENERATION), F_TPS)
    if gen:
        return median_or_none(gen)
    lat = _values(_all_runs_of_category(model_view, CAT_LATENCY), F_TPS)
    return median_or_none(lat)


def scenario_median(model_view, category, scenario, field):
    runs = (model_view.get(category, {}) or {}).get(scenario)
    return median_or_none(_values(runs, field))


def representative_latency_s(model_view):
    ms = scenario_median(model_view, CAT_LATENCY, REPRESENTATIVE_LATENCY_SCENARIO, F_LATENCY)
    return ms / 1000.0 if ms is not None else None


def context_64k_ttft_ms(model_view):
    return scenario_median(model_view, CAT_CONTEXT, CONTEXT_64K_SCENARIO, F_TTFT)


def tool_overhead_delta_s(model_view):
    """(median 10-tools latency) - (median 3-tools latency), in seconds.

    Positive = tool-schema bloat costs latency. None if either side is missing.
    """
    hi = scenario_median(model_view, CAT_TOOLS, TOOLS_HI_SCENARIO, F_LATENCY)
    lo = scenario_median(model_view, CAT_TOOLS, TOOLS_LO_SCENARIO, F_LATENCY)
    if hi is None or lo is None:
        return None
    return (hi - lo) / 1000.0


def stress_stddev_ms(model_view):
    """Latency stddev over the stress scenario -- consistency under repetition."""
    runs = (model_view.get(CAT_STRESS, {}) or {}).get(STRESS_SCENARIO)
    vals = _values(runs, F_LATENCY)
    if len(vals) < 2:
        return None
    return statistics.pstdev(vals)


def error_count(model_view):
    """Total errored runs across every scenario in every category."""
    total = 0
    for _category, scenarios in model_view.items():
        for _scenario, runs in scenarios.items():
            total += sum(1 for r in (runs or []) if r.get(F_ERROR))
    return total


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def fmt(value, digits=0, suffix=""):
    """Format a metric value, or the dash placeholder if None."""
    if value is None:
        return DASH
    if digits == 0:
        return f"{value:,.0f}{suffix}"
    return f"{value:,.{digits}f}{suffix}"


def model_label(meta):
    name = meta.get("display_name") or meta.get("model") or "unknown"
    return name


def build_matrix_rows(models):
    """models: list of (meta, model_view). Returns list of row dicts."""
    rows = []
    for meta, view in models:
        rows.append({
            "label": model_label(meta),
            "model_id": meta.get("model", ""),
            "params": meta.get("parameters", "") or "",
            "quant": meta.get("quantization", "") or "",
            "ttft": median_ttft_ms(view),
            "tps": median_decode_tps(view),
            "lat500": representative_latency_s(view),
            "ttft64k": context_64k_ttft_ms(view),
            "tool_delta": tool_overhead_delta_s(view),
            "stress_std": stress_stddev_ms(view),
            "errors": error_count(view),
        })
    return rows


def render_matrix(rows):
    header = (
        "| Model | Params | Quant | Median TTFT (ms) | Median decode (tok/s) | "
        "latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | "
        "stress stddev (ms) | Errors |"
    )
    sep = "|" + "|".join(["---"] * 10) + "|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            "| {label} | {params} | {quant} | {ttft} | {tps} | {lat500} | "
            "{ttft64k} | {delta} | {stress} | {errors} |".format(
                label=r["label"],
                params=r["params"] or DASH,
                quant=r["quant"] or DASH,
                ttft=fmt(r["ttft"], 0),
                tps=fmt(r["tps"], 1),
                lat500=fmt(r["lat500"], 1),
                ttft64k=fmt(r["ttft64k"], 0),
                delta=fmt(r["tool_delta"], 2),
                stress=fmt(r["stress_std"], 0),
                errors=r["errors"],
            )
        )
    return "\n".join(lines)


def render_category_breakdown(models):
    """Compact per-category median decode-throughput (tok/s) table.

    One row per category, one column per model. Gives a quick feel for where a
    model is fast/slow without dumping every scenario.
    """
    categories = [CAT_LATENCY, CAT_GENERATION, CAT_CONTEXT, CAT_TOOLS, CAT_STRESS]
    labels = [model_label(meta) for meta, _ in models]

    header = "| Category (median tok/s) | " + " | ".join(labels) + " |"
    sep = "|" + "|".join(["---"] * (len(labels) + 1)) + "|"
    lines = [header, sep]
    for cat in categories:
        cells = []
        for _meta, view in models:
            vals = _values(_all_runs_of_category(view, cat), F_TPS)
            cells.append(fmt(median_or_none(vals), 1))
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_report(models, source_files):
    parts = []
    parts.append("# Model Comparison Matrix")
    parts.append("")
    parts.append(f"Generated from {len(source_files)} result file(s), "
                 f"{len(models)} model(s).")
    parts.append("")
    parts.append("## Headline metrics")
    parts.append("")
    parts.append(render_matrix(build_matrix_rows(models)))
    parts.append("")
    parts.append("**Column notes**")
    parts.append("")
    parts.append("- **Median TTFT (ms)** -- median time-to-first-token over all "
                 "streaming runs (latency + generation + context_scaling). Lower is better.")
    parts.append("- **Median decode (tok/s)** -- median steady-state generation "
                 "throughput over generation scenarios. Higher is better.")
    parts.append(f"- **latency-500 (s)** -- median total latency of the "
                 f"`{REPRESENTATIVE_LATENCY_SCENARIO}` scenario (representative single-call latency).")
    parts.append(f"- **context-64k TTFT (ms)** -- prefill cost at ~64k prompt "
                 f"tokens (`{CONTEXT_64K_SCENARIO}`); measures context scaling.")
    parts.append(f"- **tool 10-3 delta (s)** -- `{TOOLS_HI_SCENARIO}` minus "
                 f"`{TOOLS_LO_SCENARIO}` median latency; cost of extra tool schemas.")
    parts.append(f"- **stress stddev (ms)** -- latency stddev over `{STRESS_SCENARIO}`; "
                 "consistency under repeated calls (lower = steadier).")
    parts.append("- **Errors** -- count of errored runs across all scenarios "
                 "(e.g. context exceeding the model's max).")
    parts.append("")
    parts.append("## Per-category throughput")
    parts.append("")
    parts.append(render_category_breakdown(models))
    parts.append("")
    parts.append("## Source files")
    parts.append("")
    for f in source_files:
        parts.append(f"- `{f}`")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a cross-model comparison matrix (Markdown) from "
                    "runner result JSON files.",
    )
    parser.add_argument("files", nargs="*", help="Result JSON files to compare.")
    parser.add_argument("--dir", dest="directory",
                        help="Directory to glob *.json from (added to any explicit files).")
    parser.add_argument("--output", dest="output",
                        help="Write the Markdown matrix to this file (also printed to stdout).")
    args = parser.parse_args(argv)

    paths = load_files(args.files, args.directory)
    if not paths:
        parser.error("no input JSON files (pass files and/or --dir <folder>)")

    # (meta, model_view) tuples, in file order then model order within a file.
    models = []
    used_files = []
    for path in paths:
        try:
            doc = json.loads(open(path, encoding="utf-8").read())
        except (OSError, ValueError) as exc:
            print(f"warning: skipping {path}: {exc}", file=sys.stderr)
            continue
        # Only treat files that look like runner output (have models + results).
        if not isinstance(doc, dict) or "models" not in doc or "results" not in doc:
            print(f"warning: skipping {path}: not a runner result JSON", file=sys.stderr)
            continue
        added = False
        for meta, view in iter_models(doc):
            models.append((meta, view))
            added = True
        if added:
            used_files.append(path)

    if not models:
        parser.error("no valid runner result JSON files found among inputs")

    report = render_report(models, used_files)
    print(report)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n[compare_models] wrote matrix to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
