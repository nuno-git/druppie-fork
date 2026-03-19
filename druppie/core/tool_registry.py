"""Tool Registry - single source of truth for all tool definitions.

Discovers MCP tools from servers via tools/list at startup.
Combines with builtin tools defined in builtin_tools.py.

Usage:
    registry = get_tool_registry()

    # Get a specific tool
    tool = registry.get("coding_write_file")
    tool = registry.get_by_server_and_name("coding", "write_file")

    # Validate arguments (returns validated dict)
    is_valid, error, args, normalized = tool.validate_arguments({"path": "test.txt", "content": "hello"})

    # Get tools for an agent
    tools = registry.get_tools_for_agent(
        agent_mcps=["coding", "docker"],
        builtin_tool_names=["done", "hitl_ask_question"],
    )

    # Convert to OpenAI format
    openai_tools = registry.to_openai_format(tools)
"""

import asyncio

import structlog

from druppie.core.mcp_config import MCPConfig, get_mcp_config
from druppie.domain.tool import ToolDefinition, ToolType

logger = structlog.get_logger()


class ToolRegistry:
    """Central registry for all tool definitions.

    MCP tools are discovered from servers via tools/list.
    Builtin tools are loaded from BUILTIN_TOOL_DEFS.
    """

    def __init__(self, mcp_config: MCPConfig | None = None):
        """Initialize the registry.

        Args:
            mcp_config: Optional MCP config to use. If None, uses singleton.
        """
        self._mcp_config = mcp_config or get_mcp_config()
        self._tools: dict[str, ToolDefinition] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the registry by discovering tools from all MCP servers.

        Call this once at application startup (e.g., FastAPI lifespan).
        """
        if self._initialized:
            return
        await self._load_all_tools()
        self._initialized = True

    def _ensure_loaded(self) -> None:
        """Check that registry is initialized. Raises if not."""
        if self._initialized:
            return

        # Fallback: try sync initialization for backwards compatibility
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context but initialize() wasn't called
                logger.warning(
                    "tool_registry_not_initialized",
                    hint="Call await registry.initialize() at startup",
                )
                # Load builtin tools only as fallback
                self._load_builtin_tools()
                self._initialized = True
                return
        except RuntimeError:
            pass

        # Not in async context - do sync load (builtin only)
        self._load_builtin_tools()
        self._initialized = True

    async def _load_all_tools(self) -> None:
        """Load all tools from both sources."""
        # Load builtin tools (sync)
        self._load_builtin_tools()

        # Load MCP tools from each server via tools/list
        for server in self._mcp_config.get_servers():
            try:
                await self._load_mcp_tools_from_server(server)
            except Exception as e:
                logger.warning(
                    "failed_to_load_server_tools",
                    server=server,
                    error=str(e),
                )

    def _load_builtin_tools(self) -> None:
        """Load builtin tools from BUILTIN_TOOL_DEFS."""
        from druppie.agents.builtin_tools import BUILTIN_TOOL_DEFS

        for name, openai_def in BUILTIN_TOOL_DEFS.items():
            func = openai_def.get("function", {})
            self._tools[name] = ToolDefinition(
                name=name,
                tool_type=ToolType.BUILTIN,
                server=None,
                description=func.get("description", ""),
                json_schema=func.get("parameters", {}),
                meta={},
                requires_approval=False,
            )

        logger.debug("loaded_builtin_tools", count=len(BUILTIN_TOOL_DEFS))

    async def _load_mcp_tools_from_server(self, server: str) -> None:
        """Discover tools from an MCP server via tools/list."""
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        url = self._mcp_config.get_server_url(server)

        try:
            transport = StreamableHttpTransport(url)
            async with Client(transport) as client:
                tools = await client.list_tools()
        except Exception as e:
            logger.warning(
                "mcp_list_tools_failed",
                server=server,
                url=url,
                error=str(e),
            )
            return

        # Get approval config from mcp_config.yaml
        tool_configs = {t["name"]: t for t in self._mcp_config.get_tools(server)}

        mcp_count = 0
        for tool in tools:
            name = tool.name
            full_name = f"{server}_{name}"

            # Get approval settings from config
            config = tool_configs.get(name, {})

            # Extract meta from tool (check various FastMCP response formats)
            meta = {}
            if hasattr(tool, "meta") and tool.meta:
                meta = dict(tool.meta)
            elif hasattr(tool, "annotations") and tool.annotations:
                meta = dict(tool.annotations)

            # Get JSON schema
            json_schema = {}
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                json_schema = (
                    dict(tool.inputSchema)
                    if not isinstance(tool.inputSchema, dict)
                    else tool.inputSchema
                )

            self._tools[full_name] = ToolDefinition(
                name=name,
                tool_type=ToolType.MCP,
                server=server,
                description=tool.description or "",
                json_schema=json_schema,
                meta=meta,
                requires_approval=config.get("requires_approval", False),
                required_role=config.get("required_role"),
            )
            mcp_count += 1

        logger.debug("loaded_mcp_tools", server=server, count=mcp_count)

    # -------------------------------------------------------------------------
    # Lookup methods
    # -------------------------------------------------------------------------

    def get(self, full_name: str) -> ToolDefinition | None:
        """Get tool by full name.

        Args:
            full_name: Full tool name (e.g., 'coding_write_file' or 'done')

        Returns:
            ToolDefinition or None if not found
        """
        self._ensure_loaded()
        return self._tools.get(full_name)

    def get_by_server_and_name(self, server: str, name: str) -> ToolDefinition | None:
        """Get tool by server and name.

        Args:
            server: Server name ('coding', 'docker', 'builtin')
            name: Tool name ('write_file', 'done')

        Returns:
            ToolDefinition or None if not found
        """
        self._ensure_loaded()

        if server == "builtin":
            return self._tools.get(name)
        return self._tools.get(f"{server}_{name}")

    def get_all(self) -> list[ToolDefinition]:
        """Get all registered tools.

        Returns:
            List of all ToolDefinitions
        """
        self._ensure_loaded()
        return list(self._tools.values())

    def get_builtin_tools(self) -> list[ToolDefinition]:
        """Get all builtin tools.

        Returns:
            List of builtin ToolDefinitions
        """
        self._ensure_loaded()
        return [t for t in self._tools.values() if t.tool_type == ToolType.BUILTIN]

    def get_mcp_tools(self, server: str | None = None) -> list[ToolDefinition]:
        """Get MCP tools, optionally filtered by server.

        Args:
            server: Optional server name to filter by

        Returns:
            List of MCP ToolDefinitions
        """
        self._ensure_loaded()
        tools = [t for t in self._tools.values() if t.tool_type == ToolType.MCP]
        if server:
            tools = [t for t in tools if t.server == server]
        return tools

    # -------------------------------------------------------------------------
    # Agent-specific methods
    # -------------------------------------------------------------------------

    def get_tools_for_agent(
        self,
        agent_mcps: list[str] | dict,
        builtin_tool_names: list[str],
    ) -> list[ToolDefinition]:
        """Get all tools available to an agent.

        Args:
            agent_mcps: MCP servers the agent can use.
                - List format: ["coding", "docker"] - all tools from these servers
                - Dict format: {"coding": ["write_file"]} - specific tools only
            builtin_tool_names: Builtin tools the agent can use

        Returns:
            List of ToolDefinitions available to the agent
        """
        self._ensure_loaded()
        tools = []

        # Add builtin tools
        for name in builtin_tool_names:
            if name in self._tools:
                tools.append(self._tools[name])
            else:
                logger.warning("unknown_builtin_tool", tool_name=name)

        # Add MCP tools
        if isinstance(agent_mcps, list):
            # List format - all tools from each server
            for server in agent_mcps:
                for tool in self._tools.values():
                    if tool.tool_type == ToolType.MCP and tool.server == server:
                        tools.append(tool)
        else:
            # Dict format - specific tools per server
            for server, tool_names in agent_mcps.items():
                for tool in self._tools.values():
                    if tool.tool_type == ToolType.MCP and tool.server == server:
                        if not tool_names or tool.name in tool_names:
                            tools.append(tool)

        # Filter out internal tools (not exposed to agents)
        tools = [t for t in tools if not t.meta.get("internal", False)]

        return tools

    def to_openai_format(self, tools: list[ToolDefinition]) -> list[dict]:
        """Convert tools to OpenAI function calling format.

        Args:
            tools: List of ToolDefinitions to convert

        Returns:
            List of OpenAI function tool definitions
        """
        return [tool.to_openai_format() for tool in tools]

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate_tool_call(
        self,
        server: str,
        tool_name: str,
        arguments: dict,
    ) -> tuple[bool, str | None, dict | None, dict | None]:
        """Validate a tool call's arguments.

        Args:
            server: Server name ('coding', 'builtin')
            tool_name: Tool name
            arguments: Arguments to validate

        Returns:
            Tuple of (is_valid, error_message, validated_args, normalized_args)
        """
        tool = self.get_by_server_and_name(server, tool_name)
        if not tool:
            return False, f"Unknown tool: {server}:{tool_name}", None, None
        return tool.validate_arguments(arguments)


# Singleton instance
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the singleton tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


async def initialize_tool_registry() -> None:
    """Initialize the tool registry. Call at app startup."""
    registry = get_tool_registry()
    await registry.initialize()


def reset_tool_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    _registry = None
