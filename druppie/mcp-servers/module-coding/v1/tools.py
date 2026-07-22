"""Coding v1 — MCP Tool Definitions (Sandbox Orchestrator Architecture).

module-coding is now a sandbox orchestrator:
- It receives MCP tool calls from agents
- Resolves them to per-agent sandbox containers
- Proxies operations via the sandbox ContainerManager interface

Each agent gets its own isolated Docker container.
Containers have NO git credentials.
push_changes extracts changes via git bundle, pushes externally. create_pr creates a PR on Gitea.

Container lifecycle:
1. On first tool call for a session+git_scope: create container, clone repo
2. All subsequent tool calls proxy to that container
3. Container destroyed when: agent calls done(), agent pauses, error occurs

Container ID format: druppie-{session_id[:12]}-{git_scope}
"""

import asyncio
import json
import logging
import os
import posixpath
import re
import shlex
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

from .mermaid_validator import validate_mermaid_in_markdown

# Configure logging
logger = logging.getLogger("coding-mcp")

MODULE_ID = "coding"
MODULE_VERSION = "2.0.0"

# Initialize FastMCP server
mcp = FastMCP(
    "Coding v1",
    version=MODULE_VERSION,
    instructions=(
        "File operations, bash, push_changes, and create_pr in isolated sandbox containers. "
        "Each session gets its own container — no shared workspace state."
    ),
)

# =============================================================================
# CONFIGURATION
# =============================================================================

GITEA_INTERNAL_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_URL = os.getenv("GITEA_URL", GITEA_INTERNAL_URL)
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")
# External Gitea (aigit.waterschap.org) — shared across environments, uses OAuth2 token
EXTERNAL_GITEA_TOKEN = os.getenv("EXTERNAL_GITEA_TOKEN", "")
EXTERNAL_GITEA_URL = os.getenv("EXTERNAL_GITEA_URL", "https://aigit.waterschap.org")
# Core repo lives on the external Gitea (aigit.waterschap.org), not the internal one.
# The sandbox container may need to reach it externally for clone/push/PR.
DRUPPIE_CORE_GITEA_URL = os.getenv("DRUPPIE_CORE_GITEA_URL", "https://aigit.waterschap.org")
DRUPPIE_CORE_REPO_OWNER = os.getenv("DRUPPIE_CORE_REPO_OWNER", "ai")
DRUPPIE_CORE_REPO_NAME = os.getenv("DRUPPIE_CORE_REPO_NAME", "druppie")
DRUPPIE_CORE_REPO_BRANCH = os.getenv("DRUPPIE_CORE_REPO_BRANCH", "colab-dev")


SANDBOX_IMAGE = os.getenv("DRUPPIE_SANDBOX_IMAGE", "druppie-sandbox:latest")
SANDBOX_MEMORY = os.getenv("DRUPPIE_DOCKER_MEMORY_LIMIT", "16g")
SANDBOX_CPU = os.getenv("DRUPPIE_DOCKER_CPU_LIMIT", "6")
SANDBOX_PIDS_LIMIT = int(os.getenv("DRUPPIE_DOCKER_PIDS_LIMIT", "32768"))
SANDBOX_NETWORK = os.getenv("DRUPPIE_SANDBOX_NETWORK", "bridge")
SANDBOX_INET_NETWORK = os.getenv("DRUPPIE_SANDBOX_INET_NETWORK", "")
SANDBOX_MODULES_NETWORK = os.getenv("DRUPPIE_SANDBOX_MODULES_NETWORK", "")

# Sandbox mode: "docker" (local dev) or "k8s" (production with agent-sandbox CRD).
# In k8s mode, sandboxes are managed by the agent-sandbox controller with gVisor.
SANDBOX_MODE = os.getenv("DRUPPIE_SANDBOX_MODE", "docker")

# Docker-specific config (only used when SANDBOX_MODE == "docker")
SANDBOX_RUNTIME = os.getenv("DRUPPIE_SANDBOX_RUNTIME", "sysbox-runc")
_ALLOWED_RUNTIMES = {"sysbox-runc", "kata-runtime"}
if SANDBOX_MODE == "docker":
    assert SANDBOX_RUNTIME in _ALLOWED_RUNTIMES, (
        f"Invalid DRUPPIE_SANDBOX_RUNTIME={SANDBOX_RUNTIME!r}. "
        f"Must be one of {_ALLOWED_RUNTIMES}. "
        f"Or set DRUPPIE_SANDBOX_MODE=k8s to use agent-sandbox."
    )
SANDBOX_CACHE_VOLUME = os.getenv("DRUPPIE_SANDBOX_CACHE_VOLUME", "sandbox_dep_cache")
SANDBOX_USER = os.getenv("DRUPPIE_SANDBOX_USER", "druppie")

# Max seconds a sandbox may sit idle (no tool activity) before the watchdog
# reaps it. Catches stuck/dead sessions whose sandbox pod is still Running but
# whose agent session is wedged — the exact leak that starves the cluster.
# Reaping only loses UNCOMMITTED in-sandbox edits; pushed commits live in Gitea
# and bundles on the host PVC. A reaped sandbox is recreated (fresh clone) on
# the next tool call. Default 15 min (> normal LLM think time).
SANDBOX_MAX_IDLE = int(os.getenv("DRUPPIE_SANDBOX_MAX_IDLE", "900"))

# K8s sandbox manager (initialized lazily when SANDBOX_MODE == "k8s")
_k8s_manager = None


def _get_k8s_manager():
    """Lazily initialize the K8s sandbox manager."""
    global _k8s_manager
    if _k8s_manager is None:
        from k8s_sandbox import K8sSandboxManager
        _k8s_manager = K8sSandboxManager()
    return _k8s_manager

# Sandbox container registry
# Key: "{session_id}::{git_scope}"
# Value: {"container_name": str, "container_id": str, "git_scope": str,
#          "session_id": str, "branch": str, "created_at": float,
#          "repo_name": str, "repo_owner": str}
sandbox_containers: dict[str, dict] = {}
_container_locks: dict[str, asyncio.Lock] = {}
_network_locks: dict[str, asyncio.Lock] = {}


def _get_container_lock(key: str) -> asyncio.Lock:
    if key not in _container_locks:
        _container_locks[key] = asyncio.Lock()
    return _container_locks[key]


def _get_network_lock(key: str) -> asyncio.Lock:
    if key not in _network_locks:
        _network_locks[key] = asyncio.Lock()
    return _network_locks[key]


def _touch_sandbox(key: str) -> None:
    """Record activity on a tracked sandbox (called from every tool op).

    The watchdog reaps sandboxes whose ``last_activity`` is older than
    ``SANDBOX_MAX_IDLE``; without this, a sandbox whose pod is up but whose
    session is frozen would never be collected.
    """
    entry = sandbox_containers.get(key)
    if entry is not None:
        entry["last_activity"] = time.time()

# =============================================================================
# SECURITY: COMMAND BLOCKLIST
# =============================================================================

BLOCKED_COMMAND_PATTERNS = [
    r"rm\s+(-[rf]+\s+)*\s*/\s*$",
    r"rm\s+(-[rf]+\s+)*\s*/\*",
    r"rm\s+(-[rf]+\s+)+\s*/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bsudo\b",
    r"\bsu\s+-",
    r"\bsu\s+root",
    r"\bchmod\s+777\b",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+.*\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[0-6]",
    r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|network)",
    r":\(\)\s*{\s*:\|\s*:&\s*}\s*;",
    r">\s*/dev/sd[a-z]",
    r">\s*/dev/null\s*2>&1\s*&",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
    r">\s*/etc/sudoers",
    r"\bnc\s+-[elp]",
    r"\bbash\s+-i\s+>&\s+/dev/tcp",
    r"\bcurl\s+.*\|\s*bash",
    r"\bwget\s+.*\|\s*bash",
    r"\bcurl\s+.*\|\s*sh",
    r"\bwget\s+.*\|\s*sh",
    # Sandbox-specific: block git push/remote/credential from bash
    # Agents must use push_changes tool for pushing, create_pr for PRs
    r"\bgit\s+push\b",
    r"\bgit\s+remote\s+",
    r"\bgit\s+config\s+credential",
]

BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMAND_PATTERNS]


def _is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches any blocked pattern."""
    for i, pattern in enumerate(BLOCKED_PATTERNS_COMPILED):
        if pattern.search(command):
            return True, BLOCKED_COMMAND_PATTERNS[i]
    return False, None


# =============================================================================
# CONTAINER MANAGEMENT (inline docker commands)
# =============================================================================


async def _docker_run(cmd: list[str], timeout: float = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    logger.debug("Running: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def _exec_in_container(
    container_id: str, command: list[str], timeout: float = 120
) -> tuple[int, str, str]:
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            return await _get_k8s_manager().exec(entry["_k8s_handle"], command, timeout=int(timeout))
    full_cmd = ["docker", "exec", container_id, *command]
    return await _docker_run(full_cmd, timeout=timeout)


def _find_entry_by_container_id(container_id: str) -> dict | None:
    """Find a sandbox_containers entry by container_id or container_name."""
    for entry in sandbox_containers.values():
        if entry.get("container_id") == container_id or entry.get("container_name") == container_id:
            return entry
    return None


async def _exec_bash_in_container(
    container_id: str, command: str, timeout: float = 120, output_file: str | None = None
) -> tuple[int, str, str]:
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            full_cmd = command
            if output_file:
                full_cmd = f"set -o pipefail; ({command}) 2>&1 | tee {shlex.quote(output_file)}"
            try:
                return await asyncio.wait_for(
                    _get_k8s_manager().exec(entry["_k8s_handle"], ["bash", "-c", full_cmd], timeout=int(timeout)),
                    timeout=timeout + 10,
                )
            except asyncio.TimeoutError:
                return (-1, "", f"Command timed out after {timeout}s")

    if output_file:
        wrapped = f"set -o pipefail; ({command}) 2>&1 | tee {shlex.quote(output_file)}"
    else:
        wrapped = command

    for attempt in range(3):
        full_cmd = ["docker", "exec", container_id, "bash", "-c", wrapped]
        rc, stdout, stderr = await _docker_run(full_cmd, timeout=timeout)
        if rc != 128 or "setns" not in (stderr or ""):
            return rc, stdout, stderr
        logger.warning(
            "docker exec setns failure (attempt %d/3), retrying in 2s: %s",
            attempt + 1, (stderr or "")[:200],
        )
        await asyncio.sleep(2)

    return rc, stdout, stderr


async def _write_to_container(
    container_id: str, container_path: str, content: str
) -> tuple[int, str]:
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            try:
                await asyncio.wait_for(
                    _get_k8s_manager().write_file(entry["_k8s_handle"], container_path, content),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                return (1, "Write file timed out")
            return 0, ""
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container_id,
        "sh", "-c", f"cat > {shlex.quote(container_path)}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=content.encode("utf-8")), timeout=30
    )
    return proc.returncode or 0, stderr.decode()


async def _copy_from_container(
    container_id: str, src_path: str, dst_path: str
) -> None:
    """Copy a file from inside a container to the host.

    Uses `docker exec cat` instead of `docker cp` because the module-coding
    MCP server runs in its own Docker container (sibling of the sandbox
    containers). `docker cp` fails between sibling containers — the Docker
    socket mount only allows API-level operations, and `docker cp` resolves
    paths on the *daemon's* host filesystem, not inside the calling container.
    Piping through `docker exec cat` avoids this entirely.

    In k8s mode the sandbox has no Docker; we read the file out through the
    agent-sandbox SDK as bytes (base64 round-trip — `cat`-as-text would corrupt
    binary content like git bundles).
    """
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            try:
                data = await asyncio.wait_for(
                    _get_k8s_manager().read_file_bytes(
                        entry["_k8s_handle"], src_path
                    ),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                raise RuntimeError(f"Read file from sandbox timed out: {src_path}")
            with open(dst_path, "wb") as f:
                f.write(data)
            return
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container_id, "cat", src_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec cat failed: {stderr.decode().strip()}")
    with open(dst_path, "wb") as f:
        f.write(stdout)


async def _is_container_running(container_id: str) -> bool:
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            return await _get_k8s_manager().is_alive(entry["_k8s_handle"])
        return False
    rc, stdout, _ = await _docker_run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
        timeout=10,
    )
    return rc == 0 and "true" in stdout.lower()


async def _get_container_death_reason(container_id: str) -> str | None:
    """If a container has exited, return a human-readable reason. None if still running."""
    if SANDBOX_MODE == "k8s":
        return "sandbox terminated (k8s mode)"
    rc, stdout, _ = await _docker_run(
        ["docker", "inspect", "--format",
         "{{.State.Running}}|{{.State.OOMKilled}}|{{.State.ExitCode}}|{{.State.Status}}",
         container_id],
        timeout=10,
    )
    if rc != 0:
        return "container not found"
    parts = stdout.strip().split("|")
    if len(parts) < 4:
        return None
    running = parts[0].strip().lower() == "true"
    oom_killed = parts[1].strip().lower() == "true"
    exit_code = parts[2].strip()
    status = parts[3].strip()

    if running:
        return None
    if oom_killed:
        return (
            f"OOMKilled (exit code {exit_code}). "
            f"Current memory limit: {SANDBOX_MEMORY}. "
            f"Consider increasing DRUPPIE_DOCKER_MEMORY_LIMIT."
        )
    if exit_code != "0":
        return f"Exited with code {exit_code} (status: {status})"
    return f"Stopped (status: {status})"


# =============================================================================
# SANDBOX CONTAINER LIFECYCLE
# =============================================================================


def _sanitize_param(value: str | None) -> str | None:
    """Sanitize LLM-provided parameter values.

    LLMs often send the literal strings "null", "none", or "undefined"
    when they don't have a value. Treat these as None.
    """
    if value and value.lower() in ("null", "none", "undefined", ""):
        return None
    return value


def _get_gitea_clone_url(repo_name: str, repo_owner: str | None = None, base_url: str | None = None) -> str:
    """Get Gitea clone URL with embedded credentials for initial clone only."""
    owner = repo_owner or GITEA_ORG
    url = (base_url or GITEA_URL).rstrip("/")
    if "aigit.waterschap.org" in url and EXTERNAL_GITEA_TOKEN:
        return f"https://oauth2:{EXTERNAL_GITEA_TOKEN}@aigit.waterschap.org/{owner}/{repo_name}.git"
    if GITEA_USER and GITEA_PASSWORD and "://" in url:
        from urllib.parse import quote
        protocol, rest = url.split("://", 1)
        return f"{protocol}://{quote(GITEA_USER)}:{quote(GITEA_PASSWORD)}@{rest}/{owner}/{repo_name}.git"
    return f"{url}/{owner}/{repo_name}.git"


def _get_public_clone_url(repo_name: str, repo_owner: str | None = None) -> str:
    """Get Gitea clone URL WITHOUT credentials (safe for remote config)."""
    owner = repo_owner or GITEA_ORG
    return f"{GITEA_URL}/{owner}/{repo_name}.git"


def _container_path(path: str) -> str:
    """Normalize a path and enforce containment under /workspace.

    Resolves ``..`` segments lexically (no filesystem access, so paths to
    files that do not yet exist are safe) and rejects anything that escapes
    /workspace after normalization.

    Raises ValueError if the normalized path is not /workspace itself or a
    descendant of it (e.g. ``../../etc/passwd`` or an absolute path like
    ``/etc/cron.d/x``).
    """
    stripped = path.lstrip("/")
    candidate = posixpath.normpath(f"/workspace/{stripped}")
    if candidate != "/workspace" and not candidate.startswith("/workspace/"):
        raise ValueError(f"path escapes /workspace: {path!r}")
    return candidate


async def _create_sandbox_container(
    session_id: str,
    git_scope: str,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    agent_networks: list[str] | None = None,
) -> str:
    """Create a new sandbox container, clone repo if applicable.

    Returns:
        Container name (used as identifier for docker exec).
    """
    # For update_core scope, always use the core repo identity on Gitea
    if git_scope == "update_core":
        repo_name = DRUPPIE_CORE_REPO_NAME
        repo_owner = DRUPPIE_CORE_REPO_OWNER
        effective_gitea_url = DRUPPIE_CORE_GITEA_URL
    else:
        effective_gitea_url = GITEA_INTERNAL_URL if SANDBOX_MODE == "k8s" else GITEA_URL

    # ── K8s mode: use agent-sandbox SDK ──────────────────────────────────
    # In k8s mode the host-side clone + push run from the workspace pod (or
    # module-coding pod), which can only reach the *internal* Gitea service
    # (ClusterIP). The external Gitea URL is unreachable from inside the cluster
    # (blocked by NetworkPolicy / no route). Use GITEA_INTERNAL_URL for all
    # in-cluster git operations. The external URL is only needed for the
    # update_core scope (aigit.waterschap.org), which has its own CNP.
    if SANDBOX_MODE == "k8s":
        scope = git_scope or "current_project"
        clone_url = None
        branch = "main"
        if scope == "current_project" and repo_name:
            clone_url = _get_gitea_clone_url(repo_name, repo_owner, GITEA_INTERNAL_URL)
        elif scope == "update_core":
            clone_url = _get_gitea_clone_url(DRUPPIE_CORE_REPO_NAME, DRUPPIE_CORE_REPO_OWNER, DRUPPIE_CORE_GITEA_URL)
            branch = DRUPPIE_CORE_REPO_BRANCH

        manager = _get_k8s_manager()
        handle = await manager.create(
            session_id=session_id,
            git_scope=scope,
            repo_clone_url=clone_url,
            branch=branch,
        )

        key = f"{session_id}::{scope}"
        sandbox_containers[key] = {
            "container_name": handle.sandbox_id,
            "container_id": handle.sandbox_id,
            "git_scope": scope,
            "session_id": session_id,
            "branch": branch,
            "created_at": handle.created_at,
            "last_activity": time.time(),
            "repo_name": repo_name,
            "repo_owner": repo_owner or GITEA_ORG,
            "gitea_url": effective_gitea_url,
            "_k8s_handle": handle,
        }
        logger.info("K8s sandbox created: %s (session=%s, scope=%s)",
                     handle.sandbox_id, session_id, scope)
        return handle.sandbox_id

    # ── Docker mode: existing Docker CLI code ────────────────────────────
    scope = git_scope or "current_project"
    short_session = session_id[:12] if session_id else "unknown"
    container_name = f"druppie-{short_session}-{scope}"

    try:
        await _docker_run(["docker", "rm", "-f", container_name], timeout=10)

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", SANDBOX_NETWORK,
            "--memory", SANDBOX_MEMORY,
            "--pids-limit", str(SANDBOX_PIDS_LIMIT),
            "--cpus", SANDBOX_CPU,
            "--shm-size", "2g",
            "--tmpfs", "/tmp:size=4g",
            "-w", "/workspace",
            "--runtime", SANDBOX_RUNTIME,
            "-v", f"{SANDBOX_CACHE_VOLUME}:/cache",
            "-e", "UV_CACHE_DIR=/cache/uv",
            "-e", "PIP_CACHE_DIR=/cache/pip",
            "-e", "TMPDIR=/cache/tmp",
            "-e", "NPM_CONFIG_CACHE=/cache/npm",
            "-e", "PNPM_HOME=/cache/pnpm",
            "-e", "YARN_CACHE_FOLDER=/cache/yarn",
            "-e", "BUN_INSTALL_CACHE_DIR=/cache/bun",
            SANDBOX_IMAGE,
            "bash", "-c", "mkdir -p /cache/tmp /cache/pip /cache/npm /cache/uv /cache/pnpm /cache/yarn /cache/bun && chmod 1777 /cache/tmp && dockerd > /var/log/dockerd.log 2>&1 & sleep infinity",
        ]
        rc, stdout, stderr = await _docker_run(cmd, timeout=60)
        if rc != 0 and "already in use" in stderr:
            logger.warning("Container name conflict for %s, forcing cleanup and retrying", container_name)
            await _docker_run(["docker", "rm", "-f", container_name], timeout=10)
            await asyncio.sleep(1)
            cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--network", SANDBOX_NETWORK,
                "--memory", SANDBOX_MEMORY,
                "--pids-limit", str(SANDBOX_PIDS_LIMIT),
                "--cpus", SANDBOX_CPU,
                "--shm-size", "2g",
                "--tmpfs", "/tmp:size=4g",
                "-w", "/workspace",
                "--runtime", SANDBOX_RUNTIME,
                "--storage-opt", "size=20G",
                "-v", f"{SANDBOX_CACHE_VOLUME}:/cache",
                "-e", "UV_CACHE_DIR=/cache/uv",
                "-e", "PIP_CACHE_DIR=/cache/pip",
                "-e", "TMPDIR=/cache/tmp",
                "-e", "NPM_CONFIG_CACHE=/cache/npm",
                "-e", "PNPM_HOME=/cache/pnpm",
                "-e", "YARN_CACHE_FOLDER=/cache/yarn",
                "-e", "BUN_INSTALL_CACHE_DIR=/cache/bun",
                SANDBOX_IMAGE,
                "bash", "-c", "mkdir -p /cache/tmp /cache/pip /cache/npm /cache/uv /cache/pnpm /cache/yarn /cache/bun && chmod 1777 /cache/tmp && dockerd > /var/log/dockerd.log 2>&1 & sleep infinity",
            ]
            rc, stdout, stderr = await _docker_run(cmd, timeout=60)
        if rc != 0:
            raise RuntimeError(f"docker run failed: {stderr}")

        container_id = stdout.strip()[:12]
    except RuntimeError:
        raise

    logger.info("Sandbox container created: %s (%s)", container_name, container_id)

    if SANDBOX_RUNTIME == "sysbox-runc":
        for _ in range(20):
            rc, stdout, stderr = await _docker_run(
                ["docker", "exec", container_name, "test", "-S", "/var/run/docker.sock"],
                timeout=5,
            )
            if rc == 0:
                logger.info("Docker daemon ready in sandbox %s", container_name)
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning("Docker daemon not ready in sandbox %s after 10s", container_name)

    if agent_networks:
        for tier in agent_networks:
            if tier == "internet" and SANDBOX_INET_NETWORK:
                await _docker_run(
                    ["docker", "network", "connect", SANDBOX_INET_NETWORK, container_name],
                    timeout=10,
                )
            elif tier == "modules" and SANDBOX_MODULES_NETWORK:
                await _docker_run(
                    ["docker", "network", "connect", SANDBOX_MODULES_NETWORK, container_name],
                    timeout=10,
                )

    # Clone repo inside container based on git_scope
    branch = "main"

    if scope == "current_project" and repo_name:
        clone_url = _get_gitea_clone_url(repo_name, repo_owner)
        public_url = _get_public_clone_url(repo_name, repo_owner)
        owner = repo_owner or GITEA_ORG

        tmp_dir = f"/tmp/sandbox-clone-{short_session}"
        await _docker_run(["rm", "-rf", tmp_dir], timeout=5)

        rc, _, err = await _docker_run(
            ["git", "-c", "http.sslVerify=false", "clone", "--depth=50", clone_url, tmp_dir],
            timeout=120,
        )
        if rc == 0:
            await _docker_run(
                ["git", "-C", tmp_dir, "remote", "set-url", "origin",
                 f"{GITEA_URL}/{owner}/{repo_name}.git"],
                timeout=10,
            )

            rc, _, err = await _docker_run(
                ["bash", "-c",
                 f"tar -cf - -C {tmp_dir} . | docker exec -i {container_name} tar -xf - -C /workspace"],
                timeout=60,
            )
            if rc != 0:
                raise RuntimeError(f"Tar pipe into sandbox failed: {err}")

            await _docker_run(["rm", "-rf", tmp_dir], timeout=5)
            logger.info(
                "Proxy-cloned %s/%s into sandbox, branch=%s", owner, repo_name, branch
            )
        else:
            logger.warning("Proxy clone failed (%s), initializing empty repo", err[:200])
            await _docker_run(["rm", "-rf", tmp_dir], timeout=5)
            await _exec_in_container(container_id, ["git", "init", "/workspace"])
            await _exec_in_container(
                container_id,
                ["git", "remote", "add", "origin", public_url],
            )

    elif scope == "update_core":
        clone_url = _get_gitea_clone_url(DRUPPIE_CORE_REPO_NAME, DRUPPIE_CORE_REPO_OWNER, DRUPPIE_CORE_GITEA_URL)
        tmp_dir = f"/tmp/sandbox-clone-{short_session}-core"
        await _docker_run(["rm", "-rf", tmp_dir], timeout=5)

        rc, _, err = await _docker_run(
            ["git", "-c", "http.sslVerify=false", "clone", "--branch", DRUPPIE_CORE_REPO_BRANCH,
             "--depth=50", clone_url, tmp_dir],
            timeout=120,
        )
        if rc == 0:
            rc, _, err = await _docker_run(
                ["bash", "-c",
                 f"tar -cf - -C {tmp_dir} . | docker exec -i {container_name} tar -xf - -C /workspace"],
                timeout=60,
            )
            if rc != 0:
                raise RuntimeError(f"Tar pipe into sandbox failed: {err}")
            await _docker_run(["rm", "-rf", tmp_dir], timeout=5)
        else:
            logger.error("update_core clone failed: %s", err[:500])
            raise RuntimeError(
                f"Failed to clone Druppie core repo ({clone_url}). "
                f"Check GITEA_TOKEN or GITEA_USER+GITEA_PASSWORD in .env. "
                f"Clone error: {err[:200]}"
            )
        branch = DRUPPIE_CORE_REPO_BRANCH

    else:
        # other_projects or unknown — bare init
        await _exec_in_container(container_id, ["git", "init", "/workspace"])

    # Configure git user inside container
    await _exec_in_container(
        container_id, ["git", "config", "user.email", "agent@druppie.local"]
    )
    await _exec_in_container(
        container_id, ["git", "config", "user.name", "Druppie Agent"]
    )

    # Register in memory
    key = f"{session_id}::{scope}"
    sandbox_containers[key] = {
        "container_name": container_name,
        "container_id": container_id,
        "git_scope": scope,
        "session_id": session_id,
        "branch": branch,
        "created_at": time.time(),
        "repo_name": repo_name,
        "repo_owner": repo_owner or GITEA_ORG,
        "gitea_url": effective_gitea_url,
    }

    return container_name


async def _sync_networks(container_name: str, requested_networks: list[str]) -> None:
    """Dynamically adjust container networks to match the agent's profile.

    Connects networks the agent needs but container doesn't have.
    Disconnects networks the container has but agent doesn't need.
    The base SANDBOX_NETWORK is always kept (never disconnected).

    In k8s mode this is a no-op: network policy is enforced at the pod level
    via the SandboxTemplate's networkPolicy + CiliumNetworkPolicy, not by
    Docker network attachments.
    """
    if SANDBOX_MODE == "k8s":
        return
    NETWORK_MAP = {
        "internet": SANDBOX_INET_NETWORK,
        "modules": SANDBOX_MODULES_NETWORK,
    }

    desired = set()
    for tier in requested_networks:
        net_name = NETWORK_MAP.get(tier)
        if net_name:
            desired.add(net_name)

    rc, stdout, _ = await _docker_run(
        ["docker", "inspect", container_name, "--format", "{{json .NetworkSettings.Networks}}"],
        timeout=10,
    )
    if rc != 0:
        logger.warning("Failed to inspect networks for %s", container_name)
        return

    try:
        current_networks = set(json.loads(stdout).keys())
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Failed to parse network info for %s", container_name)
        return

    to_connect = desired - current_networks
    to_disconnect = current_networks - desired - {SANDBOX_NETWORK}

    for net in to_connect:
        logger.info("Connecting network %s to container %s", net, container_name)
        await _docker_run(["docker", "network", "connect", net, container_name], timeout=10)

    for net in to_disconnect:
        logger.info("Disconnecting network %s from container %s", net, container_name)
        await _docker_run(["docker", "network", "disconnect", net, container_name], timeout=10)


async def _resolve_container(
    session_id: str | None,
    git_scope: str | None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    agent_networks: list[str] | None = None,
) -> str:
    """Find or create a sandbox container for this session+git_scope.

    Returns:
        Container name (used for docker exec).
    """
    session_id = _sanitize_param(session_id)
    git_scope = _sanitize_param(git_scope)
    repo_name = _sanitize_param(repo_name)
    repo_owner = _sanitize_param(repo_owner)

    if not session_id:
        raise ValueError("session_id is required")

    scope = git_scope or "current_project"
    key = f"{session_id}::{scope}"
    lock = _get_container_lock(key)

    async with lock:
        if key in sandbox_containers:
            entry = sandbox_containers[key]
            container_id = entry.get("container_id", entry["container_name"])
            if await _is_container_running(container_id):
                rc, _, _ = await _exec_in_container(container_id, ["echo", "ok"], timeout=5)
                if rc == 0:
                    _touch_sandbox(key)
                    return entry["container_name"]
                logger.warning(
                    "Container %s running but exec failed (setns?), recreating",
                    entry["container_name"],
                )
            else:
                reason = await _get_container_death_reason(container_id)
                logger.warning(
                    "Container %s not running (%s), recreating",
                    entry["container_name"],
                    reason or "unknown reason",
                )
            # Destroy the old sandbox BEFORE recreating, else its claim+pod leak
            # (the bare `del` here used to discard the handle without terminating
            # it, so recreate-on-flaky-liveness accumulated orphan SandboxClaims).
            try:
                await _destroy_container(session_id, scope)
            except Exception as e:
                logger.warning("Failed to destroy old sandbox on recreate: %s", e)
                sandbox_containers.pop(key, None)

        for attempt in range(2):
            try:
                return await _create_sandbox_container(
                    session_id, scope, repo_name, repo_owner, agent_networks=agent_networks
                )
            except Exception as e:
                if attempt == 0:
                    logger.warning("Sandbox creation failed (attempt 1), retrying: %s", e)
                    await asyncio.sleep(2)
                else:
                    raise


async def _resolve_sandbox_or_fail(
    session_id: str, git_scope: str | None, repo_name: str | None,
    repo_owner: str | None, sandbox_networks: list[str] | None = None,
) -> dict:
    """Resolve or recreate sandbox. Returns entry dict with container metadata."""
    container = await _resolve_container(
        session_id, git_scope, repo_name, repo_owner, agent_networks=sandbox_networks,
    )
    key = f"{session_id}::{git_scope or 'current_project'}"
    entry = sandbox_containers.get(key, {})
    entry["container_name"] = container
    return entry


@asynccontextmanager
async def _sandbox_session(
    session_id: str | None,
    git_scope: str | None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    agent_networks: list[str] | None = None,
):
    container = await _resolve_container(session_id, git_scope, repo_name, repo_owner, agent_networks)
    sid = _sanitize_param(session_id) or "unknown"
    scope = _sanitize_param(git_scope) or "current_project"
    key = f"{sid}::{scope}"
    net_lock = _get_network_lock(key)
    async with net_lock:
        await _sync_networks(container, agent_networks or [])
        yield container


async def _destroy_container(session_id: str, git_scope: str) -> None:
    """Stop and remove a sandbox container."""
    scope = git_scope or "current_project"
    key = f"{session_id}::{scope}"
    entry = sandbox_containers.pop(key, None)
    if not entry:
        return

    container_name = entry["container_name"]

    # K8s mode: terminate the sandbox via the SDK
    if SANDBOX_MODE == "k8s" and entry.get("_k8s_handle"):
        try:
            await _get_k8s_manager().destroy(entry["_k8s_handle"])
            logger.info("Destroyed K8s sandbox: %s", container_name)
        except Exception as e:
            logger.warning("Failed to destroy K8s sandbox %s: %s", container_name, e)
        return

    # Docker mode
    try:
        await _docker_run(["docker", "stop", container_name], timeout=15)
        await _docker_run(["docker", "rm", "-f", container_name], timeout=15)
        logger.info("Destroyed sandbox container: %s", container_name)
    except Exception as e:
        logger.warning("Failed to destroy container %s: %s", container_name, e)


async def _destroy_all_for_session(session_id: str) -> None:
    """Destroy all containers/sandboxes for a session (on done/pause/error)."""
    keys_to_remove = [k for k in sandbox_containers if k.startswith(f"{session_id}::")]
    for key in keys_to_remove:
        entry = sandbox_containers.pop(key)
        container_name = entry["container_name"]
        try:
            if SANDBOX_MODE == "k8s" and entry.get("_k8s_handle"):
                await _get_k8s_manager().destroy(entry["_k8s_handle"])
            else:
                await _docker_run(["docker", "stop", container_name], timeout=15)
                await _docker_run(["docker", "rm", "-f", container_name], timeout=15)
        except Exception as e:
            logger.warning("Failed to destroy container %s: %s", container_name, e)
    if keys_to_remove:
        logger.info(
            "Destroyed %d containers for session %s", len(keys_to_remove), session_id
        )


async def _cleanup_orphan_containers() -> int:
    """Remove sandboxes left over from a previous server run (startup) or leaked.

    Called once at server startup and periodically by the sandbox watchdog.
    """
    if SANDBOX_MODE == "k8s":
        try:
            mgr = _get_k8s_manager()
            known = set(sandbox_containers.keys())
            return await mgr.cleanup_orphan_claims(known)
        except Exception as e:
            logger.warning("k8s orphan cleanup failed: %s", e)
            return 0

    rc, stdout, _ = await _docker_run(
        ["docker", "ps", "-a", "--filter", "name=druppie-",
         "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"],
        timeout=30,
    )
    if rc != 0:
        logger.warning("Failed to list containers for orphan cleanup: rc=%d", rc)
        return 0

    tracked_names = {entry["container_name"] for entry in sandbox_containers.values()}
    orphan_names = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        name = parts[0]
        if name.startswith("k8s_"):
            continue
        compose_project = parts[1] if len(parts) > 1 else ""
        if compose_project:
            continue
        if name in tracked_names:
            continue
        orphan_names.append(name)

    cleaned = 0
    for name in orphan_names:
        logger.info("Removing orphan sandbox container: %s", name)
        try:
            await _docker_run(["docker", "rm", "-f", name], timeout=15)
            cleaned += 1
        except Exception as e:
            logger.warning("Failed to remove orphan container %s: %s", name, e)

    if cleaned:
        logger.info("Cleaned up %d orphan sandbox container(s)", cleaned)
    return cleaned


# =============================================================================
# GITEA API HELPERS
# =============================================================================


def _gitea_api_headers() -> dict:
    """Build Gitea API auth headers."""
    headers = {"Content-Type": "application/json"}
    if GITEA_TOKEN:
        headers["Authorization"] = f"token {GITEA_TOKEN}"
    elif GITEA_USER and GITEA_PASSWORD:
        import base64

        credentials = base64.b64encode(
            f"{GITEA_USER}:{GITEA_PASSWORD}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {credentials}"
    return headers


def _inject_gitea_token(repo_owner: str, repo_name: str, base_url: str | None = None) -> str:
    """Build an authenticated Gitea git-over-HTTP push URL (host-side only).

    Uses the same ``user:password`` basic auth as ``_get_gitea_clone_url`` — the
    admin account has repo write access and this is proven to authenticate by the
    clone step. ``GITEA_TOKEN`` is the *REST API* token (``Authorization: token
    …``); as a git password it needs ``write:repository`` scope and is frequently
    scoped read-only, which surfaces as ``authentication failed`` on push, so it
    is only a fallback here.

    For the external Gitea (aigit.waterschap.org) the ``EXTERNAL_GITEA_TOKEN``
    is used instead (OAuth2 token with ``git clone`` scope).
    """
    base = (base_url or GITEA_URL).rstrip("/")
    if "aigit.waterschap.org" in base and EXTERNAL_GITEA_TOKEN:
        return f"https://oauth2:{EXTERNAL_GITEA_TOKEN}@aigit.waterschap.org/{repo_owner}/{repo_name}.git"
    scheme, _, rest = base.partition("://")
    if GITEA_USER and GITEA_PASSWORD:
        from urllib.parse import quote

        return (
            f"{scheme}://{quote(GITEA_USER)}:{quote(GITEA_PASSWORD)}"
            f"@{rest}/{repo_owner}/{repo_name}.git"
        )
    if GITEA_TOKEN:
        user = GITEA_USER or "oauth2"
        return f"{scheme}://{user}:{GITEA_TOKEN}@{rest}/{repo_owner}/{repo_name}.git"
    return f"{base}/{repo_owner}/{repo_name}.git"


def _is_gitea_configured() -> bool:
    """Check if Gitea is configured with credentials."""
    return bool(GITEA_TOKEN or (GITEA_USER and GITEA_PASSWORD))


# =============================================================================
# MCP TOOLS — FILE OPERATIONS
# =============================================================================


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def read_file(
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Read file from the sandbox workspace.

    Args:
        path: File path relative to workspace
        session_id: Session ID (auto-creates sandbox if needed)
        project_id: Project ID (optional)
        user_id: User ID (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope (current_project, update_core, other_projects)

    Returns:
        Dict with success, content, path, size
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            rc, stdout, stderr = await _exec_in_container(
                container, ["cat", cpath], timeout=30
            )
            if rc != 0:
                return {"success": False, "error": f"File not found: {path}"}

            logger.info("Read file: %s (%d bytes)", path, len(stdout))
            return {
                "success": True,
                "content": stdout,
                "path": path,
                "size": len(stdout),
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error reading file %s: %s", path, e)
        return {"success": False, "error": str(e)}


async def _write_file_impl(
    path: str,
    content: str,
    session_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            parent = str(Path(cpath).parent)
            await _exec_in_container(container, ["mkdir", "-p", parent])

            rc, stderr = await _write_to_container(container, cpath, content)
            if rc != 0:
                return {"success": False, "error": f"Write failed: {stderr}"}

            logger.info("Wrote file: %s (%d bytes)", path, len(content))
            return {
                "success": True,
                "path": path,
                "size": len(content),
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error writing file %s: %s", path, e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def write_file(
    path: str,
    content: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Write (create or overwrite) a file in the sandbox workspace.

    Args:
        path: File path relative to workspace
        content: File content to write
        session_id: Session ID (auto-creates sandbox if needed)
        project_id: Project ID (optional)
        user_id: User ID (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope (current_project, update_core, other_projects)

    Returns:
        Dict with success, path, size
    """
    return await _write_file_impl(path, content, session_id, repo_name, repo_owner, git_scope, sandbox_networks)


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Edit an existing file by replacing old_string with new_string (must be unique).

    IMPORTANT: This tool can ONLY edit files that already exist. It CANNOT create new files.
    If the file does not exist, the tool returns: {"success": false, "error": "File not found: <path>"}

    To CREATE a new file, use one of these tools instead:
    - write_file(path, content, ...) — creates or overwrites a single file
    - batch_write_files(files, ...) — creates multiple files in one call

    Args:
        path: File path relative to workspace
        old_string: Text to find (must appear exactly once)
        new_string: Replacement text
        session_id: Session ID
        project_id: Project ID (optional)
        user_id: User ID (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, path, replaced
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            rc, stdout, stderr = await _exec_in_container(
                container, ["cat", cpath], timeout=30
            )
            if rc != 0:
                return {"success": False, "error": f"File not found: {path}"}

            content = stdout
            count = content.count(old_string)
            if count == 0:
                return {"success": False, "error": f"old_string not found in {path}"}
            if count > 1:
                return {
                    "success": False,
                    "error": (
                        f"old_string appears {count} times in {path}, "
                        "expected exactly 1 — add more context to make it unique"
                    ),
                }

            new_content = content.replace(old_string, new_string, 1)

            rc, stderr = await _write_to_container(container, cpath, new_content)
            if rc != 0:
                return {"success": False, "error": f"Write failed: {stderr}"}

            logger.info("Edited file: %s", path)
            return {"success": True, "path": path, "replaced": True}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error editing file %s: %s", path, e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def bash(
    command: str,
    timeout: int = 120,
    max_output_bytes: int = 8192,
    output_side: str = "tail",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
    tool_call_id: str | None = None,
) -> dict:
    """Execute a shell command in the sandbox container.

    Blocked commands: destructive operations (rm -rf /, sudo, etc.)
    and git push/remote/credential (agents must use push_changes).

    Safe git commands are allowed: add, commit, status, log, diff, branch.

    Args:
        command: Shell command to execute
        timeout: Command timeout in seconds (default 120)
        max_output_bytes: Max bytes to return. Output exceeding this is truncated
            and full output saved to /workspace/.bash_outputs/{id}.log.
            Set to 0 for unlimited (dangerous with long-running commands).
        output_side: Which part to keep when truncating: "tail" (last N bytes)
            or "head" (first N bytes). Default "tail".
        session_id: Session ID
        project_id: Project ID (optional)
        user_id: User ID (optional)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, stdout, stderr, return_code
    """
    output_file = f"/tmp/bash_{tool_call_id}.out" if tool_call_id else None
    try:
        blocked, pattern = _is_command_blocked(command)
        if blocked:
            logger.warning("Blocked command: matched pattern '%s'", pattern)
            return {
                "success": False,
                "error": f"Command blocked for safety (matched pattern: {pattern})",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }

        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:

            save_file = output_file or f"/tmp/bash_{tool_call_id or 'out'}.out"
            rc, stdout, stderr = await _exec_bash_in_container(
                container, command, timeout=timeout, output_file=save_file
            )

            combined = (stdout or "") + (stderr or "")
            combined_bytes = combined.encode()
            truncated = max_output_bytes > 0 and len(combined_bytes) > max_output_bytes

            if truncated:
                full_path = f"/workspace/.bash_outputs/{tool_call_id or 'output'}.log"
                await _exec_in_container(
                    container,
                    ["bash", "-c", f"mkdir -p /workspace/.bash_outputs && cp {shlex.quote(save_file)} {shlex.quote(full_path)}"],
                    timeout=5,
                )
                if output_side == "head":
                    snippet = combined_bytes[:max_output_bytes].decode(errors="replace")
                else:
                    snippet = combined_bytes[-max_output_bytes:].decode(errors="replace")
                display = f"... [OUTPUT TRUNCATED ({len(combined_bytes)} bytes) - full output saved to {full_path}, use search_file or read_file to examine it]\n\n{snippet}"
            else:
                display = combined

            if output_file:
                await _exec_in_container(container, ["rm", "-f", output_file], timeout=5)

            return {
                "success": rc == 0,
                "stdout": display if truncated else stdout,
                "stderr": "" if truncated else stderr,
                "return_code": rc,
            }

    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }
    except Exception as e:
        logger.error("Error executing bash command: %s", e)
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def get_partial_output(
    tool_call_id: str,
    session_id: str | None = None,
    git_scope: str | None = None,
) -> dict:
    """Get partial output from a running bash command."""
    try:
        container = await _resolve_container(session_id, git_scope, None, None)
        output_file = f"/tmp/bash_{tool_call_id}.out"
        rc, stdout, stderr = await _exec_in_container(
            container, ["cat", output_file], timeout=5
        )
        return {"output": stdout, "exists": rc == 0}
    except ValueError as e:
        return {"output": "", "exists": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting partial output: %s", e)
        return {"output": "", "exists": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def grep(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Search file contents using regex pattern.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file path to search in (default ".")
        include: Glob pattern to filter files (e.g. "*.py", "*.{js,ts}")
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, matches, count
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            cmd = ["grep", "-rn", "-E", "--binary-files=without-match", pattern, cpath]
            if include:
                cmd.extend(["--include", include])

            rc, stdout, stderr = await _exec_in_container(container, cmd, timeout=60)

            if rc == 2:
                return {"success": False, "error": f"grep error: {stderr}", "matches": [], "count": 0}

            matches = []
            for line in stdout.strip().split("\n"):
                if line.strip():
                    rel = line.strip().replace("/workspace/", "", 1)
                    matches.append(rel)

            return {"success": True, "matches": matches, "count": len(matches)}

    except ValueError as e:
        return {"success": False, "error": str(e), "matches": [], "count": 0}
    except Exception as e:
        logger.error("Error grepping: %s", e)
        return {"success": False, "error": str(e), "matches": [], "count": 0}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def find(
    path: str = ".",
    name: str | None = None,
    type: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Find files and directories matching criteria.

    Args:
        path: Directory to search in (default ".")
        name: Glob pattern to match file/directory names
        type: Filter by type: "file" or "dir"
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, files, count
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            cmd = ["find", cpath]
            if name:
                cmd.extend(["-name", name])
            if type == "file":
                cmd.extend(["-type", "f"])
            elif type == "dir":
                cmd.extend(["-type", "d"])

            cmd.extend([
                "-not", "-path", "*/.git/*",
                "-not", "-path", "*/node_modules/*",
                "-not", "-path", "*/__pycache__/*",
                "-not", "-path", "*/.venv/*",
            ])

            rc, stdout, stderr = await _exec_in_container(container, cmd, timeout=60)

            if rc != 0:
                return {"success": False, "error": stderr, "files": [], "count": 0}

            results = []
            for line in stdout.strip().split("\n"):
                stripped = line.strip()
                if stripped and stripped != "/workspace" and stripped != cpath:
                    rel = stripped.replace("/workspace/", "", 1)
                    if rel:
                        results.append(rel)

            return {"success": True, "files": results, "count": len(results)}

    except ValueError as e:
        return {"success": False, "error": str(e), "files": [], "count": 0}
    except Exception as e:
        logger.error("Error finding files: %s", e)
        return {"success": False, "error": str(e), "files": [], "count": 0}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def ls(
    path: str = ".",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """List files in a directory (simple name-only listing).

    Args:
        path: Directory path (default ".")
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, files, count
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            rc, stdout, stderr = await _exec_in_container(
                container, ["ls", "-1", cpath], timeout=30
            )
            if rc != 0:
                return {"success": False, "error": f"Path not found: {path}"}

            files = [f for f in stdout.strip().split("\n") if f.strip()]
            return {"success": True, "files": files, "count": len(files)}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing directory: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def list_dir(
    path: str = ".",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    recursive: bool = False,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """List directory contents with details (permissions, size, type).

    Args:
        path: Directory path (default ".")
        session_id: Session ID
        recursive: Whether to list recursively
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, entries, count
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            if recursive:
                cmd = [
                    "find", cpath,
                    "-not", "-path", "*/.git/*",
                    "-not", "-path", "*/node_modules/*",
                ]
                rc, stdout, stderr = await _exec_in_container(container, cmd, timeout=60)
                if rc != 0:
                    return {"success": False, "error": stderr}

                entries = []
                for line in stdout.strip().split("\n"):
                    stripped = line.strip()
                    if stripped and stripped != cpath:
                        rel = stripped.replace("/workspace/", "", 1)
                        if rel:
                            entries.append(rel)
            else:
                cmd = ["ls", "-la", cpath]
                rc, stdout, stderr = await _exec_in_container(container, cmd, timeout=30)
                if rc != 0:
                    return {"success": False, "error": f"Path not found: {path}"}

                entries = []
                for line in stdout.strip().split("\n"):
                    line = line.strip()
                    if not line or line.startswith("total"):
                        continue
                    parts = line.split()
                    if len(parts) >= 9:
                        entries.append({
                            "name": " ".join(parts[8:]),
                            "permissions": parts[0],
                            "size": parts[4],
                            "type": "dir" if parts[0].startswith("d") else "file",
                        })

            return {"success": True, "entries": entries, "count": len(entries)}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing directory: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def batch_write_files(
    files: list[dict[str, str]],
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Write multiple files to workspace in a single operation.

    Files are written to disk only. Use bash("git add -A && git commit -m ...")
    to commit, push_changes to push, and create_pr to open a PR.

    Args:
        files: List of file objects, each with 'path' and 'content' keys
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, files_created list, file_count

    Example:
        batch_write_files(
            session_id="...",
            files=[
                {"path": "src/index.js", "content": "console.log('hello');"},
                {"path": "package.json", "content": '{"name": "myapp"}'}
            ]
        )
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:

            files_created = []
            errors = []

            for file_entry in files:
                fpath = file_entry.get("path")
                content = file_entry.get("content")
                if not fpath or content is None:
                    errors.append({"path": fpath, "error": "Missing path or content"})
                    continue

                try:
                    cpath = _container_path(fpath)
                    parent = str(Path(cpath).parent)
                    await _exec_in_container(container, ["mkdir", "-p", parent])

                    rc, stderr = await _write_to_container(container, cpath, content)
                    if rc == 0:
                        files_created.append(fpath)
                    else:
                        errors.append({"path": fpath, "error": stderr})

                except Exception as e:
                    errors.append({"path": fpath, "error": str(e)})

            if not files_created:
                return {"success": False, "error": "No files were created", "errors": errors}

            result = {
                "success": True,
                "files_created": files_created,
                "file_count": len(files_created),
            }
            if errors:
                result["errors"] = errors
            return result

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def delete_file(
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Delete a file from the sandbox workspace.

    Args:
        path: File path relative to workspace
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, path
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            rc, _, stderr = await _exec_in_container(
                container, ["rm", "-f", cpath], timeout=10
            )
            if rc != 0:
                return {"success": False, "error": f"Delete failed: {stderr}"}

            logger.info("Deleted file: %s", path)
            return {"success": True, "path": path}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting file %s: %s", path, e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def search_files(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Search file contents recursively (alias for grep).

    Args:
        pattern: Regex pattern to search for
        path: Directory to search in (default ".")
        include: Glob pattern to filter files
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, matches, count
    """
    return await grep(
        pattern=pattern,
        path=path,
        include=include,
        session_id=session_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        git_scope=git_scope,
        sandbox_networks=sandbox_networks,
    )


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def get_file_info(
    path: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Get file information (stat) for a file in the sandbox.

    Args:
        path: File path relative to workspace
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, stat (raw stat output)
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            cpath = _container_path(path)

            rc, stdout, stderr = await _exec_in_container(
                container, ["stat", cpath], timeout=10
            )
            if rc != 0:
                return {"success": False, "error": f"File not found: {path}"}

            return {"success": True, "path": path, "stat": stdout.strip()}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting file info: %s", e)
        return {"success": False, "error": str(e)}


# =============================================================================
# MCP TOOLS — GIT OPERATIONS
# =============================================================================


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def get_git_status(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Get git status of the sandbox workspace (read-only, safe).

    Convenience tool for quick workspace state checks. Referenced in agent
    YAML definitions.

    Args:
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, output (git status output)
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            rc, stdout, stderr = await _exec_in_container(
                container, ["git", "status"], timeout=15
            )
            if rc != 0:
                return {"success": False, "error": stderr}

            return {"success": True, "output": stdout}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting git status: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def push_changes(
    session_id: str | None = None,
    target_branch: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Push changes from sandbox via git bundle to Gitea.

    The sandbox container has NO git credentials. This tool:
    1. Auto-commits any uncommitted changes inside the container
    2. Creates a git bundle inside the container (no credentials needed)
    3. Copies the bundle to the host (module-coding container)
    4. Extracts and pushes to Gitea WITH credentials on the host side

    Args:
        session_id: Session ID
        target_branch: Branch to push to on Gitea (defaults to current branch)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, branch, pushed_to
    """
    try:
        session_id = _sanitize_param(session_id)
        target_branch = _sanitize_param(target_branch)
        repo_name = _sanitize_param(repo_name)
        repo_owner = _sanitize_param(repo_owner)
        git_scope = _sanitize_param(git_scope)

        if not session_id:
            return {"success": False, "error": "session_id is required"}

        entry = await _resolve_sandbox_or_fail(
            session_id, git_scope, repo_name, repo_owner, sandbox_networks,
        )
        container = entry["container_name"]
        branch = entry.get("branch", "main")
        resolved_repo_name = entry.get("repo_name") or repo_name
        resolved_repo_owner = entry.get("repo_owner") or repo_owner or GITEA_ORG
        resolved_gitea_url = entry.get("gitea_url", GITEA_URL)
        scope = git_scope or "current_project"

        if not resolved_repo_name:
            return {"success": False, "error": "repo_name is required for push_changes"}

        # Get current branch from container (may have changed via bash git checkout)
        rc, stdout, _ = await _exec_in_container(
            container, ["git", "branch", "--show-current"], timeout=10
        )
        if rc == 0 and stdout.strip():
            branch = stdout.strip()
            entry["branch"] = branch

        push_branch = target_branch or branch

        # Auto-commit any uncommitted changes
        rc, status_out, _ = await _exec_in_container(
            container, ["git", "status", "--porcelain"], timeout=10
        )
        if status_out.strip():
            await _exec_in_container(container, ["git", "add", "-A"], timeout=30)
            rc, _, stderr = await _exec_in_container(
                container,
                ["git", "commit", "-m", f"Auto-commit: push to {push_branch}"],
                timeout=30,
            )
            if rc != 0 and "nothing to commit" not in stderr:
                logger.warning("Auto-commit warning: %s", stderr)

        # Create git bundle inside container
        bundle_name = f"changes-{uuid.uuid4().hex[:8]}.bundle"
        bundle_container_path = f"/tmp/{bundle_name}"

        rc, _, stderr = await _exec_in_container(
            container,
            ["git", "bundle", "create", bundle_container_path, "HEAD", "^origin/main"],
            timeout=120,
        )
        if rc != 0:
            # Fallback: bundle everything (e.g. no origin/main reference)
            rc, _, stderr = await _exec_in_container(
                container,
                ["git", "bundle", "create", bundle_container_path, "--all"],
                timeout=120,
            )
        if rc != 0:
            return {"success": False, "error": f"git bundle create failed: {stderr}"}

        # Copy bundle from sandbox container to host
        tmpdir = tempfile.mkdtemp(prefix="druppie-git-")
        try:
            bundle_host_path = os.path.join(tmpdir, bundle_name)
            await _copy_from_container(container, bundle_container_path, bundle_host_path)

            # Extract bundle on host side into bare repo
            bare_repo = os.path.join(tmpdir, "bare")
            rc, _, stderr = await _docker_run(
                ["git", "init", "--bare", bare_repo], timeout=30
            )
            if rc != 0:
                return {"success": False, "error": f"git init --bare failed: {stderr}"}

            # Fetch base branch from Gitea so prerequisites exist for bundle fetch
            push_url = _inject_gitea_token(resolved_repo_owner, resolved_repo_name, resolved_gitea_url)
            rc, _, stderr = await _docker_run(
                ["git", "-c", "http.sslVerify=false", "-C", bare_repo, "fetch", push_url, "main:refs/heads/main"],
                timeout=60,
            )
            if rc != 0:
                logger.warning(
                    "Base branch fetch failed (%s), proceeding with bundle anyway",
                    stderr[:200],
                )

            rc, _, stderr = await _docker_run(
                ["git", "-C", bare_repo, "fetch", bundle_host_path, f"HEAD:refs/heads/{branch}"],
                timeout=60,
            )
            if rc != 0:
                return {
                    "success": False,
                    "error": f"git fetch from bundle failed: {stderr}",
                }

            # Push to Gitea with credentials
            rc, _, stderr = await _docker_run(
                ["git", "-c", "http.sslVerify=false", "-C", bare_repo, "push", push_url, f"{branch}:{push_branch}"],
                timeout=60,
            )
            if rc != 0:
                return {
                    "success": False,
                    "error": f"git push to Gitea failed: {stderr}",
                }

            logger.info(
                "Pushed %s/%s branch=%s to %s",
                resolved_repo_owner, resolved_repo_name, branch, push_branch,
            )

            return {
                "success": True,
                "branch": branch,
                "pushed_to": push_branch,
            }

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            await _exec_in_container(
                container, ["rm", "-f", bundle_container_path], timeout=10
            )

    except Exception as e:
        logger.error("Error in push_changes: %s", e)
        return {"success": False, "error": str(e)}


async def _copy_to_container(
    container_id: str, src_path: str, dst_path: str
) -> None:
    """Copy a file from the host into a container (reverse of _copy_from_container)."""
    if SANDBOX_MODE == "k8s":
        entry = _find_entry_by_container_id(container_id)
        if entry and entry.get("_k8s_handle"):
            with open(src_path, "rb") as f:
                data = f.read()
            await _get_k8s_manager().write_file(
                entry["_k8s_handle"], dst_path, data
            )
            return
    with open(src_path, "rb") as f:
        data = f.read()
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container_id, "sh", "-c", f"cat > {dst_path}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(data), timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec cat > failed: {stderr.decode().strip()}")


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def git_fetch(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Fetch all branches from Gitea into the sandbox via git bundle.

    The sandbox has no git credentials. This tool fetches on the host
    (with credentials), creates a bundle, and imports it into the sandbox.
    After fetching, use bash(git checkout <branch>) to switch branches.
    """
    try:
        session_id = _sanitize_param(session_id)
        repo_name = _sanitize_param(repo_name)
        repo_owner = _sanitize_param(repo_owner)
        git_scope = _sanitize_param(git_scope)

        if not session_id:
            return {"success": False, "error": "session_id is required"}

        entry = await _resolve_sandbox_or_fail(
            session_id, git_scope, repo_name, repo_owner, sandbox_networks,
        )
        container = entry["container_name"]
        resolved_repo_name = entry.get("repo_name") or repo_name
        resolved_repo_owner = entry.get("repo_owner") or repo_owner or GITEA_ORG
        resolved_gitea_url = entry.get("gitea_url", GITEA_URL)

        if not resolved_repo_name:
            return {"success": False, "error": "repo_name is required for git_fetch"}

        fetch_url = _inject_gitea_token(resolved_repo_owner, resolved_repo_name, resolved_gitea_url)

        tmpdir = tempfile.mkdtemp(prefix="druppie-git-fetch-")
        try:
            bare_repo = os.path.join(tmpdir, "bare")
            rc, _, stderr = await _docker_run(
                ["git", "init", "--bare", bare_repo], timeout=30,
            )
            if rc != 0:
                return {"success": False, "error": f"git init --bare failed: {stderr}"}

            rc, _, stderr = await _docker_run(
                ["git", "-c", "http.sslVerify=false", "-C", bare_repo, "fetch", fetch_url, "+refs/heads/*:refs/heads/*"],
                timeout=120,
            )
            if rc != 0:
                return {"success": False, "error": f"git fetch from Gitea failed: {stderr}"}

            bundle_name = f"fetch-{uuid.uuid4().hex[:8]}.bundle"
            bundle_host_path = os.path.join(tmpdir, bundle_name)
            bundle_container_path = f"/tmp/{bundle_name}"

            rc, _, stderr = await _docker_run(
                ["git", "-C", bare_repo, "bundle", "create", bundle_host_path, "--all"],
                timeout=60,
            )
            if rc != 0:
                return {"success": False, "error": f"git bundle create failed: {stderr}"}

            await _copy_to_container(container, bundle_host_path, bundle_container_path)

            rc, _, stderr = await _exec_in_container(
                container,
                ["git", "fetch", bundle_container_path, "+refs/heads/*:refs/remotes/origin/*"],
                timeout=60,
            )
            if rc != 0:
                return {"success": False, "error": f"git fetch from bundle in sandbox failed: {stderr}"}

            rc, branches_out, _ = await _exec_in_container(
                container, ["git", "branch", "-r"], timeout=10,
            )

            await _exec_in_container(
                container, ["rm", "-f", bundle_container_path], timeout=10,
            )

            logger.info("git_fetch success for %s/%s", resolved_repo_owner, resolved_repo_name)
            return {
                "success": True,
                "message": "All branches fetched. Use bash(git checkout <branch>) to switch.",
                "branches": branches_out.strip(),
            }

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    except Exception as e:
        logger.error("Error in git_fetch: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def git_pull(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Pull (fetch + merge) from Gitea into the sandbox current branch.

    Fetches all branches via git bundle, then merges the remote version
    of the current branch into the working tree. Use this when push_changes
    fails with 'non-fast-forward' or 'rejected'.

    IMPORTANT: If you have uncommitted changes, use bash to stash them first:
      bash(command="git stash")
    Then call git_pull, then restore your changes:
      bash(command="git stash pop")
    """
    try:
        session_id = _sanitize_param(session_id)
        repo_name = _sanitize_param(repo_name)
        repo_owner = _sanitize_param(repo_owner)
        git_scope = _sanitize_param(git_scope)

        if not session_id:
            return {"success": False, "error": "session_id is required"}

        entry = await _resolve_sandbox_or_fail(
            session_id, git_scope, repo_name, repo_owner, sandbox_networks,
        )
        container = entry["container_name"]
        resolved_repo_name = entry.get("repo_name") or repo_name
        resolved_repo_owner = entry.get("repo_owner") or repo_owner or GITEA_ORG

        if not resolved_repo_name:
            return {"success": False, "error": "repo_name is required for git_pull"}

        rc, branch_out, _ = await _exec_in_container(
            container, ["git", "branch", "--show-current"], timeout=10,
        )
        current_branch = branch_out.strip() if rc == 0 else "main"

        fetch_result = await git_fetch(
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
            git_scope=git_scope,
            sandbox_networks=sandbox_networks,
        )
        if not fetch_result.get("success"):
            return fetch_result

        rc, merge_out, merge_err = await _exec_in_container(
            container, ["git", "merge", f"origin/{current_branch}", "--no-edit"], timeout=60,
        )
        if rc != 0:
            return {
                "success": False,
                "error": f"git merge failed: {merge_err}",
                "hint": "Fetch succeeded but merge had conflicts. Use bash to resolve conflicts, then commit.",
                "branch": current_branch,
            }

        logger.info("git_pull success, merged origin/%s", current_branch)
        return {
            "success": True,
            "message": f"Pulled and merged origin/{current_branch}",
            "branch": current_branch,
            "merge_output": merge_out.strip(),
        }

    except Exception as e:
        logger.error("Error in git_pull: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def create_pr(
    pr_title: str,
    pr_body: str = "",
    head_branch: str | None = None,
    base_branch: str = "main",
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Create a Pull Request on Gitea from an existing pushed branch.

    Args:
        pr_title: Pull request title
        pr_body: Pull request description (optional)
        head_branch: Source branch for the PR (defaults to current branch)
        base_branch: Target branch for the PR (default: main)
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, pr_number, pr_url, html_url, branch
    """
    try:
        session_id = _sanitize_param(session_id)
        head_branch = _sanitize_param(head_branch)
        base_branch = _sanitize_param(base_branch) or "main"
        repo_name = _sanitize_param(repo_name)
        repo_owner = _sanitize_param(repo_owner)
        git_scope = _sanitize_param(git_scope)

        if not session_id:
            return {"success": False, "error": "session_id is required"}

        entry = await _resolve_sandbox_or_fail(
            session_id, git_scope, repo_name, repo_owner, sandbox_networks,
        )
        container = entry["container_name"]
        branch = entry.get("branch", "main")
        resolved_repo_name = entry.get("repo_name") or repo_name
        resolved_repo_owner = entry.get("repo_owner") or repo_owner or GITEA_ORG
        resolved_gitea_url = entry.get("gitea_url", GITEA_URL)

        if not resolved_repo_name:
            return {"success": False, "error": "repo_name is required for create_pr"}

        if not head_branch:
            rc, stdout, _ = await _exec_in_container(
                container, ["git", "branch", "--show-current"], timeout=10
            )
            if rc == 0 and stdout.strip():
                head_branch = stdout.strip()
                entry["branch"] = head_branch
            else:
                head_branch = branch

        # --- Gitea PR path ---
        api_url = f"{resolved_gitea_url}/api/v1/repos/{resolved_repo_owner}/{resolved_repo_name}/pulls"
        pr_body_clean = pr_body.replace("\\n", "\n")
        payload = json.dumps({
            "head": head_branch,
            "base": base_branch,
            "title": pr_title,
            "body": pr_body_clean,
        })

        curl_headers = ["Content-Type: application/json"]
        is_external = "aigit.waterschap.org" in resolved_gitea_url
        if is_external and EXTERNAL_GITEA_TOKEN:
            curl_headers.append(f"Authorization: token {EXTERNAL_GITEA_TOKEN}")
        elif GITEA_TOKEN:
            curl_headers.append(f"Authorization: token {GITEA_TOKEN}")
        elif GITEA_USER and GITEA_PASSWORD:
            import base64 as _b64

            creds = _b64.b64encode(
                f"{GITEA_USER}:{GITEA_PASSWORD}".encode()
            ).decode()
            curl_headers.append(f"Authorization: Basic {creds}")
        else:
            return {
                "success": False,
                "error": "No Gitea credentials configured (GITEA_TOKEN or GITEA_USER+GITEA_PASSWORD)",
            }

        curl_args = ["curl", "-s", "-k", "-w", "\\n%{http_code}", "-X", "POST", api_url]
        for h in curl_headers:
            curl_args += ["-H", h]
        curl_args += ["-d", payload]

        proc = await asyncio.create_subprocess_exec(
            *curl_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return {
                "success": False,
                "error": f"Gitea PR creation failed (curl error): {stderr.decode()}",
            }

        # curl -w appends HTTP status code on the last line
        raw = stdout.decode()
        body, _, status_line = raw.rpartition("\n")
        http_status = int(status_line.strip()) if status_line.strip().isdigit() else 0
        pr_data = json.loads(body) if body.strip() else {}

        # Check for HTTP-level errors
        if http_status < 200 or http_status >= 300:
            err_msg = pr_data.get("message", body[:500]) if isinstance(pr_data, dict) else body[:500]
            logger.error(
                "Gitea PR creation HTTP %s: %s", http_status, err_msg,
            )
            return {
                "success": False,
                "error": f"Gitea PR creation HTTP {http_status}: {err_msg}",
            }

        pr_number = pr_data.get("number")
        html_url = pr_data.get("html_url", "")

        if not pr_number:
            logger.error(
                "Gitea PR response missing 'number': %s", body[:500],
            )
            return {
                "success": False,
                "error": f"Gitea PR response missing 'number': {body[:500]}",
            }

        logger.info(
            "Created PR #%s for %s/%s branch=%s",
            pr_number, resolved_repo_owner, resolved_repo_name, head_branch,
        )

        return {
            "success": True,
            "pr_number": pr_number,
            "pr_url": html_url,
            "html_url": html_url,
            "branch": head_branch,
        }

    except Exception as e:
        logger.error("Error in create_pr: %s", e)
        return {"success": False, "error": str(e)}


# =============================================================================
# MCP TOOLS — DESIGN VALIDATION
# =============================================================================


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def make_design(
    path: str,
    content: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Write a design document with Mermaid syntax validation.

    Validates all Mermaid diagrams in the markdown content before writing.
    If validation fails, the file is NOT written and errors are returned.

    Args:
        path: File path for the design document (e.g. "docs/functional-design.md")
        content: Full markdown content for the design document
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, path, size — or error with Mermaid validation details
    """
    try:
        # Validate Mermaid syntax before writing
        errors = validate_mermaid_in_markdown(content)
        if errors:
            error_lines = [
                f"Line {e.line_number} [{e.rule}]: {e.message}" for e in errors
            ]
            error_msg = (
                "MERMAID SYNTAX ERRORS — file was NOT written. "
                "Fix these errors and try again:\n\n"
                + "\n".join(error_lines)
                + "\n\nAfter fixing, call make_design again with the corrected content."
            )
            return {"success": False, "error": error_msg}

        return await _write_file_impl(
            path=path,
            content=content,
            session_id=session_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
            git_scope=git_scope,
            sandbox_networks=sandbox_networks,
        )

    except Exception as e:
        logger.error("Error writing design: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "internal": True},
)
async def validate_design(content: str) -> dict:
    """Validate Mermaid syntax in markdown content without writing a file.

    Internal tool for pre-validation of design documents.

    Args:
        content: Full markdown content to validate

    Returns:
        Dict with valid (bool) and optionally errors list
    """
    try:
        errors = validate_mermaid_in_markdown(content)
        if errors:
            return {
                "valid": False,
                "errors": [
                    {
                        "line_number": e.line_number,
                        "rule": e.rule,
                        "message": e.message,
                    }
                    for e in errors
                ],
            }
        return {"valid": True}
    except Exception as e:
        logger.error("Error validating design: %s", e)
        return {"valid": False, "errors": [{"message": str(e)}]}


# =============================================================================
# MCP TOOLS — TESTING (proxied to sandbox container)
# =============================================================================

# Regex patterns for test output parsing (duplicated from testing_module.py
# to keep tools.py self-contained for container exec)
_RE_JEST = re.compile(
    r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total"
)
_RE_VITEST = re.compile(
    r"Tests\s+(?:(\d+)\s+failed\s*\|?\s*)?(?:(\d+)\s+skipped\s*\|?\s*)?(?:(\d+)\s+passed\s*)?\((\d+)\)"
)
_RE_PYTEST = re.compile(
    r"(?:(\d+) failed)?(?:,\s*)?(?:(\d+) passed)?(?:,\s*)?(?:(\d+) skipped)?(?:,\s*)?(?:(\d+) warnings)?"
    r"\s+in\s+[\d.]+s"
)
_RE_GENERIC_PASSED = re.compile(r"(\d+)\s+(?:passing|passed)")
_RE_GENERIC_FAILED = re.compile(r"(\d+)\s+(?:failing|failed)")


def _detect_framework_from_container(files_json: str) -> str:
    """Detect test framework from a JSON list of filenames."""
    filenames = set()
    try:
        for entry in json.loads(files_json):
            if isinstance(entry, str):
                filenames.add(entry)
            elif isinstance(entry, dict):
                filenames.add(entry.get("name", ""))
    except (json.JSONDecodeError, TypeError):
        # Fallback: treat as plain text
        filenames = {f.strip() for f in files_json.split("\n") if f.strip()}

    if any(f in filenames for f in ["vitest.config.ts", "vitest.config.js"]) or \
       any("vite.config" in f for f in filenames):
        return "vitest"
    if "jest.config.js" in filenames or "jest.config.ts" in filenames:
        return "jest"
    if any(f in filenames for f in ["pytest.ini", "pyproject.toml", "setup.cfg"]):
        return "pytest"
    if "package.json" in filenames:
        return "npm"
    if any(f in filenames for f in ["requirements.txt", "Pipfile"]):
        return "pytest"
    return "unknown"


async def _detect_package_manager(container: str) -> str:
    """Detect the package manager from lock files in the sandbox workspace."""
    lock_file_map = [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
        ("uv.lock", "uv"),
        ("poetry.lock", "poetry"),
        ("Pipfile.lock", "pipenv"),
    ]
    for lock_file, pm in lock_file_map:
        rc, _, _ = await _exec_in_container(
            container, ["test", "-f", f"/workspace/{lock_file}"], timeout=5
        )
        if rc == 0:
            return pm

    rc, _, _ = await _exec_in_container(
        container, ["test", "-f", "/workspace/requirements.txt"], timeout=5
    )
    if rc == 0:
        return "pip"

    rc, _, _ = await _exec_in_container(
        container, ["test", "-f", "/workspace/package.json"], timeout=5
    )
    if rc == 0:
        return "npm"

    return "unknown"


async def _detect_test_framework(container: str) -> dict:
    """Detect test framework inside a sandbox container."""
    rc, stdout, _ = await _exec_in_container(
        container, ["ls", "-1", "/workspace"], timeout=10
    )
    framework = _detect_framework_from_container(stdout)
    pm = await _detect_package_manager(container)

    if framework in ("npm", "vitest", "jest"):
        rc, pkg_stdout, _ = await _exec_in_container(
            container, ["cat", "/workspace/package.json"], timeout=10
        )
        if rc == 0:
            try:
                pkg = json.loads(pkg_stdout)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "vitest" in deps:
                    framework = "vitest"
                elif "jest" in deps:
                    framework = "jest"
                js_pm = pm if pm in ("npm", "pnpm", "yarn", "bun") else "npm"
                if "scripts" in pkg and "test" in pkg["scripts"]:
                    return {
                        "framework": framework,
                        "test_command": f"{js_pm} test",
                        "package_manager": js_pm,
                    }
            except json.JSONDecodeError:
                pass

    if framework == "pytest":
        py_pm = pm if pm in ("pip", "uv", "poetry", "pipenv") else "pip"
        return {
            "framework": "pytest",
            "test_command": "pytest",
            "package_manager": py_pm,
        }

    return {"framework": framework, "test_command": None, "package_manager": pm if pm != "unknown" else None}


def _parse_test_output(framework: str, stdout: str, stderr: str) -> dict:
    """Parse test command output to extract pass/fail counts."""
    output = stdout + "\n" + stderr

    if framework == "vitest":
        m = _RE_VITEST.search(output)
        if m:
            return {
                "failed": int(m.group(1) or 0),
                "skipped": int(m.group(2) or 0),
                "passed": int(m.group(3) or 0),
                "total": int(m.group(4)),
            }
    elif framework == "jest":
        m = _RE_JEST.search(output)
        if m:
            return {
                "failed": int(m.group(1) or 0),
                "skipped": int(m.group(2) or 0),
                "passed": int(m.group(3) or 0),
                "total": int(m.group(4)),
            }
    elif framework == "pytest":
        m = _RE_PYTEST.search(output)
        if m:
            return {
                "failed": int(m.group(1) or 0),
                "passed": int(m.group(2) or 0),
                "skipped": int(m.group(3) or 0),
            }

    # Generic fallback
    passed_m = _RE_GENERIC_PASSED.search(output)
    failed_m = _RE_GENERIC_FAILED.search(output)
    if passed_m or failed_m:
        return {
            "passed": int(passed_m.group(1)) if passed_m else 0,
            "failed": int(failed_m.group(1)) if failed_m else 0,
        }

    return {"raw_output": output[:2000]}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def get_test_framework(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Auto-detect test framework in sandbox workspace (pytest, vitest, jest)."""
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            info = await _detect_test_framework(container)

            if info["framework"] == "unknown":
                return {
                    "success": True,
                    "framework": "unknown",
                    "message": (
                        "No test framework detected yet. This is normal for new projects. "
                        "Read docs/technical-design.md to determine the tech stack and set up "
                        "the appropriate test framework."
                    ),
                }

            return {"success": True, **info}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error detecting test framework: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def run_tests(
    test_path: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Run tests in the sandbox workspace.

    Auto-detects the test framework and runs the appropriate command.
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            info = await _detect_test_framework(container)
            framework = info["framework"]

            if framework == "unknown":
                return {
                    "success": False,
                    "error": "No test framework detected. Install one first.",
                }

            path_arg = test_path or ""
            pm = info.get("package_manager", "npm")
            if framework == "pytest":
                cmd = f"cd /workspace && python -m pytest {shlex.quote(path_arg)} -v --tb=short 2>&1"
            elif framework in ("vitest", "jest", "npm"):
                if pm == "pnpm":
                    cmd = f"cd /workspace && pnpm test -- {shlex.quote(path_arg)} 2>&1"
                elif pm == "yarn":
                    cmd = f"cd /workspace && yarn test {shlex.quote(path_arg)} 2>&1"
                elif pm == "bun":
                    cmd = f"cd /workspace && bun test {shlex.quote(path_arg)} 2>&1"
                else:
                    cmd = f"cd /workspace && npm test -- {shlex.quote(path_arg)} 2>&1"
            else:
                return {"success": False, "error": f"Unsupported framework: {framework}"}

            rc, stdout, stderr = await _exec_bash_in_container(container, cmd, timeout=300)

            results = _parse_test_output(framework, stdout, stderr)
            results["framework"] = framework
            results["raw_output"] = (stdout + stderr)[:5000]

            return {
                "success": rc == 0,
                "results": results,
                "framework": framework,
            }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error running tests: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def get_coverage_report(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Get test coverage report from the sandbox workspace."""
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            info = await _detect_test_framework(container)
            framework = info["framework"]

            if framework == "pytest":
                rc, stdout, _ = await _exec_in_container(
                    container, ["cat", "/workspace/coverage.json"], timeout=10
                )
                if rc == 0:
                    try:
                        return {"success": True, "coverage": json.loads(stdout), "framework": framework}
                    except json.JSONDecodeError:
                        pass
                return {"success": False, "error": "No coverage data found. Run tests with coverage first."}

            elif framework in ("vitest", "jest"):
                rc, stdout, _ = await _exec_in_container(
                    container,
                    ["cat", "/workspace/coverage/coverage-summary.json"],
                    timeout=10,
                )
                if rc == 0:
                    try:
                        return {"success": True, "coverage": json.loads(stdout), "framework": framework}
                    except json.JSONDecodeError:
                        pass
                return {"success": False, "error": "No coverage data found. Run tests with coverage first."}

            return {"success": False, "error": f"Coverage not supported for framework: {framework}"}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting coverage: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def install_test_dependencies(
    dependencies: list[str] | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Install test dependencies in the sandbox workspace.

    Args:
        dependencies: List of dependency names to install (optional)
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, results
    """
    try:
        async with _sandbox_session(
            session_id, git_scope, repo_name, repo_owner,
            agent_networks=sandbox_networks,
        ) as container:
            info = await _detect_test_framework(container)
            framework = info["framework"]

            results = []
            pm = info.get("package_manager", "npm")

            if framework in ("vitest", "jest", "npm"):
                pm_cmds = {
                    "pnpm": "pnpm install",
                    "yarn": "yarn install",
                    "bun": "bun install",
                }
                install_cmd = pm_cmds.get(pm, "npm install")
                rc, stdout, stderr = await _exec_bash_in_container(
                    container, f"cd /workspace && {install_cmd} 2>&1", timeout=300
                )
                results.append({
                    "dependency": f"{pm} install (all)",
                    "success": rc == 0,
                    "output": (stdout + stderr)[:1000],
                })
            elif framework == "pytest":
                install_cmd = None
                if pm == "uv":
                    rc, _, _ = await _exec_in_container(
                        container, ["test", "-f", "/workspace/requirements.txt"]
                    )
                    if rc == 0:
                        install_cmd = "cd /workspace && uv pip install -r requirements.txt 2>&1"
                elif pm == "poetry":
                    install_cmd = "cd /workspace && poetry install 2>&1"
                elif pm == "pipenv":
                    install_cmd = "cd /workspace && pipenv install --dev 2>&1"
                else:
                    rc, _, _ = await _exec_in_container(
                        container, ["test", "-f", "/workspace/requirements.txt"]
                    )
                    if rc == 0:
                        install_cmd = "cd /workspace && pip install -r requirements.txt 2>&1"

                if install_cmd:
                    rc, stdout, stderr = await _exec_bash_in_container(
                        container, install_cmd, timeout=300,
                    )
                    results.append({
                        "dependency": f"{pm} install (all)",
                        "success": rc == 0,
                        "output": (stdout + stderr)[:1000],
                    })

            if dependencies:
                for dep in dependencies:
                    if framework in ("vitest", "jest", "npm"):
                        dep_cmds = {
                            "pnpm": f"cd /workspace && pnpm add -D {shlex.quote(dep)} 2>&1",
                            "yarn": f"cd /workspace && yarn add -D {shlex.quote(dep)} 2>&1",
                            "bun": f"cd /workspace && bun add -d {shlex.quote(dep)} 2>&1",
                        }
                        dep_cmd = dep_cmds.get(pm, f"cd /workspace && npm install --save-dev {shlex.quote(dep)} 2>&1")
                    elif pm == "uv":
                        dep_cmd = f"uv pip install {shlex.quote(dep)} 2>&1"
                    else:
                        dep_cmd = f"pip install {shlex.quote(dep)} 2>&1"
                    rc, stdout, stderr = await _exec_bash_in_container(
                        container, dep_cmd, timeout=120,
                    )
                    results.append({
                        "dependency": dep,
                        "success": rc == 0,
                        "output": (stdout + stderr)[:500],
                    })

            all_success = all(r["success"] for r in results) if results else True
            return {"success": all_success, "results": results}

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error installing test dependencies: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool(meta={"module_id": MODULE_ID, "version": MODULE_VERSION})
async def validate_tdd(
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    coverage_threshold: float = 80.0,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Run full TDD validation (tests + coverage + threshold check).

    Args:
        session_id: Session ID
        coverage_threshold: Minimum coverage percentage (default: 80.0)
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with validation results
    """
    try:
        # Run tests first
        test_result = await run_tests(
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
            git_scope=git_scope,
            sandbox_networks=sandbox_networks,
        )

        if not test_result.get("success"):
            return {
                "success": False,
                "error": "Tests failed",
                "test_error": test_result.get("error"),
                "test_results": test_result.get("results"),
            }

        # Try to get coverage
        coverage_result = await get_coverage_report(
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            repo_name=repo_name,
            repo_owner=repo_owner,
            git_scope=git_scope,
            sandbox_networks=sandbox_networks,
        )

        coverage_percent = 0
        if coverage_result.get("success"):
            cov = coverage_result.get("coverage", {})
            # Extract overall percentage (varies by framework)
            if "total" in cov:
                total = cov["total"]
                if isinstance(total, dict):
                    lines = total.get("lines", {})
                    if isinstance(lines, dict):
                        coverage_percent = lines.get("pct", 0)
                    elif isinstance(lines, (int, float)):
                        coverage_percent = lines

        return {
            "success": True,
            "tests_passed": test_result.get("success", False),
            "coverage_percent": coverage_percent,
            "coverage_threshold": coverage_threshold,
            "coverage_met": coverage_percent >= coverage_threshold,
            "test_results": test_result.get("results"),
        }

    except Exception as e:
        logger.error("Error in TDD validation: %s", e)
        return {"success": False, "error": str(e)}


# =============================================================================
# PROJECT DISCOVERY TOOLS (cross-project read-only access via Gitea API)
# =============================================================================


@mcp.tool(
    name="list_projects",
    description=(
        "List all project repositories in the Gitea organization. "
        "Returns name, description, last update time, and default branch "
        "for each project. Use this to discover what has been built before."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_projects() -> dict:
    """List all project repos in the Gitea organization."""
    import httpx

    if not GITEA_URL or not GITEA_ORG:
        return {"success": False, "error": "Gitea not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{GITEA_URL}/api/v1/orgs/{GITEA_ORG}/repos",
                headers=_gitea_api_headers(),
                params={"limit": 50},
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Gitea API returned {response.status_code}",
                }

            repos = response.json()
            projects = [
                {
                    "name": r["name"],
                    "description": r.get("description", ""),
                    "updated_at": r.get("updated_at", ""),
                    "default_branch": r.get("default_branch", "main"),
                }
                for r in repos
            ]
            return {"success": True, "count": len(projects), "projects": projects}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="read_project_file",
    description=(
        "Read a file from any project repository in Gitea. "
        "Use this to inspect docs/technical-design.md, Dockerfiles, or source "
        "code from existing projects to understand patterns and reuse opportunities."
    ),
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def read_project_file(repo_name: str, path: str, ref: str = "main") -> dict:
    """Read a file from any project repository via Gitea API."""
    import httpx

    if not GITEA_URL:
        return {"success": False, "error": "Gitea not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = f"{GITEA_URL}/api/v1/repos/{GITEA_ORG}/{repo_name}/raw/{ref}/{path}"
            response = await client.get(url, headers=_gitea_api_headers())
            if response.status_code == 404:
                return {
                    "success": False,
                    "error": f"File not found: {path} in {repo_name}@{ref}",
                }
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Gitea API returned {response.status_code}",
                }

            content = response.text
            return {
                "success": True,
                "content": content,
                "repo": repo_name,
                "path": path,
                "ref": ref,
                "size": len(content),
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="list_project_files",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_project_files(repo_name: str, path: str = "", ref: str = "main") -> dict:
    """List files in a project repository via Gitea API."""
    import httpx

    if not GITEA_URL or not GITEA_ORG:
        return {"success": False, "error": "Gitea not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{GITEA_URL}/api/v1/repos/{GITEA_ORG}/{repo_name}/git/trees/{ref}",
                headers=_gitea_api_headers(),
                params={"recursive": "true"},
            )
            if response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Repository '{repo_name}' not found",
                }
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Gitea API returned {response.status_code}",
                }

            tree = response.json().get("tree", [])
            if path:
                prefix = path.rstrip("/") + "/"
                tree = [e for e in tree if e.get("path", "").startswith(prefix)]

            files = [
                {
                    "path": e["path"],
                    "type": e.get("type", ""),
                    "size": e.get("size", 0),
                }
                for e in tree
            ]
            return {
                "success": True,
                "repo": repo_name,
                "ref": ref,
                "count": len(files),
                "files": files,
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# INTERNAL TOOLS (used by backend, not exposed to agents)
# =============================================================================


_COMMIT_REF_RE = re.compile(r"^[0-9a-f]{7,40}(~\d+)?$")


@mcp.tool(
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION, "internal": True},
)
async def _internal_revert_to_commit(
    target_commit: str,
    session_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_scope: str | None = None,
    sandbox_networks: list[str] | None = None,
) -> dict:
    """Revert sandbox to a specific commit (hard reset) and force push.

    Internal tool used by the backend for retry/revert operations.
    Not intended for direct agent use.

    Args:
        target_commit: Commit SHA to reset to (7-40 hex chars, optionally with ~N)
        session_id: Session ID
        repo_name: Gitea repository name
        repo_owner: Gitea repository owner
        git_scope: Git scope

    Returns:
        Dict with success, previous_head, new_head
    """
    try:
        session_id = _sanitize_param(session_id)
        repo_name = _sanitize_param(repo_name)
        repo_owner = _sanitize_param(repo_owner)
        git_scope = _sanitize_param(git_scope)

        if not session_id:
            return {"success": False, "error": "session_id is required"}

        # Validate target_commit
        if not target_commit or not _COMMIT_REF_RE.match(target_commit):
            return {
                "success": False,
                "error": f"Invalid target_commit: {target_commit!r}. "
                "Expected a hex SHA (7-40 chars), optionally with ~N suffix.",
            }

        entry = await _resolve_sandbox_or_fail(
            session_id, git_scope, None, None, None,
        )
        container = entry["container_name"]
        branch = entry.get("branch", "main")

        # Capture current HEAD
        rc, stdout, _ = await _exec_in_container(
            container, ["git", "rev-parse", "HEAD"], timeout=10
        )
        previous_head = stdout.strip()[:12] if rc == 0 else "unknown"

        # Hard reset to target commit
        rc, _, stderr = await _exec_in_container(
            container, ["git", "reset", "--hard", target_commit], timeout=30
        )
        if rc != 0:
            return {"success": False, "error": f"git reset --hard failed: {stderr}"}

        # Capture new HEAD
        rc, stdout, _ = await _exec_in_container(
            container, ["git", "rev-parse", "HEAD"], timeout=10
        )
        new_head = stdout.strip()[:12] if rc == 0 else target_commit[:12]

        # Force push via bundle mechanism (same as push_changes but force)
        resolved_repo_name = entry.get("repo_name") or repo_name
        resolved_repo_owner = entry.get("repo_owner") or repo_owner or GITEA_ORG
        resolved_gitea_url = entry.get("gitea_url", GITEA_URL)

        force_pushed = False
        if resolved_repo_name and branch != "main" and _is_gitea_configured():
            # Create bundle
            bundle_name = f"revert-{uuid.uuid4().hex[:8]}.bundle"
            bundle_path = f"/tmp/{bundle_name}"

            rc, _, _ = await _exec_in_container(
                container, ["git", "bundle", "create", bundle_path, "--all"], timeout=120
            )
            if rc == 0:
                tmpdir = tempfile.mkdtemp(prefix="druppie-revert-")
                try:
                    host_bundle = os.path.join(tmpdir, bundle_name)
                    await _copy_from_container(container, bundle_path, host_bundle)

                    bare_repo = os.path.join(tmpdir, "bare")
                    await _docker_run(["git", "init", "--bare", bare_repo], timeout=30)
                    await _docker_run(
                        ["git", "-C", bare_repo, "fetch", host_bundle, f"HEAD:refs/heads/{branch}"],
                        timeout=60,
                    )

                    push_url = _inject_gitea_token(resolved_repo_owner, resolved_repo_name, resolved_gitea_url)
                    rc, _, stderr = await _docker_run(
                        ["git", "-c", "http.sslVerify=false", "-C", bare_repo, "push", "--force", push_url, f"{branch}:{branch}"],
                        timeout=60,
                    )
                    force_pushed = rc == 0
                    if rc != 0:
                        logger.warning("Force push failed during revert: %s", stderr)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    await _exec_in_container(container, ["rm", "-f", bundle_path])

        return {
            "success": True,
            "previous_head": previous_head,
            "new_head": new_head,
            "force_pushed": force_pushed,
        }

    except Exception as e:
        logger.error("revert_to_commit error: %s", e)
        return {"success": False, "error": str(e)}
