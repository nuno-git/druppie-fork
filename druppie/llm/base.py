"""Abstract base class for LLM providers.

All LLM implementations must inherit from BaseLLM.
"""

import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================


class LLMError(Exception):
    """Base exception for LLM errors."""

    def __init__(self, message: str, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class RateLimitError(LLMError):
    """Rate limit exceeded (429 status code).

    This error is retryable - user should wait and try again.
    """

    def __init__(self, message: str, provider: str = "", retry_after: int | None = None):
        super().__init__(message, provider, retryable=True)
        self.retry_after = retry_after  # Seconds to wait before retry


class AuthenticationError(LLMError):
    """Authentication failed (401/403 status code).

    API key is invalid or missing.
    """

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider, retryable=False)


class ServerError(LLMError):
    """Server error (5xx status code).

    Temporary server issue - retryable after backoff.
    """

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider, retryable=True)


class FallbackAvailableError(LLMError):
    """Primary provider failed but a fallback is available.

    Raised by FallbackLLM instead of auto-switching. The agent loop
    catches this to ask the user whether to switch providers.
    """

    def __init__(
        self,
        message: str,
        primary_provider: str,
        primary_model: str,
        fallback_provider: str,
        fallback_model: str,
        error_type: str,
    ):
        super().__init__(message, provider=primary_provider, retryable=False)
        self.primary_provider = primary_provider
        self.primary_model = primary_model
        self.fallback_provider = fallback_provider
        self.fallback_model = fallback_model
        self.error_type = error_type
        self.llm_call_id = None


_REDACT_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "[REDACTED]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}"), "Bearer [REDACTED]"),
    (re.compile(r"api[_-]?key\s*[=:]\s*[\"']?[A-Za-z0-9_.-]{10,}[\"']?"), "api_key=[REDACTED]"),
]


def clean_llm_error(raw: str) -> str:
    """Extract a short, user-facing message from verbose litellm errors."""
    for pattern, replacement in _REDACT_PATTERNS:
        raw = pattern.sub(replacement, raw)
    if "DeploymentNotFound" in raw or "does not exist" in raw:
        return "Model deployment not found"
    if "Authentication Failed" in raw or "AuthenticationError" in raw:
        return "Authentication failed — check the API key"
    if "NotFoundError" in raw:
        return "Model not found"
    if "RateLimitError" in raw or "rate_limit" in raw:
        return "Rate limited — try again later"
    if "timeout" in raw.lower():
        return "Request timed out"
    if "connection" in raw.lower() and ("refused" in raw.lower() or "reset" in raw.lower() or "closed" in raw.lower() or "error" in raw.lower()):
        return "Connection failed — check the provider URL"
    if "LLMConfigurationError" in raw:
        return raw.split("LLMConfigurationError: ", 1)[-1][:120]
    for prefix in ["LLM error: ", "litellm.", "AnthropicException - ", "OpenAIException - "]:
        if prefix in raw:
            raw = raw.split(prefix)[-1]
    return raw[:120] + "…" if len(raw) > 120 else raw


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str = ""  # Cleaned content (tool call tags removed)
    raw_content: str = ""  # Original unprocessed response from LLM
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # Parsed args
    raw_tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # Raw args strings for debugging
    finish_reason: str = ""  # "stop", "tool_calls", "length" (truncated), etc.
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
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send an asynchronous chat completion request.

        Args:
            messages: List of message dicts with role and content
            tools: Optional list of tool definitions in OpenAI format
            max_tokens: Override max tokens for this call (uses instance default if None)

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

    @property
    def supports_native_tools(self) -> bool:
        """Whether this LLM supports native OpenAI-style tool calling.

        If True, tools are passed to the API and the model returns tool_calls natively.
        If False, we inject XML format instructions into the system prompt and parse
        <tool_call>...</tool_call> from the response content.

        Override in subclasses based on model capabilities.
        """
        return False  # Safe default - use XML format
