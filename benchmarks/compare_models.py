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

# Shared, stdlib-only report.txt parser (also used by update_test_matrix.py so
# the two matrices can never drift). The committed per-model report.txt is the
# REPRODUCIBLE source of truth: the per-run result JSONs are transient (they live
# only in the sweep's temp WORKDIR and are discarded), so re-running this
# generator from the repo has no JSON to read -- it falls back to report.txt.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_metrics import extract_metrics  # noqa: E402

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
# Known-model registry -- so the matrix ALWAYS lists every registered model,
# not just the ones we happened to benchmark. Models that cannot be benchmarked
# on this hardware (too large) or only in a maintenance window (TP=2) get an
# explicit placeholder row with a status note instead of silently vanishing.
#
# Merge rule (see merge_known_with_actual): a known model is matched to an
# actual result JSON by the normalized last path segment of its HF `source`
# (e.g. "Qwen/Qwen3.6-27B" -> "qwen3.6-27b"); matched rows render real metrics,
# unmatched ones render "--" + the pending/untestable note.
#
# HARDWARE CONTEXT (drives the `fit` classes below): ONE GPU node with 2x
# NVIDIA RTX PRO 6000 Blackwell (96GB each = 192GB total). NO P2P between the
# cards, so serving is tensor-parallel=1 (one model per GPU). The `llm` namespace
# GPU ResourceQuota is hard=2 and both GPUs are normally held by the live `qwen`
# service; a benchmark run frees at most ONE GPU (scaling qwen 2->1). Using both
# GPUs (TP=2) would take prod fully down. All sizes are ESTIMATES (~).

# Fit classes, and the one-liner shown in the legend.
FIT_LEGEND = [
    ("served",
     "Currently served in prod; benchmarked in place (no serving change)."),
    ("fits-1gpu",
     "Fits one RTX PRO 6000 (<=~90GB usable). Benchmarkable now by freeing "
     "1 GPU (qwen 2->1)."),
    ("needs-2gpu",
     "Needs both GPUs (tensor-parallel 2, ~160GB). Testable only in a full "
     "maintenance window -- it takes prod fully down."),
    ("too-large",
     "Exceeds 192GB total even quantized. Not testable on this hardware "
     "(needs multi-node / RAM-MoE offload)."),
]

HARDWARE_NOTE = (
    "Hardware: 1 GPU node, 2x NVIDIA RTX PRO 6000 Blackwell (96GB each = 192GB "
    "total). No P2P between cards, so serving is tensor-parallel=1 (one model "
    "per GPU). The `llm` namespace GPU ResourceQuota is hard=2, and both GPUs "
    "are normally held by the live `qwen` service. A benchmark run frees at most "
    "ONE GPU (qwen 2->1); using both (TP=2) takes prod fully down. All sizes are "
    "ESTIMATES (~)."
)

METHODOLOGY_NOTE = (
    "All benchmarked models were served in-cluster (ka-k8s-ai) from a LOCAL-DISK "
    "model cache (`pvc://` volume, no per-run HF download) via the vLLM runtime "
    "(`runtime: vllm`) with a per-model command/args override (see the `profile` "
    "blocks in `benchmarks/candidates.yaml`), tensor-parallel=1, on 2026-07-07. "
    "On the SM120 (RTX PRO 6000 Blackwell) cards, native NVFP4/MXFP4 MoE kernels "
    "fall back to Marlin (slower) for the MoE models "
    "(Qwen3.6-35B-A3B-NVFP4, Qwen3-Coder-Next-80B-NVFP4, gpt-oss-120b). "
    "gpt-oss-120b was served at max-model-len 8192, so its 16k+ context scenarios "
    "are out-of-range BY CONFIG (not a model limit) and are counted as errors. "
    "Headline metrics here are parsed from each model's committed "
    "`results-incluster/<slug>/report.txt` (the per-run JSONs are transient), so "
    "re-running `compare_models.py` reproduces this matrix deterministically."
)

# One entry per registered `models.inference.llmkube.dev` object. Order here is
# the row order in the matrix. `note` is used when the model has NOT been
# benchmarked; `note_done` (optional) when a matching result JSON is present.
#
# `report_dir` (optional): the results-incluster/<report_dir>/report.txt whose
# committed metrics are parsed for this row when no live result JSON is present.
# This is what makes the matrix REPRODUCIBLE -- re-running the generator from the
# repo (no transient JSONs) still renders the real numbers from report.txt.
KNOWN_MODELS = [
    {
        "crd": "gemma-4-e4b",
        "source": "unsloth/gemma-4-E4B-it-GGUF",
        "label": "Gemma 4 E4B (gemma-4-E4B-it)",
        "params": "~4B (E4B eff.)",
        "quant": "GGUF ~4-8GB",
        "fit": "fits-1gpu",
        "note": "Pending -- gated (HF token not in vault).",
    },
    {
        "crd": "qwen3-6-27b",
        "source": "nvidia/Qwen3.6-27B-NVFP4",
        "report_dir": "qwen3.6-27b-nvfp4",
        "label": "Qwen3.6-27B-NVFP4",
        "params": "27B (dense)",
        "quant": "NVFP4 ~22GB",
        "fit": "served",
        "note": "Pending -- currently served in prod.",
        "note_done": "Served in prod (isvc qwen-27b); benchmarked IN PLACE from "
                     "local-disk cache, TP=1, 256K ctx OK.",
    },
    {
        "crd": "qwen3-6-27b-mtp",
        "source": "unsloth/Qwen3.6-27B-MTP-GGUF",
        "label": "Qwen3.6-27B-MTP (GGUF)",
        "params": "27B (+MTP head)",
        "quant": "GGUF ~16-30GB",
        "fit": "fits-1gpu",
        "note": "Not benchmarked -- GGUF, not staged.",
    },
    {
        "crd": "qwen3-6-35b-a3b",
        "source": "nvidia/Qwen3.6-35B-A3B-NVFP4",
        "report_dir": "qwen3.6-35b-a3b-nvfp4",
        "label": "Qwen3.6-35B-A3B-NVFP4 (MoE)",
        "params": "35B MoE (3B act.)",
        "quant": "NVFP4 ~22GB",
        "fit": "served",
        "note": "Pending -- fits 1 GPU (NVFP4).",
        "note_done": "Served in prod (isvc qwen-35b); benchmarked IN PLACE from "
                     "local-disk cache, TP=1, 256K ctx OK. SM120 Marlin MoE "
                     "fallback.",
    },
    {
        "crd": "qwen3-coder-next-80b",
        "source": "Cirrascale/Qwen3-Coder-Next-NVFP4",
        "report_dir": "qwen3-coder-next-nvfp4",
        "label": "Qwen3-Coder-Next-80B-NVFP4 (MoE)",
        "params": "80B MoE",
        "quant": "NVFP4 ~47GB",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU at NVFP4.",
        "note_done": "Benchmarked from local-disk cache via runtime:vllm + "
                     "command override, TP=1, 256K ctx OK (TTFT 30.8s@256k). "
                     "SM120 Marlin MoE fallback.",
    },
    {
        "crd": "gpt-oss-120b",
        "source": "openai/gpt-oss-120b",
        "report_dir": "gpt-oss-120b",
        "label": "gpt-oss-120b (MoE)",
        "params": "120B MoE",
        "quant": "MXFP4 ~63GB",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU (~63GB, ships native MXFP4), not yet run.",
        "note_done": "Benchmarked from local-disk cache via runtime:vllm + "
                     "command override, TP=1. Served at max-model-len 8192, so "
                     "the 16k+ context scenarios are out-of-range BY CONFIG (not "
                     "a model limit) and are the errored runs; 0 errors on the 15 "
                     "in-range scenarios. SM120 Marlin MoE fallback.",
    },
    {
        "crd": "qwen3-coder-480b-a35b",
        "source": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "label": "Qwen3-Coder-480B-A35B (MoE)",
        "params": "480B (35B act.)",
        "quant": "~270GB @Q4 / ~960GB bf16",
        "fit": "too-large",
        "note": "Too large -- >192GB total.",
    },
    {
        "crd": "deepseek-v3-1",
        "source": "unsloth/DeepSeek-V3.1-GGUF",
        "label": "DeepSeek-V3.1 (GGUF, MoE)",
        "params": "671B (37B act.)",
        "quant": "~380GB @Q4 GGUF",
        "fit": "too-large",
        "note": "Too large -- >192GB total.",
    },
    {
        "crd": "glm-5-1",
        "source": "unsloth/GLM-5.1-GGUF",
        "label": "GLM-5.1 (GGUF, MoE)",
        "params": "744B (40B act.)",
        "quant": "~220-236GB @2-bit",
        "fit": "too-large",
        "note": "Too large -- >192GB total.",
    },
    {
        "crd": "glm-4-6v",
        "source": "unsloth/GLM-4.6V-GGUF",
        "label": "GLM-4.6V (GGUF, vision)",
        "params": "106B",
        "quant": "GGUF ~60GB @Q4",
        "fit": "fits-1gpu",
        "note": "Not benchmarked -- vision GGUF, not staged.",
    },
]


def _slug(value):
    """Normalize an HF/registry model id to its last path segment, lowercased.

    "Qwen/Qwen3.6-27B" -> "qwen3.6-27b"; used to match known-model registry
    entries to actual runner result JSONs (whose meta["model"] is the source).
    """
    return (value or "").rsplit("/", 1)[-1].strip().lower()


SKIPPED_FILENAME = "SKIPPED.txt"   # written per-slug by benchmark-all-models.sh


def _runtime_skip_reason(results_dir, slug):
    """Return the runtime skip reason recorded for a slug, or None.

    The sweep writes ``<results_dir>/<slug>/SKIPPED.txt`` with a one-line reason
    whenever it size-skips a model upfront or a serving attempt fast-fails. That
    live reason takes precedence over the static registry ``note``.
    """
    if not results_dir or not slug:
        return None
    path = os.path.join(results_dir, slug, SKIPPED_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            reason = f.read().strip()
    except OSError:
        return None
    return reason or None


REPORT_FILENAME = "report.txt"    # committed per-model report under <results_dir>/<report_dir>/


def _report_metrics(results_dir, report_dir):
    """Parse committed <results_dir>/<report_dir>/report.txt -> row-ready metrics.

    Returns a dict keyed for build_matrix_rows (ttft/tps/lat500/ttft64k/
    tool_delta/stress_std/errors), or None if the report is absent/unreadable.
    This is the reproducible metric source when no live per-run JSON is present.
    """
    if not results_dir or not report_dir:
        return None
    path = os.path.join(results_dir, report_dir, REPORT_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            m = extract_metrics(f.read())
    except OSError:
        return None
    return {
        "ttft": m["ttft_ms"],
        "tps": m["tps"],
        "lat500": m["lat500_s"],
        "ttft64k": m["ttft64k_ms"],
        "tool_delta": m["tool_delta_s"],
        "stress_std": m["stress_std_ms"],
        "errors": m["errors"],
    }


def merge_known_with_actual(actual_models, results_dir=None):
    """Merge the KNOWN_MODELS registry with actual (meta, view) results.

    Returns (row_specs, benchmarked, report_sources):
      * row_specs -- ordered list of dicts for the headline matrix: every known
        model in registry order, plus any actual model NOT in the registry
        appended at the end (so real data is never dropped). Each spec has
        keys: label, params, quant, fit, note, and EITHER `view` (live per-run
        JSON, richest -- also feeds the per-category table) OR `metrics`
        (precomputed from the committed report.txt, the reproducible fallback).
      * benchmarked -- list of (meta, view) that carried a live JSON view, for
        the per-category throughput table.
      * report_sources -- report.txt paths whose metrics were parsed.

    Precedence: a live JSON view wins over report.txt (it is richer). Without any
    JSON, each registry entry with a `report_dir` renders its committed report.txt
    metrics -- so re-running from the repo reproduces the real matrix, not a blank.

    ``results_dir`` (optional) is scanned for per-slug ``SKIPPED.txt`` files: a
    live skip reason there overrides the static registry note for any model that
    did not produce results, so the matrix shows exactly why it was skipped.
    """
    actual_by_slug = {}
    for meta, view in actual_models:
        actual_by_slug.setdefault(_slug(meta.get("model")), (meta, view))

    row_specs = []
    benchmarked = []
    report_sources = []
    matched = set()
    for km in KNOWN_MODELS:
        slug = _slug(km["source"])
        hit = actual_by_slug.get(slug)
        spec = {
            "label": km["label"],
            "params": km["params"],
            "quant": km["quant"],
            "fit": km["fit"],
            "note": km["note"],
        }
        if hit:
            meta, view = hit
            spec["view"] = view
            spec["params"] = meta.get("parameters") or km["params"]
            spec["quant"] = meta.get("quantization") or km["quant"]
            spec["note"] = km.get("note_done", "Benchmarked.")
            benchmarked.append((meta, view))
            matched.add(slug)
        else:
            # No live JSON -- fall back to the committed report.txt (reproducible).
            metrics = _report_metrics(results_dir, km.get("report_dir"))
            if metrics is not None:
                spec["metrics"] = metrics
                spec["note"] = km.get("note_done", "Benchmarked.")
                report_sources.append(
                    os.path.join(results_dir, km["report_dir"], REPORT_FILENAME))
            else:
                # Not benchmarked -- prefer a live skip reason over the static note.
                reason = _runtime_skip_reason(results_dir, slug)
                if reason:
                    spec["note"] = f"Skipped -- {reason}"
        row_specs.append(spec)

    # Append any benchmarked model not covered by the registry -- never lose data.
    for slug, (meta, view) in actual_by_slug.items():
        if slug in matched:
            continue
        row_specs.append({
            "label": model_label(meta),
            "params": meta.get("parameters") or "",
            "quant": meta.get("quantization") or "",
            "fit": "served",
            "note": "Benchmarked (not in known-models registry).",
            "view": view,
        })
        benchmarked.append((meta, view))
    return row_specs, benchmarked, report_sources


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


def build_matrix_rows(row_specs):
    """row_specs: output of merge_known_with_actual. Returns list of row dicts.

    Specs WITH a `view` (benchmarked) render real metrics; specs WITHOUT one
    (pending / untestable) render every metric as "--" and rely on the
    Status/Note column to explain why.
    """
    rows = []
    for spec in row_specs:
        view = spec.get("view")
        metrics = spec.get("metrics")
        if view is not None:
            rows.append({
                "label": spec["label"],
                "params": spec["params"] or "",
                "quant": spec["quant"] or "",
                "ttft": median_ttft_ms(view),
                "tps": median_decode_tps(view),
                "lat500": representative_latency_s(view),
                "ttft64k": context_64k_ttft_ms(view),
                "tool_delta": tool_overhead_delta_s(view),
                "stress_std": stress_stddev_ms(view),
                "errors": error_count(view),
                "note": spec["note"],
            })
        elif metrics is not None:
            # Reproducible metrics parsed from the committed report.txt.
            rows.append({
                "label": spec["label"],
                "params": spec["params"] or "",
                "quant": spec["quant"] or "",
                "ttft": metrics["ttft"],
                "tps": metrics["tps"],
                "lat500": metrics["lat500"],
                "ttft64k": metrics["ttft64k"],
                "tool_delta": metrics["tool_delta"],
                "stress_std": metrics["stress_std"],
                "errors": metrics["errors"],
                "note": spec["note"],
            })
        else:
            rows.append({
                "label": spec["label"],
                "params": spec["params"] or "",
                "quant": spec["quant"] or "",
                "ttft": None, "tps": None, "lat500": None,
                "ttft64k": None, "tool_delta": None, "stress_std": None,
                "errors": DASH,          # no runs -> dash, not a real 0
                "note": spec["note"],
            })
    return rows


def render_matrix(rows):
    header = (
        "| Model | Params | Quant / size | Median TTFT (ms) | Median decode (tok/s) | "
        "latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | "
        "stress stddev (ms) | Errors | Status / Note |"
    )
    sep = "|" + "|".join(["---"] * 11) + "|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            "| {label} | {params} | {quant} | {ttft} | {tps} | {lat500} | "
            "{ttft64k} | {delta} | {stress} | {errors} | {note} |".format(
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
                note=r["note"],
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


def render_report(row_specs, benchmarked, source_files, report_sources=None):
    report_sources = report_sources or []
    benchmarked_count = sum(
        1 for s in row_specs
        if s.get("view") is not None or s.get("metrics") is not None)
    parts = []
    parts.append("# Model Comparison Matrix")
    parts.append("")
    parts.append(f"{len(row_specs)} registered model(s) tracked; "
                 f"{benchmarked_count} benchmarked "
                 f"(from {len(report_sources)} committed report.txt + "
                 f"{len(source_files)} live result JSON(s)). Models that are not "
                 f"(yet) benchmarked still appear, with a `Status / Note` "
                 f"explaining why (fits/pending, needs a maintenance window, or "
                 f"too large for this hardware).")
    parts.append("")
    parts.append("## Headline metrics")
    parts.append("")
    parts.append(render_matrix(build_matrix_rows(row_specs)))
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
                 "(e.g. context exceeding the model's max). `--` = not benchmarked.")
    parts.append("- **Status / Note** -- for un-benchmarked rows, why there are "
                 "no metrics (see fit classes below). Sizes are ESTIMATES (~).")
    parts.append("")
    parts.append("## Fit classes & hardware constraint")
    parts.append("")
    parts.append(HARDWARE_NOTE)
    parts.append("")
    for name, desc in FIT_LEGEND:
        parts.append(f"- **`{name}`** -- {desc}")
    parts.append("")
    parts.append("## Methodology")
    parts.append("")
    parts.append(METHODOLOGY_NOTE)
    parts.append("")
    parts.append("## Per-category throughput")
    parts.append("")
    if benchmarked:
        parts.append("_Benchmarked models only._")
        parts.append("")
        parts.append(render_category_breakdown(benchmarked))
    elif benchmarked_count:
        parts.append("_Per-category tok/s breakdown needs the transient per-run "
                     "result JSON (kept only in the sweep's WORKDIR, not "
                     "committed). The reproducible headline metrics above are "
                     "parsed from each model's committed `report.txt`; see "
                     "`MODEL-TEST-MATRIX.md` and the per-model `report.txt` for "
                     "the full per-scenario detail._")
    else:
        parts.append("_No benchmarked models yet -- run the sweep to populate._")
    parts.append("")
    parts.append("## Source files")
    parts.append("")
    if source_files or report_sources:
        for f in source_files:
            parts.append(f"- `{f}` (live result JSON)")
        for f in report_sources:
            parts.append(f"- `{f}` (committed report.txt)")
    else:
        parts.append("_None -- matrix rendered from the known-models registry only._")
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
    parser.add_argument("--results-dir", dest="results_dir",
                        help="Results root holding <report_dir>/report.txt (parsed "
                             "for reproducible metrics when no live JSON is given) "
                             "and per-slug SKIPPED.txt reasons. Defaults to the "
                             "results-incluster dir beside this script.")
    args = parser.parse_args(argv)

    # results_dir defaults to the conventional results-incluster dir beside this
    # script, so `python benchmarks/compare_models.py` (no args) reproduces the
    # real matrix from the committed report.txt files -- not a blank preview.
    results_dir = args.results_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results-incluster")

    # No input JSON is OK: benchmarked rows come from the committed report.txt
    # under results_dir; un-benchmarked ones show "--" + a pending/untestable note.
    paths = load_files(args.files, args.directory)

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

    # Merge actual results with the known-models registry so every registered
    # model appears -- benchmarked ones with metrics, the rest with a note (a
    # live SKIPPED.txt reason under --results-dir overrides the static note).
    row_specs, benchmarked, report_sources = merge_known_with_actual(
        models, results_dir)

    report = render_report(row_specs, benchmarked, used_files, report_sources)
    print(report)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n[compare_models] wrote matrix to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
