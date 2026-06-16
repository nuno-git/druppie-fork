"""Kubernetes module — read-only cluster introspection.

Uses the official kubernetes Python client. Loads in-cluster config when
running as a pod (ServiceAccount token), falls back to default kubeconfig
for local development.
"""

import logging
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

logger = logging.getLogger("kubernetes-mcp")


class KubernetesModule:
    def __init__(self) -> None:
        self._core: client.CoreV1Api | None = None

    def _api(self) -> client.CoreV1Api:
        if self._core is None:
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            except ConfigException:
                try:
                    config.load_kube_config()
                    logger.info("Loaded kubeconfig from default location")
                except ConfigException as exc:
                    # Distinguish "no kubeconfig at all" from "kubeconfig present
                    # but invalid/incomplete" — the latter is common when a kind
                    # cluster is still being created and the file has no
                    # current-context yet. Collapsing both into one generic
                    # message hides the real cause.
                    raise RuntimeError(
                        "Cannot load Kubernetes config. No in-cluster config, "
                        f"and the kubeconfig could not be loaded: {exc}. "
                        "Ensure a cluster exists (e.g. kind create cluster) and "
                        "a complete ~/.kube/config is mounted into the container."
                    ) from exc
            self._core = client.CoreV1Api()
        return self._core

    def _age(self, created: datetime | None) -> str:
        if created is None:
            return "unknown"
        delta = datetime.now(timezone.utc) - created.replace(tzinfo=timezone.utc)
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        if days > 0:
            return f"{days}d{hours}h"
        if hours > 0:
            return f"{hours}h{minutes}m"
        return f"{minutes}m"

    async def list_pods(self, namespace: str | None = None) -> dict:
        api = self._api()
        if namespace:
            pod_list = api.list_namespaced_pod(namespace)
        else:
            pod_list = api.list_pod_for_all_namespaces()

        pods = []
        for pod in pod_list.items:
            restarts = 0
            container_statuses = []
            for cs in (pod.status.container_statuses or []):
                restarts += cs.restart_count
                container_statuses.append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": self._container_state(cs.state),
                })

            pods.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "restarts": restarts,
                "age": self._age(pod.metadata.creation_timestamp),
                "node": pod.spec.node_name,
                "containers": container_statuses,
            })

        return {
            "pod_count": len(pods),
            "pods": pods,
        }

    async def list_nodes(self) -> dict:
        api = self._api()
        node_list = api.list_node()

        nodes = []
        for node in node_list.items:
            conditions = {
                c.type: c.status
                for c in (node.status.conditions or [])
            }
            allocatable = node.status.allocatable or {}
            capacity = node.status.capacity or {}

            nodes.append({
                "name": node.metadata.name,
                "status": "Ready" if conditions.get("Ready") == "True" else "NotReady",
                "age": self._age(node.metadata.creation_timestamp),
                "conditions": conditions,
                "capacity": {
                    "cpu": capacity.get("cpu", "?"),
                    "memory": capacity.get("memory", "?"),
                    "pods": capacity.get("pods", "?"),
                },
                "allocatable": {
                    "cpu": allocatable.get("cpu", "?"),
                    "memory": allocatable.get("memory", "?"),
                    "pods": allocatable.get("pods", "?"),
                },
                "kubelet_version": node.status.node_info.kubelet_version if node.status.node_info else "?",
            })

        return {
            "node_count": len(nodes),
            "nodes": nodes,
        }

    async def list_services(self, namespace: str | None = None) -> dict:
        api = self._api()
        if namespace:
            svc_list = api.list_namespaced_service(namespace)
        else:
            svc_list = api.list_service_for_all_namespaces()

        services = []
        for svc in svc_list.items:
            ports = []
            for p in (svc.spec.ports or []):
                port_info = {"port": p.port, "protocol": p.protocol}
                if p.target_port:
                    port_info["target_port"] = str(p.target_port)
                if p.node_port:
                    port_info["node_port"] = p.node_port
                ports.append(port_info)

            services.append({
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": ports,
                "age": self._age(svc.metadata.creation_timestamp),
            })

        return {
            "service_count": len(services),
            "services": services,
        }

    async def get_cluster_health(self) -> dict:
        nodes_result = await self.list_nodes()
        pods_result = await self.list_pods()

        unhealthy_nodes = [
            n for n in nodes_result["nodes"]
            if n["status"] != "Ready"
        ]
        problem_pods = [
            p for p in pods_result["pods"]
            if p["status"] not in ("Running", "Succeeded")
        ]
        high_restart_pods = [
            p for p in pods_result["pods"]
            if p["restarts"] > 5
        ]

        healthy = len(unhealthy_nodes) == 0 and len(problem_pods) == 0

        summary_parts = []
        if healthy and not high_restart_pods:
            summary_parts.append(
                f"Cluster is healthy. {nodes_result['node_count']} node(s) ready, "
                f"{pods_result['pod_count']} pod(s) running."
            )
        else:
            if unhealthy_nodes:
                names = ", ".join(n["name"] for n in unhealthy_nodes)
                summary_parts.append(f"Unhealthy nodes: {names}")
            if problem_pods:
                details = ", ".join(
                    f"{p['namespace']}/{p['name']} ({p['status']})"
                    for p in problem_pods
                )
                summary_parts.append(f"Problem pods: {details}")
            if high_restart_pods:
                details = ", ".join(
                    f"{p['namespace']}/{p['name']} ({p['restarts']} restarts)"
                    for p in high_restart_pods
                )
                summary_parts.append(f"High restart pods: {details}")

        return {
            "healthy": healthy,
            "summary": " | ".join(summary_parts),
            "node_count": nodes_result["node_count"],
            "unhealthy_nodes": unhealthy_nodes,
            "pod_count": pods_result["pod_count"],
            "problem_pods": problem_pods,
            "high_restart_pods": high_restart_pods,
        }

    def _container_state(self, state: client.V1ContainerState | None) -> str:
        if state is None:
            return "unknown"
        if state.running:
            return "running"
        if state.waiting:
            return f"waiting: {state.waiting.reason or 'unknown'}"
        if state.terminated:
            return f"terminated: {state.terminated.reason or 'unknown'}"
        return "unknown"
