"""MCP Server Registry.

Loads MCP server definitions from YAML files and provides them to agents.
This is the ONLY way agents can interact with external systems.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class MCPTool(BaseModel):
    """Definition of a tool provided by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPServer(BaseModel):
    """Definition of an MCP server.

    MCP servers provide tools that agents can use.
    """

    id: str
    name: str
    description: str | None = None

    # Connection
    transport: str = "stdio"  # stdio, sse, http
    command: str | None = None  # For stdio transport
    args: list[str] = Field(default_factory=list)
    url: str | None = None  # For sse/http transport
    env: dict[str, str] = Field(default_factory=dict)

    # Tools provided by this server
    tools: list[MCPTool] = Field(default_factory=list)

    # Access control
    auth_groups: list[str] = Field(default_factory=list)


class MCPRegistry:
    """Registry for MCP servers.

    Loads server definitions from YAML files in the registry directory.
    Provides lookup methods for servers and tools.
    """

    def __init__(self, registry_path: str | Path | None = None):
        self.registry_path = Path(registry_path) if registry_path else None
        self._servers: dict[str, MCPServer] = {}
        self._tool_index: dict[str, str] = {}  # tool_name -> server_id

    def load(self, registry_path: str | Path | None = None) -> None:
        """Load MCP server definitions from YAML files."""
        path = Path(registry_path) if registry_path else self.registry_path
        if not path:
            logger.warning("No registry path configured")
            return

        mcp_path = path / "mcp"
        if not mcp_path.exists():
            logger.warning("MCP registry directory not found", path=str(mcp_path))
            return

        self._servers.clear()
        self._tool_index.clear()

        for file_path in mcp_path.glob("*.yaml"):
            try:
                self._load_server_file(file_path)
            except Exception as e:
                logger.error("Failed to load MCP server", file=str(file_path), error=str(e))

        logger.info(
            "MCP registry loaded",
            servers=len(self._servers),
            tools=len(self._tool_index),
        )

    def _load_server_file(self, file_path: Path) -> None:
        """Load a single MCP server definition file."""
        with open(file_path) as f:
            data = yaml.safe_load(f)

        if not data:
            return

        # Handle single server or list of servers
        servers = data if isinstance(data, list) else [data]

        for server_data in servers:
            server = MCPServer(**server_data)
            self._servers[server.id] = server

            # Index tools by name
            for tool in server.tools:
                full_name = f"{server.id}.{tool.name}"
                self._tool_index[full_name] = server.id
                # Also index by short name if unique
                if tool.name not in self._tool_index:
                    self._tool_index[tool.name] = server.id

    def register_server(self, server: MCPServer) -> None:
        """Programmatically register an MCP server."""
        self._servers[server.id] = server
        for tool in server.tools:
            full_name = f"{server.id}.{tool.name}"
            self._tool_index[full_name] = server.id

    def get_server(self, server_id: str) -> MCPServer | None:
        """Get an MCP server by ID."""
        return self._servers.get(server_id)

    def get_server_for_tool(self, tool_name: str) -> MCPServer | None:
        """Get the MCP server that provides a given tool."""
        server_id = self._tool_index.get(tool_name)
        if server_id:
            return self._servers.get(server_id)
        return None

    def get_tool(self, tool_name: str) -> MCPTool | None:
        """Get a tool definition by name."""
        server = self.get_server_for_tool(tool_name)
        if not server:
            return None

        # Check if tool_name includes server prefix
        if "." in tool_name:
            _, short_name = tool_name.split(".", 1)
        else:
            short_name = tool_name

        for tool in server.tools:
            if tool.name == short_name:
                return tool
        return None

    def list_servers(self, groups: list[str] | None = None) -> list[MCPServer]:
        """List all registered MCP servers, optionally filtered by auth groups."""
        servers = list(self._servers.values())

        if groups is not None:
            servers = [
                s
                for s in servers
                if not s.auth_groups or any(g in s.auth_groups for g in groups)
            ]

        return servers

    def list_tools(self, groups: list[str] | None = None) -> list[dict[str, Any]]:
        """List all available tools, optionally filtered by auth groups."""
        tools = []
        for server in self.list_servers(groups):
            for tool in server.tools:
                tools.append(
                    {
                        "name": f"{server.id}.{tool.name}",
                        "description": tool.description,
                        "server": server.id,
                        "input_schema": tool.input_schema,
                    }
                )
        return tools

    def get_tools_for_langchain(self, groups: list[str] | None = None) -> list[dict[str, Any]]:
        """Get tools in LangChain-compatible format."""
        tools = []
        for server in self.list_servers(groups):
            for tool in server.tools:
                tools.append(
                    {
                        "name": f"{server.id}__{tool.name}",  # LangChain friendly name
                        "description": f"[{server.name}] {tool.description}",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    }
                )
        return tools
