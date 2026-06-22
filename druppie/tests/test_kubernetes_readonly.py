"""Isolation and read-only tests for the kubernetes MCP server.

The kubernetes module must be strictly read-only: it can list pods, nodes, and
services and report cluster health, but must never expose any tool that can
modify cluster state (delete, scale, apply, exec, patch, etc.).

These tests verify:
1. Static (tools.py): only the expected read-only tools are exposed.
2. Static (tools.py): no tool parameter allows write-like actions.
3. Static (module.py): only read-only Kubernetes API methods are used.
4. Behavioral (module.py): the module returns structured data from mocked
   Kubernetes API responses.

The module-server tree (druppie/mcp-servers/module-kubernetes) is standalone:
it depends on the `kubernetes` package. We stub the kubernetes client and
load source by path, mirroring test_azuredevops_isolation.py.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MOD_DIR = (
    Path(__file__).resolve().parents[1]
    / "mcp-servers"
    / "module-kubernetes"
)

ALLOWED_TOOLS = {"list_pods", "list_nodes", "list_services", "get_cluster_health"}

WRITE_VERBS = {
    "delete", "create", "patch", "replace", "scale", "exec",
    "apply", "restart", "cordon", "uncordon", "drain", "taint",
    "evict", "rollout",
}


def _tool_functions(source_path: Path) -> dict[str, ast.AsyncFunctionDef]:
    """Return {name: node} for every @mcp.tool()-decorated async function."""
    tree = ast.parse(source_path.read_text())
    tools: dict[str, ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                tools[node.name] = node
    return tools


def test_tools_expose_exactly_the_expected_tools():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    assert set(tools) == ALLOWED_TOOLS, (
        f"Unexpected tools exposed: {set(tools) - ALLOWED_TOOLS}"
    )


def test_no_tool_name_contains_write_verb():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    for name in tools:
        for verb in WRITE_VERBS:
            assert verb not in name.lower(), (
                f"Tool '{name}' contains write verb '{verb}'"
            )


def test_module_only_uses_readonly_k8s_api_calls():
    """Scan module.py AST for any Kubernetes API method that is not read-only."""
    source = (_MOD_DIR / "v1" / "module.py").read_text()
    tree = ast.parse(source)

    read_prefixes = ("list_", "get_", "read_")
    write_prefixes = (
        "create_", "delete_", "patch_", "replace_", "connect_",
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if any(attr.startswith(p) for p in write_prefixes):
                pytest.fail(
                    f"module.py calls '{attr}' which looks like a write operation"
                )


def _load_module_py():
    """Load module.py with kubernetes client stubbed out."""
    k8s_stub = types.ModuleType("kubernetes")
    k8s_client = types.ModuleType("kubernetes.client")
    k8s_config = types.ModuleType("kubernetes.config")
    k8s_config_exc = types.ModuleType("kubernetes.config.config_exception")

    k8s_stub.client = k8s_client
    k8s_stub.config = k8s_config

    k8s_client.CoreV1Api = MagicMock
    k8s_client.V1ContainerState = type("V1ContainerState", (), {})
    k8s_config.load_incluster_config = MagicMock()
    k8s_config.load_kube_config = MagicMock()
    k8s_config_exc.ConfigException = type("ConfigException", (Exception,), {})

    saved = {}
    for mod_name in ["kubernetes", "kubernetes.client", "kubernetes.config",
                     "kubernetes.config.config_exception"]:
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules["kubernetes"] = k8s_stub
    sys.modules["kubernetes.client"] = k8s_client
    sys.modules["kubernetes.config"] = k8s_config
    sys.modules["kubernetes.config.config_exception"] = k8s_config_exc

    try:
        spec = importlib.util.spec_from_file_location(
            "v1.module", _MOD_DIR / "v1" / "module.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for mod_name, original in saved.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original


def test_kubernetes_module_class_has_only_readonly_public_methods():
    """Verify KubernetesModule exposes no methods that could modify state."""
    mod = _load_module_py()
    cls = mod.KubernetesModule
    public_methods = [
        m for m in dir(cls)
        if not m.startswith("_") and callable(getattr(cls, m))
    ]
    for method in public_methods:
        for verb in WRITE_VERBS:
            assert verb not in method.lower(), (
                f"KubernetesModule.{method}() contains write verb '{verb}'"
            )


@pytest.mark.asyncio
async def test_list_pods_returns_structured_data():
    mod = _load_module_py()
    module = mod.KubernetesModule()

    mock_pod = MagicMock()
    mock_pod.metadata.name = "backend-abc123"
    mock_pod.metadata.namespace = "druppie"
    mock_pod.metadata.creation_timestamp = None
    mock_pod.status.phase = "Running"
    mock_pod.status.container_statuses = []
    mock_pod.spec.node_name = "node-1"

    mock_api = MagicMock()
    mock_api.list_pod_for_all_namespaces.return_value.items = [mock_pod]
    mock_api.list_pod_for_all_namespaces.return_value.metadata._continue = None
    module._core = mock_api

    result = await module.list_pods()
    assert result["pod_count"] == 1
    assert result["pods"][0]["name"] == "backend-abc123"
    assert result["pods"][0]["namespace"] == "druppie"
    assert result["pods"][0]["status"] == "Running"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_list_nodes_returns_structured_data():
    mod = _load_module_py()
    module = mod.KubernetesModule()

    mock_condition = MagicMock()
    mock_condition.type = "Ready"
    mock_condition.status = "True"

    mock_node = MagicMock()
    mock_node.metadata.name = "node-1"
    mock_node.metadata.creation_timestamp = None
    mock_node.status.conditions = [mock_condition]
    mock_node.status.allocatable = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.capacity = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.node_info.kubelet_version = "v1.29.2"

    mock_api = MagicMock()
    mock_api.list_node.return_value.items = [mock_node]
    mock_api.list_node.return_value.metadata._continue = None
    module._core = mock_api

    result = await module.list_nodes()
    assert result["node_count"] == 1
    assert result["nodes"][0]["name"] == "node-1"
    assert result["nodes"][0]["status"] == "Ready"


@pytest.mark.asyncio
async def test_get_cluster_health_healthy():
    mod = _load_module_py()
    module = mod.KubernetesModule()

    mock_condition = MagicMock()
    mock_condition.type = "Ready"
    mock_condition.status = "True"

    mock_node = MagicMock()
    mock_node.metadata.name = "node-1"
    mock_node.metadata.creation_timestamp = None
    mock_node.status.conditions = [mock_condition]
    mock_node.status.allocatable = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.capacity = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.node_info.kubelet_version = "v1.29.2"

    mock_pod = MagicMock()
    mock_pod.metadata.name = "backend-abc123"
    mock_pod.metadata.namespace = "druppie"
    mock_pod.metadata.creation_timestamp = None
    mock_pod.status.phase = "Running"
    mock_pod.status.container_statuses = []
    mock_pod.spec.node_name = "node-1"

    mock_api = MagicMock()
    mock_api.list_node.return_value.items = [mock_node]
    mock_api.list_node.return_value.metadata._continue = None
    mock_api.list_pod_for_all_namespaces.return_value.items = [mock_pod]
    mock_api.list_pod_for_all_namespaces.return_value.metadata._continue = None
    module._core = mock_api

    result = await module.get_cluster_health()
    assert result["healthy"] is True
    assert result["truncated"] is False
    assert "healthy" in result["summary"].lower()


@pytest.mark.asyncio
async def test_get_cluster_health_unhealthy_node():
    mod = _load_module_py()
    module = mod.KubernetesModule()

    mock_condition = MagicMock()
    mock_condition.type = "Ready"
    mock_condition.status = "False"

    mock_node = MagicMock()
    mock_node.metadata.name = "bad-node"
    mock_node.metadata.creation_timestamp = None
    mock_node.status.conditions = [mock_condition]
    mock_node.status.allocatable = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.capacity = {"cpu": "4", "memory": "8Gi", "pods": "110"}
    mock_node.status.node_info.kubelet_version = "v1.29.2"

    mock_api = MagicMock()
    mock_api.list_node.return_value.items = [mock_node]
    mock_api.list_node.return_value.metadata._continue = None
    mock_api.list_pod_for_all_namespaces.return_value.items = []
    mock_api.list_pod_for_all_namespaces.return_value.metadata._continue = None
    module._core = mock_api

    result = await module.get_cluster_health()
    assert result["healthy"] is False
    assert "bad-node" in result["summary"]


@pytest.mark.asyncio
async def test_list_pods_passes_limit_and_flags_truncation():
    """list_pods forwards the limit to the API and reports truncation."""
    mod = _load_module_py()
    module = mod.KubernetesModule()

    mock_pod = MagicMock()
    mock_pod.metadata.name = "backend-abc123"
    mock_pod.metadata.namespace = "druppie"
    mock_pod.metadata.creation_timestamp = None
    mock_pod.status.phase = "Running"
    mock_pod.status.container_statuses = []
    mock_pod.spec.node_name = "node-1"

    mock_api = MagicMock()
    mock_api.list_pod_for_all_namespaces.return_value.items = [mock_pod]
    # A non-empty continue token means the cluster has more pods than the limit.
    mock_api.list_pod_for_all_namespaces.return_value.metadata._continue = "next-token"
    module._core = mock_api

    result = await module.list_pods(limit=50)

    mock_api.list_pod_for_all_namespaces.assert_called_once_with(limit=50)
    assert result["limit"] == 50
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_list_calls_run_in_thread_not_blocking_event_loop():
    """The synchronous kubernetes client calls must be offloaded to a thread.

    We assert the API method runs on a worker thread (not the event loop
    thread), which is what asyncio.to_thread guarantees.
    """
    import threading

    mod = _load_module_py()
    module = mod.KubernetesModule()

    loop_thread = threading.get_ident()
    call_threads = []

    def fake_list_node(**kwargs):
        call_threads.append(threading.get_ident())
        result = MagicMock()
        result.items = []
        result.metadata._continue = None
        return result

    mock_api = MagicMock()
    mock_api.list_node.side_effect = fake_list_node
    module._core = mock_api

    await module.list_nodes()

    assert call_threads and call_threads[0] != loop_thread
