#!/usr/bin/env python3
"""
KEDA e2e ramp test — sustained submission rate to trigger KEDA → HPA → CA chain.

Submits chat sessions at increasing rates. Each session creates an agent_run that
stays in 'running' status for ~30 seconds (mock LLM delay). KEDA queries
agent_runs WHERE status = 'running' every 15 seconds, sees the count growing,
and scales up backend pods. Cluster Autoscaler provisions new nodes for the pods.

Usage:
    python testing/autoscaling/test-keda-ramp.py
    python testing/autoscaling/test-keda-ramp.py --max-rate 100 --max-target 1500
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx

KUBECONFIG = os.environ.get("KUBECONFIG", os.path.join(os.path.dirname(__file__), "..", "..", "kubeconfig"))

RAMP_STAGES = [
    (10, 60),    (20, 60),    (50, 90),
    (75, 90),    (100, 90),   (150, 120),
]


def kubectl_json(args: list[str]) -> dict | None:
    try:
        out = subprocess.run(
            ["kubectl"] + args + ["-o", "json"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        return json.loads(out.stdout)
    except Exception:
        return None


def get_cluster_state() -> dict:
    state = {"running_agent_runs": "?", "backend_replicas": "?", "app_nodes": "?", "keda_metric": "?"}

    # Running agent_runs from DB
    try:
        out = subprocess.run(
            ["kubectl", "exec", "-n", "druppie", "druppie-druppie-db-0", "--",
             "psql", "-U", "druppie", "-d", "druppie", "-t", "-c",
             "SELECT COUNT(*) FROM agent_runs WHERE status = 'running';"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        count = out.stdout.strip().split("\n")[-1].strip()
        state["running_agent_runs"] = int(count) if count.isdigit() else 0
    except Exception:
        pass

    # KEDA HPA
    hpa = kubectl_json(["get", "hpa", "keda-hpa-druppie-backend", "-n", "druppie"])
    if hpa:
        state["backend_replicas"] = hpa.get("status", {}).get("currentReplicas", "?")
        metrics = hpa.get("status", {}).get("currentMetrics", [])
        if metrics:
            val = metrics[0].get("external", {}).get("current", {}).get("averageValue", "?")
            state["keda_metric"] = val

    # App nodes
    try:
        out = subprocess.run(
            ["kubectl", "get", "nodes", "-l", "pool=app", "--no-headers"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "KUBECONFIG": KUBECONFIG},
        )
        state["app_nodes"] = len([l for l in out.stdout.strip().split("\n") if "Ready" in l])
    except Exception:
        pass

    return state


def print_state(state: dict, prefix: str = ""):
    print(f"  {prefix}running={state['running_agent_runs']:>5} | "
          f"replicas={state['backend_replicas']:>3} | "
          f"nodes={state['app_nodes']:>2} | "
          f"keda_metric={state['keda_metric']}")


async def submit_session(client: httpx.AsyncClient, base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{base_url}/api/chat",
            json={"message": "load test — describe a simple todo app"},
            headers=headers,
            timeout=30,
        )
        elapsed = (time.monotonic() - t0) * 1000
        body = r.json()
        return {
            "status": r.status_code,
            "latency_ms": elapsed,
            "session_id": body.get("session_id", ""),
            "success": body.get("success", False),
            "error": body.get("message") if not body.get("success") else None,
        }
    except Exception as e:
        return {"status": 0, "latency_ms": (time.monotonic() - t0) * 1000, "error": str(e)}


async def get_token(client: httpx.AsyncClient, auth_url: str, username: str, password: str) -> str:
    r = await client.post(
        f"{auth_url}/realms/druppie/protocol/openid-connect/token",
        data={"client_id": "druppie-frontend", "username": username, "password": password, "grant_type": "password"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def run_stage(client: httpx.AsyncClient, base_url: str, auth_url: str,
                    username: str, password: str, rate: int, duration: int) -> list[dict]:
    token = await get_token(client, auth_url, username, password)
    results = []
    interval = 1.0 / rate

    async def bounded_submit(sem):
        async with sem:
            return await submit_session(client, base_url, token)

    sem = asyncio.Semaphore(rate * 5)
    tasks = []
    end_time = time.monotonic() + duration
    submitted = 0

    while time.monotonic() < end_time:
        tasks.append(asyncio.create_task(bounded_submit(sem)))
        submitted += 1
        if submitted % 50 == 0:
            state = get_cluster_state()
            print_state(state, prefix=f"[{submitted} submitted] ")
        await asyncio.sleep(interval)

    print(f"  Submitted {submitted} sessions, waiting for responses...")
    for coro in asyncio.as_completed(tasks):
        try:
            result = await asyncio.wait_for(coro, timeout=30)
            results.append(result)
        except Exception:
            results.append({"status": 0, "error": "timeout"})

    return results


def summarize(results: list[dict]) -> str:
    total = len(results)
    ok = sum(1 for r in results if r.get("status") == 200 and r.get("success"))
    fail = total - ok
    lats = sorted([r["latency_ms"] for r in results if r.get("latency_ms") and r["status"] == 200])
    p50 = lats[len(lats) // 2] if lats else 0
    p95 = lats[int(len(lats) * 0.95)] if lats else 0
    return f"ok={ok} fail={fail} p50={p50:.0f}ms p95={p95:.0f}ms"


async def main():
    parser = argparse.ArgumentParser(description="KEDA e2e ramp test")
    parser.add_argument("--domain", default="druppie.rijnland.dev")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin123!")
    parser.add_argument("--max-rate", type=int, default=0, help="Override max submission rate (sessions/sec)")
    parser.add_argument("--max-target", type=int, default=1500, help="Target peak concurrent running sessions")
    args = parser.parse_args()

    base_url = f"https://{args.domain}"
    auth_url = f"https://auth.{args.domain}"

    stages = RAMP_STAGES
    if args.max_rate:
        stages = [(args.max_rate, 120)]

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   KEDA E2E Ramp Test — Session-Based Autoscaling           ║")
    print(f"║   Target: {args.domain:<48s}║")
    print(f"║   Mock delay: 25-35s | KEDA poll: 15s | Target: {args.max_target:<12}║")
    print("╚══════════════════════════════════════════════════════════════╝")

    state = get_cluster_state()
    print("\nBaseline:")
    print_state(state, prefix="  ")

    import urllib3
    urllib3.disable_warnings()

    async with httpx.AsyncClient(timeout=60, verify=False) as client:
        for i, (rate, duration) in enumerate(stages, 1):
            print(f"\n{'═'*60}")
            print(f"  Stage {i}/{len(stages)}: {rate} sessions/sec × {duration}s")
            print(f"  Expected steady-state running: ~{rate * 30} agent_runs")
            print(f"{'═'*60}")

            results = await run_stage(client, base_url, auth_url,
                                       args.username, args.password, rate, duration)

            state = get_cluster_state()
            print(f"\n  Results: {summarize(results)}")
            print_state(state, prefix="POST-STAGE: ")

            if i < len(stages):
                print("  Cooldown 15s...")
                await asyncio.sleep(15)

    print(f"\n{'═'*60}")
    print("  Ramp complete. Watching scale-down...")
    print(f"{'═'*60}")

    for tick in range(12):
        await asyncio.sleep(30)
        state = get_cluster_state()
        elapsed = (tick + 1) * 30
        print_state(state, prefix=f"[{elapsed:3d}s] ")
        if state["backend_replicas"] == "?" or (isinstance(state["backend_replicas"], int) and state["backend_replicas"] <= 1):
            if isinstance(state["app_nodes"], int) and state["app_nodes"] <= 1:
                print("  Scaled back to baseline.")
                break

    state = get_cluster_state()
    print(f"\n  Final: replicas={state['backend_replicas']} | nodes={state['app_nodes']}")


if __name__ == "__main__":
    asyncio.run(main())
