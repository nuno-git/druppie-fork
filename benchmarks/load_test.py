#!/usr/bin/env python3
"""Concurrency / load benchmark for an OpenAI-compatible LLM endpoint.

Complements the single-stream suite (benchmarks/runner.py): that measures one
request at a time, but production sends MANY concurrent requests. This sweeps a
set of concurrency levels and, at each level, fires that many concurrent
streaming /v1/chat/completions requests to measure how the endpoint behaves
under load -- where aggregate throughput saturates and where latency knees.

Stdlib + httpx only (async). No application dependencies.

Per concurrency level it reports:
  * aggregate system throughput (sum of output tokens / wall-clock, tok/s)
  * completed requests/sec
  * median & p95 end-to-end latency
  * median & p95 time-to-first-token (TTFT)
  * median per-request decode tok/s (generation phase, excludes TTFT)
  * error count

It then detects the SATURATION point (concurrency where aggregate tok/s stops
rising / p95 latency knees) and emits both a human-readable table and JSON,
wrapped in the ===REPORT_TXT_START/END=== and ===RESULTS_JSON_START/END===
markers the in-cluster Job scraper already consumes.

Config via CLI flags or env vars (flags win):
  LOADTEST_BASE_URL          endpoint base url (…/v1)          --base-url
  LOADTEST_MODEL             model id                          --model
  LOADTEST_CONCURRENCY       comma list, default 1,8,32,64,128 --concurrency
  LOADTEST_MAX_TOKENS        max_tokens per request, def 256   --max-tokens
  LOADTEST_REQ_MULTIPLIER    requests per level = mult*C, def 3 --req-multiplier
  LOADTEST_WINDOW_SECONDS    max seconds per level, def 45     --window
  LOADTEST_MIN_REQUESTS      floor on requests per level, def 8 --min-requests
  LOADTEST_TIMEOUT           per-request timeout s, def 300    --timeout
  LOADTEST_DISPLAY_NAME      label for the report              --display-name
  LOADTEST_OUTPUT            write JSON to this path           --output
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

# A fixed ~200-input-token prompt (Dutch waterschap domain, matches the suite's
# theme). Kept constant across every request + level so throughput/latency are
# comparable. vLLM prefix-caching will cache the shared prefix; that is exactly
# the production shape (a shared system prompt across many concurrent calls).
SYSTEM_PROMPT = (
    "Je bent een behulpzame assistent voor een Nederlands waterschap. Beantwoord "
    "vragen kort, feitelijk en in het Nederlands. Geef geen uitgebreide toelichting "
    "tenzij daar expliciet om wordt gevraagd."
)

USER_PROMPT = (
    "Het waterschap is verantwoordelijk voor het beheer van het watersysteem in "
    "het beheergebied. Dit omvat het onderhoud van dijken, watergangen, gemalen "
    "en stuwen. Het waterschap zorgt ervoor dat het waterpeil op het juiste niveau "
    "blijft, zowel in droge als natte perioden. Daarnaast is het waterschap "
    "verantwoordelijk voor de zuivering van afvalwater en het bewaken van de "
    "waterkwaliteit. Bij extreme weersomstandigheden, zoals hevige regenval of "
    "langdurige droogte, neemt het waterschap maatregelen om overlast te voorkomen "
    "en de watervoorziening veilig te stellen. Het waterschap werkt samen met "
    "gemeenten, provincies en Rijkswaterstaat om een integraal waterbeheer te "
    "realiseren dat rekening houdt met klimaatverandering en verstedelijking.\n\n"
    "Vraag: vat in maximaal drie zinnen samen welke kerntaken het waterschap heeft."
)


@dataclass
class RequestResult:
    """One request's measurements."""

    latency_ms: float = 0.0
    ttft_ms: float | None = None
    output_tokens: int = 0
    prompt_tokens: int = 0
    decode_tps: float = 0.0  # output tokens / (end - first_token), generation-only
    error: str | None = None
    start_wall: float = 0.0  # perf_counter at request start
    end_wall: float = 0.0    # perf_counter at request end


@dataclass
class LevelResult:
    """Aggregated stats for one concurrency level."""

    concurrency: int = 0
    total_requests: int = 0
    ok: int = 0
    errors: int = 0
    wall_clock_s: float = 0.0
    agg_tok_s: float = 0.0        # sum output tokens / wall clock
    req_per_s: float = 0.0        # completed ok / wall clock
    latency_ms_median: float = 0.0
    latency_ms_p95: float = 0.0
    ttft_ms_median: float = 0.0
    ttft_ms_p95: float = 0.0
    decode_tps_median: float = 0.0
    total_output_tokens: int = 0
    prompt_tokens: int = 0
    error_samples: list[str] = field(default_factory=list)


def _pctile(values: list[float], q: float) -> float:
    """Return the q-percentile (0..100) of values via linear interpolation."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (q / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _auth_headers(api_key: str) -> dict:
    key = api_key or "no-key-required"
    return {"Authorization": f"Bearer {key}"}


async def _one_request(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    model: str,
    max_tokens: int,
    timeout: float,
) -> RequestResult:
    """Fire a single streaming chat-completion and measure it."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    res = RequestResult()
    first_token_time: float | None = None
    text_len = 0
    usage = None
    start = time.perf_counter()
    res.start_wall = start
    try:
        async with client.stream(
            "POST", url, headers=headers, json=body,
            timeout=httpx.Timeout(timeout),
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                res.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                res.end_wall = time.perf_counter()
                res.latency_ms = (res.end_wall - start) * 1000
                return res
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta", {}) or {}
                    content = delta.get("content")
                    if content:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                            res.ttft_ms = (first_token_time - start) * 1000
                        text_len += len(content)
                if chunk.get("usage"):
                    usage = chunk["usage"]
    except httpx.TimeoutException:
        res.end_wall = time.perf_counter()
        res.latency_ms = (res.end_wall - start) * 1000
        res.error = f"Timeout after {timeout}s"
        return res
    except Exception as e:  # noqa: BLE001
        res.end_wall = time.perf_counter()
        res.latency_ms = (res.end_wall - start) * 1000
        res.error = f"{type(e).__name__}: {e}"
        return res

    end = time.perf_counter()
    res.end_wall = end
    res.latency_ms = (end - start) * 1000

    if usage:
        res.output_tokens = usage.get("completion_tokens", 0) or 0
        res.prompt_tokens = usage.get("prompt_tokens", 0) or 0
    if res.output_tokens == 0 and text_len > 0:
        # Rough fallback if the server omitted usage.
        res.output_tokens = max(1, text_len // 4)

    if first_token_time is not None and res.output_tokens > 0:
        decode_s = end - first_token_time
        if decode_s > 0:
            res.decode_tps = res.output_tokens / decode_s
    return res


async def _run_level(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    model: str,
    concurrency: int,
    total_requests: int,
    window_s: float,
    max_tokens: int,
    timeout: float,
) -> LevelResult:
    """Keep `concurrency` requests in flight until total_requests done or window elapsed."""
    results: list[RequestResult] = []
    next_idx = 0
    lock = asyncio.Lock()
    level_start = time.perf_counter()
    deadline = level_start + window_s

    async def worker() -> None:
        nonlocal next_idx
        while True:
            async with lock:
                if next_idx >= total_requests or time.perf_counter() >= deadline:
                    return
                next_idx += 1
            r = await _one_request(client, url, headers, model, max_tokens, timeout)
            results.append(r)

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    await asyncio.gather(*workers)

    lvl = LevelResult(concurrency=concurrency, total_requests=len(results))
    ok = [r for r in results if not r.error]
    errs = [r for r in results if r.error]
    lvl.ok = len(ok)
    lvl.errors = len(errs)
    lvl.error_samples = list({e.error for e in errs})[:5]

    if results:
        wall = max(r.end_wall for r in results) - min(r.start_wall for r in results)
        lvl.wall_clock_s = wall
        total_out = sum(r.output_tokens for r in ok)
        lvl.total_output_tokens = total_out
        if wall > 0:
            lvl.agg_tok_s = total_out / wall
            lvl.req_per_s = len(ok) / wall

    if ok:
        latencies = [r.latency_ms for r in ok]
        ttfts = [r.ttft_ms for r in ok if r.ttft_ms is not None]
        decodes = [r.decode_tps for r in ok if r.decode_tps > 0]
        lvl.latency_ms_median = _median(latencies)
        lvl.latency_ms_p95 = _pctile(latencies, 95)
        lvl.ttft_ms_median = _median(ttfts)
        lvl.ttft_ms_p95 = _pctile(ttfts, 95)
        lvl.decode_tps_median = _median(decodes)
        lvl.prompt_tokens = _median([float(r.prompt_tokens) for r in ok if r.prompt_tokens])
    return lvl


def _detect_saturation(levels: list[LevelResult]) -> dict:
    """Find where aggregate tok/s stops rising / p95 latency knees.

    Heuristics:
      * peak_concurrency: level with the highest aggregate tok/s.
      * knee_concurrency: first level where the aggregate tok/s gain over the
        previous level is < 10% (throughput has flattened). If none flattens,
        it equals peak_concurrency.
    """
    ok_levels = [lv for lv in levels if lv.ok > 0]
    if not ok_levels:
        return {"peak_concurrency": None, "peak_tok_s": 0.0, "knee_concurrency": None}

    peak = max(ok_levels, key=lambda lv: lv.agg_tok_s)
    knee = None
    prev = None
    for lv in ok_levels:
        if prev is not None and prev.agg_tok_s > 0:
            gain = (lv.agg_tok_s - prev.agg_tok_s) / prev.agg_tok_s
            if gain < 0.10:
                knee = prev.concurrency
                break
        prev = lv
    if knee is None:
        knee = peak.concurrency
    return {
        "peak_concurrency": peak.concurrency,
        "peak_tok_s": round(peak.agg_tok_s, 1),
        "knee_concurrency": knee,
    }


def _fmt_report(
    display_name: str,
    base_url: str,
    model: str,
    max_tokens: int,
    levels: list[LevelResult],
    saturation: dict,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append(f"LLM Concurrency / Load Benchmark - {now}")
    lines.append(f"Model:    {display_name} ({model})")
    lines.append(f"Endpoint: {base_url}")
    prompt_tokens = next((int(lv.prompt_tokens) for lv in levels if lv.prompt_tokens), 0)
    lines.append(f"Prompt:   ~{prompt_tokens or '?'} input tokens, max_tokens={max_tokens}, streaming")
    lines.append("")
    lines.append(
        "Concurrency sweep (each level keeps N streaming requests in flight):"
    )
    header = (
        f"{'Conc':>4} | {'Reqs':>4} | {'Err':>3} | {'AggTok/s':>9} | "
        f"{'Req/s':>6} | {'Lat p50':>8} | {'Lat p95':>8} | "
        f"{'TTFT p50':>9} | {'TTFT p95':>9} | {'Decode p50':>10}"
    )
    lines.append("-" * len(header))
    lines.append(header)
    lines.append("-" * len(header))
    for lv in levels:
        lines.append(
            f"{lv.concurrency:>4} | {lv.total_requests:>4} | {lv.errors:>3} | "
            f"{lv.agg_tok_s:>9.1f} | {lv.req_per_s:>6.2f} | "
            f"{lv.latency_ms_median / 1000:>7.1f}s | {lv.latency_ms_p95 / 1000:>7.1f}s | "
            f"{lv.ttft_ms_median:>8.0f}ms | {lv.ttft_ms_p95:>8.0f}ms | "
            f"{lv.decode_tps_median:>8.1f}t/s"
        )
    lines.append("-" * len(header))
    lines.append("")
    lines.append("Saturation analysis:")
    lines.append(
        f"  Peak aggregate throughput: {saturation['peak_tok_s']} tok/s "
        f"at concurrency {saturation['peak_concurrency']}"
    )
    lines.append(
        f"  Throughput knee (flattens / p95 climbs): concurrency {saturation['knee_concurrency']}"
    )
    total_err = sum(lv.errors for lv in levels)
    lines.append(f"  Total errors across sweep: {total_err}")
    if total_err:
        samples = []
        for lv in levels:
            for s in lv.error_samples:
                if s not in samples:
                    samples.append(s)
        for s in samples[:5]:
            lines.append(f"    - {s}")
    lines.append("")
    return "\n".join(lines)


def _to_json(
    display_name: str,
    base_url: str,
    model: str,
    max_tokens: int,
    concurrency_levels: list[int],
    req_multiplier: int,
    window_s: float,
    levels: list[LevelResult],
    saturation: dict,
) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test": "concurrency_load",
        "display_name": display_name,
        "endpoint": base_url,
        "model": model,
        "settings": {
            "concurrency_levels": concurrency_levels,
            "max_tokens": max_tokens,
            "req_multiplier": req_multiplier,
            "window_seconds": window_s,
            "streaming": True,
        },
        "saturation": saturation,
        "levels": [
            {
                "concurrency": lv.concurrency,
                "total_requests": lv.total_requests,
                "ok": lv.ok,
                "errors": lv.errors,
                "wall_clock_s": round(lv.wall_clock_s, 3),
                "aggregate_tok_s": round(lv.agg_tok_s, 2),
                "req_per_s": round(lv.req_per_s, 3),
                "latency_ms_median": round(lv.latency_ms_median, 1),
                "latency_ms_p95": round(lv.latency_ms_p95, 1),
                "ttft_ms_median": round(lv.ttft_ms_median, 1),
                "ttft_ms_p95": round(lv.ttft_ms_p95, 1),
                "decode_tps_median": round(lv.decode_tps_median, 2),
                "total_output_tokens": lv.total_output_tokens,
                "prompt_tokens": int(lv.prompt_tokens),
                "error_samples": lv.error_samples,
            }
            for lv in levels
        ],
    }


def _parse_concurrency(raw: str) -> list[int]:
    out = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok:
            out.append(int(tok))
    return out or [1, 8, 32, 64, 128]


async def _amain(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json", **_auth_headers(args.api_key)}
    concurrency_levels = _parse_concurrency(args.concurrency)
    max_conn = max(concurrency_levels) + 8

    print(f">> Load test: {args.display_name} ({args.model})", file=sys.stderr)
    print(f">> Endpoint: {base_url}", file=sys.stderr)
    print(f">> Concurrency levels: {concurrency_levels}", file=sys.stderr)

    limits = httpx.Limits(
        max_connections=max_conn,
        max_keepalive_connections=max_conn,
    )
    levels: list[LevelResult] = []
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(args.timeout)) as client:
        # Warmup: one request to prime the connection + prefix cache.
        print(">> Warmup request...", file=sys.stderr)
        await _one_request(client, url, headers, args.model, args.max_tokens, args.timeout)

        for c in concurrency_levels:
            total = max(args.min_requests, args.req_multiplier * c)
            print(
                f">> Level c={c}: up to {total} requests (window {args.window}s)...",
                file=sys.stderr,
            )
            lvl = await _run_level(
                client, url, headers, args.model,
                concurrency=c, total_requests=total, window_s=args.window,
                max_tokens=args.max_tokens, timeout=args.timeout,
            )
            print(
                f"   done: {lvl.ok} ok / {lvl.errors} err, "
                f"agg {lvl.agg_tok_s:.1f} tok/s, "
                f"lat p95 {lvl.latency_ms_p95 / 1000:.1f}s, "
                f"ttft p95 {lvl.ttft_ms_p95:.0f}ms",
                file=sys.stderr,
            )
            levels.append(lvl)

    saturation = _detect_saturation(levels)
    report = _fmt_report(
        args.display_name, base_url, args.model, args.max_tokens, levels, saturation
    )
    data = _to_json(
        args.display_name, base_url, args.model, args.max_tokens,
        concurrency_levels, args.req_multiplier, args.window, levels, saturation,
    )

    # Emit marker-wrapped report + JSON so the in-cluster Job scraper picks them
    # up out of the pod logs (same markers as runner.py / job.yaml).
    print("===REPORT_TXT_START===")
    print(report)
    print("===REPORT_TXT_END===")
    print("===RESULTS_JSON_START===")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("===RESULTS_JSON_END===")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f">> JSON written to {args.output}", file=sys.stderr)

    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Concurrency / load benchmark for an OpenAI-compatible endpoint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    env = os.environ.get
    p.add_argument("--base-url", default=env("LOADTEST_BASE_URL", ""),
                   help="Endpoint base url (…/v1)")
    p.add_argument("--model", default=env("LOADTEST_MODEL", ""),
                   help="Model id to send")
    p.add_argument("--api-key", default=env("LOADTEST_API_KEY", "no-key-required"))
    p.add_argument("--concurrency", default=env("LOADTEST_CONCURRENCY", "1,8,32,64,128"),
                   help="Comma-separated concurrency levels")
    p.add_argument("--max-tokens", type=int,
                   default=int(env("LOADTEST_MAX_TOKENS", "256")))
    p.add_argument("--req-multiplier", type=int,
                   default=int(env("LOADTEST_REQ_MULTIPLIER", "3")),
                   help="Requests per level = multiplier * concurrency")
    p.add_argument("--min-requests", type=int,
                   default=int(env("LOADTEST_MIN_REQUESTS", "8")),
                   help="Floor on requests per level")
    p.add_argument("--window", type=float,
                   default=float(env("LOADTEST_WINDOW_SECONDS", "45")),
                   help="Max seconds per level")
    p.add_argument("--timeout", type=float,
                   default=float(env("LOADTEST_TIMEOUT", "300")),
                   help="Per-request timeout in seconds")
    p.add_argument("--display-name", default=env("LOADTEST_DISPLAY_NAME", ""),
                   help="Label for the report")
    p.add_argument("--output", default=env("LOADTEST_OUTPUT", ""),
                   help="Write JSON results to this path")
    args = p.parse_args()

    if not args.base_url or not args.model:
        print("Error: --base-url and --model are required (or set "
              "LOADTEST_BASE_URL / LOADTEST_MODEL).", file=sys.stderr)
        sys.exit(2)
    if not args.display_name:
        args.display_name = args.model

    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
