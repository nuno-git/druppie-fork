"""Simple HTTP client for MCP servers.

This module provides a clean HTTP interface to MCP server containers.
It does NOT contain business logic - just HTTP communication.

Business logic (approval checking, etc.) is handled by ToolExecutor.
"""

import asyncio
import json
from typing import Any

import structlog
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from druppie.core.mcp_config import MCPConfig

logger = structlog.get_logger()


class MCPHttpError(Exception):
    """Error communicating with MCP server."""

    def __init__(self, server: str, tool: str, message: str, retryable: bool = False):
        self.server = server
        self.tool = tool
        self.retryable = retryable
        super().__init__(message)


class MCPHttp:
    """Simple HTTP client for MCP servers.

    Usage:
        mcp_http = MCPHttp(mcp_config)
        result = await mcp_http.call("coding", "read_file", {"path": "/app/main.py"})
    """

    def __init__(self, config: MCPConfig):
        """Initialize with MCP configuration.

        Args:
            config: MCP configuration (server URLs, etc.)
        """
        self.config = config
        self._clients: dict[str, Client] = {}

    def _get_client(self, server: str) -> Client:
        """Get or create FastMCP client for a server."""
        if server not in self._clients:
            url = self.config.get_server_url(server)
            transport = StreamableHttpTransport(url)
            self._clients[server] = Client(transport)
        return self._clients[server]

    async def call(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """Call an MCP tool via HTTP.

        Args:
            server: MCP server name (coding, docker)
            tool: Tool name (read_file, write_file, build, etc.)
            args: Tool arguments
            timeout_seconds: Request timeout

        Returns:
            Tool result as dict

        Raises:
            MCPHttpError: If the call fails
        """
        url = self.config.get_server_url(server)

        logger.info(
            "mcp_http_call",
            server=server,
            tool=tool,
            url=url,
            args_preview=str(args)[:200],
        )

        try:
            client = self._get_client(server)

            # Use asyncio.wait_for for Python 3.10 compatibility
            # (asyncio.timeout requires Python 3.11+)
            async def _do_call():
                async with client:
                    return await client.call_tool(tool, args)

            result = await asyncio.wait_for(_do_call(), timeout=timeout_seconds)

            # Parse FastMCP response
            result_dict = self._parse_result(result)

            logger.info(
                "mcp_http_call_completed",
                server=server,
                tool=tool,
                success=result_dict.get("success", True),
                result_preview=str(result_dict)[:200],
            )

            return result_dict

        except asyncio.TimeoutError:
            logger.error("mcp_http_timeout", server=server, tool=tool)
            raise MCPHttpError(
                server, tool,
                f"Timeout calling {server}:{tool}",
                retryable=True,
            )
        except ConnectionError as e:
            logger.error("mcp_http_connection_error", server=server, tool=tool, error=str(e))
            raise MCPHttpError(
                server, tool,
                f"Connection error: {e}",
                retryable=True,
            )
        except Exception as e:
            logger.error("mcp_http_error", server=server, tool=tool, error=str(e))
            raise MCPHttpError(
                server, tool,
                f"Error calling {server}:{tool}: {e}",
                retryable=False,
            )

    def _parse_result(self, result: Any) -> dict[str, Any]:
        """Parse FastMCP response into a dict.

        FastMCP call_tool returns a list of content items.
        Each item typically has: type="text" and text=<json_string>
        """
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if hasattr(first_item, "text"):
                try:
                    return json.loads(first_item.text)
                except json.JSONDecodeError:
                    return {"success": True, "content": first_item.text}
            elif hasattr(first_item, "content"):
                return {"success": True, "content": str(first_item.content)}
            else:
                return {"success": True, "data": str(first_item)}

        elif hasattr(result, "data"):
            if isinstance(result.data, dict):
                return result.data
            return {"success": True, "data": result.data}

        elif hasattr(result, "content"):
            if isinstance(result.content, list) and len(result.content) > 0:
                first_content = result.content[0]
                if hasattr(first_content, "text"):
                    try:
                        return json.loads(first_content.text)
                    except json.JSONDecodeError:
                        return {"success": True, "content": first_content.text}
                return {"success": True, "content": str(first_content)}
            return {"success": True, "content": str(result.content)}

        return {"success": True, "result": str(result)}

    async def list_tools(self, server: str) -> list[dict[str, Any]]:
        """List available tools from an MCP server.

        Args:
            server: MCP server name

        Returns:
            List of tool definitions
        """
        try:
            client = self._get_client(server)
            async with client:
                tools = await client.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or f"Execute {tool.name}",
                        "parameters": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                    }
                    for tool in tools
                ]
        except Exception as e:
            logger.warning("mcp_list_tools_failed", server=server, error=str(e))
            return []
