"""Kubernetes client wrapper for the Druppie dev VM lifecycle.

Provisions and tears down the Pod + Service + PVC triple that backs a single
developer dev VM. The dev VM image (``dev-vm-base:latest``) runs as a
privileged container so it can run inner Docker; a Guacamole RDP connection
is fronted by a ClusterIP Service that selects the pod.

The official ``kubernetes`` Python client is synchronous, so every method here
wraps its SDK call in :func:`asyncio.to_thread` to avoid blocking the FastAPI
event loop. This mirrors the ``asyncio.to_thread`` pattern used by the
read-only ``druppie/mcp-servers/module-kubernetes/v1/module.py`` (config
loading is copied from there; nothing is imported across that boundary since
the MCP server is a separate process).

Config loading prefers in-cluster credentials (the backend pod's ServiceAccount)
and falls back to the local kubeconfig for development outside the cluster.
"""

import asyncio
import os
import time

import structlog
from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config import ConfigException

logger = structlog.get_logger()

# Namespace that holds every dev VM resource. Env-overridable, matching the
# module-level config style used by ``dev_env_service`` and ``guacamole``.
DEV_VM_NAMESPACE = os.getenv("DEV_VM_NAMESPACE", "druppie")


def _load_config() -> None:
    """Load kubernetes configuration, preferring in-cluster then kubeconfig.

    Raises:
        RuntimeError: if neither in-cluster config nor a usable kubeconfig is
            available. The caller is expected to surface this to the operator.
    """
    try:
        config.load_incluster_config()
    except ConfigException:
        try:
            config.load_kube_config()
        except ConfigException as exc:
            raise RuntimeError(
                "Could not load kubernetes configuration. "
                "Set KUBECONFIG or run inside a cluster."
            ) from exc


class KubernetesClient:
    """Async wrapper around ``kubernetes.client.CoreV1Api``.

    The underlying SDK client is lazily initialised on first use so that simply
    constructing a client (e.g. at service-wire time) never triggers network or
    filesystem access.
    """

    def __init__(self, namespace: str = DEV_VM_NAMESPACE):
        self._namespace = namespace
        self._core: client.CoreV1Api | None = None

    @property
    def namespace(self) -> str:
        """Namespace this client operates in (read-only)."""
        return self._namespace

    def _api(self) -> client.CoreV1Api:
        if self._core is None:
            _load_config()
            self._core = client.CoreV1Api()
        return self._core

    # -------------------------------------------------------------------------
    # Pods
    # -------------------------------------------------------------------------

    async def create_pod(
        self,
        name: str,
        image: str,
        branch: str,
        pvc_name: str | None = None,
    ) -> str:
        """Create a dev VM pod. Returns the pod name.

        The container runs privileged so it can run inner Docker (k3s with
        ``--docker`` does not map RuntimeClass handlers to Docker runtimes, so a
        privileged security context is used instead of the ``sysbox``
        RuntimeClass). The image ENTRYPOINT (``dev-vm-entrypoint.sh``) starts
        dbus/sshd/xrdp/Gitea, so no ``command``/``args`` are set here. When
        ``pvc_name`` is given the home directory is backed by that PVC;
        otherwise an ``emptyDir`` is used.
        """
        api = self._api()

        labels = {
            "app.kubernetes.io/name": "druppie",
            "app.kubernetes.io/instance": "dev-vm",
            "app.kubernetes.io/component": "dev-vm",
            "dev-vm-name": name,
        }

        container = client.V1Container(
            name="dev-vm",
            image=image,
            ports=[
                client.V1ContainerPort(container_port=3389, name="rdp"),
                client.V1ContainerPort(container_port=22, name="ssh"),
                client.V1ContainerPort(container_port=8080, name="code-server"),
                client.V1ContainerPort(container_port=3000, name="gitea"),
            ],
            env=[client.V1EnvVar(name="DRUPPIE_GIT_BRANCH", value=branch)],
            resources=client.V1ResourceRequirements(
                limits={"memory": "12Gi", "cpu": "4"},
                requests={"memory": "2Gi", "cpu": "1"},
            ),
            volume_mounts=[
                client.V1VolumeMount(name="home", mount_path="/home/developer"),
                client.V1VolumeMount(name="shm", mount_path="/dev/shm"),
                client.V1VolumeMount(name="tmp", mount_path="/tmp"),
            ],
            security_context=client.V1SecurityContext(privileged=True),
        )

        volumes = [
            client.V1Volume(
                name="shm",
                empty_dir=client.V1EmptyDirVolumeSource(
                    medium="Memory", size_limit="2Gi"
                ),
            ),
            client.V1Volume(
                name="tmp",
                empty_dir=client.V1EmptyDirVolumeSource(
                    medium="Memory", size_limit="4Gi"
                ),
            ),
        ]
        if pvc_name:
            volumes.append(
                client.V1Volume(
                    name="home",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=pvc_name
                    ),
                )
            )
        else:
            volumes.append(
                client.V1Volume(
                    name="home",
                    empty_dir=client.V1EmptyDirVolumeSource(size_limit="20Gi"),
                )
            )

        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=name, namespace=self._namespace, labels=labels
            ),
            spec=client.V1PodSpec(
                containers=[container],
                volumes=volumes,
            ),
        )

        try:
            created = await asyncio.to_thread(
                api.create_namespaced_pod, namespace=self._namespace, body=pod
            )
        except ApiException as exc:
            raise RuntimeError(
                f"Failed to create pod '{name}' in namespace "
                f"'{self._namespace}': {exc.reason} (status={exc.status})"
            ) from exc

        logger.info(
            "k8s_pod_created",
            pod=name,
            namespace=self._namespace,
            image=image,
            branch=branch,
            pvc=pvc_name,
        )
        return created.metadata.name

    async def delete_pod(self, name: str) -> bool:
        """Delete a pod. Best-effort: returns True on success (incl. 404)."""
        api = self._api()
        try:
            # grace_period_seconds=0 forces immediate termination, mirroring the
            # ``docker rm -f`` semantics this replaces.
            await asyncio.to_thread(
                api.delete_namespaced_pod,
                name=name,
                namespace=self._namespace,
                grace_period_seconds=0,
            )
            logger.info("k8s_pod_deleted", pod=name, namespace=self._namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return True
            logger.warning(
                "k8s_pod_delete_failed",
                pod=name,
                namespace=self._namespace,
                status=exc.status,
                reason=exc.reason,
            )
            return False

    async def get_pod_ip(self, name: str) -> str:
        """Get the pod IP. Raises if the pod is missing or has no IP yet."""
        api = self._api()
        try:
            pod = await asyncio.to_thread(
                api.read_namespaced_pod, name=name, namespace=self._namespace
            )
        except ApiException as exc:
            raise RuntimeError(
                f"Could not read pod '{name}' in namespace "
                f"'{self._namespace}': {exc.reason} (status={exc.status})"
            ) from exc
        ip = pod.status.pod_ip
        if not ip:
            raise RuntimeError(f"Pod '{name}' has no IP assigned yet")
        return ip

    async def get_pod_status(self, name: str) -> str:
        """Get pod phase: Pending, Running, Succeeded, Failed, Unknown."""
        api = self._api()
        try:
            pod = await asyncio.to_thread(
                api.read_namespaced_pod, name=name, namespace=self._namespace
            )
        except ApiException as exc:
            raise RuntimeError(
                f"Could not read pod '{name}' in namespace "
                f"'{self._namespace}': {exc.reason} (status={exc.status})"
            ) from exc
        return pod.status.phase or "Unknown"

    async def wait_pod_ready(self, name: str, timeout: int = 120) -> bool:
        """Wait until the pod is Running and has an IP. Returns True on success.

        Polls every 2 seconds. A transient 404 (pod not yet observed by the
        API) is tolerated and retried until the deadline.
        """
        api = self._api()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                pod = await asyncio.to_thread(
                    api.read_namespaced_pod, name=name, namespace=self._namespace
                )
            except ApiException as exc:
                if exc.status == 404:
                    await asyncio.sleep(2)
                    continue
                raise RuntimeError(
                    f"Could not read pod '{name}' while waiting for readiness: "
                    f"{exc.reason} (status={exc.status})"
                ) from exc

            phase = pod.status.phase
            ip = pod.status.pod_ip
            if phase == "Running" and ip:
                logger.info(
                    "k8s_pod_ready",
                    pod=name,
                    namespace=self._namespace,
                    phase=phase,
                    pod_ip=ip,
                )
                return True
            await asyncio.sleep(2)

        logger.warning(
            "k8s_pod_not_ready",
            pod=name,
            namespace=self._namespace,
            timeout=timeout,
        )
        return False

    # -------------------------------------------------------------------------
    # Services
    # -------------------------------------------------------------------------

    async def create_service(self, name: str, pod_name: str, port: int = 3389) -> str:
        """Create a ClusterIP Service for a dev VM pod. Returns service name.

        The service selects the pod via its ``dev-vm-name`` label, exposing the
        RDP port. Guacamole connects to this service's stable DNS name rather
        than the pod IP (which changes on every pod restart).
        """
        api = self._api()
        service = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/name": "druppie",
                    "app.kubernetes.io/component": "dev-vm",
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"dev-vm-name": pod_name},
                ports=[
                    client.V1ServicePort(
                        name="rdp", port=port, target_port=port
                    )
                ],
            ),
        )
        try:
            created = await asyncio.to_thread(
                api.create_namespaced_service,
                namespace=self._namespace,
                body=service,
            )
        except ApiException as exc:
            raise RuntimeError(
                f"Failed to create service '{name}' in namespace "
                f"'{self._namespace}': {exc.reason} (status={exc.status})"
            ) from exc

        logger.info(
            "k8s_service_created",
            service=name,
            namespace=self._namespace,
            pod=pod_name,
            port=port,
        )
        return created.metadata.name

    async def delete_service(self, name: str) -> bool:
        """Delete a service. Best-effort: returns True on success (incl. 404)."""
        api = self._api()
        try:
            await asyncio.to_thread(
                api.delete_namespaced_service,
                name=name,
                namespace=self._namespace,
            )
            logger.info("k8s_service_deleted", service=name, namespace=self._namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return True
            logger.warning(
                "k8s_service_delete_failed",
                service=name,
                namespace=self._namespace,
                status=exc.status,
                reason=exc.reason,
            )
            return False

    # -------------------------------------------------------------------------
    # PersistentVolumeClaims
    # -------------------------------------------------------------------------

    async def create_pvc(self, name: str, size: str = "20Gi") -> str:
        """Create a PVC for the dev VM home dir. Returns PVC name."""
        api = self._api()
        pvc = client.V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/name": "druppie",
                    "app.kubernetes.io/component": "dev-vm",
                },
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=client.V1VolumeResourceRequirements(
                    requests={"storage": size}
                ),
                storage_class_name="local-path",
            ),
        )
        try:
            created = await asyncio.to_thread(
                api.create_namespaced_persistent_volume_claim,
                namespace=self._namespace,
                body=pvc,
            )
        except ApiException as exc:
            raise RuntimeError(
                f"Failed to create PVC '{name}' in namespace "
                f"'{self._namespace}': {exc.reason} (status={exc.status})"
            ) from exc

        logger.info(
            "k8s_pvc_created",
            pvc=name,
            namespace=self._namespace,
            size=size,
        )
        return created.metadata.name

    async def delete_pvc(self, name: str) -> bool:
        """Delete a PVC. Best-effort: returns True on success (incl. 404)."""
        api = self._api()
        try:
            await asyncio.to_thread(
                api.delete_namespaced_persistent_volume_claim,
                name=name,
                namespace=self._namespace,
            )
            logger.info("k8s_pvc_deleted", pvc=name, namespace=self._namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return True
            logger.warning(
                "k8s_pvc_delete_failed",
                pvc=name,
                namespace=self._namespace,
                status=exc.status,
                reason=exc.reason,
            )
            return False
