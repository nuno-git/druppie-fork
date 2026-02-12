"""LLM Service for managing LLM instances.

All providers use LiteLLM internally for standardized tool calling.

Environment variables:
    LLM_PROVIDER: zai, deepinfra (default: zai)

    For ZAI:
        ZAI_API_KEY (required)
        ZAI_MODEL (default: glm-4.7)
        ZAI_BASE_URL (default: https://api.z.ai/api/coding/paas/v4)

    For DeepInfra:
        DEEPINFRA_API_KEY (required)
        DEEPINFRA_MODEL (default: Qwen/Qwen3-32B)
        DEEPINFRA_BASE_URL (default: https://api.deepinfra.com/v1/openai)
"""

import os
from typing import Any

import structlog

from .base import BaseLLM
from .litellm_provider import ChatLiteLLM, LITELLM_AVAILABLE

logger = structlog.get_logger()


class LLMConfigurationError(Exception):
    """Raised when LLM is not properly configured."""

    pass


class LLMService:
    """Service for managing LLM instances.

    All providers go through LiteLLM for standardized tool calling.
    """

    # Supported providers and their required API key env vars
    PROVIDERS = {
        "zai": "ZAI_API_KEY",
        "deepinfra": "DEEPINFRA_API_KEY",
    }

    def __init__(self):
        """Initialize LLM service."""
        self._llm: BaseLLM | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name."""
        if self._provider is not None:
            return self._provider

        if not LITELLM_AVAILABLE:
            raise LLMConfigurationError(
                "litellm is not installed. Install it with: pip install litellm"
            )

        provider = os.getenv("LLM_PROVIDER", "zai").lower()

        # Validate provider
        if provider not in self.PROVIDERS:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER: {provider}. "
                f"Valid options: {', '.join(self.PROVIDERS.keys())}"
            )

        # Check API key
        api_key_env = self.PROVIDERS[provider]
        if not os.getenv(api_key_env):
            raise LLMConfigurationError(
                f"{api_key_env} environment variable is required for LLM_PROVIDER={provider}"
            )

        self._provider = provider
        logger.info("llm_provider_selected", provider=self._provider)
        return self._provider

    def get_llm(self) -> BaseLLM:
        """Get or create LLM client."""
        if self._llm is not None:
            return self._llm

        provider = self.get_provider()

        # All providers use LiteLLM
        self._llm = ChatLiteLLM(provider=provider)

        logger.info(
            "llm_initialized",
            provider=provider,
            model=self._llm.model,
            api_base=self._llm.api_base or "default",
        )

        return self._llm

    def get_call_history(self) -> list[dict[str, Any]]:
        """Get the history of LLM API calls."""
        if self._llm is None:
            return []
        return self._llm.get_call_history()

    def clear_call_history(self) -> None:
        """Clear the LLM call history."""
        if self._llm is not None:
            self._llm.clear_call_history()


# Global singleton instance
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the global LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
