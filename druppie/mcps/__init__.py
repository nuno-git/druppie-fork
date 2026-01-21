"""MCP (Model Context Protocol) servers for Druppie platform.

All agent capabilities are exposed through MCPs.
Agents can ONLY act through these MCP tools.

DEPRECATION NOTICE:
These in-process MCP implementations are deprecated in favor of the
HTTP-based MCP microservices in mcp-servers/. Use the MCPClient from
core/mcp_client.py for HTTP-based calls to:
  - mcp-servers/coding/ (port 9001)
  - mcp-servers/docker/ (port 9002)
  - mcp-servers/hitl/ (port 9003)

Set USE_MCP_MICROSERVICES=true in environment to use the new architecture.
This legacy code is kept for backwards compatibility during transition.
"""

from .registry import (
    ApprovalType,
    MCPRegistry,
    MCPServer,
    MCPTool,
    get_mcp_registry,
)

__all__ = [
    "ApprovalType",
    "MCPRegistry",
    "MCPServer",
    "MCPTool",
    "get_mcp_registry",
]
