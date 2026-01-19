"""Dispatcher for routing steps to executors."""

import structlog
from typing import Any

from .base import Executor, ExecutorResult
from druppie.core.models import Step, TokenUsage

logger = structlog.get_logger()


class Dispatcher:
    """Routes steps to appropriate executors.

    The dispatcher maintains a list of executors and finds the right one
    for each step based on the action type.
    """

    def __init__(self):
        """Initialize the Dispatcher."""
        self.executors: list[Executor] = []
        self.logger = logger.bind(component="dispatcher")

    def register(self, executor: Executor) -> None:
        """Register an executor.

        Executors are checked in order of registration.
        Register more specific executors first.

        Args:
            executor: The executor to register
        """
        self.executors.append(executor)
        self.logger.debug("executor_registered", executor=type(executor).__name__)

    def get_executor(self, action: str) -> Executor | None:
        """Get the executor for an action.

        Args:
            action: The action to find an executor for

        Returns:
            The first executor that can handle the action, or None
        """
        for executor in self.executors:
            if executor.can_handle(action):
                return executor
        return None

    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute a step using the appropriate executor.

        Args:
            step: The step to execute
            context: Additional context

        Returns:
            ExecutorResult from the executor
        """
        executor = self.get_executor(step.action)

        if executor is None:
            self.logger.error(
                "no_executor_found",
                action=step.action,
                agent_id=step.agent_id,
            )
            return ExecutorResult(
                success=False,
                error=f"No executor found for action: {step.action}",
            )

        self.logger.info(
            "executing_step",
            step_id=step.id,
            action=step.action,
            executor=type(executor).__name__,
        )

        try:
            result = await executor.execute(step, context)
            self.logger.info(
                "step_executed",
                step_id=step.id,
                success=result.success,
            )
            return result
        except Exception as e:
            self.logger.error(
                "step_execution_failed",
                step_id=step.id,
                error=str(e),
            )
            return ExecutorResult(
                success=False,
                error=str(e),
            )


def create_default_dispatcher() -> Dispatcher:
    """Create a dispatcher with default executors.

    Returns:
        Dispatcher with all built-in executors registered
    """
    from .mcp_executor import MCPExecutor
    from .developer import DeveloperExecutor
    from .architect import ArchitectExecutor
    from .business_analyst import BusinessAnalystExecutor
    from .compliance import ComplianceExecutor

    dispatcher = Dispatcher()

    # Register executors in priority order
    # MCP executor first - handles dynamic tool calls
    dispatcher.register(MCPExecutor())

    # Specialized executors
    dispatcher.register(DeveloperExecutor())
    dispatcher.register(ArchitectExecutor())
    dispatcher.register(BusinessAnalystExecutor())
    dispatcher.register(ComplianceExecutor())

    return dispatcher
