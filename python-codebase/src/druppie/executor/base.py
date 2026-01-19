"""Base executor interface."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from dataclasses import dataclass

from druppie.core.models import Step, TokenUsage


@dataclass
class ExecutorResult:
    """Result from executing a step."""

    success: bool
    result: Any = None
    error: str | None = None
    usage: TokenUsage | None = None
    output_messages: list[str] | None = None  # Log messages during execution


class Executor(ABC):
    """Base class for step executors.

    Each executor handles specific actions for an agent type.
    The dispatcher routes steps to the appropriate executor.
    """

    @abstractmethod
    def can_handle(self, action: str) -> bool:
        """Check if this executor can handle the given action.

        Args:
            action: The action name from the step

        Returns:
            True if this executor can handle the action
        """
        pass

    @abstractmethod
    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute a step.

        Args:
            step: The step to execute
            context: Additional context (project path, previous results, etc.)

        Returns:
            ExecutorResult with success status and result/error
        """
        pass

    async def stream_execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Execute a step with streaming output.

        Default implementation calls execute() and yields result.
        Override for true streaming support.

        Args:
            step: The step to execute
            context: Additional context

        Yields:
            Output messages during execution
        """
        result = await self.execute(step, context)
        if result.output_messages:
            for msg in result.output_messages:
                yield msg
        if result.error:
            yield f"Error: {result.error}"
        elif result.result:
            yield str(result.result)
