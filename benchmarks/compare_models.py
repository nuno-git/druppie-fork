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

# One entry per registered `models.inference.llmkube.dev` object. Order here is
# the row order in the matrix. `note` is used when the model has NOT been
# benchmarked; `note_done` (optional) when a matching result JSON is present.
KNOWN_MODELS = [
    {
        "crd": "gemma-4-e4b",
        "source": "unsloth/gemma-4-E4B-it-GGUF",
        "label": "Gemma 4 E4B (gemma-4-E4B-it)",
        "params": "~4B (E4B eff.)",
        "quant": "GGUF ~4-8GB",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU easily (~4-8GB GGUF), not yet run.",
    },
    {
        "crd": "qwen3-6-27b",
        "source": "Qwen/Qwen3.6-27B",
        "label": "Qwen3.6-27B",
        "params": "27B",
        "quant": "bf16 ~54GB",
        "fit": "served",
        "note": "Pending -- currently served in prod.",
        "note_done": "Benchmarked in place -- prod, no serving change "
                     "(see qwen3.6-27b/report.txt).",
    },
    {
        "crd": "qwen3-6-27b-mtp",
        "source": "unsloth/Qwen3.6-27B-MTP-GGUF",
        "label": "Qwen3.6-27B-MTP (GGUF)",
        "params": "27B (+MTP head)",
        "quant": "GGUF ~16-30GB",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU (~16-30GB GGUF quant), not yet run.",
    },
    {
        "crd": "qwen3-6-35b-a3b",
        "source": "Qwen/Qwen3.6-35B-A3B",
        "label": "Qwen3.6-35B-A3B (MoE)",
        "params": "35B (3B act.)",
        "quant": "bf16 ~70GB",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU (~70GB bf16, tight). Prior run failed on "
                "HF download timeout, NOT VRAM.",
    },
    {
        "crd": "qwen3-coder-next-80b",
        "source": "Qwen/Qwen3-Coder-Next-80B",
        "label": "Qwen3-Coder-Next-80B",
        "params": "80B",
        "quant": "bf16 ~160GB",
        "fit": "needs-2gpu",
        "note": "Needs 2 GPUs (TP=2, ~160GB bf16) -- testable only in a full "
                "maintenance window (or with quantization).",
    },
    {
        "crd": "gpt-oss-120b",
        "source": "openai/gpt-oss-120b",
        "label": "gpt-oss-120b",
        "params": "120B (MoE)",
        "quant": "MXFP4 ~63GB (native)",
        "fit": "fits-1gpu",
        "note": "Pending -- fits 1 GPU (~63GB, ships native MXFP4), not yet run.",
    },
    {
        "crd": "qwen3-coder-480b-a35b",
        "source": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "label": "Qwen3-Coder-480B-A35B (MoE)",
        "params": "480B (35B act.)",
        "quant": "~270GB @Q4 / ~960GB bf16",
        "fit": "too-large",
        "note": "Not benchmarked -- exceeds VRAM (~270GB @Q4 / ~960GB bf16 > "
                "192GB total; needs multi-node).",
    },
    {
        "crd": "deepseek-v3-1",
        "source": "unsloth/DeepSeek-V3.1-GGUF",
        "label": "DeepSeek-V3.1 (GGUF, MoE)",
        "params": "671B (37B act.)",
        "quant": "~380GB @Q4 GGUF",
        "fit": "too-large",
        "note": "Not benchmarked -- exceeds VRAM (671B MoE, ~380GB @Q4 GGUF > "
                "192GB total; needs multi-node).",
    },
    {
        "crd": "glm-5-1",
        "source": "unsloth/GLM-5.1-GGUF",
        "label": "GLM-5.1 (GGUF, MoE)",
        "params": "744B (40B act.)",
        "quant": "~220-236GB @2-bit",
        "fit": "too-large",
        "note": "Not benchmarked -- exceeds VRAM (744B MoE, ~220-236GB even "
                "@2-bit dynamic GGUF > 192GB total; needs RAM/MoE offload or "
                "multi-node).",
    },
    {
        "crd": "glm-4-6v",
        "source": "unsloth/GLM-4.6V-GGUF",
        "label": "GLM-4.6V (GGUF, vision)",
        "params": "106B",
        "quant": "GGUF ~60GB @Q4",
        "fit": "fits-1gpu",
        "note": "Pending (uncertain) -- ~60GB @Q4 GGUF fits 1 GPU, but "
                "vision/multimodal serving on vLLM needs verification; bf16 "
                "(~212GB) would not fit.",
    },
]


def _slug(value):
    """Normalize an HF/registry model id to its last path segment, lowercased.

    "Qwen/Qwen3.6-27B" -> "qwen3.6-27b"; used to match known-model registry
    entries to actual runner result JSONs (whose meta["model"] is the source).
    """
    return (value or "").rsplit("/", 1)[-1].strip().lower()


def merge_known_with_actual(actual_models):
    """Merge the KNOWN_MODELS registry with actual (meta, view) results.

    Returns (row_specs, benchmarked):
      * row_specs -- ordered list of dicts for the headline matrix: every known
        model in registry order, plus any actual model NOT in the registry
        appended at the end (so real data is never dropped). Each spec has
        keys: label, params, quant, fit, note, and optionally view (present
        only when the model was actually benchmarked).
      * benchmarked -- list of (meta, view) that carried real results, for the
        per-category throughput table.
    """
    actual_by_slug = {}
    for meta, view in actual_models:
        actual_by_slug.setdefault(_slug(meta.get("model")), (meta, view))

    row_specs = []
    benchmarked = []
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
    return row_specs, benchmarked


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


def render_report(row_specs, benchmarked, source_files):
    parts = []
    parts.append("# Model Comparison Matrix")
    parts.append("")
    parts.append(f"{len(row_specs)} registered model(s) tracked; "
                 f"{len(benchmarked)} benchmarked from {len(source_files)} "
                 f"result file(s). Models that are not (yet) benchmarked still "
                 f"appear, with a `Status / Note` explaining why (fits/pending, "
                 f"needs a maintenance window, or too large for this hardware).")
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
    parts.append("## Per-category throughput")
    parts.append("")
    if benchmarked:
        parts.append("_Benchmarked models only._")
        parts.append("")
        parts.append(render_category_breakdown(benchmarked))
    else:
        parts.append("_No benchmarked models yet -- run the sweep to populate._")
    parts.append("")
    parts.append("## Source files")
    parts.append("")
    if source_files:
        for f in source_files:
            parts.append(f"- `{f}`")
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
    args = parser.parse_args(argv)

    # No input JSON is OK: the matrix still lists every registered model from
    # the known-models registry (all rows show "--" metrics + a pending/untestable
    # note). This lets us regenerate a static preview without cluster access.
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
    # model appears -- benchmarked ones with metrics, the rest with a note.
    row_specs, benchmarked = merge_known_with_actual(models)

    report = render_report(row_specs, benchmarked, used_files)
    print(report)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n[compare_models] wrote matrix to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
