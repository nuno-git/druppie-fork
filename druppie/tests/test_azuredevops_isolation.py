"""Isolation tests for the azuredevops MCP server.

The whole point of this module is that an agent can read backlog / work items
from exactly ONE configured Azure DevOps project and can never reach another
project. These tests pin that guarantee from two angles:

1. Static (tools.py): there is no project picker — no `list_projects` tool and
   no tool parameter that lets the caller choose a project / org.
2. Behavioral (module.py + client.py): every request the module issues is
   path-scoped to AZURE_DEVOPS_PROJECT and every WIQL query carries the
   [System.TeamProject] = '<project>' clause.

The module-server tree (`druppie/mcp-servers/module-azuredevops`) is a
standalone service: it depends on `httpx` and `azure-identity`, which are NOT
installed in the main druppie test environment, and `tools.py` additionally
needs `fastmcp`. We therefore stub the network/auth deps and load the source by
path, mirroring `test_dataaccess_charts.py`.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_MOD_DIR = (
    Path(__file__).resolve().parents[1]
    / "mcp-servers"
    / "module-azuredevops"
)
_PROJECT = "TheOnlyProject"


# ---------------------------------------------------------------------------
# Static check — tools.py exposes no project picker
# ---------------------------------------------------------------------------

def _tool_functions(source_path: Path) -> dict[str, ast.AsyncFunctionDef]:
    """Return {name: node} for every @mcp.tool()-decorated async function."""
    tree = ast.parse(source_path.read_text())
    tools: dict[str, ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            # Matches @mcp.tool() and @mcp.tool
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                tools[node.name] = node
    return tools


def test_tools_expose_exactly_the_expected_tools():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    assert set(tools) == {
        "get_current_sprint",
        "get_sprint_summary",
        "list_backlog_items",
        "get_work_item",
        "search_work_items",
        "create_work_item",
        "update_work_item",
    }


def test_no_project_picker_tool():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    # A tool that lists or selects projects would break single-project isolation.
    assert "list_projects" not in tools
    assert not any("project" in name for name in tools)


def test_no_tool_accepts_a_project_or_org_argument():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    forbidden = {"project", "project_id", "project_name", "org", "org_url", "organization"}
    for name, node in tools.items():
        params = {a.arg for a in node.args.args}
        leaked = params & forbidden
        assert not leaked, f"tool {name} exposes project/org argument(s): {leaked}"


# ---------------------------------------------------------------------------
# Behavioral check — every request is scoped to the configured project
# ---------------------------------------------------------------------------

def _install_dep_stubs() -> None:
    """Provide minimal stand-ins for httpx + azure-identity (not installed here)."""
    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")

        class _AsyncClient:  # pragma: no cover - never actually used (we patch _post/_get)
            def __init__(self, *a, **k):
                ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        httpx.AsyncClient = _AsyncClient
        sys.modules["httpx"] = httpx

    if "azure.identity.aio" not in sys.modules:
        azure = sys.modules.setdefault("azure", types.ModuleType("azure"))
        identity = sys.modules.setdefault(
            "azure.identity", types.ModuleType("azure.identity")
        )
        aio = types.ModuleType("azure.identity.aio")

        class _Token:
            token = "stub-token"

        class _ClientSecretCredential:
            def __init__(self, *a, **k):
                ...

            async def get_token(self, *a, **k):
                return _Token()

            async def close(self):
                ...

        aio.ClientSecretCredential = _ClientSecretCredential
        azure.identity = identity
        identity.aio = aio
        sys.modules["azure.identity.aio"] = aio


def _load_module_under_test(monkeypatch):
    """Load v1.module (and its v1.client dependency) with env + deps stubbed."""
    _install_dep_stubs()
    monkeypatch.setenv("AZURE_DEVOPS_ORG_URL", "https://dev.azure.com/acme")
    monkeypatch.setenv("AZURE_DEVOPS_PROJECT", _PROJECT)
    monkeypatch.setenv("AZURE_DEVOPS_TENANT_ID", "t")
    monkeypatch.setenv("AZURE_DEVOPS_CLIENT_ID", "c")
    monkeypatch.setenv("AZURE_DEVOPS_CLIENT_SECRET", "s")

    # Load v1.client then v1.module by path under a synthetic package so the
    # `from .client import ...` relative import in module.py resolves.
    pkg = types.ModuleType("ado_v1")
    pkg.__path__ = [str(_MOD_DIR / "v1")]
    sys.modules["ado_v1"] = pkg

    for name in ("client", "module"):
        spec = importlib.util.spec_from_file_location(
            f"ado_v1.{name}", _MOD_DIR / "v1" / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"ado_v1.{name}"] = mod
        spec.loader.exec_module(mod)

    return sys.modules["ado_v1.module"]


class _RecordingClient:
    """Wraps the real client but records every REST path + WIQL it sends."""

    def __init__(self, real):
        self._real = real
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict | None]] = []
        self.patches: list[tuple[str, list]] = []

    @property
    def project(self):
        return self._real.project

    @property
    def org_url(self):
        return self._real.org_url

    async def query_wiql(self, wiql, top):
        self.posts.append((f"{self._real.project}/_apis/wit/wiql", {"query": wiql}))
        return [1, 2]

    async def get_work_items(self, ids, fields=None):
        self.posts.append(
            (f"{self._real.project}/_apis/wit/workitemsbatch", {"ids": ids})
        )
        return [
            {"id": i, "fields": {"System.Title": f"WI {i}", "System.State": "New"}}
            for i in ids
        ]

    async def get_work_item(self, item_id):
        self.gets.append((f"{self._real.project}/_apis/wit/workitems/{item_id}", None))
        return {"id": item_id, "fields": {"System.Title": "WI"}}

    async def create_work_item(self, work_item_type, operations):
        path = f"{self._real.project}/_apis/wit/workitems/${work_item_type}"
        self.posts.append((path, {"operations": operations}))
        return {
            "id": 999,
            "fields": {
                "System.Title": "Created",
                "System.WorkItemType": work_item_type,
                "System.State": "New",
            },
        }

    async def update_work_item(self, item_id, operations):
        path = f"{self._real.project}/_apis/wit/workitems/{item_id}"
        self.patches.append((path, operations))
        return {
            "id": item_id,
            "fields": {
                "System.Title": "Updated",
                "System.WorkItemType": "Bug",
                "System.State": "New",
            },
        }


@pytest.mark.asyncio
async def test_all_requests_are_scoped_to_configured_project(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    mod = module_mod.AzureDevOpsModule()

    rec = _RecordingClient(mod._client)
    mod._client = rec

    await mod.list_backlog_items(work_item_type="Bug", state="Active", limit=10)
    await mod.search_work_items("login", limit=5)
    await mod.get_work_item(4321)

    prefix = f"{_PROJECT}/_apis/"
    for path, _ in rec.posts:
        assert path.startswith(prefix), f"POST escaped project scope: {path}"
    for path, _ in rec.gets:
        assert path.startswith(prefix), f"GET escaped project scope: {path}"

    # Every WIQL query must pin the team project explicitly.
    wiqls = [body["query"] for path, body in rec.posts if path.endswith("/wiql")]
    assert wiqls, "expected at least one WIQL query"
    for q in wiqls:
        assert f"[System.TeamProject] = '{_PROJECT}'" in q


@pytest.mark.asyncio
async def test_missing_config_fails_fast(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    monkeypatch.delenv("AZURE_DEVOPS_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError) as exc:
        module_mod.AzureDevOpsModule()
    assert "AZURE_DEVOPS_CLIENT_SECRET" in str(exc.value)


def test_wiql_escaping_prevents_quote_breakout(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    # Single quotes in user/config values must be doubled so they cannot break
    # out of the WIQL string literal (and thus cannot drop the project clause).
    assert module_mod._wiql_escape("a'b") == "a''b"


@pytest.mark.asyncio
async def test_create_work_item_is_project_scoped(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    mod = module_mod.AzureDevOpsModule()
    rec = _RecordingClient(mod._client)
    mod._client = rec

    result = await mod.create_work_item(work_item_type="Bug", title="Test bug")
    assert result["success"] is True

    prefix = f"{_PROJECT}/_apis/"
    for path, _ in rec.posts:
        assert path.startswith(prefix), f"POST escaped project scope: {path}"


@pytest.mark.asyncio
async def test_update_work_item_is_project_scoped(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    mod = module_mod.AzureDevOpsModule()
    rec = _RecordingClient(mod._client)
    mod._client = rec

    result = await mod.update_work_item(item_id=123, title="Updated title")
    assert result["success"] is True

    prefix = f"{_PROJECT}/_apis/"
    for path, _ in rec.patches:
        assert path.startswith(prefix), f"PATCH escaped project scope: {path}"


@pytest.mark.asyncio
async def test_create_work_item_rejects_invalid_type(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    mod = module_mod.AzureDevOpsModule()

    result = await mod.create_work_item(work_item_type="Invalid", title="Test")
    assert result["success"] is False
    assert "Invalid" in result["error"]


@pytest.mark.asyncio
async def test_update_work_item_rejects_empty_update(monkeypatch):
    module_mod = _load_module_under_test(monkeypatch)
    mod = module_mod.AzureDevOpsModule()

    result = await mod.update_work_item(item_id=123)
    assert result["success"] is False
    assert "No fields" in result["error"]
