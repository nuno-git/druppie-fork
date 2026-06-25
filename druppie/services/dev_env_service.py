"""Dev environment service.

Orchestrates the full lifecycle of a developer dev VM:
  1. Launch a Kubernetes Pod (sysbox RuntimeClass, SSH/RDP/code-server ready
     image) plus its Service + PVC
  2. Register a Guacamole RDP connection pointing at the pod's Service
  3. Grant the owning user READ access on that connection
  4. Track state in the database via DevVMRepository

The Pod/Service/PVC lifecycle runs through the async Kubernetes client
``druppie.core.kubernetes`` which wraps the synchronous official SDK in
``asyncio.to_thread``. Guacamole is called through the core client
``druppie.core.guacamole``.
"""

import base64
import os
from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..core.guacamole import get_guacamole_client
from ..core.kubernetes import DEV_VM_NAMESPACE, KubernetesClient
from ..domain import DevVMDetail, DevVMSummary
from ..repositories import DevVMRepository

logger = structlog.get_logger()

# Dev VM launch configuration (env-overridable).
DEV_VM_IMAGE = os.getenv("DEV_VM_IMAGE", "dev-vm-base:latest")

# Guacamole deep-link base (host-facing URL users open in the browser).
GUACAMOLE_PUBLIC_URL = os.getenv("GUACAMOLE_PUBLIC_URL", "http://localhost:30020")

# RDP credentials baked into the dev-vm-base image.
DEV_VM_RDP_USERNAME = os.getenv("DEV_VM_RDP_USERNAME", "developer")
DEV_VM_RDP_PASSWORD = os.getenv("DEV_VM_RDP_PASSWORD", "developer")


class DevEnvService:
    """Business logic for developer dev VMs."""

    def __init__(self, dev_vm_repo: DevVMRepository):
        self.dev_vm_repo = dev_vm_repo
        self.guac = get_guacamole_client()
        self._k8s = KubernetesClient(namespace=DEV_VM_NAMESPACE)

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
        """Launch a dev VM pod + register a Guacamole connection.

        Creates the DB record up front (status=creating), then performs the
        pod launch and Guacamole registration inline. On any failure the
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

        pod_name = f"dev-vm-{name}-{str(vm.id)[:8]}"
        creds = self._generate_vm_credentials()

        try:
            pod_name, service_dns = await self._launch_pod(pod_name, branch, creds)

            connection_id = await self._register_guacamole(
                container_name=pod_name,
                container_ip=service_dns,
                username=username,
                creds=creds,
            )

            self.dev_vm_repo.update(
                vm.id,
                status="running",
                container_id=pod_name,
                container_name=pod_name,
                guacamole_connection_id=connection_id,
                rdp_username=creds["rdp_username"],
                rdp_password=creds["rdp_password"],
            )
            self.dev_vm_repo.commit()
            logger.info(
                "dev_vm_created",
                vm_id=str(vm.id),
                pod_name=pod_name,
                connection_id=connection_id,
            )
        except Exception as e:
            self.dev_vm_repo.update(vm.id, status="error")
            self.dev_vm_repo.commit()
            logger.error(
                "dev_vm_create_failed",
                vm_id=str(vm.id),
                pod_name=pod_name,
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

        # 1. Remove the pod + service + PVC (best-effort).
        if vm.container_name:
            pod_name = vm.container_name
            service_name = f"{pod_name}-svc"
            pvc_name = f"{pod_name}-home"
            try:
                await self._k8s.delete_service(service_name)
                await self._k8s.delete_pod(pod_name)
                await self._k8s.delete_pvc(pvc_name)
            except Exception as e:
                logger.warning(
                    "dev_vm_pod_remove_failed",
                    vm_id=str(vm_id),
                    pod=pod_name,
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
    # Pod / Guacamole helpers
    # -------------------------------------------------------------------------

    def _generate_vm_credentials(self) -> dict:
        return {
            "rdp_username": "developer",
            "rdp_password": "developer",
            "ssh_username": "developer",
        }

    async def _launch_pod(
        self, pod_name: str, branch: str, creds: dict
    ) -> tuple[str, str]:
        """Launch the dev VM as a Kubernetes pod.

        Provisions a fresh PVC + Pod + Service triple, waiting for the pod to
        become ready. Returns ``(pod_name, service_dns)`` where ``service_dns``
        is the stable in-cluster DNS name Guacamole should connect to (stable
        across pod restarts, unlike the pod IP).
        """
        pvc_name = f"{pod_name}-home"
        service_name = f"{pod_name}-svc"

        # Best-effort cleanup of stale resources with the same name.
        await self._k8s.delete_service(service_name)
        await self._k8s.delete_pod(pod_name)
        await self._k8s.delete_pvc(pvc_name)

        # Create fresh resources.
        await self._k8s.create_pvc(pvc_name)
        await self._k8s.create_pod(pod_name, DEV_VM_IMAGE, branch, pvc_name=pvc_name)
        await self._k8s.create_service(service_name, pod_name)

        # Wait for the pod to be Running with an IP assigned.
        ready = await self._k8s.wait_pod_ready(pod_name, timeout=120)
        if not ready:
            raise RuntimeError(f"Pod {pod_name} did not become ready within 120s")

        # Stable DNS name for Guacamole (NOT the pod IP, which changes on
        # restart).
        service_dns = f"{service_name}.{self._k8s.namespace}.svc.cluster.local"
        _ = creds  # reserved for future per-VM credential injection
        return pod_name, service_dns

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
