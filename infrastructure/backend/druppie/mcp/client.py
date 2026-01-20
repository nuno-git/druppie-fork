"""MCP Client for invoking tools on MCP servers.

Handles the communication with MCP servers via stdio or HTTP.
"""

import asyncio
import json
import subprocess
from typing import Any

import httpx
import structlog

from druppie.mcp.registry import MCPRegistry, MCPServer

logger = structlog.get_logger()


class MCPClient:
    """Client for invoking tools on MCP servers.

    Supports both stdio and HTTP transports.
    """

    def __init__(self, registry: MCPRegistry):
        self.registry = registry
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MCPClient":
        self._http_client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._http_client:
            await self._http_client.aclose()
        for proc in self._processes.values():
            proc.terminate()
        self._processes.clear()

    async def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on an MCP server.

        Args:
            tool_name: The tool to invoke (e.g., "filesystem.read_file")
            arguments: Arguments to pass to the tool

        Returns:
            The tool's response
        """
        server = self.registry.get_server_for_tool(tool_name)
        if not server:
            raise ValueError(f"No server found for tool: {tool_name}")

        # Extract short tool name
        if "." in tool_name:
            _, short_name = tool_name.split(".", 1)
        else:
            short_name = tool_name

        logger.debug(
            "Invoking MCP tool",
            server=server.id,
            tool=short_name,
            arguments=arguments,
        )

        if server.transport == "stdio":
            return await self._invoke_stdio(server, short_name, arguments or {})
        elif server.transport in ("http", "sse"):
            return await self._invoke_http(server, short_name, arguments or {})
        else:
            raise ValueError(f"Unsupported transport: {server.transport}")

    async def _invoke_stdio(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a tool via stdio transport."""
        if not server.command:
            raise ValueError(f"Server {server.id} has no command configured")

        # Build the JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        # Get or start the process
        proc = self._get_or_start_process(server)

        # Send request
        request_bytes = json.dumps(request).encode() + b"\n"
        proc.stdin.write(request_bytes)  # type: ignore
        proc.stdin.flush()  # type: ignore

        # Read response (simple line-based protocol)
        response_line = proc.stdout.readline()  # type: ignore
        if not response_line:
            raise RuntimeError(f"No response from MCP server {server.id}")

        response = json.loads(response_line)

        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")

        return response.get("result", {})

    def _get_or_start_process(self, server: MCPServer) -> subprocess.Popen[bytes]:
        """Get existing process or start a new one."""
        if server.id in self._processes:
            proc = self._processes[server.id]
            if proc.poll() is None:  # Still running
                return proc

        # Start new process
        env = dict(**server.env) if server.env else None
        cmd = [server.command] + server.args if server.command else server.args

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._processes[server.id] = proc
        logger.info("Started MCP server process", server=server.id, pid=proc.pid)
        return proc

    async def _invoke_http(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a tool via HTTP transport."""
        if not server.url:
            raise ValueError(f"Server {server.id} has no URL configured")

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=60.0)

        # Build the JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        response = await self._http_client.post(
            server.url,
            json=request,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()

        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error']}")

        return result.get("result", {})

    async def list_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        """List tools available on a specific server (via MCP protocol)."""
        server = self.registry.get_server(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")

        # For now, return tools from registry
        # In production, this would query the server directly
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in server.tools
        ]


def create_langchain_tool(client: MCPClient, tool_name: str):
    """Create a LangChain-compatible tool from an MCP tool.

    This allows MCP tools to be used directly with LangChain/LangGraph.
    """
    from langchain_core.tools import StructuredTool

    tool_def = client.registry.get_tool(tool_name)
    if not tool_def:
        raise ValueError(f"Tool not found: {tool_name}")

    server = client.registry.get_server_for_tool(tool_name)
    server_name = server.name if server else "Unknown"

    async def invoke_tool(**kwargs: Any) -> str:
        result = await client.invoke(tool_name, kwargs)
        return json.dumps(result)

    # Create sync wrapper for LangChain
    def sync_invoke(**kwargs: Any) -> str:
        return asyncio.get_event_loop().run_until_complete(invoke_tool(**kwargs))

    return StructuredTool.from_function(
        func=sync_invoke,
        coroutine=invoke_tool,
        name=tool_name.replace(".", "__"),  # LangChain-safe name
        description=f"[{server_name}] {tool_def.description}",
        args_schema=None,  # Would need Pydantic model from input_schema
    )


def get_langchain_tools(client: MCPClient, tool_names: list[str] | None = None):
    """Get multiple LangChain tools from MCP registry.

    Args:
        client: The MCP client
        tool_names: Specific tools to get, or None for all tools

    Returns:
        List of LangChain tools
    """
    if tool_names is None:
        # Get all tools from registry
        all_tools = client.registry.list_tools()
        tool_names = [t["name"] for t in all_tools]

    return [create_langchain_tool(client, name) for name in tool_names]
