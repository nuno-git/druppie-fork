#!/usr/bin/env python3
"""LLM Performance Benchmark Runner.

Standalone tool for measuring LLM performance on OpenAI-compatible endpoints
(Ollama, vLLM, TGI on Nutanix/K8s). No application dependencies — only httpx and pyyaml.

Usage:
  python -m benchmarks.runner                              # all scenarios, all models
  python -m benchmarks.runner --model gpt-oss:20b          # all scenarios, 1 model
  python -m benchmarks.runner --category latency            # only latency scenarios
  python -m benchmarks.runner --scenario latency-50         # 1 specific scenario
  python -m benchmarks.runner --runs 5                      # 5x per test
  python -m benchmarks.runner --output results.json         # export to JSON
  python -m benchmarks.runner --output results.csv          # export to CSV
  python -m benchmarks.runner --fetch-models ollama         # list models on endpoint
"""

import argparse
import sys
from pathlib import Path

import yaml

from benchmarks.llm_client import (
    BenchmarkResult,
    EndpointConfig,
    ModelConfig,
    call_llm,
    fetch_models,
)
from benchmarks.reporter import (
    CategoryResults,
    export_csv,
    export_json,
    print_report,
)

BENCHMARKS_DIR = Path(__file__).resolve().parent
SCENARIOS_DIR = BENCHMARKS_DIR / "scenarios"

FILLER_PARAGRAPH = (
    "Het waterschap is verantwoordelijk voor het beheer van het watersysteem in het "
    "beheergebied. Dit omvat het onderhoud van dijken, watergangen, gemalen en stuwen. "
    "Het waterschap zorgt ervoor dat het waterpeil op het juiste niveau blijft, zowel "
    "in droge als natte perioden. Daarnaast is het waterschap verantwoordelijk voor de "
    "zuivering van afvalwater en het bewaken van de waterkwaliteit. Bij extreme "
    "weersomstandigheden, zoals hevige regenval of langdurige droogte, neemt het "
    "waterschap maatregelen om overlast te voorkomen en de watervoorziening veilig te "
    "stellen. Het waterschap werkt samen met gemeenten, provincies en Rijkswaterstaat "
    "om een integraal waterbeheer te realiseren dat rekening houdt met klimaatverandering "
    "en de toenemende verstedelijking. "
)


def load_config() -> dict:
    config_path = BENCHMARKS_DIR / "config.yaml"
    if not config_path.exists():
        print(f"Error: config.yaml not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_config(raw: dict) -> tuple[list[ModelConfig], dict]:
    endpoints = {}
    for name, ep_data in raw.get("endpoints", {}).items():
        endpoints[name] = EndpointConfig(
            base_url=ep_data["base_url"],
            api_key=ep_data.get("api_key", ""),
            ssl_verify=ep_data.get("ssl_verify", True),
            auth_type=ep_data.get("auth_type", "bearer"),
        )

    models = []
    for m in raw.get("models", []):
        ep_name = m["endpoint"]
        if ep_name not in endpoints:
            print(f"Warning: endpoint '{ep_name}' not found for model '{m['model']}'", file=sys.stderr)
            continue
        models.append(ModelConfig(
            endpoint_name=ep_name,
            model=m["model"],
            display_name=m.get("display_name", m["model"]),
            max_context=m.get("max_context", 32768),
            parameters=m.get("parameters", ""),
            quantization=m.get("quantization"),
            kv_cache_quant=m.get("kv_cache_quant"),
            flash_attention=m.get("flash_attention", False),
            gpu_layers=m.get("gpu_layers", -1),
            notes=m.get("notes", ""),
            endpoint=endpoints[ep_name],
        ))

    settings = raw.get("settings", {})
    return models, settings


def load_scenarios(
    category_filter: str | None = None,
    scenario_filter: str | None = None,
) -> list[dict]:
    if not SCENARIOS_DIR.exists():
        print(f"Error: scenarios directory not found at {SCENARIOS_DIR}", file=sys.stderr)
        sys.exit(1)

    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data or "scenario" not in data:
            continue
        scenario = data["scenario"]
        if category_filter and scenario.get("category") != category_filter:
            continue
        if scenario_filter and scenario.get("name") != scenario_filter:
            continue
        scenarios.append(scenario)

    return scenarios


def _generate_filler_text(target_tokens: int) -> str:
    """Generate filler text of approximately the target token count.

    Rough estimate: 1 token ≈ 4 characters for Dutch text.
    """
    target_chars = target_tokens * 4
    repetitions = (target_chars // len(FILLER_PARAGRAPH)) + 1
    full_text = FILLER_PARAGRAPH * repetitions
    return full_text[:target_chars]


def build_messages(scenario: dict, model_config: ModelConfig) -> list[dict] | None:
    """Build the messages array for a scenario, including context filler if needed."""
    messages = []

    system_prompt = scenario.get("system_prompt", "")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    context_tokens = scenario.get("context_tokens")
    if context_tokens:
        if context_tokens > model_config.max_context:
            return None
        filler = _generate_filler_text(context_tokens)
        user_content = f"{filler}\n\n{scenario.get('user_prompt', '')}"
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": scenario.get("user_prompt", "")})

    return messages


def run_scenario(
    scenario: dict,
    model_config: ModelConfig,
    runs: int,
    warmup_runs: int,
    timeout: float,
) -> list[BenchmarkResult]:
    """Run a single scenario against a model, returning results for measured runs."""
    messages = build_messages(scenario, model_config)
    if messages is None:
        return [BenchmarkResult(
            error=f"Context {scenario.get('context_tokens')} exceeds model max {model_config.max_context}",
        )]

    tools = scenario.get("tools")
    max_tokens = scenario.get("max_output_tokens")
    repeat = scenario.get("repeat", 1)

    total_runs = warmup_runs + runs

    results = []
    for i in range(total_runs):
        is_warmup = i < warmup_runs
        for _ in range(repeat if not is_warmup else 1):
            result = call_llm(
                model_config=model_config,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                timeout=timeout,
                stream=tools is None,
            )
            if not is_warmup:
                results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="LLM Performance Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--model", help="Run only this model (by model ID, e.g. gpt-oss:20b)")
    parser.add_argument("--category", help="Run only this category (latency, generation, context_scaling, tool_overhead, stress)")
    parser.add_argument("--scenario", help="Run only this scenario (by name)")
    parser.add_argument("--runs", type=int, help="Number of measured runs per scenario (overrides config)")
    parser.add_argument("--warmup", type=int, help="Number of warmup runs (overrides config)")
    parser.add_argument("--timeout", type=float, help="Timeout per LLM call in seconds (overrides config)")
    parser.add_argument("--output", help="Export results to file (JSON or CSV, detected by extension)")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming (no TTFT measurement)")
    parser.add_argument("--list", action="store_true", help="List available scenarios and models, then exit")
    parser.add_argument("--fetch-models", metavar="ENDPOINT", help="Fetch available models from an endpoint (by name from config), then exit")
    args = parser.parse_args()

    raw_config = load_config()
    models, settings = parse_config(raw_config)
    endpoints = {}
    for name, ep_data in raw_config.get("endpoints", {}).items():
        endpoints[name] = EndpointConfig(
            base_url=ep_data["base_url"],
            api_key=ep_data.get("api_key", ""),
            ssl_verify=ep_data.get("ssl_verify", True),
            auth_type=ep_data.get("auth_type", "bearer"),
        )

    if args.fetch_models:
        ep_name = args.fetch_models
        if ep_name not in endpoints:
            print(f"Error: endpoint '{ep_name}' not found in config.yaml", file=sys.stderr)
            print(f"Available endpoints: {', '.join(endpoints.keys())}", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching models from {ep_name} ({endpoints[ep_name].base_url})...\n")
        remote_models = fetch_models(endpoints[ep_name])
        if not remote_models:
            print("No models found (or endpoint unreachable).")
        else:
            print(f"Found {len(remote_models)} models:\n")
            for rm in remote_models:
                model_id = rm.get("id", rm.get("name", "?"))
                details = []
                if rm.get("parameter_size"):
                    details.append(rm["parameter_size"])
                if rm.get("quantization_level"):
                    details.append(rm["quantization_level"])
                if rm.get("family"):
                    details.append(rm["family"])
                detail_str = f"  ({', '.join(details)})" if details else ""
                print(f"  {model_id}{detail_str}")
        return

    runs = args.runs or settings.get("runs_per_test", 3)
    warmup = args.warmup if args.warmup is not None else settings.get("warmup_runs", 1)
    timeout = args.timeout or settings.get("timeout_seconds", 300)

    if args.model:
        models = [m for m in models if m.model == args.model]
        if not models:
            print(f"Error: model '{args.model}' not found in config.yaml", file=sys.stderr)
            sys.exit(1)

    scenarios = load_scenarios(
        category_filter=args.category,
        scenario_filter=args.scenario,
    )

    if args.list:
        print("Available models (from config.yaml):")
        for m in models:
            print(f"  {m.model:30s} ({m.display_name}, {m.config_summary()})")
        print(f"\nAvailable scenarios ({len(scenarios)}):")
        for s in scenarios:
            print(f"  {s['name']:30s} [{s.get('category', '?')}] {s.get('description', '')}")
        print(f"\nTip: use --fetch-models <endpoint> to see models available on a remote endpoint")
        return

    if not scenarios:
        print("No scenarios found matching filters.", file=sys.stderr)
        sys.exit(1)

    if not models:
        print("No models found matching filters.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(scenarios)} scenarios x {len(models)} models ({runs} runs each, {warmup} warmup)")
    print()

    all_results: CategoryResults = {}

    for model in models:
        print(f"  Model: {model.display_name} ({model.model})")
        for scenario in scenarios:
            category = scenario.get("category", "other")
            name = scenario["name"]
            print(f"    {name}...", end=" ", flush=True)

            results = run_scenario(scenario, model, runs, warmup, timeout)

            ok_count = sum(1 for r in results if not r.error)
            err_count = sum(1 for r in results if r.error)
            if ok_count > 0:
                avg_latency = sum(r.total_latency_ms for r in results if not r.error) / ok_count
                print(f"{avg_latency:.0f}ms avg", end="")
            if err_count > 0:
                print(f" ({err_count} errors)", end="")
            print()

            if category not in all_results:
                all_results[category] = {}
            if name not in all_results[category]:
                all_results[category][name] = {}
            all_results[category][name][model.display_name] = results

    print_report(all_results, models, settings)

    if args.output:
        if args.output.endswith(".csv"):
            export_csv(all_results, models, settings, args.output)
        else:
            export_json(all_results, models, settings, args.output)


if __name__ == "__main__":
    main()
