#!/usr/bin/env python3
"""
Scalability proof test — READ-heavy API load test with chart generation.

Tests that GET endpoints (sessions, projects, agents, etc.) stay fast under
progressive concurrent load, while collecting pods/nodes/CPU/mem metrics.

Produces PNG charts in testing/autoscaling/results/:
  1. response_time_by_endpoint.png   — p50/p95/p99 bar chart per endpoint
  2. latency_over_time.png           — p50/p95 timeline as load ramps
  3. scaling_timeline.png            — pods + nodes over time
  4. throughput_vs_latency.png       — scatter: rps vs p95
  5. resource_usage.png             — backend CPU/mem + DB CPU/mem

Usage:
    python3 testing/autoscaling/scalability-proof.py
    python3 testing/autoscaling/scalability-proof.py --domain druppie.rijnland.dev
"""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

KUBECONFIG = os.environ.get("KUBECONFIG", os.path.join(os.path.dirname(__file__), "..", "..", "kubeconfig"))

READ_ENDPOINTS = [
    ("/health", False),
    ("/api/sessions?limit=20", True),
    ("/api/sessions?limit=50", True),
    ("/api/projects", True),
    ("/api/agents", True),
    ("/api/modules", True),
    ("/api/approvals", True),
    ("/api/deployments", True),
]

RAMP_STAGES = [
    (10, 20),
    (25, 20),
    (50, 30),
    (75, 30),
    (100, 40),
    (125, 40),
]


@dataclass
class RequestResult:
    endpoint: str
    method: str
    status: int
    latency_ms: float
    timestamp: float
    stage: str


@dataclass
class MetricSnapshot:
    timestamp: float
    backend_pods: int
    backend_ready: int
    app_nodes: int
    backend_cpu_m: float
    backend_mem_mi: float
    db_cpu_m: float
    db_mem_mi: float
    db_connections: int
    running_agent_runs: int


@dataclass
class TestData:
    requests: list[RequestResult] = field(default_factory=list)
    metrics: list[MetricSnapshot] = field(default_factory=list)
    start_time: float = 0.0


def kubectl(args: list[str]) -> str:
    try:
        env = {**os.environ, "KUBECONFIG": KUBECONFIG}
        r = subprocess.run(["kubectl"] + args, capture_output=True, text=True, timeout=10, env=env)
        return r.stdout.strip()
    except Exception:
        return ""


def get_token(base_url: str, auth_url: str, username: str, password: str) -> str:
    import urllib3
    urllib3.disable_warnings()
    r = httpx.post(
        f"{auth_url}/realms/druppie/protocol/openid-connect/token",
        data={"client_id": "druppie-frontend", "username": username, "password": password, "grant_type": "password"},
        timeout=15, verify=False,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def collect_metrics() -> MetricSnapshot:
    pods_raw = kubectl(["get", "pods", "-n", "druppie", "-l", "app.kubernetes.io/component=backend", "--no-headers"])
    pod_lines = [l for l in pods_raw.split("\n") if l.strip()] if pods_raw else []
    backend_pods = len(pod_lines)
    backend_ready = sum(1 for l in pod_lines if "1/1" in l and "Running" in l)

    nodes_raw = kubectl(["get", "nodes", "-l", "pool=app", "--no-headers"])
    app_nodes = len([l for l in nodes_raw.split("\n") if "Ready" in l]) if nodes_raw else 0

    top_pods = kubectl(["top", "pods", "-n", "druppie", "-l", "app.kubernetes.io/component=backend", "--no-headers"])
    backend_cpu_m = 0.0
    backend_mem_mi = 0.0
    for line in top_pods.split("\n"):
        if "m" in line and "Mi" in line:
            parts = line.split()
            for p in parts:
                if p.endswith("m") and p[:-1].isdigit():
                    backend_cpu_m += int(p[:-1])
                elif p.endswith("Mi") and p[:-2].isdigit():
                    backend_mem_mi += int(p[:-2])

    db_top = kubectl(["top", "pods", "-n", "druppie", "druppie-druppie-db-0", "--no-headers"])
    db_cpu_m = 0.0
    db_mem_mi = 0.0
    for p in db_top.split():
        if p.endswith("m") and p[:-1].isdigit():
            db_cpu_m = int(p[:-1])
        elif p.endswith("Mi") and p[:-2].isdigit():
            db_mem_mi = int(p[:-2])

    db_conn_raw = kubectl(["exec", "-n", "druppie", "druppie-druppie-db-0", "--",
                           "psql", "-U", "druppie", "-d", "druppie", "-t", "-c",
                           "SELECT count(*) FROM pg_stat_activity WHERE state != 'idle';"])
    db_connections = 0
    for line in db_conn_raw.split("\n"):
        line = line.strip()
        if line.isdigit():
            db_connections = int(line)
            break

    running_raw = kubectl(["exec", "-n", "druppie", "druppie-druppie-db-0", "--",
                           "psql", "-U", "druppie", "-d", "druppie", "-t", "-c",
                           "SELECT count(*) FROM agent_runs WHERE status = 'running';"])
    running = 0
    for line in running_raw.split("\n"):
        line = line.strip()
        if line.isdigit():
            running = int(line)
            break

    return MetricSnapshot(
        timestamp=time.time(),
        backend_pods=backend_pods,
        backend_ready=backend_ready,
        app_nodes=app_nodes,
        backend_cpu_m=backend_cpu_m,
        backend_mem_mi=backend_mem_mi,
        db_cpu_m=db_cpu_m,
        db_mem_mi=db_mem_mi,
        db_connections=db_connections,
        running_agent_runs=running,
    )


async def metrics_collector(test_data: TestData, stop_event: asyncio.Event):
    while not stop_event.is_set():
        snap = collect_metrics()
        test_data.metrics.append(snap)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


async def hit_endpoint(client: httpx.AsyncClient, base_url: str, path: str, token: str, method: str, stage: str) -> RequestResult:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    t0 = time.monotonic()
    try:
        r = await client.request(method, f"{base_url}{path}", headers=headers, timeout=30)
        ms = (time.monotonic() - t0) * 1000
        return RequestResult(endpoint=path, method=method, status=r.status_code, latency_ms=ms, timestamp=time.time(), stage=stage)
    except Exception as exc:
        ms = (time.monotonic() - t0) * 1000
        return RequestResult(endpoint=path, method=method, status=0, latency_ms=ms, timestamp=time.time(), stage=stage)


async def run_stage(client: httpx.AsyncClient, base_url: str, auth_url: str,
                    username: str, password: str, rate: int, duration: int,
                    stage_name: str, test_data: TestData) -> None:
    token = get_token(base_url, auth_url, username, password)
    endpoints = [(ep, "GET", auth) for ep, auth in READ_ENDPOINTS]
    interval = 1.0 / rate
    end_time = time.monotonic() + duration
    tasks: list[asyncio.Task] = []

    idx = 0
    while time.monotonic() < end_time:
        path, method, needs_auth = endpoints[idx % len(endpoints)]
        ep_token = token if needs_auth else ""
        tasks.append(asyncio.create_task(
            hit_endpoint(client, base_url, path, ep_token, method, stage_name)
        ))
        idx += 1
        await asyncio.sleep(interval)

    results = await asyncio.gather(*tasks)
    test_data.requests.extend(results)

    ok = sum(1 for r in results if 200 <= r.status < 300)
    lats = sorted(r.latency_ms for r in results if 200 <= r.status < 300)
    p50 = lats[len(lats)//2] if lats else 0
    p95 = lats[int(len(lats)*0.95)] if lats else 0
    print(f"  {stage_name}: {len(results)} reqs | ok={ok} | p50={p50:.0f}ms p95={p95:.0f}ms")


def percentile(data: list[float], pct: int) -> float:
    if not data:
        return 0
    s = sorted(data)
    idx = min(int(len(s) * pct / 100), len(s) - 1)
    return s[idx]


def generate_charts(test_data: TestData, output_dir: Path, domain: str):
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    reqs = test_data.requests
    metrics = test_data.metrics
    start = test_data.start_time

    # ---- Chart 1: Response Time by Endpoint ----
    fig, ax = plt.subplots(figsize=(14, 6))
    ep_stats = defaultdict(lambda: {"p50": [], "p95": [], "p99": []})
    for r in reqs:
        if 200 <= r.status < 300:
            ep_stats[r.endpoint]["p50"].append(r.latency_ms)
    labels = []
    p50s, p95s, p99s = [], [], []
    for ep in READ_ENDPOINTS:
        path = ep[0]
        lats = ep_stats.get(path, {}).get("p50", [])
        if lats:
            labels.append(path.replace("/api/", "").replace("/health", "/health")[:25])
            p50s.append(percentile(lats, 50))
            p95s.append(percentile(lats, 95))
            p99s.append(percentile(lats, 99))
    x = np.arange(len(labels))
    w = 0.25
    ax.bar(x - w, p50s, w, label="p50", color="#2196F3", alpha=0.85)
    ax.bar(x, p95s, w, label="p95", color="#FF9800", alpha=0.85)
    ax.bar(x + w, p99s, w, label="p99", color="#F44336", alpha=0.85)
    ax.set_ylabel("Latency (ms)", fontsize=12)
    ax.set_title(f"API Response Time by Endpoint — {domain}", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
    ax.legend(fontsize=11)
    ax.axhline(y=100, color="green", linestyle="--", alpha=0.5, label="100ms target")
    ax.axhline(y=500, color="orange", linestyle="--", alpha=0.5)
    ax.annotate("100ms (good)", xy=(0.5, 110), fontsize=8, color="green", alpha=0.7)
    ax.annotate("500ms (acceptable)", xy=(0.5, 510), fontsize=8, color="orange", alpha=0.7)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / f"response_time_by_endpoint_{ts}.png", dpi=150)
    plt.close()
    print(f"  Chart 1: response_time_by_endpoint_{ts}.png")

    # ---- Chart 2: Latency Over Time ----
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [2, 1]})
    time_buckets = defaultdict(list)
    for r in reqs:
        if 200 <= r.status < 300:
            bucket = int(r.timestamp - start) // 5
            time_buckets[bucket].append(r.latency_ms)
    buckets = sorted(time_buckets.keys())
    times = [(b * 5) for b in buckets]
    p50_vals = [percentile(time_buckets[b], 50) for b in buckets]
    p95_vals = [percentile(time_buckets[b], 95) for b in buckets]
    p99_vals = [percentile(time_buckets[b], 99) for b in buckets]
    req_counts = [len(time_buckets[b]) for b in buckets]

    ax1.plot(times, p50_vals, color="#2196F3", linewidth=2, label="p50")
    ax1.plot(times, p95_vals, color="#FF9800", linewidth=2, label="p95")
    ax1.plot(times, p99_vals, color="#F44336", linewidth=1.5, label="p99", alpha=0.7)
    ax1.axhline(y=100, color="green", linestyle="--", alpha=0.4)
    ax1.axhline(y=500, color="orange", linestyle="--", alpha=0.4)
    ax1.fill_between(times, p50_vals, p95_vals, alpha=0.1, color="#FF9800")
    ax1.set_ylabel("Latency (ms)", fontsize=12)
    ax1.set_title(f"Response Latency Over Time — {domain}", fontsize=14, fontweight="bold")
    ax1.legend(fontsize=11)
    ax1.grid(alpha=0.3)

    for i, (rate, dur) in enumerate(RAMP_STAGES):
        stage_start = sum(d for _, d in RAMP_STAGES[:i])
        stage_end = stage_start + dur
        ax1.axvspan(stage_start, stage_end, alpha=0.05, color=f"C{i}")
        mid = (stage_start + stage_end) / 2
        ax1.text(mid, ax1.get_ylim()[1] * 0.95, f"{rate}rps", ha="center", fontsize=7, alpha=0.6)

    ax2.bar(times, req_counts, width=3, color="#4CAF50", alpha=0.7)
    ax2.set_xlabel("Time (seconds)", fontsize=12)
    ax2.set_ylabel("Requests / 5s", fontsize=12)
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / f"latency_over_time_{ts}.png", dpi=150)
    plt.close()
    print(f"  Chart 2: latency_over_time_{ts}.png")

    # ---- Chart 3: Scaling Timeline ----
    fig, ax1 = plt.subplots(figsize=(14, 5))
    if metrics:
        m_times = [m.timestamp - start for m in metrics]
        pods = [m.backend_pods for m in metrics]
        ready = [m.backend_ready for m in metrics]
        nodes = [m.app_nodes for m in metrics]

        ax1.step(m_times, pods, where="post", color="#2196F3", linewidth=2.5, label="Backend pods", marker="o", markersize=4)
        ax1.step(m_times, ready, where="post", color="#4CAF50", linewidth=2, label="Ready pods", marker="s", markersize=4, alpha=0.7)
        ax1.fill_between(m_times, pods, alpha=0.1, color="#2196F3", step="post")

        ax2 = ax1.twinx()
        ax2.step(m_times, nodes, where="post", color="#FF5722", linewidth=2.5, label="App nodes", marker="D", markersize=5)
        ax2.set_ylabel("App Nodes", fontsize=12, color="#FF5722")
        ax2.set_ylim(0, max(nodes) + 2 if nodes else 3)
        ax2.tick_params(axis="y", labelcolor="#FF5722")

        ax1.set_xlabel("Time (seconds)", fontsize=12)
        ax1.set_ylabel("Backend Pods", fontsize=12, color="#2196F3")
        ax1.set_title(f"Autoscaling Timeline — Pods & Nodes — {domain}", fontsize=14, fontweight="bold")
        ax1.set_ylim(0, max(pods) + 2 if pods else 5)
        ax1.grid(alpha=0.3)

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=11)

        for i, (rate, dur) in enumerate(RAMP_STAGES):
            stage_start = sum(d for _, d in RAMP_STAGES[:i])
            ax1.axvline(x=stage_start, color="gray", linestyle=":", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / f"scaling_timeline_{ts}.png", dpi=150)
    plt.close()
    print(f"  Chart 3: scaling_timeline_{ts}.png")

    # ---- Chart 4: Throughput vs Latency ----
    fig, ax = plt.subplots(figsize=(10, 6))
    stage_p95 = defaultdict(list)
    for r in reqs:
        if 200 <= r.status < 300:
            stage_p95[r.stage].append(r.latency_ms)
    stage_rates = {}
    for i, (rate, dur) in enumerate(RAMP_STAGES):
        sname = f"stage-{i+1}"
        stage_rates[sname] = rate
    for stage, lats in stage_p95.items():
        rate = stage_rates.get(stage, 0)
        if rate > 0 and lats:
            ax.scatter(rate, percentile(lats, 95), s=150, zorder=5, edgecolors="black", linewidth=0.5)
            ax.annotate(f"p50={percentile(lats, 50):.0f}ms", (rate, percentile(lats, 95)),
                        textcoords="offset points", xytext=(10, 5), fontsize=9)
    ax.set_xlabel("Requests / second", fontsize=12)
    ax.set_ylabel("p95 Latency (ms)", fontsize=12)
    ax.set_title(f"Throughput vs Latency — {domain}", fontsize=14, fontweight="bold")
    ax.axhline(y=100, color="green", linestyle="--", alpha=0.4, label="100ms target")
    ax.axhline(y=500, color="orange", linestyle="--", alpha=0.4, label="500ms acceptable")
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / f"throughput_vs_latency_{ts}.png", dpi=150)
    plt.close()
    print(f"  Chart 4: throughput_vs_latency_{ts}.png")

    # ---- Chart 5: Resource Usage ----
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
    if metrics:
        m_times = [m.timestamp - start for m in metrics]
        be_cpu = [m.backend_cpu_m for m in metrics]
        be_mem = [m.backend_mem_mi for m in metrics]
        db_cpu = [m.db_cpu_m for m in metrics]
        db_mem = [m.db_mem_mi for m in metrics]
        db_conn = [m.db_connections for m in metrics]

        ax1.plot(m_times, [c / 1000 for c in be_cpu], color="#2196F3", linewidth=2, label="Backend CPU (cores)")
        ax1.plot(m_times, [c / 1000 for c in db_cpu], color="#FF9800", linewidth=2, label="DB CPU (cores)")
        ax1a = ax1.twinx()
        ax1a.plot(m_times, [m / 1024 for m in be_mem], color="#2196F3", linewidth=1.5, alpha=0.5, linestyle="--", label="Backend Mem (Gi)")
        ax1a.plot(m_times, [m / 1024 for m in db_mem], color="#FF9800", linewidth=1.5, alpha=0.5, linestyle="--", label="DB Mem (Gi)")
        ax1.set_ylabel("CPU (cores)", fontsize=12)
        ax1a.set_ylabel("Memory (Gi)", fontsize=12)
        ax1.set_title("CPU & Memory Usage", fontsize=14, fontweight="bold")
        ax1.grid(alpha=0.3)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax1a.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

        ax2.plot(m_times, db_conn, color="#9C27B0", linewidth=2.5, marker="o", markersize=3, label="Active DB connections")
        ax2.fill_between(m_times, db_conn, alpha=0.1, color="#9C27B0")
        ax2.set_xlabel("Time (seconds)", fontsize=12)
        ax2.set_ylabel("Active DB Connections", fontsize=12, color="#9C27B0")
        ax2.tick_params(axis="y", labelcolor="#9C27B0")
        ax2.set_title("Database Active Connections (non-idle)", fontsize=12)
        ax2.grid(alpha=0.3)
        ax2.legend(fontsize=11)
    plt.tight_layout()
    plt.savefig(output_dir / f"resource_usage_{ts}.png", dpi=150)
    plt.close()
    print(f"  Chart 5: resource_usage_{ts}.png")

    return ts


async def main():
    parser = argparse.ArgumentParser(description="Scalability proof test with charts")
    parser.add_argument("--domain", default="druppie.rijnland.dev")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin123!")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    base_url = f"https://{args.domain}"
    auth_url = f"https://auth.{args.domain}"
    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "results"

    import urllib3
    urllib3.disable_warnings()

    total_duration = sum(d for _, d in RAMP_STAGES)
    print("=" * 60)
    print("  SCALABILITY PROOF TEST")
    print(f"  Target: {args.domain}")
    print(f"  Stages: {len(RAMP_STAGES)} | Duration: ~{total_duration}s | Max: {max(r for r,_ in RAMP_STAGES)} rps")
    print(f"  Endpoints: {len(READ_ENDPOINTS)} GET endpoints (round-robin)")
    print(f"  Charts: {output_dir}/")
    print("=" * 60)

    test_data = TestData(start_time=time.time())
    stop_event = asyncio.Event()
    metrics_task = asyncio.create_task(metrics_collector(test_data, stop_event))

    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        print("\nAcquiring token...")
        token = get_token(base_url, auth_url, args.username, args.password)
        print("Token acquired.\n")

        print("--- Progressive Load Test ---")
        for i, (rate, duration) in enumerate(RAMP_STAGES, 1):
            stage_name = f"stage-{i}"
            print(f"\nStage {i}/{len(RAMP_STAGES)}: {rate} rps × {duration}s")
            await run_stage(client, base_url, auth_url, args.username, args.password,
                           rate, duration, stage_name, test_data)
            if i < len(RAMP_STAGES):
                await asyncio.sleep(5)

    stop_event.set()
    await metrics_task

    print("\n" + "=" * 60)
    print("  GENERATING CHARTS")
    print("=" * 60)
    ts = generate_charts(test_data, output_dir, args.domain)

    # Summary stats
    all_lats = [r.latency_ms for r in test_data.requests if 200 <= r.status < 300]
    all_reqs = len(test_data.requests)
    ok_reqs = sum(1 for r in test_data.requests if 200 <= r.status < 300)
    max_pods = max((m.backend_pods for m in test_data.metrics), default=0)
    max_nodes = max((m.app_nodes for m in test_data.metrics), default=0)
    max_db_conn = max((m.db_connections for m in test_data.metrics), default=0)

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Total requests:     {all_reqs}")
    print(f"  Successful (2xx):   {ok_reqs} ({ok_reqs/all_reqs*100:.1f}%)")
    print(f"  p50 latency:        {percentile(all_lats, 50):.0f}ms")
    print(f"  p95 latency:        {percentile(all_lats, 95):.0f}ms")
    print(f"  p99 latency:        {percentile(all_lats, 99):.0f}ms")
    print(f"  Max latency:        {max(all_lats):.0f}ms")
    print(f"  Peak backend pods:  {max_pods}")
    print(f"  Peak app nodes:     {max_nodes}")
    print(f"  Peak DB conns:      {max_db_conn}")
    print(f"  Charts saved to:    {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
