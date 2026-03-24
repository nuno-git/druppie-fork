"""MCP (Model Context Protocol) module.

MCP servers follow the module convention in mcp-servers/module-<name>/:
  - module-coding (port 9001) - File operations + git
  - module-docker (port 9002) - Docker container operations
  - module-hitl (port 9003) - Human-in-the-loop questions
  - module-filesearch (port 9004) - Local file search
  - module-web (port 9005) - File search + web browsing
  - module-archimate (port 9006) - ArchiMate architecture reference
  - module-registry (port 9007) - Platform building block catalog

Use MCPHttp from execution/mcp_http.py for HTTP-based calls to these services.
Configuration is in core/mcp_config.yaml.
"""

__all__ = []
