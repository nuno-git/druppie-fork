"""MCP (Model Context Protocol) integration.

This module provides:
- MCPRegistry: Loads and manages MCP server definitions
- MCPClient: Connects to MCP servers and invokes tools
"""

from druppie.mcp.client import MCPClient
from druppie.mcp.registry import MCPRegistry, MCPServer, MCPTool

__all__ = ["MCPClient", "MCPRegistry", "MCPServer", "MCPTool"]
