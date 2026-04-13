"""MCP (Model Context Protocol) module.

Every MCP server is a Druppie module (mcp-servers/module-<name>/):
  - module-coding (port 9001) - File operations + git
  - module-docker (port 9002) - Docker container operations
  - module-filesearch (port 9004) - Local file search
  - module-web (port 9005) - File search + web browsing
  - module-archimate (port 9006) - ArchiMate architecture reference
  - module-registry (port 9007) - Platform building block catalog

HITL (Human-in-the-Loop) is NOT a module — it's handled by builtin tools
(hitl_ask_question, hitl_ask_multiple_choice_question) because it needs to
pause/resume the agent loop directly.

Use MCPHttp from execution/mcp_http.py for HTTP-based calls to these services.
Configuration is in core/mcp_config.yaml.
"""

__all__ = []
