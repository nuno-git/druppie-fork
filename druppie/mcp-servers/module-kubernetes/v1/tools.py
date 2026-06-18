"""Kubernetes v1 — MCP Tool Definitions.

Read-only cluster introspection: pod status, node health, services, and an
overall cluster health summary. No write, delete, scale, apply, or exec
operations are exposed.
"""

import logging

from fastmcp import FastMCP

from .module import DEFAULT_LIST_LIMIT, KubernetesModule

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
async def list_pods(
    namespace: str | None = None, limit: int = DEFAULT_LIST_LIMIT
) -> dict:
    """List pods with their status, restart count, and age.

    Returns pods across the cluster by default, or scoped to a single
    namespace. Use this to check which workloads are running, identify
    crashlooping pods, or spot pods stuck in Pending/Unknown state.

    Args:
        namespace: Optional namespace filter. When omitted, returns pods
            from all namespaces.
        limit: Maximum number of pods to return (default 100). Raise this to
            inspect more pods at the cost of a larger response.

    Returns:
        Dict with pod_count, a list of pods (each containing name,
        namespace, status, restarts, age, node, and container details),
        the applied limit, and a truncated flag indicating whether more
        pods exist beyond the limit.
    """
    return await module.list_pods(namespace, limit)


@mcp.tool()
async def list_nodes(limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """List cluster nodes with their status and resource capacity.

    Returns cluster nodes with their Ready/NotReady status, conditions,
    CPU/memory capacity and allocatable resources, and kubelet version.

    Args:
        limit: Maximum number of nodes to return (default 100).

    Returns:
        Dict with node_count, a list of nodes (each containing name,
        status, age, conditions, capacity, allocatable resources, and
        kubelet version), the applied limit, and a truncated flag.
    """
    return await module.list_nodes(limit)


@mcp.tool()
async def list_services(
    namespace: str | None = None, limit: int = DEFAULT_LIST_LIMIT
) -> dict:
    """List services with their type, cluster IP, and ports.

    Returns services across the cluster by default, or scoped to a single
    namespace. Use this to check service endpoints and port mappings.

    Args:
        namespace: Optional namespace filter. When omitted, returns
            services from all namespaces.
        limit: Maximum number of services to return (default 100).

    Returns:
        Dict with service_count, a list of services (each containing
        name, namespace, type, cluster_ip, ports, and age), the applied
        limit, and a truncated flag.
    """
    return await module.list_services(namespace, limit)


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
