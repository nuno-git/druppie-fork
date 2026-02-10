"""LiteLLM provider - unified LLM interface.

Uses LiteLLM for standardized tool calling across all providers.
This is the only LLM implementation - all providers go through LiteLLM.

Environment variables:
    LLM_PROVIDER: zai, deepinfra

    For ZAI:
        ZAI_API_KEY, ZAI_MODEL, ZAI_BASE_URL

    For DeepInfra:
        DEEPINFRA_API_KEY, DEEPINFRA_MODEL, DEEPINFRA_BASE_URL
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

# Import litellm
try:
    import litellm
    from litellm import acompletion, completion
    from litellm.integrations.custom_logger import CustomLogger

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    CustomLogger = object


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
        # Handle both datetime.timedelta and float types for duration
        if hasattr(end_time - start_time, 'total_seconds'):
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
        else:
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
        # Handle both datetime.timedelta and float types for duration
        if hasattr(end_time - start_time, 'total_seconds'):
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
        else:
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


# Global logger instance
_druppie_logger: DruppieLogger | None = None


def get_druppie_logger() -> DruppieLogger:
    """Get or create the global Druppie logger."""
    global _druppie_logger
    if _druppie_logger is None:
        _druppie_logger = DruppieLogger()
        if LITELLM_AVAILABLE:
            litellm.callbacks = [_druppie_logger]
    return _druppie_logger


# Provider configurations
# Both zai and deepinfra are OpenAI-compatible, so they use the same "openai/" prefix
# with different api_base URLs. This is how LiteLLM handles custom OpenAI-compatible endpoints.
PROVIDER_CONFIGS = {
    "zai": {
        "prefix": "openai",  # OpenAI-compatible API
        "default_model": "glm-4.7",
        "api_key_env": "ZAI_API_KEY",
        "model_env": "ZAI_MODEL",
        "base_url_env": "ZAI_BASE_URL",
        "default_base_url": "https://api.z.ai/api/coding/paas/v4",
    },
    "deepinfra": {
        "prefix": "openai",  # OpenAI-compatible API (same as zai)
        "default_model": "Qwen/Qwen3-32B",
        "api_key_env": "DEEPINFRA_API_KEY",
        "model_env": "DEEPINFRA_MODEL",
        "base_url_env": "DEEPINFRA_BASE_URL",
        "default_base_url": "https://api.deepinfra.com/v1/openai",
    },
}


class ChatLiteLLM(BaseLLM):
    """Unified LLM provider using LiteLLM.

    This is the only LLM implementation. All providers (zai, deepinfra, openai,
    anthropic) go through LiteLLM for standardized tool calling.
    """

    def __init__(
        self,
        provider: str = "zai",
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        timeout: float = 300.0,
        max_retries: int = 3,
    ):
        """Initialize LiteLLM provider.

        Args:
            provider: Provider name (zai, deepinfra, openai, anthropic)
            model: Model name (uses provider default if not specified)
            api_key: API key (reads from env if not specified)
            api_base: Custom API base URL (reads from env if not specified)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
            max_retries: Maximum retries for transient errors
        """
        if not LITELLM_AVAILABLE:
            raise ImportError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        self.provider = provider
        config = PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["zai"])

        # Load configuration from environment
        self.api_key = api_key or os.getenv(config["api_key_env"], "")
        self.api_base = api_base or os.getenv(config["base_url_env"], "") or config["default_base_url"]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

        # Model name (user-friendly, e.g., "glm-4.7")
        self._model = model or os.getenv(config["model_env"], "") or config["default_model"]

        # LiteLLM model format (e.g., "openai/glm-4.7" for custom endpoints)
        prefix = config["prefix"]
        if prefix and not self._model.startswith(f"{prefix}/"):
            self._litellm_model = f"{prefix}/{self._model}"
        else:
            self._litellm_model = self._model

        # Configure LiteLLM environment
        self._configure_litellm()

        # Initialize logger
        self._logger = get_druppie_logger()

        # Bound tools
        self._bound_tools: list[dict] = []

        logger.info(
            "llm_initialized",
            provider=self.provider,
            model=self.model,
            api_base=self.api_base or "default",
        )

    def _configure_litellm(self):
        """Set environment variables for LiteLLM."""
        # Both zai and deepinfra are OpenAI-compatible, so we set OPENAI_API_KEY
        # for LiteLLM to use with the "openai/" prefix
        if self.api_key:
            os.environ["OPENAI_API_KEY"] = self.api_key

    @property
    def model(self) -> str:
        """User-friendly model name (e.g., 'zai/glm-4.7')."""
        return f"{self.provider}/{self._model}"

    @property
    def model_name(self) -> str:
        """Alias for model property."""
        return self.model

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return self.provider

    @property
    def supports_native_tools(self) -> bool:
        """LiteLLM handles tool calling standardization."""
        return True

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ChatLiteLLM":
        """Create new instance with tools bound."""
        new_instance = ChatLiteLLM(
            provider=self.provider,
            model=self._model,
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

        content = message.content or ""

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
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

                # Normalize common LLM mistakes in argument values
                if isinstance(args, dict):
                    args = self._normalize_tool_args(args)

                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": args if isinstance(args, dict) else {},
                })

        usage = response.usage

        return LLMResponse(
            content=content,
            raw_content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            model=self.model,  # User-friendly: "zai/glm-4.7"
            provider=self.provider,
        )

    def _normalize_tool_args(self, args: dict) -> dict:
        """Normalize common LLM mistakes in tool call argument values.

        Some LLMs (like glm-4.7) send string representations instead of proper
        JSON types in tool calls:
        - "null" string instead of JSON null
        - "{}" string instead of empty object {}
        - "[]" string instead of empty array []
        - "true"/"false" strings instead of booleans

        This normalizes these at the provider level before validation.
        """
        normalized = {}
        for key, value in args.items():
            if isinstance(value, str):
                # Handle string "null" -> None
                if value.lower() == "null":
                    normalized[key] = None
                # Handle string booleans -> bool
                elif value.lower() == "true":
                    normalized[key] = True
                elif value.lower() == "false":
                    normalized[key] = False
                # Handle string JSON objects/arrays -> parsed
                elif value.startswith(("{", "[")):
                    try:
                        parsed = json.loads(value)
                        normalized[key] = parsed
                    except json.JSONDecodeError:
                        normalized[key] = value  # Keep original if not valid JSON
                else:
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized

    def _convert_exception(self, e: Exception) -> LLMError:
        """Convert LiteLLM exceptions to our exception types."""
        error_str = str(e).lower()

        if "rate limit" in error_str or "429" in error_str:
            return RateLimitError(
                f"Rate limit exceeded: {e}",
                provider=self.provider,
            )
        elif "authentication" in error_str or "401" in error_str or "403" in error_str:
            return AuthenticationError(
                f"Authentication failed: {e}",
                provider=self.provider,
            )
        elif "500" in error_str or "502" in error_str or "503" in error_str:
            return ServerError(
                f"Server error: {e}",
                provider=self.provider,
            )
        else:
            return LLMError(
                f"LLM error: {e}",
                provider=self.provider,
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
