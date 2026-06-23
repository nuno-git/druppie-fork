#!/usr/bin/env python3
"""
KEDA comprehensive load test — progressive load with Prometheus metrics,
API endpoint benchmarks, scaling event detection, and rich report generation.

Architecture:
  1. Port-forward Prometheus in a background thread
  2. Start a metrics collector thread (Prometheus + kubectl every 15s)
  3. Run API endpoint benchmarks BEFORE load (baseline)
  4. Run progressive load test (chat sessions)
  5. Run API endpoint benchmarks DURING load
  6. Run API endpoint benchmarks AFTER load
  7. Watch scale-down
  8. Produce final report + CSV

Usage:
    python testing/autoscaling/test-keda-comprehensive.py
    python testing/autoscaling/test-keda-comprehensive.py --domain druppie.example.com
    python testing/autoscaling/test-keda-comprehensive.py --max-rate 50 --output-dir ./results
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KUBECONFIG = os.environ.get(
    "KUBECONFIG",
    os.path.join(os.path.dirname(__file__), "..", "..", "kubeconfig"),
)

PROMETHEUS_NAMESPACE = "monitoring"
PROMETHEUS_SERVICE = "monitoring-kube-prometheus-prometheus"
PROMETHEUS_PORT = 9090
METRICS_INTERVAL = 15  # seconds between metric snapshots

RAMP_STAGES = [
    (5, 90),    # 5 sessions/sec for 90s   — warmup, 1→2 pods
    (10, 90),   # 10 sessions/sec for 90s  — moderate, 2→3 pods
    (15, 120),  # 15 sessions/sec for 120s — heavier, 3→5 pods
    (20, 120),  # 20 sessions/sec for 120s — peak, 5→7 pods, 2nd node
    (25, 120),  # 25 sessions/sec for 120s — max sustained, 7→8 pods
]

API_ENDPOINTS = [
    ("GET", "/health", False),
    ("GET", "/api/sessions", True),
    ("GET", "/api/projects", True),
    ("GET", "/api/agents", True),
    ("GET", "/api/mcps", True),
    ("GET", "/api/modules", True),
    ("GET", "/api/approvals", True),
    ("GET", "/api/workspace/files", True),
    ("GET", "/api/deployments", True),
    ("GET", "/api/documentation", True),
]

ENDPOINT_HITS = 10  # number of requests per endpoint per benchmark phase

METRIC_QUERIES = {
    "backend_cpu_millicores": (
        'sum(rate(container_cpu_usage_seconds_total'
        '{namespace="druppie",container="backend"}[1m])) * 1000'
    ),
    "backend_memory_mb": (
        'sum(container_memory_working_set_bytes'
        '{namespace="druppie",container="backend"}) / 1024 / 1024'
    ),
    "backend_replicas": (
        'kube_deployment_status_replicas'
        '{namespace="druppie",deployment="druppie-backend"}'
    ),
    "frontend_replicas": (
        'kube_deployment_status_replicas'
        '{namespace="druppie",deployment="druppie-frontend"}'
    ),
    "app_nodes": 'count(kube_node_info{pool="app"})',
    "keda_metric_value": (
        'kube_horizontalpodautoscaler_status_target_metric'
        '{namespace="druppie",hpa="keda-hpa-druppie-backend"}'
    ),
    "node_cpu_percent": 'instance:node_cpu:ratio',
    "node_memory_percent": 'instance:node_memory_utilisation:ratio',
    "hpa_desired_replicas": (
        'kube_horizontalpodautoscaler_status_desired_replicas'
        '{namespace="druppie",hpa="keda-hpa-druppie-backend"}'
    ),
    "hpa_min_replicas": (
        'kube_horizontalpodautoscaler_spec_min_replicas'
        '{namespace="druppie",hpa="keda-hpa-druppie-backend"}'
    ),
    "hpa_max_replicas": (
        'kube_horizontalpodautoscaler_spec_max_replicas'
        '{namespace="druppie",hpa="keda-hpa-druppie-backend"}'
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("keda-test")


# ---------------------------------------------------------------------------
# Kubectl helpers
# ---------------------------------------------------------------------------

def _kubectl_env() -> dict[str, str]:
    return {**os.environ, "KUBECONFIG": KUBECONFIG}


def kubectl_json(args: list[str]) -> dict | None:
    """Run kubectl with -o json and return parsed output."""
    try:
        out = subprocess.run(
            ["kubectl"] + args + ["-o", "json"],
            capture_output=True, text=True, timeout=10,
            env=_kubectl_env(),
        )
        return json.loads(out.stdout)
    except Exception as exc:
        log.debug("kubectl %s failed: %s", " ".join(args), exc)
        return None


def kubectl_output(args: list[str]) -> str:
    """Run kubectl and return raw stdout."""
    try:
        out = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=10,
            env=_kubectl_env(),
        )
        return out.stdout
    except Exception as exc:
        log.debug("kubectl %s failed: %s", " ".join(args), exc)
        return ""


def get_running_agent_runs() -> int:
    """Count agent_runs with status='running' from the database pod."""
    try:
        out = subprocess.run(
            [
                "kubectl", "exec", "-n", "druppie",
                "druppie-druppie-db-0", "--",
                "psql", "-U", "druppie", "-d", "druppie", "-t", "-c",
                "SELECT COUNT(*) FROM agent_runs WHERE status = 'running';",
            ],
            capture_output=True, text=True, timeout=10,
            env=_kubectl_env(),
        )
        line = out.stdout.strip().split("\n")[-1].strip()
        return int(line) if line.isdigit() else 0
    except Exception:
        return -1


def get_keda_active() -> bool | None:
    """Check if KEDA ScaledObject is active."""
    out = kubectl_output([
        "get", "scaledobject", "-n", "druppie",
        "-o", "jsonpath={.items[0].status.conditions[0].status}",
    ])
    if out.strip().lower() == "true":
        return True
    if out.strip().lower() == "false":
        return False
    return None


def get_pod_top() -> str:
    """Get kubectl top pods output for druppie namespace."""
    return kubectl_output(["top", "pods", "-n", "druppie"])


# ---------------------------------------------------------------------------
# Prometheus port-forward
# ---------------------------------------------------------------------------

class PrometheusPortForward:
    """Manages a kubectl port-forward to Prometheus in a background process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self.ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait up to 10s for port-forward to be ready
        self.ready.wait(timeout=10)

    def _run(self) -> None:
        try:
            self._process = subprocess.Popen(
                [
                    "kubectl", "port-forward",
                    f"svc/{PROMETHEUS_SERVICE}",
                    f"-n", PROMETHEUS_NAMESPACE,
                    f"{PROMETHEUS_PORT}:{PROMETHEUS_PORT}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_kubectl_env(),
            )
            # Give it a moment to establish
            time.sleep(3)
            self.ready.set()
            self._process.wait()
        except Exception as exc:
            log.warning("Prometheus port-forward failed: %s", exc)
            self.ready.set()  # Unblock caller regardless

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    @property
    def url(self) -> str:
        return f"http://localhost:{PROMETHEUS_PORT}"


# ---------------------------------------------------------------------------
# Prometheus queries
# ---------------------------------------------------------------------------

def query_prometheus(prom_url: str, query: str) -> float | None:
    """Execute an instant PromQL query and return the first value."""
    try:
        r = requests.get(
            f"{prom_url}/api/v1/query",
            params={"query": query},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("data", {}).get("result", [])
        if not results:
            return None
        val = results[0].get("value", [None, None])
        if val and val[1] is not None:
            return float(val[1])
    except Exception as exc:
        log.debug("Prometheus query failed [%s]: %s", query[:60], exc)
    return None


# ---------------------------------------------------------------------------
# Metrics collector (runs in background thread)
# ---------------------------------------------------------------------------

@dataclass
class MetricSnapshot:
    timestamp: float
    phase: str
    sessions_submitted: int
    sessions_completed: int
    running_agent_runs: int
    backend_replicas: float | None
    frontend_replicas: float | None
    app_nodes: float | None
    backend_cpu_millicores: float | None
    backend_memory_mb: float | None
    keda_metric: float | None
    node_cpu_percent: float | None
    node_memory_percent: float | None
    hpa_desired: float | None
    hpa_min: float | None
    hpa_max: float | None
    keda_active: bool | None


class MetricsCollector:
    """Background thread that collects metrics every METRICS_INTERVAL seconds."""

    def __init__(self, prom_url: str | None) -> None:
        self._prom_url = prom_url
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.snapshots: list[MetricSnapshot] = []
        self.scale_events: list[dict[str, Any]] = []
        self._sessions_submitted = 0
        self._sessions_completed = 0
        self._phase = "init"
        self._lock = threading.Lock()
        self._prev_replicas: float | None = None
        self._prev_nodes: float | None = None
        self._prev_keda_active: bool | None = None

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    def add_submitted(self, count: int = 1) -> None:
        with self._lock:
            self._sessions_submitted += count

    def add_completed(self, count: int = 1) -> None:
        with self._lock:
            self._sessions_completed += count

    @property
    def current_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self._phase,
                "submitted": self._sessions_submitted,
                "completed": self._sessions_completed,
            }

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._collect()
            self._stop_event.wait(METRICS_INTERVAL)

    def _collect(self) -> None:
        prom_metrics: dict[str, float | None] = {}
        if self._prom_url:
            for name, query in METRIC_QUERIES.items():
                prom_metrics[name] = query_prometheus(self._prom_url, query)
        else:
            for name in METRIC_QUERIES:
                prom_metrics[name] = None

        # kubectl-based metrics as fallback/supplement
        running = get_running_agent_runs()
        keda_active = get_keda_active()
        pod_top = get_pod_top()

        # If prometheus didn't give us replicas, try kubectl
        if prom_metrics.get("backend_replicas") is None:
            hpa = kubectl_json(["get", "hpa", "keda-hpa-druppie-backend", "-n", "druppie"])
            if hpa:
                prom_metrics["backend_replicas"] = float(
                    hpa.get("status", {}).get("currentReplicas", 0) or 0
                )

        if prom_metrics.get("app_nodes") is None:
            out = kubectl_output(["get", "nodes", "-l", "pool=app", "--no-headers"])
            count = len([l for l in out.strip().split("\n") if "Ready" in l])
            prom_metrics["app_nodes"] = float(count) if count > 0 else None

        with self._lock:
            phase = self._phase
            submitted = self._sessions_submitted
            completed = self._sessions_completed

        snap = MetricSnapshot(
            timestamp=time.time(),
            phase=phase,
            sessions_submitted=submitted,
            sessions_completed=completed,
            running_agent_runs=running,
            backend_replicas=prom_metrics.get("backend_replicas"),
            frontend_replicas=prom_metrics.get("frontend_replicas"),
            app_nodes=prom_metrics.get("app_nodes"),
            backend_cpu_millicores=prom_metrics.get("backend_cpu_millicores"),
            backend_memory_mb=prom_metrics.get("backend_memory_mb"),
            keda_metric=prom_metrics.get("keda_metric_value"),
            node_cpu_percent=prom_metrics.get("node_cpu_percent"),
            node_memory_percent=prom_metrics.get("node_memory_percent"),
            hpa_desired=prom_metrics.get("hpa_desired_replicas"),
            hpa_min=prom_metrics.get("hpa_min_replicas"),
            hpa_max=prom_metrics.get("hpa_max_replicas"),
            keda_active=keda_active,
        )
        self.snapshots.append(snap)

        # Detect scaling events
        self._detect_events(snap)

        # Log current state
        self._log_snapshot(snap, pod_top)

    def _detect_events(self, snap: MetricSnapshot) -> None:
        replicas = snap.backend_replicas
        nodes = snap.app_nodes
        keda = snap.keda_active
        elapsed = snap.timestamp - (self.snapshots[0].timestamp if len(self.snapshots) > 1 else snap.timestamp)

        def fmt_time(secs: float) -> str:
            m, s = divmod(int(secs), 60)
            return f"{m:02d}:{s:02d}"

        if replicas is not None and self._prev_replicas is not None and replicas != self._prev_replicas:
            event = {
                "time": snap.timestamp,
                "elapsed": elapsed,
                "type": "scale",
                "message": f"SCALE EVENT: backend {int(self._prev_replicas)} -> {int(replicas)} replicas",
            }
            self.scale_events.append(event)
            log.info("[%s] %s", fmt_time(elapsed), event["message"])

        if nodes is not None and self._prev_nodes is not None and nodes != self._prev_nodes:
            direction = "provisioned" if nodes > self._prev_nodes else "removed"
            event = {
                "time": snap.timestamp,
                "elapsed": elapsed,
                "type": "node",
                "message": f"NODE EVENT: {int(self._prev_nodes)} -> {int(nodes)} app nodes ({direction})",
            }
            self.scale_events.append(event)
            log.info("[%s] %s", fmt_time(elapsed), event["message"])

        if keda is not None and self._prev_keda_active is not None and keda != self._prev_keda_active:
            status = "ACTIVE" if keda else "IDLE"
            event = {
                "time": snap.timestamp,
                "elapsed": elapsed,
                "type": "keda",
                "message": f"KEDA: {status}",
            }
            self.scale_events.append(event)
            log.info("[%s] %s", fmt_time(elapsed), event["message"])

        self._prev_replicas = replicas
        self._prev_nodes = nodes
        self._prev_keda_active = keda

    def _log_snapshot(self, snap: MetricSnapshot, pod_top: str) -> None:
        parts = []
        if snap.running_agent_runs >= 0:
            parts.append(f"running={snap.running_agent_runs}")
        if snap.backend_replicas is not None:
            parts.append(f"replicas={int(snap.backend_replicas)}")
        if snap.app_nodes is not None:
            parts.append(f"nodes={int(snap.app_nodes)}")
        if snap.backend_cpu_millicores is not None:
            parts.append(f"cpu={snap.backend_cpu_millicores:.0f}m")
        if snap.backend_memory_mb is not None:
            parts.append(f"mem={snap.backend_memory_mb:.0f}Mi")
        if snap.keda_metric is not None:
            parts.append(f"keda_metric={snap.keda_metric:.0f}")
        log.info("[metrics] %s", " | ".join(parts))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def get_token(
    client: httpx.AsyncClient, auth_url: str, username: str, password: str,
) -> str:
    """Acquire a Keycloak access token."""
    r = await client.post(
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


# ---------------------------------------------------------------------------
# API endpoint benchmark
# ---------------------------------------------------------------------------

@dataclass
class EndpointResult:
    method: str
    path: str
    status_codes: list[int]
    latencies_ms: list[float]
    errors: list[str]

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p50_ms(self) -> float:
        return _percentile(self.latencies_ms, 50)

    @property
    def p95_ms(self) -> float:
        return _percentile(self.latencies_ms, 95)

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def avg_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def success_rate(self) -> float:
        ok = sum(1 for s in self.status_codes if 200 <= s < 300)
        return (ok / len(self.status_codes) * 100) if self.status_codes else 0.0


def _percentile(sorted_data: list[float], pct: int) -> float:
    if not sorted_data:
        return 0.0
    s = sorted(sorted_data)
    idx = min(int(len(s) * pct / 100), len(s) - 1)
    return s[idx]


async def benchmark_endpoints(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    phase: str,
) -> list[EndpointResult]:
    """Hit each API endpoint ENDPOINT_HITS times and collect latency stats."""
    results: list[EndpointResult] = []
    headers = {"Authorization": f"Bearer {token}"}

    for method, path, needs_auth in API_ENDPOINTS:
        req_headers = headers if needs_auth else {}
        latencies: list[float] = []
        statuses: list[int] = []
        errors: list[str] = []

        for _ in range(ENDPOINT_HITS):
            t0 = time.monotonic()
            try:
                r = await client.request(
                    method, f"{base_url}{path}",
                    headers=req_headers, timeout=30,
                )
                elapsed = (time.monotonic() - t0) * 1000
                latencies.append(elapsed)
                statuses.append(r.status_code)
                if r.status_code >= 400:
                    errors.append(f"HTTP {r.status_code}")
            except Exception as exc:
                elapsed = (time.monotonic() - t0) * 1000
                latencies.append(elapsed)
                statuses.append(0)
                errors.append(str(exc)[:80])

        results.append(EndpointResult(
            method=method, path=path,
            status_codes=statuses,
            latencies_ms=latencies,
            errors=errors,
        ))
        log.debug(
            "[%s] %s %s: p50=%.0fms p95=%.0fms",
            phase, method, path,
            results[-1].p50_ms, results[-1].p95_ms,
        )

    return results


# ---------------------------------------------------------------------------
# Load test session submission
# ---------------------------------------------------------------------------

async def submit_session(
    client: httpx.AsyncClient, base_url: str, token: str,
) -> dict[str, Any]:
    """Submit a single chat session and return result dict."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{base_url}/api/chat",
            json={"message": "load test -- describe a simple todo app"},
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
    except Exception as exc:
        return {
            "status": 0,
            "latency_ms": (time.monotonic() - t0) * 1000,
            "error": str(exc)[:120],
        }


async def run_stage(
    client: httpx.AsyncClient,
    base_url: str,
    auth_url: str,
    username: str,
    password: str,
    rate: int,
    duration: int,
    stage_num: int,
    total_stages: int,
    collector: MetricsCollector,
) -> list[dict[str, Any]]:
    """Run a single ramp stage at the given rate for the given duration."""
    token = await get_token(client, auth_url, username, password)
    results: list[dict[str, Any]] = []
    interval = 1.0 / rate

    sem = asyncio.Semaphore(rate * 5)
    tasks: list[asyncio.Task] = []
    end_time = time.monotonic() + duration
    submitted = 0

    async def bounded_submit() -> dict[str, Any]:
        async with sem:
            return await submit_session(client, base_url, token)

    log.info(
        "Stage %d/%d: %d sessions/sec for %ds (expected steady-state: ~%d running)",
        stage_num, total_stages, rate, duration, rate * 30,
    )

    while time.monotonic() < end_time:
        task = asyncio.create_task(bounded_submit())
        tasks.append(task)
        submitted += 1
        collector.add_submitted(1)

        if submitted % 100 == 0:
            log.info("  [submitted: %d]", submitted)

        # Token refresh every 200 requests to avoid expiry
        if submitted % 200 == 0:
            try:
                token = await get_token(client, auth_url, username, password)
            except Exception as exc:
                log.warning("Token refresh failed: %s", exc)

        await asyncio.sleep(interval)

    log.info("Submitted %d sessions in stage %d, awaiting responses...", submitted, stage_num)

    for coro in asyncio.as_completed(tasks):
        try:
            result = await asyncio.wait_for(coro, timeout=30)
            results.append(result)
            collector.add_completed(1)
        except Exception:
            results.append({"status": 0, "error": "timeout"})
            collector.add_completed(1)

    return results


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def fmt_ms(val: float) -> str:
    return f"{val:.0f}ms"


def fmt_secs(secs: float) -> str:
    if secs < 60:
        return f"{secs:.0f}s"
    m, s = divmod(int(secs), 60)
    return f"{m}m {s:02d}s"


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics for load test results."""
    total = len(results)
    ok = sum(1 for r in results if r.get("status") == 200 and r.get("success"))
    fail = total - ok
    lats = sorted(
        r["latency_ms"]
        for r in results
        if r.get("latency_ms") and r.get("status") == 200
    )
    return {
        "total": total,
        "ok": ok,
        "fail": fail,
        "success_pct": (ok / total * 100) if total else 0,
        "avg_ms": sum(lats) / len(lats) if lats else 0,
        "p50_ms": _percentile(lats, 50),
        "p95_ms": _percentile(lats, 95),
        "p99_ms": _percentile(lats, 99),
        "max_ms": max(lats) if lats else 0,
    }


def build_benchmark_table(
    phases: dict[str, list[EndpointResult]],
) -> str:
    """Build a formatted benchmark comparison table."""
    phase_names = list(phases.keys())
    # Header
    col1 = 30
    col_each = 14
    header = f"{'Endpoint':<{col1}}"
    for pname in phase_names:
        header += f" {pname:>{col_each}}"
    lines = [header, "-" * len(header)]

    # Find all unique endpoints (ordered by first phase)
    seen: set[str] = set()
    ordered_paths: list[tuple[str, str]] = []
    for results in phases.values():
        for r in results:
            key = f"{r.method} {r.path}"
            if key not in seen:
                seen.add(key)
                ordered_paths.append((r.method, r.path))

    for method, path in ordered_paths:
        label = f"{method} {path}"
        row = f"{label:<{col1}}"
        for pname in phase_names:
            # Find matching result
            matched = next(
                (r for r in phases[pname] if r.method == method and r.path == path),
                None,
            )
            if matched:
                row += f" {fmt_ms(matched.p50_ms):>{col_each}}"
            else:
                row += f" {'N/A':>{col_each}}"
        lines.append(row)

    return "\n".join(lines)


def build_scale_timeline(events: list[dict[str, Any]], start_time: float) -> str:
    """Build a timeline of scaling events."""
    if not events:
        return "  No scaling events detected."

    lines = []
    for ev in events:
        elapsed = ev["elapsed"]
        m, s = divmod(int(elapsed), 60)
        lines.append(f"  [{m:02d}:{s:02d}] {ev['message']}")
    return "\n".join(lines)


def build_resource_section(snapshots: list[MetricSnapshot]) -> str:
    """Build resource usage summary from metric snapshots."""
    cpu_vals = [s.backend_cpu_millicores for s in snapshots if s.backend_cpu_millicores is not None]
    mem_vals = [s.backend_memory_mb for s in snapshots if s.backend_memory_mb is not None]
    node_cpu = [s.node_cpu_percent for s in snapshots if s.node_cpu_percent is not None]
    node_mem = [s.node_memory_percent for s in snapshots if s.node_memory_percent is not None]

    lines = []
    if cpu_vals:
        lines.append(f"  Backend CPU:    peak {max(cpu_vals):.0f}m  | avg {sum(cpu_vals)/len(cpu_vals):.0f}m")
    else:
        lines.append("  Backend CPU:    (no data)")
    if mem_vals:
        lines.append(f"  Backend Memory: peak {max(mem_vals):.0f}Mi  | avg {sum(mem_vals)/len(mem_vals):.0f}Mi")
    else:
        lines.append("  Backend Memory: (no data)")
    if node_cpu:
        lines.append(f"  Node CPU:       peak {max(node_cpu)*100:.0f}%  | avg {sum(node_cpu)/len(node_cpu)*100:.0f}%")
    else:
        lines.append("  Node CPU:       (no data)")
    if node_mem:
        lines.append(f"  Node Memory:    peak {max(node_mem)*100:.0f}%  | avg {sum(node_mem)/len(node_mem)*100:.0f}%")
    else:
        lines.append("  Node Memory:    (no data)")

    return "\n".join(lines)


def write_csv(
    snapshots: list[MetricSnapshot],
    all_results: list[dict[str, Any]],
    output_dir: Path,
    start_time: float,
) -> Path:
    """Write time-series CSV data to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"comprehensive-{ts}.csv"

    # Compute rolling response time from results submitted near each snapshot
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "elapsed_s", "phase",
            "sessions_submitted", "sessions_completed",
            "running_agent_runs",
            "backend_replicas", "frontend_replicas", "app_nodes",
            "backend_cpu_millicores", "backend_memory_mb",
            "keda_metric", "node_cpu_percent", "node_memory_percent",
            "hpa_desired", "hpa_min", "hpa_max",
        ])
        for snap in snapshots:
            elapsed = snap.timestamp - start_time
            writer.writerow([
                datetime.fromtimestamp(snap.timestamp, tz=timezone.utc).isoformat(),
                f"{elapsed:.1f}",
                snap.phase,
                snap.sessions_submitted,
                snap.sessions_completed,
                snap.running_agent_runs,
                f"{int(snap.backend_replicas)}" if snap.backend_replicas is not None else "",
                f"{int(snap.frontend_replicas)}" if snap.frontend_replicas is not None else "",
                f"{int(snap.app_nodes)}" if snap.app_nodes is not None else "",
                f"{snap.backend_cpu_millicores:.1f}" if snap.backend_cpu_millicores is not None else "",
                f"{snap.backend_memory_mb:.1f}" if snap.backend_memory_mb is not None else "",
                f"{snap.keda_metric:.1f}" if snap.keda_metric is not None else "",
                f"{snap.node_cpu_percent:.4f}" if snap.node_cpu_percent is not None else "",
                f"{snap.node_memory_percent:.4f}" if snap.node_memory_percent is not None else "",
                f"{int(snap.hpa_desired)}" if snap.hpa_desired is not None else "",
                f"{int(snap.hpa_min)}" if snap.hpa_min is not None else "",
                f"{int(snap.hpa_max)}" if snap.hpa_max is not None else "",
            ])

    return path


def build_limits_section(
    snapshots: list[MetricSnapshot],
    all_results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    """Analyze scaling limits and bottlenecks."""
    replicas_vals = [
        int(s.backend_replicas)
        for s in snapshots
        if s.backend_replicas is not None
    ]
    nodes_vals = [
        int(s.app_nodes)
        for s in snapshots
        if s.app_nodes is not None
    ]
    cpu_vals = [
        s.backend_cpu_millicores
        for s in snapshots
        if s.backend_cpu_millicores is not None
    ]
    mem_vals = [
        s.backend_memory_mb
        for s in snapshots
        if s.backend_memory_mb is not None
    ]

    max_replicas = max(replicas_vals) if replicas_vals else 0
    max_nodes = max(nodes_vals) if nodes_vals else 0
    hpa_max_vals = [
        int(s.hpa_max)
        for s in snapshots
        if s.hpa_max is not None
    ]
    configured_max = max(hpa_max_vals) if hpa_max_vals else 0

    # Estimate max concurrent sessions from the heaviest stage
    max_running = max(
        (s.running_agent_runs for s in snapshots if s.running_agent_runs >= 0),
        default=0,
    )

    lines = []
    lines.append(f"  Max concurrent agent_runs observed: {max_running}")
    lines.append(f"  Max backend replicas reached:       {max_replicas}")
    if configured_max:
        lines.append(f"  KEDA maxReplicaCount configured:     {configured_max}")
        if max_replicas >= configured_max:
            lines.append(f"  Bottleneck: KEDA maxReplicaCount ({configured_max}) -- hit limit")
        else:
            lines.append(f"  Bottleneck: none (replicas did not hit KEDA limit)")
    lines.append(f"  Max app nodes provisioned:           {max_nodes}")

    if cpu_vals and max_replicas > 0:
        # Per-pod CPU estimate at peak (total / replicas)
        peak_snap = max(snapshots, key=lambda s: s.backend_cpu_millicores or 0)
        if peak_snap.backend_cpu_millicores and peak_snap.backend_replicas:
            per_pod_cpu = peak_snap.backend_cpu_millicores / peak_snap.backend_replicas
            # Backend limit is 2 CPU = 2000m
            headroom_pct = max(0, (2000 - per_pod_cpu) / 2000 * 100)
            lines.append(f"  CPU headroom at peak:               {headroom_pct:.0f}% per pod (limit: 2000m)")
    if mem_vals and max_replicas > 0:
        peak_snap = max(snapshots, key=lambda s: s.backend_memory_mb or 0)
        if peak_snap.backend_memory_mb and peak_snap.backend_replicas:
            per_pod_mem = peak_snap.backend_memory_mb / peak_snap.backend_replicas
            # Backend memory limit is 4Gi = 4096Mi
            headroom_pct = max(0, (4096 - per_pod_mem) / 4096 * 100)
            lines.append(f"  Memory headroom at peak:            {headroom_pct:.0f}% per pod (limit: 4096Mi)")

    return "\n".join(lines)


def build_timing_section(events: list[dict[str, Any]], start_time: float) -> str:
    """Analyze scaling timing."""
    lines = []
    scale_events = [e for e in events if e["type"] == "scale"]
    node_events = [e for e in events if e["type"] == "node"]

    if scale_events:
        first_scale = min(e["elapsed"] for e in scale_events)
        lines.append(f"  First KEDA scale-up:     {fmt_secs(first_scale)} after load started")
    else:
        lines.append("  First KEDA scale-up:     (not detected)")

    if node_events:
        first_node = min(e["elapsed"] for e in node_events)
        lines.append(f"  First CA node provision: {fmt_secs(first_node)} after load started")
    else:
        lines.append("  First CA node provision: (not detected)")

    if scale_events:
        max_rep_event = max(scale_events, key=lambda e: e["elapsed"])
        lines.append(f"  Last scale event:        {fmt_secs(max_rep_event['elapsed'])} after load started")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="KEDA comprehensive load test with Prometheus metrics and API benchmarks",
    )
    parser.add_argument("--domain", default="druppie.rijnland.dev", help="Target domain")
    parser.add_argument("--username", default="admin", help="Keycloak username")
    parser.add_argument("--password", default="Admin123!", help="Keycloak password")
    parser.add_argument("--max-rate", type=int, default=0, help="Override: run single stage at this rate")
    parser.add_argument("--output-dir", default=None, help="Output directory for CSV (default: testing/autoscaling/results/)")
    args = parser.parse_args()

    base_url = f"https://{args.domain}"
    auth_url = f"https://auth.{args.domain}"

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).parent / "results"

    stages = RAMP_STAGES
    if args.max_rate:
        stages = [(args.max_rate, 120)]

    total_duration = sum(d for _, d in stages)
    max_rate = max(r for r, _ in stages)

    log.info("=" * 64)
    log.info("  KEDA COMPREHENSIVE LOAD TEST")
    log.info("  Target: %s", args.domain)
    log.info("  Stages: %d | Total duration: ~%s | Max rate: %d/sec",
             len(stages), fmt_secs(total_duration), max_rate)
    log.info("  Output: %s", output_dir)
    log.info("=" * 64)

    # Suppress SSL warnings
    try:
        import urllib3
        urllib3.disable_warnings()
    except ImportError:
        pass

    # Start Prometheus port-forward
    prom_pf = PrometheusPortForward()
    prom_url: str | None = None
    try:
        prom_pf.start()
        # Verify Prometheus is reachable
        try:
            r = requests.get(f"{prom_pf.url}/api/v1/query",
                             params={"query": "up"}, timeout=5)
            r.raise_for_status()
            prom_url = prom_pf.url
            log.info("Prometheus port-forward active at %s", prom_url)
        except Exception as exc:
            log.warning("Prometheus not reachable via port-forward: %s", exc)
            log.warning("Falling back to kubectl-only metrics collection")
            prom_pf.stop()
            prom_url = None
    except Exception as exc:
        log.warning("Could not start Prometheus port-forward: %s", exc)
        prom_url = None

    # Start metrics collector
    collector = MetricsCollector(prom_url)
    collector.start()

    test_start_time = time.time()
    all_results: list[dict[str, Any]] = []
    benchmark_phases: dict[str, list[EndpointResult]] = {}

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            # Get initial token
            log.info("Authenticating as %s...", args.username)
            token = await get_token(client, auth_url, args.username, args.password)
            log.info("Authentication successful")

            # ---- Phase 1: Baseline API benchmarks ----
            collector.set_phase("baseline")
            log.info("")
            log.info("--- Phase 1: Baseline API benchmarks ---")
            baseline_results = await benchmark_endpoints(client, base_url, token, "baseline")
            benchmark_phases["Baseline"] = baseline_results

            # Print baseline
            for r in baseline_results:
                auth_tag = "" if r.path == "/health" else " (auth)"
                log.info(
                    "  %s %s%s: p50=%s p95=%s [%d/%d ok]",
                    r.method, r.path, auth_tag,
                    fmt_ms(r.p50_ms), fmt_ms(r.p95_ms),
                    sum(1 for s in r.status_codes if 200 <= s < 300),
                    len(r.status_codes),
                )

            # ---- Phase 2: Progressive load test ----
            log.info("")
            log.info("--- Phase 2: Progressive load test ---")

            for i, (rate, duration) in enumerate(stages, 1):
                collector.set_phase(f"stage-{i}-{rate}rps")
                log.info("")
                log.info("Stage %d/%d: %d sessions/sec x %ds", i, len(stages), rate, duration)

                stage_results = await run_stage(
                    client, base_url, auth_url,
                    args.username, args.password,
                    rate, duration, i, len(stages), collector,
                )
                all_results.extend(stage_results)

                stage_summary = summarize_results(stage_results)
                log.info(
                    "  Stage %d results: ok=%d fail=%d (%.1f%%) p50=%s p95=%s",
                    i, stage_summary["ok"], stage_summary["fail"],
                    stage_summary["success_pct"],
                    fmt_ms(stage_summary["p50_ms"]),
                    fmt_ms(stage_summary["p95_ms"]),
                )

                # Mid-load benchmark during the heaviest stages
                if rate >= 50 and i == len(stages) // 2 + 1:
                    collector.set_phase("mid-load-bench")
                    log.info("")
                    log.info("  Mid-load API benchmarks...")
                    # Refresh token for benchmarks
                    token = await get_token(client, auth_url, args.username, args.password)
                    mid_results = await benchmark_endpoints(client, base_url, token, "mid-load")
                    benchmark_phases["Under Load"] = mid_results

                if i < len(stages):
                    log.info("  Cooldown 15s...")
                    await asyncio.sleep(15)

            # ---- Phase 3: Post-load API benchmarks ----
            log.info("")
            log.info("--- Phase 3: Post-load API benchmarks ---")
            collector.set_phase("post-load-bench")
            # Wait a moment for things to settle
            await asyncio.sleep(5)
            token = await get_token(client, auth_url, args.username, args.password)
            post_results = await benchmark_endpoints(client, base_url, token, "post-load")
            benchmark_phases["Post-Load"] = post_results

            # ---- Phase 4: Watch scale-down ----
            log.info("")
            log.info("--- Phase 4: Watching scale-down (up to 10 min) ---")
            collector.set_phase("scale-down")

            for tick in range(20):
                await asyncio.sleep(30)
                state = collector.current_state
                latest = collector.snapshots[-1] if collector.snapshots else None
                if latest:
                    rep = int(latest.backend_replicas) if latest.backend_replicas is not None else "?"
                    nodes = int(latest.app_nodes) if latest.app_nodes is not None else "?"
                    log.info(
                        "[scale-down %ds] replicas=%s | nodes=%s | running=%s",
                        (tick + 1) * 30, rep, nodes,
                        latest.running_agent_runs,
                    )
                    if (isinstance(rep, int) and rep <= 1
                            and isinstance(nodes, int) and nodes <= 1):
                        log.info("Scaled back to baseline.")
                        break

    finally:
        collector.stop()
        if prom_url:
            prom_pf.stop()

    test_end_time = time.time()
    total_elapsed = test_end_time - test_start_time

    # ---- Generate report ----
    summary = summarize_results(all_results)

    log.info("")
    log.info("=" * 64)
    log.info("  DRUPPIE LOAD TEST REPORT")
    log.info("=" * 64)
    log.info("Date: %s", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    log.info("Duration: %s", fmt_secs(total_elapsed))
    log.info("Target: %s", args.domain)
    log.info("")

    # API benchmarks
    if benchmark_phases:
        log.info("--- API Response Times ---")
        log.info(build_benchmark_table(benchmark_phases))
        log.info("")

    # Load test results
    log.info("--- Load Test Results ---")
    log.info("  Total sessions submitted:    %s", f"{summary['total']:,}")
    log.info("  Successful (200):            %s (%.1f%%)", f"{summary['ok']:,}", summary["success_pct"])
    log.info("  Failed:                      %s (%.1f%%)", f"{summary['fail']:,}",
             100 - summary["success_pct"] if summary["total"] else 0)
    log.info("  Average latency:             %s", fmt_ms(summary["avg_ms"]))
    log.info("  P50 latency:                 %s", fmt_ms(summary["p50_ms"]))
    log.info("  P95 latency:                 %s", fmt_ms(summary["p95_ms"]))
    log.info("  P99 latency:                 %s", fmt_ms(summary["p99_ms"]))
    log.info("")

    # Scaling events
    log.info("--- Scaling Events ---")
    log.info(build_scale_timeline(collector.scale_events, test_start_time))
    log.info("")

    # Resource usage
    log.info("--- Resource Usage ---")
    log.info(build_resource_section(collector.snapshots))
    log.info("")

    # Limits
    log.info("--- Limits Found ---")
    log.info(build_limits_section(collector.snapshots, all_results, summary))
    log.info("")

    # Scaling timing
    log.info("--- Scaling Timing ---")
    log.info(build_timing_section(collector.scale_events, test_start_time))

    log.info("=" * 64)

    # Write CSV
    csv_path = write_csv(collector.snapshots, all_results, output_dir, test_start_time)
    log.info("CSV data written to: %s", csv_path)

    # Also write a plain text report
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = output_dir / f"report-{ts}.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "=" * 64,
        "  DRUPPIE LOAD TEST REPORT",
        "=" * 64,
        f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Duration: {fmt_secs(total_elapsed)}",
        f"Target: {args.domain}",
        "",
        "--- API Response Times ---",
        build_benchmark_table(benchmark_phases) if benchmark_phases else "(no benchmark data)",
        "",
        "--- Load Test Results ---",
        f"  Total sessions submitted:    {summary['total']:,}",
        f"  Successful (200):            {summary['ok']:,} ({summary['success_pct']:.1f}%)",
        f"  Failed:                      {summary['fail']:,} ({100 - summary['success_pct']:.1f}%)",
        f"  Average latency:             {fmt_ms(summary['avg_ms'])}",
        f"  P50 latency:                 {fmt_ms(summary['p50_ms'])}",
        f"  P95 latency:                 {fmt_ms(summary['p95_ms'])}",
        f"  P99 latency:                 {fmt_ms(summary['p99_ms'])}",
        "",
        "--- Scaling Events ---",
        build_scale_timeline(collector.scale_events, test_start_time),
        "",
        "--- Resource Usage ---",
        build_resource_section(collector.snapshots),
        "",
        "--- Limits Found ---",
        build_limits_section(collector.snapshots, all_results, summary),
        "",
        "--- Scaling Timing ---",
        build_timing_section(collector.scale_events, test_start_time),
        "=" * 64,
    ]

    with open(report_path, "w") as f:
        f.write("\n".join(report_lines) + "\n")
    log.info("Text report written to: %s", report_path)


if __name__ == "__main__":
    asyncio.run(main())
