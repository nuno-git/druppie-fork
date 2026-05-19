"""
KataContainerManager — sandbox containers via containerd + Kata runtime.

Uses `ctr` CLI for container operations. Kata provides hardware-isolated
VM-based containers for the strongest sandboxing boundary.
"""

import asyncio
import json
import logging

from . import config
from .manager import ContainerError, ContainerManager, _run

log = logging.getLogger(__name__)


def _ctr(*args: str) -> list[str]:
    return ["ctr", "-n", config.CONTAINERD_NAMESPACE, *args]


class KataContainerManager(ContainerManager):
    """Manage sandbox containers via containerd + Kata VM runtime."""

    async def create(self, sandbox_id: str, env_vars: dict[str, str]) -> str:
        image = config.SANDBOX_IMAGE
        container_id = sandbox_id

        await _run(_ctr("tasks", "kill", container_id), timeout=10)
        await _run(_ctr("tasks", "delete", container_id), timeout=10)
        await _run(_ctr("containers", "delete", container_id), timeout=10)

        env_flags: list[str] = []
        for k, v in env_vars.items():
            env_flags.extend(["--env", f"{k}={v}"])

        rc, stdout, stderr = await _run(
            _ctr("images", "check", f"name=={image}"), timeout=30
        )
        if rc != 0 or image not in (stderr + stdout):
            log.info("Pulling image %s", image)
            await _run(_ctr("images", "pull", image), timeout=300)

        cmd = _ctr(
            "run",
            "-d",
            "--runtime",
            config.KATA_RUNTIME,
            *env_flags,
            "--net-host",
            image,
            container_id,
            "sleep",
            "infinity",
        )

        rc, _, stderr = await _run(cmd, timeout=60)
        if rc != 0:
            raise ContainerError(f"Failed to create Kata container: {stderr}")

        log.info("Kata container started: %s", container_id)
        return container_id

    async def stop(self, container_id: str) -> None:
        await _run(_ctr("tasks", "kill", container_id))
        await _run(_ctr("tasks", "delete", container_id))
        await _run(_ctr("containers", "delete", container_id))
        log.info("Kata container removed: %s", container_id)

    async def exec(
        self, container_id: str, command: list[str], timeout: float = 120
    ) -> tuple[int, str, str]:
        # ctr task exec requires --exec-id (unique per exec session)
        import uuid

        exec_id = uuid.uuid4().hex[:12]
        full_cmd = _ctr(
            "tasks", "exec", "--exec-id", exec_id, container_id, *command
        )
        return await _run(full_cmd, timeout=timeout)

    async def copy_to(self, container_id: str, src_path: str, dst_path: str) -> None:
        tar_proc = await asyncio.create_subprocess_exec(
            "tar",
            "cf",
            "-",
            "-C",
            src_path.rsplit("/", 1)[0] or ".",
            src_path.rsplit("/", 1)[-1],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        import uuid

        exec_id = uuid.uuid4().hex[:12]
        ctr_proc = await asyncio.create_subprocess_exec(
            *_ctr(
                "tasks",
                "exec",
                "--exec-id",
                exec_id,
                container_id,
                "tar",
                "xf",
                "-",
                "-C",
                dst_path.rsplit("/", 1)[0] or "/",
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await tar_proc.communicate()
        if tar_proc.returncode != 0:
            raise ContainerError(f"Host tar failed: {stderr.decode()}")

        _, stderr = await ctr_proc.communicate(input=stdout)
        if ctr_proc.returncode != 0:
            raise ContainerError(f"Container tar extract failed: {stderr.decode()}")

    async def copy_from(
        self, container_id: str, src_path: str, dst_path: str
    ) -> None:
        import uuid

        exec_id = uuid.uuid4().hex[:12]
        rc, stdout, stderr = await _run(
            _ctr(
                "tasks",
                "exec",
                "--exec-id",
                exec_id,
                container_id,
                "tar",
                "cf",
                "-",
                "-C",
                src_path.rsplit("/", 1)[0] or "/",
                src_path.rsplit("/", 1)[-1],
            ),
            timeout=60,
        )
        if rc != 0:
            raise ContainerError(f"Container tar failed: {stderr}")

        import os

        os.makedirs(dst_path.rsplit("/", 1)[0] or ".", exist_ok=True)
        tar_proc = await asyncio.create_subprocess_exec(
            "tar",
            "xf",
            "-",
            "-C",
            dst_path.rsplit("/", 1)[0] or ".",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await tar_proc.communicate(input=stdout.encode())
        if tar_proc.returncode != 0:
            raise ContainerError(f"Host tar extract failed: {stderr.decode()}")

    async def is_running(self, container_id: str) -> bool:
        rc, stdout, _ = await _run(_ctr("tasks", "inspect", container_id), timeout=10)
        if rc != 0:
            return False
        try:
            status = json.loads(stdout)
            return status.get("Status") == "running"
        except (json.JSONDecodeError, KeyError):
            return False
