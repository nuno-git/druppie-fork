"""LiteLLM provider - unified LLM interface.

Uses LiteLLM for standardized tool calling across all providers.
This is the only LLM implementation - all providers go through LiteLLM.

Environment variables:
    LLM_PROVIDER: zai, deepinfra, deepseek, azure_foundry

    For ZAI:
        ZAI_API_KEY, ZAI_MODEL, ZAI_BASE_URL

    For DeepInfra:
        DEEPINFRA_API_KEY, DEEPINFRA_MODEL, DEEPINFRA_BASE_URL

    For DeepSeek:
        DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL

    For Azure Foundry:
        FOUNDRY_API_KEY, FOUNDRY_MODEL, FOUNDRY_API_URL
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

    def log_failure_event(self, kwargs=None, exception=None, start_time=None, end_time=None, **extra):
        """Capture failed request.

        Uses keyword defaults for compatibility with different litellm callback signatures.
        """

        duration_ms = 0
        if start_time and end_time:
            diff = end_time - start_time
            if hasattr(diff, 'total_seconds'):
                duration_ms = int(diff.total_seconds() * 1000)
            else:
                duration_ms = int(diff * 1000)

        call_record = {
            "timestamp": self.last_request.get("timestamp") if self.last_request else None,
            "model": (kwargs or {}).get("model", ""),
            "provider": "litellm",
            "status": "error",
            "duration_ms": duration_ms,
            "error": str(exception) if exception else "unknown",
            "error_type": type(exception).__name__ if exception else "unknown",
        }

        self.call_history.append(call_record)

    async def async_log_failure_event(self, kwargs=None, exception=None, start_time=None, end_time=None, **extra):
        """Async version - same logic."""
        self.log_failure_event(kwargs=kwargs, exception=exception, start_time=start_time, end_time=end_time, **extra)


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
    "deepseek": {
        "prefix": "deepseek",  # LiteLLM native DeepSeek support
        "default_model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com/v1",
    },
    "azure_foundry": {
        "prefix": "openai",  # OpenAI-compatible API
        "default_model": "GPT-5-MINI",
        "api_key_env": "FOUNDRY_API_KEY",
        "model_env": "FOUNDRY_MODEL",
        "base_url_env": "FOUNDRY_API_URL",
        "default_base_url": "https://druppie.cognitiveservices.azure.com/openai/v1",
        "use_max_completion_tokens": True,
        "default_temperature": 1.0,
        "force_temperature": True,  # GPT-5-MINI only supports temperature=1.0
        "auth_type": "bearer",  # Use Bearer token instead of api-key header
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
        temperature: float | None = None,
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
            temperature: Temperature for generation (None = use provider default)
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
        # Provider may force a specific temperature (e.g. GPT-5-MINI only supports 1.0)
        if config.get("force_temperature"):
            self.temperature = config["default_temperature"]
        elif temperature is not None:
            self.temperature = temperature
        else:
            self.temperature = config.get("default_temperature", 0.7)
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

        # Model name (user-friendly, e.g., "glm-4.7")
        self._model = model or os.getenv(config["model_env"], "") or config["default_model"]

        # Some providers (e.g. Azure OpenAI) require max_completion_tokens instead of max_tokens
        self._use_max_completion_tokens = config.get("use_max_completion_tokens", False)

        # Bearer token auth (e.g. Azure Foundry) — send key as Authorization header
        self._auth_type = config.get("auth_type", "api_key")
        self._extra_headers: dict[str, str] = {}
        if self._auth_type == "bearer" and self.api_key:
            self._extra_headers["Authorization"] = f"Bearer {self.api_key}"

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
        """Configure LiteLLM environment.

        For bearer-auth providers we set a dummy OPENAI_API_KEY so LiteLLM
        doesn't reject the request — the real auth goes via extra_headers.
        The actual API key is always passed per-request via the api_key kwarg
        to avoid race conditions when multiple providers are active.
        """
        if not os.getenv("OPENAI_API_KEY"):
            # Set a placeholder so LiteLLM doesn't error on missing key.
            # The real key is passed per-request in _build_kwargs.
            os.environ["OPENAI_API_KEY"] = "placeholder-see-per-request-api-key"

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

    def _build_kwargs(self, messages, tools, max_tokens_override=None):
        """Build common kwargs for LiteLLM completion calls."""
        effective_tools = tools or self._bound_tools
        effective_max_tokens = min(max_tokens_override or self.max_tokens, 16384)

        token_param = "max_completion_tokens" if self._use_max_completion_tokens else "max_tokens"
        kwargs = {
            "model": self._litellm_model,
            "messages": messages,
            "temperature": self.temperature,
            # Bearer-auth providers authenticate via extra_headers; pass a dummy
            # key so LiteLLM doesn't inject the real key as an api-key header.
            "api_key": "bearer-via-header" if self._auth_type == "bearer" else self.api_key,
            token_param: effective_max_tokens,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
        }

        if self.api_base:
            kwargs["api_base"] = self.api_base

        if self._extra_headers:
            kwargs["extra_headers"] = self._extra_headers

        if effective_tools:
            kwargs["tools"] = effective_tools
            kwargs["tool_choice"] = "auto"

        return kwargs

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send synchronous chat completion request."""
        kwargs = self._build_kwargs(messages, tools)

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
        kwargs = self._build_kwargs(messages, tools, max_tokens_override=max_tokens or self.max_tokens)

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
        raw_tool_calls = []  # Keep original for debugging
        if message.tool_calls:
            for tc in message.tool_calls:
                raw_args = tc.function.arguments  # Keep raw for debugging

                # Store raw tool call (original string) for debugging
                raw_tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": raw_args,  # Original string from LLM
                })

                # Parse args for use
                args = raw_args
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

        usage = response.usage

        return LLMResponse(
            content=content,
            raw_content=content,
            tool_calls=tool_calls,
            raw_tool_calls=raw_tool_calls,  # Store raw for debugging
            finish_reason=choice.finish_reason or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            model=self.model,  # User-friendly: "zai/glm-4.7"
            provider=self.provider,
        )

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
