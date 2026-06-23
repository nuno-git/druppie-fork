"""Tests for druppie.agent_runtime.tools.mcp."""


import pytest

from druppie.agent_runtime.tools.mcp import MCPConnection


class TestMCPConnection:
    def test_mcp_connection_creation(self):
        conn = MCPConnection(
            server_name="sandbox",
            endpoint="http://localhost:9001",
            tools=[{"name": "read_file", "parameters": {}}],
        )
        assert conn.server_name == "sandbox"
        assert conn.endpoint == "http://localhost:9001"
        assert len(conn.tools) == 1

    def test_mcp_connection_in_process(self):
        conn = MCPConnection(server_name="core-tools", endpoint=None)
        assert conn.endpoint is None

    def test_mcp_connection_tools_list(self):
        tools = [
            {"name": "read_file", "parameters": {"type": "object"}},
            {"name": "write_file", "parameters": {"type": "object"}},
        ]
        conn = MCPConnection(server_name="sandbox", endpoint=None, tools=tools)
        assert len(conn.tools) == 2
        assert conn.tools[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_mcp_connection_call_tool(self):
        async def mock_call(name, args):
            return {"success": True, "data": f"result of {name}"}

        conn = MCPConnection(
            server_name="test",
            endpoint=None,
            _call_tool_fn=mock_call,
        )
        result = await conn.call_tool("read_file", {"path": "/tmp/test.txt"})
        assert result["success"] is True
        assert "read_file" in result["data"]

    @pytest.mark.asyncio
    async def test_mcp_connection_call_tool_no_fn(self):
        conn = MCPConnection(server_name="test", endpoint=None)
        result = await conn.call_tool("read_file", {})
        assert result["success"] is False
        assert "No call_tool function" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_connection_call_tool_error(self):
        async def failing_call(name, args):
            raise RuntimeError("Server crashed")

        conn = MCPConnection(
            server_name="test",
            endpoint=None,
            _call_tool_fn=failing_call,
        )
        result = await conn.call_tool("read_file", {})
        assert result["success"] is False
        assert "Server crashed" in result["error"]
