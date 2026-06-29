"""
K8s Sandbox Manager — abstraction layer over the agent-sandbox SDK.

Replaces Docker-based sandbox management with Kubernetes-native sandboxes
managed by the agent-sandbox controller (kubernetes-sigs/agent-sandbox).

The interface mirrors the Docker-based functions in module-coding/tools.py:
  - create sandbox (was: docker run)
  - exec command (was: docker exec)
  - read/write files (was: docker exec cat/tee)
  - destroy sandbox (was: docker rm -f)

Two backends are supported:
  1. "k8s"    — uses agent-sandbox SDK (production, gVisor isolation)
  2. "docker" — uses Docker CLI (local dev, backward compatible)

The backend is selected via DRUPPIE_SANDBOX_MODE env var.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

SANDBOX_MODE = os.getenv("DRUPPIE_SANDBOX_MODE", "docker")  # "k8s" or "docker"
SANDBOX_NAMESPACE = os.getenv("SANDBOX_NAMESPACE", "sandbox-runtime")
SANDBOX_WARMPOOL = os.getenv("SANDBOX_WARMPOOL", "agent-coding-warmpool")


@dataclass
class SandboxHandle:
    """Opaque handle representing an active sandbox. Passed back to tools.py."""
    sandbox_id: str
    session_id: str
    git_scope: str
    branch: str = "main"
    created_at: float = field(default_factory=time.time)
    _backend: object = None  # backend-specific object (SDK sandbox or docker container)


class K8sSandboxManager:
    """Manages agent sandboxes via the agent-sandbox CRD + Python SDK."""

    def __init__(self):
        try:
            from k8s_agent_sandbox import AsyncSandboxClient
            from k8s_agent_sandbox.models import SandboxInClusterConnectionConfig
        except ImportError:
            raise RuntimeError(
                "k8s-agent-sandbox package not installed. "
                "Install with: pip install k8s-agent-sandbox[async]"
            )

        config = SandboxInClusterConnectionConfig()
        self.client = AsyncSandboxClient(connection_config=config)
        self._sandboxes: dict[str, object] = {}
        logger.info("K8sSandboxManager initialized (namespace=%s, warmpool=%s)",
                     SANDBOX_NAMESPACE, SANDBOX_WARMPOOL)

    async def create(
        self,
        session_id: str,
        git_scope: str,
        repo_clone_url: Optional[str] = None,
        branch: str = "main",
    ) -> SandboxHandle:
        """Claim a sandbox from the warm pool and optionally clone a repo."""
        labels = {
            "session-id": session_id[:63],
            "git-scope": git_scope,
        }

        sandbox = await self.client.create_sandbox(
            warmpool=SANDBOX_WARMPOOL,
            namespace=SANDBOX_NAMESPACE,
            labels=labels,
        )
        sandbox_id = sandbox.sandbox_id
        logger.info("Sandbox claimed: %s (session=%s, scope=%s)",
                     sandbox_id, session_id, git_scope)

        if repo_clone_url:
            clone_cmd = (
                f"git clone --depth 50 --branch {branch} "
                f"{repo_clone_url} /workspace/repo 2>&1"
            )
            result = await sandbox.commands.run(clone_cmd)
            if result.returncode != 0:
                logger.warning("Git clone failed in sandbox %s: %s",
                               sandbox_id, result.stderr[:200])
            else:
                await sandbox.commands.run(
                    "cd /workspace/repo && find . -maxdepth 1 -exec mv {} /workspace/ \; 2>/dev/null; "
                    "rmdir /workspace/repo 2>/dev/null; true"
                )

        await sandbox.commands.run("git config user.email 'agent@druppie.local'")
        await sandbox.commands.run("git config user.name 'Druppie Agent'")

        self._sandboxes[f"{session_id}::{git_scope}"] = sandbox
        return SandboxHandle(
            sandbox_id=sandbox_id,
            session_id=session_id,
            git_scope=git_scope,
            branch=branch,
            _backend=sandbox,
        )

    async def exec(self, handle: SandboxHandle, command: list[str] | str,
                   timeout: int = 60) -> tuple[int, str, str]:
        """Execute a command in the sandbox. Returns (exit_code, stdout, stderr)."""
        if isinstance(command, list):
            command = " ".join(command)
        result = await handle._backend.commands.run(command, timeout=timeout)
        return result.exit_code, result.stdout, result.stderr

    async def read_file(self, handle: SandboxHandle, path: str) -> str:
        """Read a file from the sandbox."""
        result = await handle._backend.commands.run(f"cat {path}")
        return result.stdout

    async def write_file(self, handle: SandboxHandle, path: str, content: str) -> None:
        """Write a file into the sandbox."""
        handle._backend.files.write(path, content)

    async def file_exists(self, handle: SandboxHandle, path: str) -> bool:
        """Check if a file exists in the sandbox."""
        result = await handle._backend.commands.run(f"test -f {path} && echo yes || echo no")
        return "yes" in result.stdout

    async def destroy(self, handle: SandboxHandle) -> None:
        """Terminate the sandbox and clean up."""
        key = f"{handle.session_id}::{handle.git_scope}"
        sandbox = self._sandboxes.pop(key, None)
        if sandbox:
            try:
                await sandbox.terminate()
                logger.info("Sandbox destroyed: %s", handle.sandbox_id)
            except Exception as e:
                logger.warning("Failed to destroy sandbox %s: %s",
                               handle.sandbox_id, e)

    async def is_alive(self, handle: SandboxHandle) -> bool:
        """Check if the sandbox is still running."""
        try:
            result = await handle._backend.commands.run("echo ok", timeout=5)
            return result.exit_code == 0
        except Exception:
            return False

    async def destroy_all_for_session(self, session_id: str) -> int:
        """Destroy all sandboxes for a session. Returns count destroyed."""
        count = 0
        keys_to_remove = [
            k for k in self._sandboxes if k.startswith(f"{session_id}::")
        ]
        for key in keys_to_remove:
            sandbox = self._sandboxes.pop(key)
            try:
                await sandbox.terminate()
                count += 1
            except Exception:
                pass
        return count


def get_sandbox_manager():
    """Factory: returns the appropriate manager based on DRUPPIE_SANDBOX_MODE."""
    if SANDBOX_MODE == "k8s":
        return K8sSandboxManager()
    else:
        return None  # Docker mode — caller uses existing Docker CLI code
