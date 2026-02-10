"""Tool Registry - single source of truth for all tool definitions.

Combines:
- MCP tools with their Pydantic parameter models
- Builtin tools with their Pydantic parameter models

The registry maps tool names to ToolDefinition objects, which contain:
- Tool metadata (name, description, server)
- A Pydantic model class for type-safe parameters
- Approval requirements

Usage:
    registry = get_tool_registry()

    # Get a specific tool
    tool = registry.get("coding_write_file")
    tool = registry.get_by_server_and_name("coding", "write_file")

    # Validate arguments (returns typed model)
    is_valid, error, params = tool.validate_arguments({"path": "test.txt", "content": "hello"})
    if is_valid:
        print(params.path)  # Type-safe access!

    # Get tools for an agent
    tools = registry.get_tools_for_agent(
        agent_mcps=["coding", "docker"],
        builtin_tool_names=["done", "hitl_ask_question"],
    )

    # Convert to OpenAI format
    openai_tools = registry.to_openai_format(tools)
"""

from typing import Type

import structlog
from pydantic import BaseModel

from druppie.core.mcp_config import MCPConfig, get_mcp_config
from druppie.domain.tool import EmptyParams, ToolDefinition, ToolType

# Import all parameter models
from druppie.tools.params.builtin import (
    CreateMessageParams,
    DoneParams,
    HitlAskMultipleChoiceQuestionParams,
    HitlAskQuestionParams,
    MakePlanParams,
    SetIntentParams,
)
from druppie.tools.params.coding import (
    BatchWriteFilesParams,
    CommitAndPushParams,
    CreateBranchParams,
    CreatePullRequestParams,
    DeleteFileParams,
    GetGitStatusParams,
    ListDirParams,
    MergePullRequestParams,
    MergeToMainParams,
    ReadFileParams,
    WriteFileParams,
)
from druppie.tools.params.docker import (
    DockerBuildParams,
    DockerExecCommandParams,
    DockerInspectParams,
    DockerListContainersParams,
    DockerLogsParams,
    DockerRemoveParams,
    DockerRunParams,
    DockerStopParams,
)

logger = structlog.get_logger()


# Mapping from (server, tool_name) to Pydantic params model
PARAMS_MODEL_MAP: dict[tuple[str, str], Type[BaseModel]] = {
    # Coding tools
    ("coding", "read_file"): ReadFileParams,
    ("coding", "write_file"): WriteFileParams,
    ("coding", "batch_write_files"): BatchWriteFilesParams,
    ("coding", "list_dir"): ListDirParams,
    ("coding", "delete_file"): DeleteFileParams,
    ("coding", "commit_and_push"): CommitAndPushParams,
    ("coding", "create_branch"): CreateBranchParams,
    ("coding", "merge_to_main"): MergeToMainParams,
    ("coding", "create_pull_request"): CreatePullRequestParams,
    ("coding", "merge_pull_request"): MergePullRequestParams,
    ("coding", "get_git_status"): GetGitStatusParams,
    # Docker tools
    ("docker", "build"): DockerBuildParams,
    ("docker", "run"): DockerRunParams,
    ("docker", "stop"): DockerStopParams,
    ("docker", "logs"): DockerLogsParams,
    ("docker", "remove"): DockerRemoveParams,
    ("docker", "list_containers"): DockerListContainersParams,
    ("docker", "inspect"): DockerInspectParams,
    ("docker", "exec_command"): DockerExecCommandParams,
    # Builtin tools
    ("builtin", "done"): DoneParams,
    ("builtin", "hitl_ask_question"): HitlAskQuestionParams,
    ("builtin", "hitl_ask_multiple_choice_question"): HitlAskMultipleChoiceQuestionParams,
    ("builtin", "set_intent"): SetIntentParams,
    ("builtin", "make_plan"): MakePlanParams,
    ("builtin", "create_message"): CreateMessageParams,
}


class ToolRegistry:
    """Central registry for all tool definitions.

    Loads tools from MCP config and builtin tools, mapping each to its
    corresponding Pydantic parameter model for type-safe validation.
    """

    def __init__(self, mcp_config: MCPConfig | None = None):
        """Initialize the registry.

        Args:
            mcp_config: Optional MCP config to use. If None, uses singleton.
        """
        self._mcp_config = mcp_config or get_mcp_config()
        self._tools: dict[str, ToolDefinition] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazy load all tools on first access."""
        if self._loaded:
            return
        self._load_all_tools()
        self._loaded = True

    def _load_all_tools(self) -> None:
        """Load all tools from both sources."""
        # Import here to avoid circular imports
        from druppie.agents.builtin_tools import BUILTIN_TOOL_DEFS

        # Load builtin tools
        for name, openai_def in BUILTIN_TOOL_DEFS.items():
            func = openai_def.get("function", {})
            params_model = PARAMS_MODEL_MAP.get(("builtin", name), EmptyParams)

            self._tools[name] = ToolDefinition(
                name=name,
                tool_type=ToolType.BUILTIN,
                server=None,
                description=func.get("description", ""),
                params_model=params_model,
                requires_approval=False,
            )

        logger.debug("loaded_builtin_tools", count=len(BUILTIN_TOOL_DEFS))

        # Load MCP tools
        mcp_count = 0
        for server in self._mcp_config.get_servers():
            for tool_config in self._mcp_config.get_tools(server):
                name = tool_config["name"]
                full_name = f"{server}_{name}"
                params_model = PARAMS_MODEL_MAP.get((server, name), EmptyParams)

                self._tools[full_name] = ToolDefinition(
                    name=name,
                    tool_type=ToolType.MCP,
                    server=server,
                    description=tool_config.get("description", ""),
                    params_model=params_model,
                    requires_approval=tool_config.get("requires_approval", False),
                    required_role=tool_config.get("required_role"),
                )
                mcp_count += 1

        logger.debug("loaded_mcp_tools", count=mcp_count)

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
    ) -> tuple[bool, str | None, BaseModel | None]:
        """Validate a tool call's arguments.

        Args:
            server: Server name ('coding', 'builtin')
            tool_name: Tool name
            arguments: Arguments to validate

        Returns:
            Tuple of (is_valid, error_message, validated_params)
        """
        tool = self.get_by_server_and_name(server, tool_name)
        if not tool:
            return False, f"Unknown tool: {server}:{tool_name}", None
        return tool.validate_arguments(arguments)


# Singleton instance
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the singleton tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    _registry = None
