"""Provider abstraction layer for LLM Integration Module.

Uses LiteLLM for multi-provider support with automatic failover.
"""

import os
from typing import Any

import litellm
import tiktoken
from litellm import completion

from .config import Config, ProviderConfig
from .logging import get_logger, log_llm_request, log_provider_failover
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    TokenCountRequest,
    TokenCountResponse,
    TokenUsage,
)

logger = get_logger()

# Cost per 1K tokens (approximate, should be configurable)
COST_PER_1K_TOKENS = {
    "gpt-4": {"prompt": 0.03, "completion": 0.06},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-3.5-turbo": {"prompt": 0.0015, "completion": 0.002},
    "claude-3-opus": {"prompt": 0.015, "completion": 0.075},
    "claude-3-sonnet": {"prompt": 0.003, "completion": 0.015},
    "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
}

# Default models per provider
DEFAULT_MODELS = {
    "openai": "gpt-3.5-turbo",
    "anthropic": "claude-3-sonnet-20240229",
    "ollama": "llama2",
}


class ProviderError(Exception):
    """Provider-specific error."""

    def __init__(self, message: str, provider: str, is_retryable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.is_retryable = is_retryable


class ProviderManager:
    """Manages LLM providers with failover support."""

    def __init__(self, config: Config | None = None):
        """Initialize provider manager.

        Args:
            config: Configuration instance or None to use global config.
        """
        self.config = config or Config()
        self._setup_litellm()

    def _setup_litellm(self) -> None:
        """Configure LiteLLM with API keys from environment."""
        # LiteLLM reads API keys from environment automatically
        # but we can also set them explicitly
        if os.getenv("OPENAI_API_KEY"):
            litellm.openai_key = os.getenv("OPENAI_API_KEY")
        if os.getenv("ANTHROPIC_API_KEY"):
            litellm.anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    def _get_model_for_provider(self, provider: str, requested_model: str | None) -> str:
        """Get the model identifier for a provider.

        Args:
            provider: Provider name.
            requested_model: Requested model or None for default.

        Returns:
            Model identifier string.
        """
        if requested_model:
            return requested_model
        return DEFAULT_MODELS.get(provider.lower(), "gpt-3.5-turbo")

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost for token usage.

        Args:
            model: Model identifier.
            prompt_tokens: Number of prompt tokens.
            completion_tokens: Number of completion tokens.

        Returns:
            Estimated cost in USD.
        """
        # Normalize model name
        model_key = model.lower()
        for key in COST_PER_1K_TOKENS:
            if key in model_key:
                costs = COST_PER_1K_TOKENS[key]
                prompt_cost = (prompt_tokens / 1000) * costs["prompt"]
                completion_cost = (completion_tokens / 1000) * costs["completion"]
                return round(prompt_cost + completion_cost, 6)

        # Default: very rough estimate
        return round((prompt_tokens + completion_tokens) * 0.000002, 6)

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """Execute chat completion with automatic failover.

        Args:
            request: Chat completion request.

        Returns:
            Chat completion response.

        Raises:
            ProviderError: If all providers fail.
        """
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        last_error: Exception | None = None
        tried_providers: list[str] = []

        for provider_config in self.config.providers:
            provider_name = provider_config.name
            tried_providers.append(provider_name)
            model = "unknown"

            try:
                model = self._get_model_for_provider(provider_name, request.model)

                # Build completion kwargs
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": request.stream,
                }

                if request.max_tokens is not None:
                    kwargs["max_tokens"] = request.max_tokens
                if request.temperature is not None:
                    kwargs["temperature"] = request.temperature

                # Add base_url for Ollama
                if provider_config.base_url:
                    kwargs["api_base"] = provider_config.base_url

                # Execute completion
                response = completion(**kwargs)

                # Extract response data
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                # Get token usage
                usage_data = response.usage
                token_usage = TokenUsage(
                    prompt_tokens=usage_data.prompt_tokens,
                    completion_tokens=usage_data.completion_tokens,
                    total_tokens=usage_data.total_tokens,
                )

                # Calculate cost
                estimated_cost = self._estimate_cost(
                    model,
                    token_usage.prompt_tokens,
                    token_usage.completion_tokens,
                )

                # Log metadata (no content)
                log_llm_request(
                    logger,
                    provider_name,
                    model,
                    token_usage.prompt_tokens,
                    token_usage.completion_tokens,
                    "success",
                )

                return ChatCompletionResponse(
                    content=content,
                    model=model,
                    provider=provider_name,
                    usage=token_usage,
                    estimated_cost=estimated_cost,
                    finish_reason=finish_reason,
                )

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # Check if it's a rate limit error
                is_rate_limit = "rate limit" in error_msg.lower() or "429" in error_msg

                # Log the failure
                log_llm_request(
                    logger,
                    provider_name,
                    model,
                    0,
                    0,
                    "error",
                    error=error_msg,
                )

                # Try next provider if this one failed
                if provider_config != self.config.providers[-1]:
                    next_provider = self.config.providers[
                        self.config.providers.index(provider_config) + 1
                    ].name
                    log_provider_failover(
                        logger,
                        provider_name,
                        next_provider,
                        "rate_limit" if is_rate_limit else "error",
                    )
                continue

        # All providers failed
        error_msg = f"All providers failed: {', '.join(tried_providers)}. Last error: {last_error}"
        logger.error(error_msg)
        raise ProviderError(error_msg, "all", is_retryable=False)

    async def count_tokens(self, request: TokenCountRequest) -> TokenCountResponse:
        """Count tokens for given text.

        Args:
            request: Token count request.

        Returns:
            Token count response.
        """
        model = request.model or "gpt-3.5-turbo"

        try:
            # Use tiktoken for OpenAI models
            if "gpt" in model.lower():
                encoding = tiktoken.encoding_for_model(model)
                token_count = len(encoding.encode(request.text))
            else:
                # Fallback: rough estimate (4 chars per token)
                token_count = len(request.text) // 4

            return TokenCountResponse(
                token_count=token_count,
                model=model,
            )
        except Exception as e:
            # Fallback on any error
            logger.warning(f"Token counting failed for {model}: {e}, using estimate")
            token_count = len(request.text) // 4
            return TokenCountResponse(
                token_count=token_count,
                model=model,
            )

    def list_providers(self) -> list[dict[str, Any]]:
        """List available providers and their status.

        Returns:
            List of provider information dictionaries.
        """
        providers = []

        for config in self.config.providers:
            # Check if provider is available
            is_available = self._check_provider_available(config)

            provider_info = {
                "name": config.name,
                "priority": config.priority,
                "available": is_available,
                "models": [DEFAULT_MODELS.get(config.name.lower(), "unknown")],
            }
            providers.append(provider_info)

        return providers

    def _check_provider_available(self, config: ProviderConfig) -> bool:
        """Check if a provider is available.

        Args:
            config: Provider configuration.

        Returns:
            True if provider appears to be available.
        """
        # For cloud providers, check if API key is set
        if config.name.lower() in ["openai", "anthropic"]:
            return config.api_key is not None

        # For Ollama, we could ping the server, but for now assume available
        return True
