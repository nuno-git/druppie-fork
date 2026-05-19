"""
Sandbox configuration — runtime selection and resource limits.

Environment variables (all optional, with sensible defaults):
  DRUPPIE_SANDBOX_RUNTIME   — "docker" | "sysbox" | "kata"  (default: "docker")
  DRUPPIE_SANDBOX_IMAGE     — container image tag             (default: "druppie-sandbox:latest")
  DRUPPIE_SANDBOX_TIMEOUT   — max container lifetime in seconds (default: 7200)

Docker / Sysbox settings:
  DRUPPIE_DOCKER_MEMORY_LIMIT  — memory cap, e.g. "4g"    (default: "4g")
  DRUPPIE_DOCKER_CPU_LIMIT     — CPU count, "0" = unlimited (default: "2")
  DRUPPIE_DOCKER_PIDS_LIMIT    — max PIDs                  (default: 8192)
  DRUPPIE_DOCKER_NETWORK       — Docker network name, empty = host mode
  DRUPPIE_SANDBOX_CACHE_VOLUME — shared dep-cache volume mount
  DRUPPIE_SANDBOX_SDK_HOST_PATH— host path mounted read-only at /druppie-sdk

Sysbox settings:
  DRUPPIE_SYSBOX_RUNTIME       — Sysbox OCI runtime binary (default: "sysbox-runc")

Kata settings:
  DRUPPIE_KATA_RUNTIME         — Kata OCI runtime          (default: "io.containerd.kata.v2")
  DRUPPIE_CONTAINERD_NAMESPACE — containerd namespace      (default: "default")

Warm pool settings:
  DRUPPIE_POOL_SIZE            — pre-warmed containers per scope (default: 3)
  DRUPPIE_POOL_RECYCLE_S       — seconds before a warm container is recycled (default: 3600)
"""

import os


def get(key: str, default: str = "") -> str:
    """Read an environment variable with a default."""
    return os.environ.get(key, default)


# ── Runtime selection ──────────────────────────────────────────────────────
# "docker"  — Docker CLI; works on Linux, Windows, macOS
# "sysbox"  — Docker CLI + Sysbox runtime; stronger namespace isolation
# "kata"    — containerd + Kata runtime; Linux only, requires nested virt
SANDBOX_RUNTIME = get("DRUPPIE_SANDBOX_RUNTIME", "docker")

# Container image (used by all runtimes).
SANDBOX_IMAGE = get("DRUPPIE_SANDBOX_IMAGE", "druppie-sandbox:latest")

# Default sandbox timeout in seconds.
DEFAULT_SANDBOX_TIMEOUT_SECONDS = int(get("DRUPPIE_SANDBOX_TIMEOUT", "7200"))

# ── Docker / Sysbox resource limits ────────────────────────────────────────
DOCKER_MEMORY_LIMIT = get("DRUPPIE_DOCKER_MEMORY_LIMIT", "4g")
DOCKER_CPU_LIMIT = get("DRUPPIE_DOCKER_CPU_LIMIT", "2")
DOCKER_PIDS_LIMIT = int(get("DRUPPIE_DOCKER_PIDS_LIMIT", "8192"))
DOCKER_NETWORK = get("DRUPPIE_DOCKER_NETWORK", "")
SANDBOX_CACHE_VOLUME = get("DRUPPIE_SANDBOX_CACHE_VOLUME", "")
SANDBOX_SDK_HOST_PATH = get("DRUPPIE_SANDBOX_SDK_HOST_PATH", "")

# ── Sysbox-specific settings ───────────────────────────────────────────────
SYSBOX_RUNTIME = get("DRUPPIE_SYSBOX_RUNTIME", "sysbox-runc")

# ── Kata-specific settings ─────────────────────────────────────────────────
KATA_RUNTIME = get("DRUPPIE_KATA_RUNTIME", "io.containerd.kata.v2")
CONTAINERD_NAMESPACE = get("DRUPPIE_CONTAINERD_NAMESPACE", "default")

# ── Warm pool settings ─────────────────────────────────────────────────────
POOL_SIZE = int(get("DRUPPIE_POOL_SIZE", "3"))
POOL_RECYCLE_SECONDS = int(get("DRUPPIE_POOL_RECYCLE_S", "3600"))
