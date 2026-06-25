"""Dev environment service.

Orchestrates the full lifecycle of a developer dev VM:
  1. Launch a sysbox-runc container (SSH/RDP/code-server ready image)
  2. Register a Guacamole RDP connection pointing at the container
  3. Grant the owning user READ access on that connection
  4. Track state in the database via DevVMRepository

Docker commands run via ``asyncio.create_subprocess_exec`` mirroring the
sandbox container launch in ``druppie/mcp-servers/module-coding/v1/tools.py``.
Guacamole is called through the core client ``druppie.core.guacamole``.
"""

import asyncio
import base64
import os
import secrets as pysecrets
from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..core.guacamole import get_guacamole_client
from ..domain import DevVMDetail, DevVMSummary
from ..repositories import DevVMRepository

logger = structlog.get_logger()

# Sysbox container launch configuration (env-overridable).
DEV_VM_IMAGE = os.getenv("DEV_VM_IMAGE", "dev-vm-base:latest")
DEV_VM_NETWORK = os.getenv("SANDBOX_NETWORK", "druppie-sandbox-net")
DEV_VM_RUNTIME = os.getenv("DEV_VM_RUNTIME", "sysbox-runc")
DEV_VM_MEMORY = os.getenv("DEV_VM_MEMORY", "12g")
DEV_VM_CPUS = os.getenv("DEV_VM_CPUS", "4")

# Guacamole deep-link base (host-facing URL users open in the browser).
GUACAMOLE_PUBLIC_URL = os.getenv("GUACAMOLE_PUBLIC_URL", "http://localhost:30020")

# RDP credentials baked into the dev-vm-base image.
DEV_VM_RDP_USERNAME = os.getenv("DEV_VM_RDP_USERNAME", "developer")
DEV_VM_RDP_PASSWORD = os.getenv("DEV_VM_RDP_PASSWORD", "developer")


async def _run_cmd(cmd: list[str], timeout: float = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr).

    Mirrors ``_docker_run`` in module-coding/v1/tools.py so docker invocations
    stay consistent with the sandbox launcher.
    """
    logger.debug("dev_vm_run_cmd", cmd=" ".join(cmd))
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


class DevEnvService:
    """Business logic for developer dev VMs."""

    def __init__(self, dev_vm_repo: DevVMRepository):
        self.dev_vm_repo = dev_vm_repo
        self.guac = get_guacamole_client()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def create_dev_vm(
        self,
        owner_id: UUID,
        name: str,
        branch: str,
        username: str | None,
        user_roles: list[str],
    ) -> DevVMDetail:
        """Launch a sysbox dev VM + register a Guacamole connection.

        Creates the DB record up front (status=creating), then performs the
        container launch and Guacamole registration inline. On any failure the
        record is marked status=error and the error is re-raised so the route
        surfaces it.
        """
        vm = self.dev_vm_repo.create(
            name=name,
            branch=branch,
            owner_id=owner_id,
            status="creating",
        )
        self.dev_vm_repo.commit()

        container_name = f"dev-vm-{name}-{str(vm.id)[:8]}"
        creds = self._generate_vm_credentials()

        try:
            container_id = await self._launch_container(container_name, branch, creds)
            container_ip = await self._get_container_ip(container_name)

            connection_id = await self._register_guacamole(
                container_name=container_name,
                container_ip=container_ip,
                username=username,
                creds=creds,
            )

            self.dev_vm_repo.update(
                vm.id,
                status="running",
                container_id=container_id,
                container_name=container_name,
                guacamole_connection_id=connection_id,
                rdp_username=creds["rdp_username"],
                rdp_password=creds["rdp_password"],
            )
            self.dev_vm_repo.commit()
            logger.info(
                "dev_vm_created",
                vm_id=str(vm.id),
                container_name=container_name,
                connection_id=connection_id,
            )
        except Exception as e:
            self.dev_vm_repo.update(vm.id, status="error")
            self.dev_vm_repo.commit()
            logger.error(
                "dev_vm_create_failed",
                vm_id=str(vm.id),
                container_name=container_name,
                error=str(e),
                exc_info=True,
            )
            raise

        detail = self.dev_vm_repo.get_detail(vm.id)
        if detail is None:
            raise NotFoundError("dev_vm", str(vm.id))
        detail.guacamole_url = self._build_guacamole_url(detail.guacamole_connection_id)
        _ = user_roles  # role gating happens at the route layer
        return detail

    async def stop_dev_vm(
        self,
        vm_id: UUID,
        owner_id: UUID,
        user_roles: list[str],
    ) -> dict:
        """Stop and remove the dev VM + delete the Guacamole connection."""
        vm = self.dev_vm_repo.get_by_id(vm_id)
        if not vm:
            raise NotFoundError("dev_vm", str(vm_id))

        is_owner = vm.owner_id == owner_id
        is_admin = "admin" in user_roles
        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can stop a dev VM")

        # 1. Remove the docker container (best-effort).
        if vm.container_name:
            try:
                await _run_cmd(["docker", "rm", "-f", vm.container_name], timeout=30)
            except Exception as e:
                logger.warning(
                    "dev_vm_container_remove_failed",
                    vm_id=str(vm_id),
                    container=vm.container_name,
                    error=str(e),
                )

        # 2. Delete the Guacamole connection (best-effort).
        if vm.guacamole_connection_id:
            try:
                result = await self.guac.delete_connection(vm.guacamole_connection_id)
                if not result.get("success"):
                    logger.warning(
                        "dev_vm_guac_delete_failed",
                        vm_id=str(vm_id),
                        connection_id=vm.guacamole_connection_id,
                        error=result.get("error"),
                    )
            except Exception as e:
                logger.warning(
                    "dev_vm_guac_delete_failed",
                    vm_id=str(vm_id),
                    error=str(e),
                )

        # 3. Mark stopped (keep the row for history) and commit.
        self.dev_vm_repo.update(vm.id, status="stopped")
        self.dev_vm_repo.commit()
        logger.info("dev_vm_stopped", vm_id=str(vm_id), by_user=str(owner_id))
        return {"success": True, "vm_id": str(vm_id), "status": "stopped"}

    def list_dev_vms(
        self,
        owner_id: UUID,
        user_roles: list[str],
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[DevVMSummary], int]:
        """List dev VMs. Admin sees all, others see only their own."""
        offset = (page - 1) * limit
        if "admin" in user_roles:
            items, total = self.dev_vm_repo.list_all(limit, offset)
        else:
            items, total = self.dev_vm_repo.list_for_user(owner_id, limit, offset)
        for item in items:
            item.guacamole_url = self._build_guacamole_url(item.guacamole_connection_id)
        return items, total

    def get_dev_vm(
        self,
        vm_id: UUID,
        owner_id: UUID,
        user_roles: list[str],
    ) -> DevVMDetail:
        """Get a single dev VM detail with the Guacamole deep-link."""
        vm = self.dev_vm_repo.get_by_id(vm_id)
        if not vm:
            raise NotFoundError("dev_vm", str(vm_id))

        is_owner = vm.owner_id == owner_id
        is_admin = "admin" in user_roles
        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can view dev VM")

        detail = self.dev_vm_repo.get_detail(vm_id)
        if detail is None:
            raise NotFoundError("dev_vm", str(vm_id))
        detail.guacamole_url = self._build_guacamole_url(detail.guacamole_connection_id)
        return detail

    # -------------------------------------------------------------------------
    # Container / Guacamole helpers
    # -------------------------------------------------------------------------

    def _generate_vm_credentials(self) -> dict:
        return {
            "rdp_username": "developer",
            "rdp_password": "developer",
            "ssh_username": "developer",
        }

    async def _launch_container(
        self, container_name: str, branch: str, creds: dict
    ) -> str:
        """Launch the sysbox dev VM container. Returns the short container id."""
        # Best-effort cleanup of a stale container with the same name.
        await _run_cmd(["docker", "rm", "-f", container_name], timeout=15)

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DEV_VM_NETWORK,
            "--runtime", DEV_VM_RUNTIME,
            "--memory", DEV_VM_MEMORY,
            "--cpus", DEV_VM_CPUS,
            "--shm-size", "2g",
            "--tmpfs", "/tmp:size=4g",
            "--storage-opt", "size=20G",
            "-e", f"DRUPPIE_GIT_BRANCH={branch}",
            DEV_VM_IMAGE,
            "bash", "-c",
            "dockerd > /var/log/dockerd.log 2>&1 & sleep infinity",
        ]
        rc, stdout, stderr = await _run_cmd(cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"docker run failed for {container_name}: {stderr.strip()}")

        container_id = stdout.strip()[:12]

        # Wait for the in-VM docker daemon (sysbox) to be ready, mirroring the
        # sandbox readiness check in module-coding/v1/tools.py.
        for _ in range(20):
            rc, _, _ = await _run_cmd(
                ["docker", "exec", container_name, "test", "-S", "/var/run/docker.sock"],
                timeout=5,
            )
            if rc == 0:
                logger.info("dev_vm_dockerd_ready", container=container_name)
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning("dev_vm_dockerd_not_ready", container=container_name)

        return container_id

    async def _get_container_ip(self, container_name: str) -> str:
        """Resolve the container's IP on its docker network."""
        fmt = "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}"
        rc, stdout, stderr = await _run_cmd(
            ["docker", "inspect", "-f", fmt, container_name],
            timeout=15,
        )
        ip = stdout.strip()
        if rc != 0 or not ip:
            raise RuntimeError(
                f"Could not resolve IP for {container_name}: {stderr.strip()}"
            )
        return ip

    async def _register_guacamole(
        self,
        container_name: str,
        container_ip: str,
        username: str | None,
        creds: dict,
    ) -> str:
        """Register an RDP Guacamole connection and grant the owner READ.

        Returns the Guacamole connection identifier.
        """
        rdp_username = creds.get("rdp_username") or DEV_VM_RDP_USERNAME
        rdp_password = creds.get("rdp_password") or DEV_VM_RDP_PASSWORD
        result = await self.guac.create_connection(
            name=container_name,
            protocol="rdp",
            hostname=container_ip,
            port="3389",
            username=rdp_username,
            password=rdp_password,
            **{"ignore-cert": "true", "resize-method": "display-update", "security": "any"},
        )
        if not result.get("success"):
            raise RuntimeError(
                f"Guacamole connection creation failed: {result.get('error') or result}"
            )

        connection_id = result.get("connection_id")
        if not connection_id:
            raise RuntimeError("Guacamole did not return a connection identifier")

        # Grant READ to the owning user (best-effort: a missing Guacamole user
        # should not block VM creation, just log it).
        if username:
            grant = await self.guac.grant_read_permission(username, container_name)
            if not grant.get("success"):
                logger.warning(
                    "dev_vm_guac_grant_failed",
                    connection=container_name,
                    username=username,
                    error=grant.get("error"),
                )

        return str(connection_id)

    def _build_guacamole_url(self, connection_id: str | None) -> str | None:
        """Construct the Guacamole deep-link for a connection, or None."""
        if not connection_id:
            return None
        base = GUACAMOLE_PUBLIC_URL.rstrip("/")
        blob = "\0".join([connection_id, "c", "postgresql"])
        raw_b64 = base64.b64encode(blob.encode("utf-8")).decode("ascii")
        urlsafe = raw_b64.replace("+", "-").replace("/", "_").rstrip("=")
        return f"{base}/guacamole/#/client/{urlsafe}"
