"""MCP (Model Context Protocol) servers for Druppie platform.

All agent capabilities are exposed through MCPs.
Agents can ONLY act through these MCP tools.
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
