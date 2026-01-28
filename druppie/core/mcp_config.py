"""MCP Configuration - loads mcp_config.yaml and provides approval rules.

This module handles:
- Loading MCP server configuration from YAML
- Server URLs (with environment variable substitution)
- Approval requirements (which tools need approval)
- Layered approval system (agent overrides > global defaults)

The approval rules work in two layers:
1. Global defaults from mcp_config.yaml
2. Agent-specific overrides from agent YAML definitions

Example mcp_config.yaml:
    mcps:
      coding:
        url: ${MCP_CODING_URL:-http://mcp-coding:9001}
        tools:
          - name: write_file
            requires_approval: false
          - name: run_command
            requires_approval: true
            required_role: developer
"""

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml

if TYPE_CHECKING:
    from druppie.agents.models import AgentDefinition

logger = structlog.get_logger()


class MCPConfig:
    """MCP configuration loaded from mcp_config.yaml.

    Usage:
        config = MCPConfig()
        url = config.get_server_url("coding")
        needs_approval, role = config.needs_approval("coding", "write_file")
    """

    def __init__(self, config_path: str | Path | None = None):
        """Load MCP configuration.

        Args:
            config_path: Path to mcp_config.yaml. If None, uses default location.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "mcp_config.yaml"
        self._config_path = Path(config_path)
        self._config: dict | None = None

    @property
    def config(self) -> dict:
        """Lazy load configuration."""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> dict:
        """Load and parse mcp_config.yaml with environment variable substitution."""
        if not self._config_path.exists():
            logger.warning("mcp_config_not_found", path=str(self._config_path))
            return {"mcps": {}}

        with open(self._config_path) as f:
            content = f.read()

        # Handle ${VAR:-default} syntax
        def replace_with_default(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.getenv(var_name, default)

        content = re.sub(r"\$\{(\w+):-([^}]+)\}", replace_with_default, content)

        # Handle ${VAR} syntax
        def replace_simple(match):
            var_name = match.group(1)
            return os.getenv(var_name, "")

        content = re.sub(r"\$\{(\w+)\}", replace_simple, content)

        return yaml.safe_load(content) or {"mcps": {}}

    def get_server_url(self, server: str) -> str:
        """Get URL for an MCP server.

        Args:
            server: Server name (coding, docker)

        Returns:
            Server URL with /mcp suffix for FastMCP
        """
        mcp = self.config.get("mcps", {}).get(server, {})
        url = mcp.get("url", f"http://mcp-{server}:9001")

        # Ensure URL ends with /mcp for FastMCP HTTP transport
        if not url.endswith("/mcp"):
            url = url.rstrip("/") + "/mcp"

        return url

    def get_servers(self) -> list[str]:
        """Get list of configured MCP server names."""
        return list(self.config.get("mcps", {}).keys())

    def get_tools(self, server: str) -> list[dict]:
        """Get tool configurations for a server.

        Args:
            server: Server name

        Returns:
            List of tool config dicts
        """
        mcp = self.config.get("mcps", {}).get(server, {})
        return mcp.get("tools", [])

    def get_tool_config(self, server: str, tool: str) -> dict:
        """Get configuration for a specific tool.

        Args:
            server: Server name
            tool: Tool name

        Returns:
            Tool configuration dict (empty if not found)
        """
        for t in self.get_tools(server):
            if t.get("name") == tool:
                return t
        return {}

    def is_builtin_server(self, server: str) -> bool:
        """Check if server is builtin (no HTTP call needed)."""
        mcp = self.config.get("mcps", {}).get(server, {})
        return mcp.get("builtin", False)

    def needs_approval(
        self,
        server: str,
        tool: str,
        agent_definition: "AgentDefinition | None" = None,
    ) -> tuple[bool, str | None]:
        """Check if a tool needs approval and what role can approve.

        Uses layered approval system:
        1. First check agent's approval_overrides (if provided)
        2. Fall back to global defaults from mcp_config.yaml

        Args:
            server: MCP server name
            tool: Tool name
            agent_definition: Optional agent definition for overrides

        Returns:
            Tuple of (requires_approval, required_role)
        """
        # Layer 1: Check agent-specific overrides
        if agent_definition is not None:
            override = agent_definition.get_approval_override(server, tool)
            if override is not None:
                logger.debug(
                    "using_agent_approval_override",
                    agent_id=agent_definition.id,
                    tool=f"{server}:{tool}",
                    requires_approval=override.requires_approval,
                    required_role=override.required_role,
                )
                return (override.requires_approval, override.required_role)

        # Layer 2: Fall back to global config
        tool_config = self.get_tool_config(server, tool)
        requires = tool_config.get("requires_approval", False)

        # Support both "required_role" (new) and "required_roles" (old array format)
        required_role = tool_config.get("required_role")
        if required_role is None:
            old_roles = tool_config.get("required_roles", [])
            required_role = old_roles[0] if old_roles else None

        return (requires, required_role)

    def get_all_tools_for_agent(self, agent_mcps: list[str] | dict) -> list[dict]:
        """Get all tool definitions for an agent's configured MCPs.

        Args:
            agent_mcps: Either a list of MCP names or dict mapping MCP to tools

        Returns:
            List of tool definitions with full info
        """
        tools = []

        if isinstance(agent_mcps, list):
            # List format - all tools from each MCP
            for server in agent_mcps:
                for tool in self.get_tools(server):
                    tools.append({
                        "server": server,
                        "name": tool["name"],
                        "full_name": f"{server}:{tool['name']}",
                        "description": tool.get("description", ""),
                        "requires_approval": tool.get("requires_approval", False),
                        "parameters": tool.get("parameters", {}),
                    })
        else:
            # Dict format - specific tools per MCP
            for server, tool_names in agent_mcps.items():
                for tool in self.get_tools(server):
                    if not tool_names or tool["name"] in tool_names:
                        tools.append({
                            "server": server,
                            "name": tool["name"],
                            "full_name": f"{server}:{tool['name']}",
                            "description": tool.get("description", ""),
                            "requires_approval": tool.get("requires_approval", False),
                            "parameters": tool.get("parameters", {}),
                        })

        return tools


# Singleton instance
_config: MCPConfig | None = None


def get_mcp_config() -> MCPConfig:
    """Get the singleton MCP config instance."""
    global _config
    if _config is None:
        _config = MCPConfig()
    return _config
