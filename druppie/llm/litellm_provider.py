"""LiteLLM provider implementation.

Unified LLM interface using LiteLLM for standardized tool calling across providers.

Supported providers (via LiteLLM):
- deepinfra: DeepInfra API (Qwen, Llama, etc.)
- zai: Z.AI GLM models (via OpenAI-compatible API)
- openai: OpenAI API (GPT-4, etc.)
- anthropic: Anthropic API (Claude, etc.)

Environment variables:
    LITELLM_PROVIDER: Which provider to use (deepinfra, zai, openai, anthropic)
    LITELLM_MODEL: Model name (provider-specific)
    LITELLM_API_KEY: API key for the provider
    LITELLM_API_BASE: Custom API base URL (optional)
    LITELLM_MAX_TOKENS: Max tokens for generation (default: 16384)
    LITELLM_TEMPERATURE: Temperature (default: 0.7)
    LITELLM_TIMEOUT: Request timeout in seconds (default: 300)
    LITELLM_MAX_RETRIES: Max retries for transient errors (default: 3)
"""

import json
import os
import time
from typing import Any

import structlog

from .base import (
    AuthenticationError,
    BaseLLM,
    LLMError,
    LLMResponse,
    RateLimitError,
    ServerError,
)

logger = structlog.get_logger()

# Import litellm - will be installed as dependency
try:
    import litellm
    from litellm import acompletion, completion
    from litellm.integrations.custom_logger import CustomLogger

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    CustomLogger = object  # Fallback for type hints


class DruppieLogger(CustomLogger if LITELLM_AVAILABLE else object):
    """Custom logger to capture raw requests/responses for database storage."""

    def __init__(self):
        self.last_request: dict[str, Any] | None = None
        self.last_response: dict[str, Any] | None = None
        self.call_history: list[dict[str, Any]] = []

    def log_pre_api_call(self, model, messages, kwargs):
        """Capture raw request before sending to API."""
        self.last_request = {
            "model": model,
            "messages": messages,
            "tools": kwargs.get("tools"),
            "tool_choice": kwargs.get("tool_choice"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Capture successful response."""
        duration_ms = int((end_time - start_time) * 1000)

        call_record = {
            "timestamp": self.last_request.get("timestamp") if self.last_request else None,
            "model": kwargs.get("model", ""),
            "provider": "litellm",
            "status": "success",
            "duration_ms": duration_ms,
            "response_cost": kwargs.get("response_cost"),
        }

        self.last_response = {
            "id": getattr(response_obj, "id", None),
            "model": getattr(response_obj, "model", None),
            "choices": [
                {
                    "message": {
                        "content": choice.message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in (choice.message.tool_calls or [])
                        ]
                        if choice.message.tool_calls
                        else None,
                    },
                    "finish_reason": choice.finish_reason,
                }
                for choice in response_obj.choices
            ],
            "usage": {
                "prompt_tokens": response_obj.usage.prompt_tokens if response_obj.usage else 0,
                "completion_tokens": response_obj.usage.completion_tokens if response_obj.usage else 0,
                "total_tokens": response_obj.usage.total_tokens if response_obj.usage else 0,
            },
        }

        self.call_history.append(call_record)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Async version - same logic."""
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    def log_failure_event(self, kwargs, exception, start_time, end_time):
        """Capture failed request."""
        duration_ms = int((end_time - start_time) * 1000)

        call_record = {
            "timestamp": self.last_request.get("timestamp") if self.last_request else None,
            "model": kwargs.get("model", ""),
            "provider": "litellm",
            "status": "error",
            "duration_ms": duration_ms,
            "error": str(exception),
            "error_type": type(exception).__name__,
        }

        self.call_history.append(call_record)

    async def async_log_failure_event(self, kwargs, exception, start_time, end_time):
        """Async version - same logic."""
        self.log_failure_event(kwargs, exception, start_time, end_time)


# Global logger instance for capturing requests
_druppie_logger: DruppieLogger | None = None


def get_druppie_logger() -> DruppieLogger:
    """Get or create the global Druppie logger."""
    global _druppie_logger
    if _druppie_logger is None:
        _druppie_logger = DruppieLogger()
        if LITELLM_AVAILABLE:
            litellm.callbacks = [_druppie_logger]
    return _druppie_logger


class ChatLiteLLM(BaseLLM):
    """Unified LLM provider using LiteLLM.

    Supports multiple providers through LiteLLM's unified interface:
    - deepinfra: "deepinfra/model-name"
    - zai: Uses openai/* with custom base URL
    - openai: "gpt-4", "gpt-3.5-turbo", etc.
    - anthropic: "claude-3-opus-20240229", etc.
    """

    # Provider-specific model prefixes for LiteLLM
    PROVIDER_PREFIXES = {
        "deepinfra": "deepinfra/",
        "openai": "",  # OpenAI models don't need prefix
        "anthropic": "",  # Anthropic models don't need prefix
        "zai": "openai/",  # ZAI uses OpenAI-compatible API
    }

    # Default models per provider
    DEFAULT_MODELS = {
        "deepinfra": "Qwen/Qwen3-32B",
        "openai": "gpt-4",
        "anthropic": "claude-3-opus-20240229",
        "zai": "GLM-4.7",
    }

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ):
        """Initialize LiteLLM provider.

        Args:
            provider: Provider name (deepinfra, zai, openai, anthropic)
            model: Model name (uses provider default if not specified)
            api_key: API key for the provider
            api_base: Custom API base URL
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
            max_retries: Maximum retries for transient errors
        """
        if not LITELLM_AVAILABLE:
            raise ImportError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        # Load from environment with fallbacks
        self.provider = provider or os.getenv("LITELLM_PROVIDER", "deepinfra")
        self.api_key = api_key or os.getenv("LITELLM_API_KEY", "")
        self.api_base = api_base or os.getenv("LITELLM_API_BASE", "")
        self.temperature = temperature or float(os.getenv("LITELLM_TEMPERATURE", "0.7"))
        self.max_tokens = max_tokens or int(os.getenv("LITELLM_MAX_TOKENS", "16384"))
        self.timeout = timeout or float(os.getenv("LITELLM_TIMEOUT", "300"))
        self.max_retries = max_retries or int(os.getenv("LITELLM_MAX_RETRIES", "3"))

        # Determine model names
        # display_model: User-friendly name (e.g., "glm-4.7")
        # _litellm_model: LiteLLM format with prefix (e.g., "openai/glm-4.7")
        raw_model = model or os.getenv("LITELLM_MODEL", self.DEFAULT_MODELS.get(self.provider, ""))
        prefix = self.PROVIDER_PREFIXES.get(self.provider, "")

        # Store display model (without litellm prefix)
        self.display_model = raw_model

        # Build LiteLLM model format (with prefix if needed)
        if raw_model.startswith(prefix) or "/" in raw_model:
            self._litellm_model = raw_model
        else:
            self._litellm_model = f"{prefix}{raw_model}"

        # Configure LiteLLM based on provider
        self._configure_provider()

        # Initialize logger
        self._logger = get_druppie_logger()

        # Bound tools
        self._bound_tools: list[dict] = []

        logger.info(
            "litellm_provider_initialized",
            provider=self.provider,
            model=self.display_model,
            litellm_model=self._litellm_model,
            api_base=self.api_base or "default",
        )

    def _configure_provider(self):
        """Configure LiteLLM for the selected provider."""
        # Set provider-specific environment variables that LiteLLM reads
        if self.provider == "deepinfra":
            if self.api_key:
                os.environ["DEEPINFRA_API_KEY"] = self.api_key
            if not self.api_base:
                self.api_base = "https://api.deepinfra.com/v1/openai"

        elif self.provider == "zai":
            # ZAI uses OpenAI-compatible API
            if self.api_key:
                os.environ["OPENAI_API_KEY"] = self.api_key
            if not self.api_base:
                self.api_base = "https://api.z.ai/api/coding/paas/v4"

        elif self.provider == "openai":
            if self.api_key:
                os.environ["OPENAI_API_KEY"] = self.api_key

        elif self.provider == "anthropic":
            if self.api_key:
                os.environ["ANTHROPIC_API_KEY"] = self.api_key

    @property
    def model_name(self) -> str:
        """Return user-friendly model name (e.g., 'glm-4.7' not 'openai/glm-4.7')."""
        return self.display_model

    @property
    def model(self) -> str:
        """Alias for display_model for backward compatibility with service.py logging."""
        return self.display_model

    @property
    def provider_name(self) -> str:
        return f"litellm/{self.provider}"

    @property
    def supports_native_tools(self) -> bool:
        """LiteLLM handles tool calling standardization."""
        return True

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ChatLiteLLM":
        """Create new instance with tools bound."""
        new_instance = ChatLiteLLM(
            provider=self.provider,
            model=self.display_model,  # Use display model, not litellm format
            api_key=self.api_key,
            api_base=self.api_base,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )
        new_instance._bound_tools = tools
        return new_instance

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send synchronous chat completion request."""
        effective_tools = tools or self._bound_tools

        kwargs = {
            "model": self._litellm_model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
        }

        # Add API base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if effective_tools:
            kwargs["tools"] = effective_tools
            kwargs["tool_choice"] = "auto"

        try:
            response = completion(**kwargs)
            return self._parse_response(response)

        except Exception as e:
            raise self._convert_exception(e)

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send asynchronous chat completion request."""
        effective_tools = tools or self._bound_tools
        effective_max_tokens = max_tokens or self.max_tokens

        kwargs = {
            "model": self._litellm_model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": effective_max_tokens,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
        }

        # Add API base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if effective_tools:
            kwargs["tools"] = effective_tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)

        except Exception as e:
            raise self._convert_exception(e)

    def _parse_response(self, response) -> LLMResponse:
        """Parse LiteLLM response into our LLMResponse format."""
        choice = response.choices[0]
        message = choice.message

        # Extract content
        content = message.content or ""

        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                # Parse arguments if string
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        logger.warning(
                            "failed_to_parse_tool_args",
                            tool_name=tc.function.name,
                            args_preview=args[:100] if args else "",
                        )
                        args = {}

                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": args if isinstance(args, dict) else {},
                })

        # Extract usage
        usage = response.usage

        return LLMResponse(
            content=content,
            raw_content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            model=self.display_model,  # User-friendly model name
            provider=self.provider_name,
        )

    def _convert_exception(self, e: Exception) -> LLMError:
        """Convert LiteLLM exceptions to our exception types."""
        error_str = str(e).lower()

        if "rate limit" in error_str or "429" in error_str:
            return RateLimitError(
                f"Rate limit exceeded: {e}",
                provider=self.provider_name,
            )
        elif "authentication" in error_str or "401" in error_str or "403" in error_str:
            return AuthenticationError(
                f"Authentication failed: {e}",
                provider=self.provider_name,
            )
        elif "500" in error_str or "502" in error_str or "503" in error_str:
            return ServerError(
                f"Server error: {e}",
                provider=self.provider_name,
            )
        else:
            return LLMError(
                f"LLM error: {e}",
                provider=self.provider_name,
            )

    def get_call_history(self) -> list[dict]:
        """Get history of LLM calls for debugging."""
        return self._logger.call_history.copy()

    def clear_call_history(self) -> None:
        """Clear call history."""
        self._logger.call_history = []

    def get_last_raw_request(self) -> dict[str, Any] | None:
        """Get the last raw request sent to the API."""
        return self._logger.last_request

    def get_last_raw_response(self) -> dict[str, Any] | None:
        """Get the last raw response from the API."""
        return self._logger.last_response
