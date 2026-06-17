#!/usr/bin/env python3
"""
Autoscaling ramp test — realistic user flow.

For each virtual user:
  1. POST /api/chat  (create session + start agent)
  2. GET  /api/sessions/{id}  (poll until completed or timeout)

Measures end-to-end latency at each concurrency level and writes CSV.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx

STAGES = [
    (10, 30),
    (25, 30),
    (50, 45),
    (100, 60),
    (250, 90),
    (500, 120),
]

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results", "autoscaling")
KUBECONFIG = os.environ.get("KUBECONFIG", os.path.join(os.path.dirname(__file__), "..", "..", "kubeconfig"))


def get_token(client: httpx.Client, auth_url: str, username: str, password: str) -> str:
    r = client.post(
        f"{auth_url}/realms/druppie/protocol/openid-connect/token",
        data={
            "client_id": "druppie-frontend",
            "username": username,
            "password": password,
            "grant_type": "password",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_hpa_state() -> tuple[str, str]:
    try:
        out = subprocess.run(
            ["kubectl", "get", "hpa", "druppie-backend", "-n", "druppie", "-o", "json"],
            capture_output=True, text=True, env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        d = json.loads(out.stdout)
        replicas = d.get("status", {}).get("currentReplicas", "?")
        metrics = d.get("status", {}).get("currentMetrics", [{}])
        cpu = metrics[0].get("resource", {}).get("current", {}).get("averageUtilization", "?")
        return str(replicas), str(cpu)
    except Exception:
        return "?", "?"


def get_node_count() -> int:
    try:
        out = subprocess.run(
            ["kubectl", "get", "nodes", "-l", "pool=app", "--no-headers"],
            capture_output=True, text=True, env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        return len([l for l in out.stdout.strip().split("\n") if l.strip()])
    except Exception:
        return 0


def user_flow(
    client: httpx.Client, base_url: str, token: str, poll_timeout: int = 120
) -> dict:
    """Simulate one user: POST a chat message, then poll the session."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    result = {
        "post_status": None,
        "post_latency_ms": None,
        "session_id": None,
        "poll_count": 0,
        "poll_total_ms": None,
        "final_status": None,
        "error": None,
    }

    # Step 1: POST /api/chat
    t0 = time.monotonic()
    try:
        r = client.post(
            f"{base_url}/api/chat",
            json={"message": "load test — please describe a simple todo app"},
            headers=headers,
            timeout=30,
        )
        result["post_latency_ms"] = (time.monotonic() - t0) * 1000
        result["post_status"] = r.status_code
        body = r.json()
        result["session_id"] = body.get("session_id", "")
        if not body.get("success"):
            result["error"] = body.get("message", "unknown")
            return result
    except Exception as e:
        result["post_latency_ms"] = (time.monotonic() - t0) * 1000
        result["error"] = str(e)
        return result

    if not result["session_id"]:
        result["error"] = "no session_id returned"
        return result

    # Step 2: GET /api/sessions/{id} — poll until completed or timeout
    sid = result["session_id"]
    poll_start = time.monotonic()
    while time.monotonic() - poll_start < poll_timeout:
        result["poll_count"] += 1
        try:
            r = client.get(
                f"{base_url}/api/sessions/{sid}",
                headers=headers,
                timeout=15,
            )
            if r.status_code == 200:
                session = r.json()
                status = session.get("status", "")
                result["final_status"] = status
                if status in ("completed", "failed", "paused", "cancelled"):
                    break
        except Exception:
            pass
        time.sleep(2)

    result["poll_total_ms"] = (time.monotonic() - poll_start) * 1000
    return result


def run_stage(
    stage_num: int,
    concurrency: int,
    duration: int,
    client: httpx.Client,
    base_url: str,
    auth_url: str,
    username: str,
    password: str,
) -> list[dict]:
    print(f"\n{'═'*55}")
    print(f"  Stage {stage_num}: {concurrency} users × up to {duration}s")
    print(f"{'═'*55}")

    # Refresh token
    token = get_token(client, auth_url, username, password)

    results = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(user_flow, client, base_url, token): i
            for i in range(concurrency)
        }
        for future in as_completed(futures, timeout=duration + 30):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"error": str(e), "post_status": 0, "post_latency_ms": 0})

    elapsed = time.monotonic() - t0
    return results, elapsed


def summarize(results: list[dict], elapsed: float) -> dict:
    total = len(results)
    post_ok = [r for r in results if r["post_status"] == 200 and not r.get("error")]
    post_fail = total - len(post_ok)
    latencies = [r["post_latency_ms"] for r in post_ok if r["post_latency_ms"]]
    latencies.sort()
    polls = [r["poll_count"] for r in results if r.get("poll_count")]

    def pct(arr, p):
        if not arr:
            return 0
        idx = int(len(arr) * p / 100)
        return arr[min(idx, len(arr) - 1)]

    return {
        "total": total,
        "post_ok": len(post_ok),
        "post_fail": post_fail,
        "rps": round(total / max(elapsed, 0.1), 1),
        "lat_avg": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "lat_p50": round(pct(latencies, 50), 1),
        "lat_p95": round(pct(latencies, 95), 1),
        "lat_p99": round(pct(latencies, 99), 1),
        "lat_max": round(max(latencies), 1) if latencies else 0,
        "poll_avg": round(sum(polls) / len(polls), 1) if polls else 0,
        "elapsed_s": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Druppie autoscaling ramp test")
    parser.add_argument("--domain", default="druppie.rijnland.dev")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin123!")
    parser.add_argument("--max-stage", type=int, default=len(STAGES), help="Stop after N stages")
    args = parser.parse_args()

    base_url = f"https://{args.domain}"
    auth_url = f"https://auth.{args.domain}"

    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    csv_path = os.path.join(RESULTS_DIR, f"ramp-{ts}.csv")

    print("╔══════════════════════════════════════════════════╗")
    print("║   Druppie Autoscaling Ramp Test                 ║")
    print(f"║   Target: {args.domain:<38s}║")
    print(f"║   CSV:    ramp-{ts}.csv    ")
    print("╚══════════════════════════════════════════════════╝")

    replicas, cpu = get_hpa_state()
    print(f"\nBaseline: {replicas} replicas, {cpu}% CPU, {get_node_count()} app nodes")

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "stage", "concurrency", "total_reqs", "post_ok", "post_fail",
            "rps", "lat_avg_ms", "lat_p50_ms", "lat_p95_ms", "lat_p99_ms", "lat_max_ms",
            "poll_avg_count", "elapsed_s", "backend_replicas", "backend_cpu_pct", "app_nodes",
        ])

    with httpx.Client(timeout=60, verify=False) as client:
        import urllib3
        urllib3.disable_warnings()

        for i, (concurrency, duration) in enumerate(STAGES[:args.max_stage], 1):
            results, elapsed = run_stage(
                i, concurrency, duration, client, base_url, auth_url,
                args.username, args.password,
            )
            s = summarize(results, elapsed)
            replicas, cpu = get_hpa_state()
            nodes = get_node_count()

            print(f"  POST  → ok: {s['post_ok']} | fail: {s['post_fail']} | RPS: {s['rps']}")
            print(f"  Latency → avg: {s['lat_avg']:.0f}ms | p50: {s['lat_p50']:.0f}ms | p95: {s['lat_p95']:.0f}ms | p99: {s['lat_p99']:.0f}ms")
            print(f"  Polls  → avg: {s['poll_avg']} GETs per session")
            print(f"  HPA   → replicas: {replicas} | CPU: {cpu}% | app nodes: {nodes}")

            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    i, concurrency, s["total"], s["post_ok"], s["post_fail"],
                    s["rps"], s["lat_avg"], s["lat_p50"], s["lat_p95"], s["lat_p99"],
                    s["lat_max"], s["poll_avg"], s["elapsed_s"],
                    replicas, cpu, nodes,
                ])

            time.sleep(10)

    print(f"\n{'═'*55}")
    print("  Done. Final state:")
    replicas, cpu = get_hpa_state()
    print(f"  Replicas: {replicas} | CPU: {cpu}% | Nodes: {get_node_count()}")
    print(f"  CSV: {csv_path}")
    print(f"  Watch scale-down: KUBECONFIG=./kubeconfig kubectl get hpa -n druppie -w")
    print(f"{'═'*55}")


if __name__ == "__main__":
    main()
