"""MCP executor for executing MCP tool calls."""

import structlog
from typing import Any

from .base import Executor, ExecutorResult
from druppie.core.models import Step
from druppie.mcp import MCPClient

logger = structlog.get_logger()


class MCPExecutor(Executor):
    """Executes MCP tool calls.

    This executor handles any action that maps to an MCP tool.
    It's typically registered first in the dispatcher to handle
    dynamic tool calls.
    """

    def __init__(self, mcp_client: MCPClient | None = None):
        """Initialize the MCPExecutor.

        Args:
            mcp_client: MCP client for invoking tools
        """
        self.mcp_client = mcp_client
        self.available_tools: set[str] = set()
        self.logger = logger.bind(executor="mcp")

    def set_client(self, mcp_client: MCPClient) -> None:
        """Set the MCP client."""
        self.mcp_client = mcp_client

    def set_available_tools(self, tools: list[str]) -> None:
        """Set the list of available MCP tools.

        Tools should be in format "server.tool_name"
        """
        self.available_tools = set(tools)

    def can_handle(self, action: str) -> bool:
        """Check if this executor can handle the action.

        Returns True if the action matches an available MCP tool.
        """
        # Check if action is in available tools
        if action in self.available_tools:
            return True

        # Check if action contains a dot (server.tool format)
        if "." in action:
            return action in self.available_tools

        return False

    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute an MCP tool call."""
        context = context or {}

        if self.mcp_client is None:
            return ExecutorResult(
                success=False,
                error="No MCP client configured",
            )

        action = step.action
        params = step.params

        self.logger.info(
            "executing_mcp_tool",
            tool=action,
            params=list(params.keys()),
        )

        try:
            result = await self.mcp_client.invoke(action, params)

            self.logger.info(
                "mcp_tool_completed",
                tool=action,
                success=True,
            )

            return ExecutorResult(
                success=True,
                result=result,
                output_messages=[f"MCP tool {action} executed successfully"],
            )

        except Exception as e:
            self.logger.error(
                "mcp_tool_failed",
                tool=action,
                error=str(e),
            )
            return ExecutorResult(
                success=False,
                error=f"MCP tool execution failed: {e}",
            )
