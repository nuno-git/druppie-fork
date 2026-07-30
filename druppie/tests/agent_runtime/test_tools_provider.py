"""Tests for druppie.agent_runtime.tools.provider."""

from unittest.mock import AsyncMock

import pytest

from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.tools.provider import MCPToolProvider, ToolProvider


def _make_connection(
    server_name: str,
    tool_names: list[str],
    call_fn=None,
) -> MCPConnection:
    """Helper to create a mock MCPConnection."""
    tools = [{"name": n, "parameters": {"type": "object", "properties": {}}} for n in tool_names]
    return MCPConnection(
        server_name=server_name,
        endpoint=f"http://{server_name}:9000",
        tools=tools,
        _call_tool_fn=call_fn or AsyncMock(return_value={"success": True, "data": "ok"}),
    )


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_tools_aggregates_all(self):
        sandbox = _make_connection("sandbox", ["read_file", "write_file"])
        core = _make_connection("core-tools", ["make_plan", "hitl_ask"])
        provider = MCPToolProvider({"sandbox": sandbox, "core-tools": core})

        tools = await provider.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"read_file", "write_file", "make_plan", "hitl_ask"}

    @pytest.mark.asyncio
    async def test_list_tools_empty(self):
        provider = MCPToolProvider()
        tools = await provider.list_tools()
        assert tools == []


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_routes_to_correct_server(self):
        call_fn = AsyncMock(return_value={"success": True, "data": "file content"})
        sandbox = _make_connection("sandbox", ["read_file"], call_fn)
        provider = MCPToolProvider({"sandbox": sandbox})

        result = await provider.execute("read_file", {"path": "/tmp/test.txt"})
        assert result["success"] is True
        call_fn.assert_called_once_with("read_file", {"path": "/tmp/test.txt"})

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        provider = MCPToolProvider()
        result = await provider.execute("unknown_tool", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_success(self):
        call_fn = AsyncMock(return_value={"success": True, "data": "result"})
        conn = _make_connection("test", ["my_tool"], call_fn)
        provider = MCPToolProvider({"test": conn})

        result = await provider.execute("my_tool", {"arg": "value"})
        assert result["success"] is True
        assert result["data"] == "result"

    @pytest.mark.asyncio
    async def test_execute_error_returns_error_dict(self):
        call_fn = AsyncMock(return_value={"success": False, "error": "Something broke"})
        conn = _make_connection("test", ["failing_tool"], call_fn)
        provider = MCPToolProvider({"test": conn})

        result = await provider.execute("failing_tool", {})
        assert result["success"] is False
        assert "Something broke" in result["error"]


class TestToolMapping:
    def test_tool_name_mapping_built(self):
        sandbox = _make_connection("sandbox", ["read_file", "write_file"])
        core = _make_connection("core-tools", ["make_plan"])
        provider = MCPToolProvider({"sandbox": sandbox, "core-tools": core})

        assert provider.get_server_for_tool("read_file") == "sandbox"
        assert provider.get_server_for_tool("write_file") == "sandbox"
        assert provider.get_server_for_tool("make_plan") == "core-tools"
        assert provider.get_server_for_tool("unknown") is None

    def test_mapping_updated_on_add(self):
        provider = MCPToolProvider()
        conn = _make_connection("test", ["new_tool"])
        provider.add_connection("test", conn)
        assert provider.get_server_for_tool("new_tool") == "test"

    def test_mapping_updated_on_remove(self):
        conn = _make_connection("test", ["my_tool"])
        provider = MCPToolProvider({"test": conn})
        assert provider.get_server_for_tool("my_tool") == "test"
        provider.remove_connection("test")
        assert provider.get_server_for_tool("my_tool") is None


class TestClose:
    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        conn = _make_connection("test", ["tool1"])
        provider = MCPToolProvider({"test": conn})
        await provider.close()
        assert len(provider._connections) == 0
        assert len(provider._tool_to_server) == 0


class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_approval_gate_pending(self):
        call_fn = AsyncMock(return_value={"success": True, "data": "should not be called"})
        conn = _make_connection("sandbox", ["push_changes"], call_fn)
        provider = MCPToolProvider(
            {"sandbox": conn},
            approval_overrides={
                "sandbox:push_changes": {"requires_approval": True, "required_role": "architect"},
            },
        )

        result = await provider.execute("push_changes", {"branch": "main"})
        assert result["success"] is True
        assert result.get("_pending") is True
        assert "resume_id" in result
        assert result["required_role"] == "architect"
        call_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_approval_for_non_overridden_tool(self):
        call_fn = AsyncMock(return_value={"success": True, "data": "done"})
        conn = _make_connection("sandbox", ["read_file"], call_fn)
        provider = MCPToolProvider(
            {"sandbox": conn},
            approval_overrides={
                "sandbox:push_changes": {"requires_approval": True},
            },
        )

        result = await provider.execute("read_file", {"path": "/tmp"})
        assert result["success"] is True
        assert result.get("_pending") is None
        call_fn.assert_called_once()


class TestPrevalidation:
    @pytest.mark.asyncio
    async def test_prevalidation_hook_pass(self):
        calls = []

        async def mock_call(name, args):
            calls.append(name)
            if name == "validate_mermaid":
                return {"success": True, "data": "valid"}
            return {"success": True, "data": "design created"}

        conn = _make_connection("sandbox", ["submit_design_for_review", "validate_mermaid"], mock_call)
        provider = MCPToolProvider(
            {"sandbox": conn},
            approval_overrides={
                "sandbox:submit_design_for_review": {"pre_validate": "validate_mermaid"},
            },
        )

        result = await provider.execute("submit_design_for_review", {"content": "graph TD..."})
        assert result["success"] is True
        assert calls == ["validate_mermaid", "submit_design_for_review"]

    @pytest.mark.asyncio
    async def test_prevalidation_hook_fail(self):
        async def mock_call(name, args):
            if name == "validate_mermaid":
                return {"success": False, "error": "Invalid mermaid syntax"}
            return {"success": True, "data": "should not reach"}

        conn = _make_connection("sandbox", ["submit_design_for_review", "validate_mermaid"], mock_call)
        provider = MCPToolProvider(
            {"sandbox": conn},
            approval_overrides={
                "sandbox:submit_design_for_review": {"pre_validate": "validate_mermaid"},
            },
        )

        result = await provider.execute("submit_design_for_review", {"content": "bad syntax"})
        assert result["success"] is False
        assert "Invalid mermaid" in result["error"]


class TestProtocolCompliance:
    def test_protocol_compliance(self):
        provider = MCPToolProvider()
        assert isinstance(provider, ToolProvider)
