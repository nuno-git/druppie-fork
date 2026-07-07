#!/usr/bin/env python3
"""Shared, stdlib-only parser for the rendered benchmark ``report.txt`` files.

Both ``benchmarks/compare_models.py`` (COMPARISON-MATRIX.md) and
``benchmarks/update_test_matrix.py`` (MODEL-TEST-MATRIX.md) need the SAME
headline metrics out of each per-model ``results-incluster/<slug>/report.txt``.
The per-run result JSONs are transient (they live only in the sweep's temp
WORKDIR and are discarded), so the committed ``report.txt`` is the reproducible
source of truth. Keeping the parser here -- imported by both generators -- means
the two matrices can never drift out of agreement.

Pure Python 3 stdlib (``re`` + ``statistics``) only, so it runs anywhere the
benchmark tooling does (including the stock ``python:3.12-slim`` Job image, which
has no PyYAML -- hence this lives apart from ``update_test_matrix`` which imports
yaml).

The headline metrics mirror the COMPARISON-MATRIX columns exactly:
  ttft_ms       -- median time-to-first-token over streaming scenarios
                   (context-*/generate-*/latency-*), matching
                   compare_models.median_ttft_ms (tools/stress excluded).
  tps           -- median decode throughput over the generation scenarios.
  lat500_s      -- latency-500 total latency, in seconds.
  ttft64k_ms    -- context-64k prefill TTFT, in ms (None if out-of-range/errored).
  tool_delta_s  -- tool-call-10-tools minus tool-call-3-tools latency, in seconds.
  stress_std_ms -- repeated-50 latency stddev, in ms.
  errors        -- total errored runs (summed from the "(N errors)" annotations).
"""

import re
import statistics

# report.txt scenario names used for the headline columns.
LATENCY_500_SCENARIO = "latency-500"
CONTEXT_64K_SCENARIO = "context-64k"
TOOLS_HI_SCENARIO = "tool-call-10-tools"
TOOLS_LO_SCENARIO = "tool-call-3-tools"
STRESS_SCENARIO = "repeated-50"

# TTFT median is taken over the streaming scenarios (latency/generation/context),
# mirroring compare_models.median_ttft_ms (which excludes non-streaming tools/stress).
TTFT_STREAMING_PREFIXES = ("context-", "generate-", "latency-")


# ---------------------------------------------------------------------------
# report.txt parsing
# ---------------------------------------------------------------------------
# Section titles (substring match on the stripped "===" banner title line) ->
# internal section key. LATENCY must be matched by startswith so it does not
# swallow "CONTEXT SCALING (latency)" / "TOOL CALLING OVERHEAD (latency)".
def _detect_section(stripped):
    if "CONTEXT SCALING" in stripped:
        return "context"
    if "GENERATION SPEED" in stripped:
        return "generation"
    if stripped.startswith("LATENCY"):
        return "latency"
    if "STRESS" in stripped:
        return "stress"
    if "TOOL CALLING OVERHEAD" in stripped:
        return "tools"
    if "TIME TO FIRST TOKEN" in stripped:
        return "ttft"
    return None


def parse_report(text):
    """Parse a rendered report.txt into {section: {scenario: raw_value_string}}.

    Only the "Scenario | value" tables under each section banner are read; the
    leading per-scenario summary block is ignored (errors are counted separately).
    """
    sections = {}
    current = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        section = _detect_section(stripped)
        if section is not None:
            current = section
            continue
        if current is None or "|" not in raw_line:
            continue
        left, _, right = raw_line.partition("|")
        scenario = left.strip()
        value = right.strip()
        # Skip the table header row and the dashed separator row.
        if not scenario or scenario == "Scenario" or set(scenario) <= {"-"}:
            continue
        sections.setdefault(current, {})[scenario] = value
    return sections


# --- value parsers ---------------------------------------------------------
def _duration_to_ms(value):
    """"560ms" / "1.2s" / "189.4s (±11.7)" -> milliseconds. "-"/"ERROR" -> None."""
    if not value:
        return None
    token = value.split()[0]
    m = re.match(r"^([0-9.]+)(ms|s)$", token)
    if not m:
        return None
    num = float(m.group(1))
    return num if m.group(2) == "ms" else num * 1000.0


def _stddev_to_ms(value):
    """"6.3s (±2.8)" -> stddev in ms (unit taken from the leading value)."""
    if not value:
        return None
    unit_m = re.match(r"^[0-9.]+(ms|s)", value)
    paren_m = re.search(r"±\s*([0-9.]+)", value)
    if not unit_m or not paren_m:
        return None
    num = float(paren_m.group(1))
    return num if unit_m.group(1) == "ms" else num * 1000.0


def _tps(value):
    """"26 t/s" -> 26.0. "-" -> None."""
    if not value:
        return None
    token = value.split()[0]
    try:
        return float(token)
    except ValueError:
        return None


def _median(values):
    return statistics.median(values) if values else None


# --- metric extraction -----------------------------------------------------
def extract_metrics(text):
    """Pull the COMPARISON-MATRIX headline metrics out of a report.txt body."""
    sec = parse_report(text)
    ttft = sec.get("ttft", {})
    generation = sec.get("generation", {})
    latency = sec.get("latency", {})
    tools = sec.get("tools", {})
    stress = sec.get("stress", {})

    # Median TTFT over streaming scenarios (context/generation/latency).
    ttft_vals = [
        ms
        for scen, val in ttft.items()
        if scen.startswith(TTFT_STREAMING_PREFIXES)
        for ms in (_duration_to_ms(val),)
        if ms is not None
    ]
    median_ttft = _median(ttft_vals)

    # Median decode throughput over the generation scenarios.
    tps_vals = [t for val in generation.values() for t in (_tps(val),) if t is not None]
    median_tps = _median(tps_vals)

    # latency-500 total latency, in seconds.
    lat500_ms = _duration_to_ms(latency.get(LATENCY_500_SCENARIO, ""))
    lat500_s = lat500_ms / 1000.0 if lat500_ms is not None else None

    # context-64k prefill TTFT, in ms.
    ttft64k = _duration_to_ms(ttft.get(CONTEXT_64K_SCENARIO, ""))

    # tool 10-tools minus 3-tools latency, in seconds.
    hi = _duration_to_ms(tools.get(TOOLS_HI_SCENARIO, ""))
    lo = _duration_to_ms(tools.get(TOOLS_LO_SCENARIO, ""))
    tool_delta_s = (hi - lo) / 1000.0 if hi is not None and lo is not None else None

    # stress consistency: stddev over the repeated-50 scenario, in ms.
    stress_std = _stddev_to_ms(stress.get(STRESS_SCENARIO, ""))

    # Total errored runs, summed from the "(N errors)" annotations in the report.
    errors = sum(int(n) for n in re.findall(r"\((\d+)\s+errors?\)", text))

    return {
        "ttft_ms": median_ttft,
        "tps": median_tps,
        "lat500_s": lat500_s,
        "ttft64k_ms": ttft64k,
        "tool_delta_s": tool_delta_s,
        "stress_std_ms": stress_std,
        "errors": errors,
    }
