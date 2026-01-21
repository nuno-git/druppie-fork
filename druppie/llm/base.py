"""Abstract base class for LLM providers.

All LLM implementations must inherit from BaseLLM.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    provider: str = ""


class BaseLLM(ABC):
    """Abstract base class for LLM providers.

    All LLM implementations must provide:
    - chat(): Synchronous chat completion
    - achat(): Asynchronous chat completion
    - bind_tools(): Create instance with tools bound
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a synchronous chat completion request.

        Args:
            messages: List of message dicts with role and content
            tools: Optional list of tool definitions in OpenAI format

        Returns:
            LLMResponse with content and optional tool_calls
        """
        ...

    @abstractmethod
    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send an asynchronous chat completion request.

        Args:
            messages: List of message dicts with role and content
            tools: Optional list of tool definitions in OpenAI format

        Returns:
            LLMResponse with content and optional tool_calls
        """
        ...

    def bind_tools(self, tools: list[dict[str, Any]]) -> "BaseLLM":
        """Create a new instance with tools bound.

        Default implementation just returns self.
        Override in subclasses to create new instance with tools.
        """
        return self

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        ...
