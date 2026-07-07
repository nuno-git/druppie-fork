#!/usr/bin/env python3
"""Self-updating model test matrix generator for the in-cluster LLM benchmarks.

Reads the canonical candidate backlog (``benchmarks/candidates.yaml``) and marks
each model Tested or To-test purely by the presence of its per-model result
report (``benchmarks/results-incluster/<slug>/report.txt``). For Tested models it
parses the same headline metrics that ``benchmarks/compare_models.py`` surfaces
in COMPARISON-MATRIX.md -- median TTFT, median decode tok/s, latency-500,
context-64k TTFT, tool 10-3 delta, stress stddev, error count -- straight out of
the rendered report.txt (the per-run JSONs are transient and not kept on disk).

Output: ``benchmarks/results-incluster/MODEL-TEST-MATRIX.md`` -- one LOCAL table
and one API table, deterministic and idempotent. Per-run performance detail still
lives in COMPARISON-MATRIX.md and each per-model report.txt.

Dependencies: Python 3 stdlib + PyYAML (``import yaml``), matching the rest of the
benchmark tooling (benchmarks/runner.py).

Usage:
  python benchmarks/update_test_matrix.py
  python benchmarks/update_test_matrix.py \
      --candidates benchmarks/candidates.yaml \
      --results-dir benchmarks/results-incluster \
      --output benchmarks/results-incluster/MODEL-TEST-MATRIX.md
"""

import argparse
import os
import sys

import yaml

# Shared, stdlib-only report.txt parser (also used by compare_models.py so the
# two matrices can never drift). Importable because the script's own directory
# is on sys.path[0] when run as `python benchmarks/update_test_matrix.py`.
from report_metrics import extract_metrics

# ---------------------------------------------------------------------------
# Paths (defaults resolve relative to this file so the script runs from anywhere)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CANDIDATES = os.path.join(SCRIPT_DIR, "candidates.yaml")
DEFAULT_RESULTS_DIR = os.path.join(SCRIPT_DIR, "results-incluster")
DEFAULT_OUTPUT = os.path.join(DEFAULT_RESULTS_DIR, "MODEL-TEST-MATRIX.md")

REPORT_FILENAME = "report.txt"
SKIPPED_FILENAME = "SKIPPED.txt"   # written by benchmark-all-models.sh on skip/fast-fail
DASH = "--"

STATUS_TESTED = "✅ Tested"    # green check
STATUS_TO_TEST = "⬜ To test"  # white square
STATUS_SKIPPED = "⛔ Skipped"  # could not / will not run (reason in Notes)


def _empty_metrics():
    return {
        "ttft_ms": None,
        "tps": None,
        "lat500_s": None,
        "ttft64k_ms": None,
        "tool_delta_s": None,
        "stress_std_ms": None,
        "errors": None,
    }


# ---------------------------------------------------------------------------
# Candidate loading + status resolution
# ---------------------------------------------------------------------------
def load_candidates(path):
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    models = doc.get("models") or []
    if not isinstance(models, list):
        raise ValueError(f"{path}: top-level 'models' must be a list")
    return models


def _read_skip_reason(results_dir, slug):
    """Return the runtime skip reason for a slug, or None.

    The sweep (benchmark-all-models.sh) writes results-incluster/<slug>/SKIPPED.txt
    with a one-line reason whenever it size-skips a model or a serving attempt
    fast-fails. That runtime reason takes precedence over the static skip_reason
    declared in candidates.yaml.
    """
    if not slug:
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


def resolve_rows(candidates, results_dir):
    """Attach status (tested/skipped/to-test) + parsed metrics to each candidate.

    Status precedence, per candidate (yaml order preserved):
      * tested  -- results-incluster/<slug>/report.txt exists (real metrics).
      * skipped -- no report, but either a runtime SKIPPED.txt exists OR the
                   candidate declares a static skip_reason in candidates.yaml.
      * to-test -- otherwise (on the backlog, nothing recorded yet).
    """
    rows = []
    for entry in candidates:
        slug = (entry.get("slug") or "").strip()
        report_path = os.path.join(results_dir, slug, REPORT_FILENAME)
        tested = bool(slug) and os.path.isfile(report_path)
        if tested:
            with open(report_path, encoding="utf-8") as f:
                metrics = extract_metrics(f.read())
        else:
            metrics = _empty_metrics()

        # A skip reason (runtime file wins; else the static candidates.yaml one).
        skip_reason = None
        if not tested:
            skip_reason = (_read_skip_reason(results_dir, slug)
                           or (entry.get("skip_reason") or "").strip() or None)

        if tested:
            status = "tested"
        elif skip_reason:
            status = "skipped"
        else:
            status = "to_test"

        rows.append({
            "name": entry.get("name", "") or "",
            "source": entry.get("source", "") or "",
            "slug": slug,
            "category": (entry.get("category", "") or "").strip().lower(),
            "params": entry.get("params", "") or "",
            "notes": entry.get("notes", "") or "",
            "status": status,
            "tested": tested,
            "skip_reason": skip_reason,
            "metrics": metrics,
        })
    return rows


# Sort priority per status: tested first, then skipped, then to-test.
_STATUS_ORDER = {"tested": 0, "skipped": 1, "to_test": 2}


def sort_rows(rows):
    """Stable sort: tested, then skipped, then to-test, preserving yaml order."""
    indexed = sorted(
        enumerate(rows),
        key=lambda item: (_STATUS_ORDER.get(item[1]["status"], 3), item[0]),
    )
    return [row for _, row in indexed]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _fmt(value, digits, suffix):
    if value is None:
        return DASH
    if digits == 0:
        return f"{value:,.0f}{suffix}"
    return f"{value:,.{digits}f}{suffix}"


def _cells(m):
    return [
        _fmt(m["ttft_ms"], 0, " ms"),
        _fmt(m["tps"], 1, " t/s"),
        _fmt(m["lat500_s"], 1, " s"),
        _fmt(m["ttft64k_ms"], 0, " ms"),
        _fmt(m["tool_delta_s"], 2, " s"),
        _fmt(m["stress_std_ms"], 0, " ms"),
        DASH if m["errors"] is None else str(m["errors"]),
    ]


HEADER = (
    "| Model | Source | Params | Status | TTFT (med) | Decode tok/s | Lat-500 | "
    "Ctx-64k TTFT | Tool Δ | Stress σ | Errors | Notes |"
)
SEP = "|" + "|".join(["---"] * 12) + "|"


_STATUS_LABEL = {
    "tested": STATUS_TESTED,
    "skipped": STATUS_SKIPPED,
    "to_test": STATUS_TO_TEST,
}


def _notes_cell(r):
    """Notes column: for skipped rows, lead with the skip reason, then the
    static candidate note (de-duplicated)."""
    reason = r.get("skip_reason")
    base = r["notes"] or ""
    if r["status"] == "skipped" and reason:
        if base and base not in reason and reason not in base:
            return f"Skipped -- {reason} ({base})"
        return f"Skipped -- {reason}"
    return base


def render_table(rows):
    lines = [HEADER, SEP]
    for r in rows:
        status = _STATUS_LABEL.get(r["status"], STATUS_TO_TEST)
        cells = _cells(r["metrics"])
        lines.append(
            "| " + " | ".join([
                r["name"] or DASH,
                f"`{r['source']}`" if r["source"] else DASH,
                r["params"] or DASH,
                status,
                *cells,
                _notes_cell(r),
            ]) + " |"
        )
    return "\n".join(lines)


def render_matrix(rows):
    local = sort_rows([r for r in rows if r["category"] == "local"])
    api = sort_rows([r for r in rows if r["category"] == "api"])
    tested = sum(1 for r in rows if r["status"] == "tested")
    skipped = sum(1 for r in rows if r["status"] == "skipped")
    total = len(rows)

    parts = []
    parts.append("# Model Test Matrix")
    parts.append("")
    parts.append(
        "Self-updating backlog of LLM benchmark candidates. Regenerated every "
        "sweep by `benchmarks/update_test_matrix.py` from `benchmarks/candidates.yaml`; "
        "a model is **Tested** once `results-incluster/<slug>/report.txt` exists, or "
        "**Skipped** when the sweep records a reason (a runtime "
        "`results-incluster/<slug>/SKIPPED.txt`, or a static `skip_reason` in "
        "`candidates.yaml` for models too large / needing 2 GPUs)."
    )
    parts.append("")
    parts.append("**Legend** -- "
                 f"{STATUS_TESTED}: benchmarked, metrics parsed from its `report.txt`. "
                 f"{STATUS_SKIPPED}: not benchmarked, reason in Notes (too large / needs "
                 f"a maintenance window / serving fast-failed). "
                 f"{STATUS_TO_TEST}: on the backlog, not yet attempted (`--` metrics).")
    parts.append("")
    parts.append(f"**Progress:** {tested} tested / {skipped} skipped / {total} total "
                 f"({len(local)} local, {len(api)} API).")
    parts.append("")
    parts.append(
        "Columns: TTFT (med) = median time-to-first-token over streaming scenarios; "
        "Decode tok/s = median generation throughput; Lat-500 = `latency-500` total "
        "latency; Ctx-64k TTFT = `context-64k` prefill; Tool Δ = "
        "`tool-call-10-tools` minus `tool-call-3-tools` latency; Stress σ = "
        "`repeated-50` latency stddev; Errors = errored runs. Per-run detail lives in "
        "`COMPARISON-MATRIX.md` and each per-model `report.txt`."
    )
    parts.append("")
    parts.append("## Local models (downloadable weights, benchmarked in-cluster)")
    parts.append("")
    parts.append(render_table(local))
    parts.append("")
    parts.append("## API models (OpenRouter-hosted, API-only)")
    parts.append("")
    parts.append(render_table(api))
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate the model test matrix (Markdown) from candidates.yaml "
                    "and the presence of per-model result reports.",
    )
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES,
                        help=f"Candidate list YAML (default: {DEFAULT_CANDIDATES}).")
    parser.add_argument("--results-dir", dest="results_dir", default=DEFAULT_RESULTS_DIR,
                        help=f"Results root holding <slug>/report.txt (default: {DEFAULT_RESULTS_DIR}).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Markdown output path (default: {DEFAULT_OUTPUT}).")
    args = parser.parse_args(argv)

    candidates = load_candidates(args.candidates)
    rows = resolve_rows(candidates, args.results_dir)
    matrix = render_matrix(rows)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(matrix + "\n")

    tested = sum(1 for r in rows if r["tested"])
    print(f"[update_test_matrix] wrote {args.output} ({tested}/{len(rows)} tested)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
