"""
Container management for per-agent sandboxes.

Provides:
  - ContainerManager ABC — async interface for container lifecycle
  - DockerContainerManager — Docker CLI implementation with security hardening
  - SysboxContainerManager — Docker + Sysbox runtime for stronger isolation
  - create_container_manager() — factory based on DRUPPIE_SANDBOX_RUNTIME

Security hardening (Docker / Sysbox):
  --security-opt=no-new-privileges   blocks setuid/setgid escalation
  --cap-drop=ALL + minimal cap-add   principle of least privilege
  --memory limit                     prevents OOM on host
  --pids-limit                       prevents fork bombs
  Default seccomp + AppArmor         Docker builtin profiles
  No --privileged
"""

import asyncio
import logging
import platform
from abc import ABC, abstractmethod

from . import config

log = logging.getLogger(__name__)


class ContainerError(Exception):
    """Raised when a container operation fails."""


async def _run(cmd: list[str], timeout: float = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    log.debug("Running: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ContainerError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
    return proc.returncode or 0, stdout.decode(), stderr.decode()


class ContainerManager(ABC):
    """Async interface for sandbox container lifecycle."""

    @abstractmethod
    async def create(self, sandbox_id: str, env_vars: dict[str, str]) -> str:
        """Create and start a sandbox container. Returns container ID."""

    @abstractmethod
    async def stop(self, container_id: str) -> None:
        """Stop and remove a sandbox container."""

    @abstractmethod
    async def exec(
        self, container_id: str, command: list[str], timeout: float = 120
    ) -> tuple[int, str, str]:
        """Execute command in container. Returns (exit_code, stdout, stderr)."""

    @abstractmethod
    async def copy_to(self, container_id: str, src_path: str, dst_path: str) -> None:
        """Copy file from host to container."""

    @abstractmethod
    async def copy_from(self, container_id: str, src_path: str, dst_path: str) -> None:
        """Copy file from container to host."""

    @abstractmethod
    async def is_running(self, container_id: str) -> bool:
        """Check if container is running."""


class DockerContainerManager(ContainerManager):
    """Manage sandbox containers via the Docker CLI with hardened security."""

    def _security_flags(self) -> list[str]:
        return [
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--cap-add=NET_RAW",
            f"--memory={config.DOCKER_MEMORY_LIMIT}",
            *(
                []
                if config.DOCKER_CPU_LIMIT == "0"
                else [f"--cpus={config.DOCKER_CPU_LIMIT}"]
            ),
            f"--pids-limit={config.DOCKER_PIDS_LIMIT}",
            "--tmpfs=/tmp:rw,exec,size=2g",
        ]

    def _network_flags(self) -> list[str]:
        if config.DOCKER_NETWORK:
            return [f"--network={config.DOCKER_NETWORK}"]
        if platform.system() == "Linux":
            return ["--network=host"]
        return []

    def _volume_flags(self) -> list[str]:
        flags: list[str] = []
        if config.SANDBOX_CACHE_VOLUME:
            flags.extend(["-v", f"{config.SANDBOX_CACHE_VOLUME}:/cache:rw"])
        if config.SANDBOX_SDK_HOST_PATH:
            flags.extend(["-v", f"{config.SANDBOX_SDK_HOST_PATH}:/druppie-sdk:ro"])
        return flags

    async def create(self, sandbox_id: str, env_vars: dict[str, str]) -> str:
        image = config.SANDBOX_IMAGE
        container_name = sandbox_id

        await _run(["docker", "rm", "-f", container_name])

        env_flags: list[str] = []
        for k, v in env_vars.items():
            env_flags.extend(["-e", f"{k}={v}"])

        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            *self._security_flags(),
            *self._network_flags(),
            *self._volume_flags(),
            *env_flags,
            "-w",
            "/workspace",
            image,
            "sleep",
            "infinity",
        ]

        rc, stdout, stderr = await _run(cmd, timeout=60)
        if rc != 0:
            raise ContainerError(f"Failed to create container: {stderr.strip()}")

        container_id = stdout.strip()[:12]
        log.info("Container started: %s (%s)", container_name, container_id)
        return container_id

    async def stop(self, container_id: str) -> None:
        await _run(["docker", "stop", "-t", "10", container_id])
        await _run(["docker", "rm", "-f", container_id])
        log.info("Container removed: %s", container_id)

    async def exec(
        self, container_id: str, command: list[str], timeout: float = 120
    ) -> tuple[int, str, str]:
        full_cmd = ["docker", "exec", container_id, *command]
        rc, stdout, stderr = await _run(full_cmd, timeout=timeout)
        return rc, stdout, stderr

    async def copy_to(self, container_id: str, src_path: str, dst_path: str) -> None:
        with open(src_path, "rb") as f:
            content = f.read()
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", container_id,
            "sh", "-c", f"cat > {dst_path}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=content), timeout=60
        )
        if proc.returncode != 0:
            raise ContainerError(f"docker exec write failed: {stderr.decode().strip()}")

    async def copy_from(
        self, container_id: str, src_path: str, dst_path: str
    ) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "cat", src_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise ContainerError(
                f"docker exec cat failed for {src_path}: {stderr.decode().strip()}"
            )
        with open(dst_path, "wb") as f:
            f.write(stdout)

    async def is_running(self, container_id: str) -> bool:
        rc, stdout, _ = await _run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
            timeout=10,
        )
        return rc == 0 and "true" in stdout.lower()


class SysboxContainerManager(DockerContainerManager):
    """Docker + Sysbox runtime — stronger namespace isolation automatically."""

    def _security_flags(self) -> list[str]:
        base = super()._security_flags()
        return [f"--runtime={config.SYSBOX_RUNTIME}", *base]


def create_container_manager() -> ContainerManager:
    """Factory: return the appropriate manager based on DRUPPIE_SANDBOX_RUNTIME."""
    runtime = config.SANDBOX_RUNTIME
    if runtime == "kata":
        from .kata_manager import KataContainerManager

        return KataContainerManager()
    if runtime == "sysbox":
        return SysboxContainerManager()
    return DockerContainerManager()
