"""Kubernetes v1 — MCP Tool Definitions.

Read-only cluster introspection: pod status, node health, services, and an
overall cluster health summary. No write, delete, scale, apply, or exec
operations are exposed.
"""

import logging

from fastmcp import FastMCP

from .module import KubernetesModule

logger = logging.getLogger("kubernetes-mcp")

MODULE_ID = "kubernetes"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Kubernetes v1",
    version=MODULE_VERSION,
    instructions=(
        "Read-only access to Kubernetes cluster status. You can list pods, "
        "nodes, and services, and get an overall health summary. No write "
        "operations are available — this server cannot modify the cluster."
    ),
)

module = KubernetesModule()


@mcp.tool()
async def list_pods(namespace: str | None = None) -> dict:
    """List pods with their status, restart count, and age.

    Returns all pods across the cluster by default, or scoped to a single
    namespace. Use this to check which workloads are running, identify
    crashlooping pods, or spot pods stuck in Pending/Unknown state.

    Args:
        namespace: Optional namespace filter. When omitted, returns pods
            from all namespaces.

    Returns:
        Dict with pod_count and a list of pods, each containing name,
        namespace, status, restarts, age, node, and container details.
    """
    return await module.list_pods(namespace)


@mcp.tool()
async def list_nodes() -> dict:
    """List cluster nodes with their status and resource capacity.

    Returns every node in the cluster with its Ready/NotReady status,
    conditions, CPU/memory capacity and allocatable resources, and
    kubelet version.

    Returns:
        Dict with node_count and a list of nodes, each containing name,
        status, age, conditions, capacity, allocatable resources, and
        kubelet version.
    """
    return await module.list_nodes()


@mcp.tool()
async def list_services(namespace: str | None = None) -> dict:
    """List services with their type, cluster IP, and ports.

    Returns all services across the cluster by default, or scoped to a
    single namespace. Use this to check service endpoints and port
    mappings.

    Args:
        namespace: Optional namespace filter. When omitted, returns
            services from all namespaces.

    Returns:
        Dict with service_count and a list of services, each containing
        name, namespace, type, cluster_ip, ports, and age.
    """
    return await module.list_services(namespace)


@mcp.tool()
async def get_cluster_health() -> dict:
    """Get an overall cluster health summary.

    Checks all nodes and pods and returns a single healthy/unhealthy
    verdict with details about any problems found. Flags unhealthy nodes,
    pods not in Running/Succeeded state, and pods with high restart counts
    (more than 5 restarts).

    Returns:
        Dict with healthy (bool), a human-readable summary, node and pod
        counts, and lists of unhealthy_nodes, problem_pods, and
        high_restart_pods.
    """
    return await module.get_cluster_health()
