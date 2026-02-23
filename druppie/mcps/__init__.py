"""MCP (Model Context Protocol) module.

MCP servers are now implemented as HTTP microservices in mcp-servers/:
  - mcp-servers/coding/ (port 9001) - File operations + git
  - mcp-servers/docker/ (port 9002) - Docker container operations
  - mcp-servers/hitl/ (port 9003) - Human-in-the-loop questions

Use MCPClient from core/mcp_client.py for HTTP-based calls to these services.
Configuration is in core/mcp_config.yaml.
"""

__all__ = []
