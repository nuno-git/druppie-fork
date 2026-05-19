"""Benchmark result reporting - console tables, JSON, and CSV export."""

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from benchmarks.llm_client import BenchmarkResult, ModelConfig


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _fmt_latency(ms: float, stddev_ms: float = 0.0) -> str:
    if ms == 0:
        return "-"
    sec = ms / 1000
    if stddev_ms > 0:
        return f"{sec:.1f}s (±{stddev_ms / 1000:.1f})"
    return f"{sec:.1f}s"


def _fmt_tps(tps: float) -> str:
    if tps == 0:
        return "-"
    return f"{tps:.0f} t/s"


def _fmt_ttft(ms: float) -> str:
    if ms == 0:
        return "-"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _pad(text: str, width: int) -> str:
    return text.ljust(width)[:width]


CategoryResults = dict[str, dict[str, dict[str, list[BenchmarkResult]]]]


def print_report(
    results: CategoryResults,
    models: list[ModelConfig],
    settings: dict,
) -> None:
    """Print a formatted benchmark report to stdout."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    endpoints = set(m.endpoint_name for m in models)

    print(f"\nLLM Performance Benchmark - {now}")
    for ep in sorted(endpoints):
        ep_model = next((m for m in models if m.endpoint_name == ep), None)
        if ep_model:
            print(f"Endpoint: {ep} ({ep_model.endpoint.base_url})")
    print(f"Runs per test: {settings.get('runs_per_test', 1)}")
    print(f"Warmup runs: {settings.get('warmup_runs', 0)}")

    print("\nModel Configurations:")
    for m in models:
        print(f"  {_pad(m.display_name, 22)} - {m.config_summary()}")

    model_names = [m.display_name for m in models]
    model_col_width = max(14, max((len(n) for n in model_names), default=14) + 2)

    category_labels = {
        "latency": "LATENCY (total response time)",
        "generation": "GENERATION SPEED",
        "context_scaling": "CONTEXT SCALING (latency)",
        "tool_overhead": "TOOL CALLING OVERHEAD (latency)",
        "stress": "STRESS / CONSISTENCY",
    }

    for category, scenarios in results.items():
        label = category_labels.get(category, category.upper())
        print(f"\n{'=' * 80}")
        print(f"  {label}")
        print(f"{'=' * 80}")

        header = _pad("Scenario", 22) + " | "
        header += " | ".join(_pad(n, model_col_width) for n in model_names)
        print(header)
        print("-" * len(header))

        for scenario_name, model_results in sorted(scenarios.items()):
            row = _pad(scenario_name, 22) + " | "
            cells = []
            for m in models:
                runs = model_results.get(m.display_name, [])
                if not runs or all(r.error for r in runs):
                    cells.append(_pad("ERROR" if runs else "-", model_col_width))
                    continue

                ok_runs = [r for r in runs if not r.error]
                if category == "generation":
                    tps_values = [r.tokens_per_second for r in ok_runs if r.tokens_per_second > 0]
                    cells.append(_pad(_fmt_tps(_mean(tps_values)), model_col_width))
                else:
                    latencies = [r.total_latency_ms for r in ok_runs]
                    cells.append(_pad(
                        _fmt_latency(_mean(latencies), _stddev(latencies)),
                        model_col_width,
                    ))
            row += " | ".join(cells)
            print(row)

    _print_ttft_section(results, models, model_col_width)
    _print_summary(results, models, model_col_width)


def _print_ttft_section(
    results: CategoryResults,
    models: list[ModelConfig],
    model_col_width: int,
) -> None:
    """Print time-to-first-token section if data is available."""
    model_names = [m.display_name for m in models]
    has_ttft = False
    for scenarios in results.values():
        for model_results in scenarios.values():
            for runs in model_results.values():
                if any(r.time_to_first_token_ms for r in runs if not r.error):
                    has_ttft = True
                    break

    if not has_ttft:
        return

    print(f"\n{'=' * 80}")
    print("  TIME TO FIRST TOKEN (TTFT)")
    print(f"{'=' * 80}")

    header = _pad("Scenario", 22) + " | "
    header += " | ".join(_pad(n, model_col_width) for n in model_names)
    print(header)
    print("-" * len(header))

    for category, scenarios in results.items():
        for scenario_name, model_results in sorted(scenarios.items()):
            row = _pad(scenario_name, 22) + " | "
            cells = []
            for m in models:
                runs = model_results.get(m.display_name, [])
                ok_runs = [r for r in runs if not r.error and r.time_to_first_token_ms]
                if not ok_runs:
                    cells.append(_pad("-", model_col_width))
                else:
                    ttfts = [r.time_to_first_token_ms for r in ok_runs]
                    cells.append(_pad(_fmt_ttft(_mean(ttfts)), model_col_width))
            row += " | ".join(cells)
            print(row)


def _print_summary(
    results: CategoryResults,
    models: list[ModelConfig],
    model_col_width: int,
) -> None:
    """Print overall summary per model."""
    print(f"\n{'=' * 80}")
    print("  SUMMARY")
    print(f"{'=' * 80}")

    header = (
        _pad("Model", 22)
        + " | " + _pad("Avg Latency", 12)
        + " | " + _pad("Avg Tok/s", 10)
        + " | " + _pad("Avg TTFT", 10)
        + " | " + _pad("Errors", 8)
    )
    print(header)
    print("-" * len(header))

    for m in models:
        all_latencies = []
        all_tps = []
        all_ttft = []
        error_count = 0
        total_count = 0

        for scenarios in results.values():
            for model_results in scenarios.values():
                runs = model_results.get(m.display_name, [])
                for r in runs:
                    total_count += 1
                    if r.error:
                        error_count += 1
                    else:
                        all_latencies.append(r.total_latency_ms)
                        if r.tokens_per_second > 0:
                            all_tps.append(r.tokens_per_second)
                        if r.time_to_first_token_ms:
                            all_ttft.append(r.time_to_first_token_ms)

        row = (
            _pad(m.display_name, 22)
            + " | " + _pad(_fmt_latency(_mean(all_latencies)), 12)
            + " | " + _pad(_fmt_tps(_mean(all_tps)), 10)
            + " | " + _pad(_fmt_ttft(_mean(all_ttft)) if all_ttft else "-", 10)
            + " | " + _pad(f"{error_count}/{total_count}", 8)
        )
        print(row)
    print()


def export_json(
    results: CategoryResults,
    models: list[ModelConfig],
    settings: dict,
    output_path: str,
) -> None:
    """Export all results to JSON."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "settings": settings,
        "models": [
            {
                "display_name": m.display_name,
                "endpoint": m.endpoint_name,
                "model": m.model,
                "max_context": m.max_context,
                "parameters": m.parameters,
                "quantization": m.quantization,
                "kv_cache_quant": m.kv_cache_quant,
                "flash_attention": m.flash_attention,
                "gpu_layers": m.gpu_layers,
                "notes": m.notes,
            }
            for m in models
        ],
        "results": {},
    }

    for category, scenarios in results.items():
        data["results"][category] = {}
        for scenario_name, model_results in scenarios.items():
            data["results"][category][scenario_name] = {}
            for model_name, runs in model_results.items():
                data["results"][category][scenario_name][model_name] = [
                    {
                        "total_latency_ms": r.total_latency_ms,
                        "time_to_first_token_ms": r.time_to_first_token_ms,
                        "prompt_tokens": r.prompt_tokens,
                        "completion_tokens": r.completion_tokens,
                        "total_tokens": r.total_tokens,
                        "tokens_per_second": r.tokens_per_second,
                        "prompt_eval_rate": r.prompt_eval_rate,
                        "error": r.error,
                    }
                    for r in runs
                ]

    Path(output_path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nJSON results exported to {output_path}")


def export_csv(
    results: CategoryResults,
    models: list[ModelConfig],
    settings: dict,
    output_path: str,
) -> None:
    """Export all results to CSV (flat table)."""
    rows = []
    for category, scenarios in results.items():
        for scenario_name, model_results in scenarios.items():
            for model_name, runs in model_results.items():
                model = next((m for m in models if m.display_name == model_name), None)
                for i, r in enumerate(runs):
                    rows.append({
                        "category": category,
                        "scenario": scenario_name,
                        "model": model_name,
                        "endpoint": model.endpoint_name if model else "",
                        "model_id": model.model if model else "",
                        "parameters": model.parameters if model else "",
                        "quantization": model.quantization if model else "",
                        "kv_cache_quant": model.kv_cache_quant if model else "",
                        "flash_attention": model.flash_attention if model else "",
                        "run": i + 1,
                        "total_latency_ms": round(r.total_latency_ms, 1),
                        "ttft_ms": round(r.time_to_first_token_ms, 1) if r.time_to_first_token_ms else "",
                        "prompt_tokens": r.prompt_tokens,
                        "completion_tokens": r.completion_tokens,
                        "total_tokens": r.total_tokens,
                        "tokens_per_second": round(r.tokens_per_second, 1),
                        "prompt_eval_rate": round(r.prompt_eval_rate, 1),
                        "error": r.error or "",
                    })

    if not rows:
        print("No results to export.")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV results exported to {output_path}")
