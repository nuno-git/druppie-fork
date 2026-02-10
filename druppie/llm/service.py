"""LLM Service for managing LLM instances.

Provides factory methods and singleton access to LLM providers.

Supported providers:
- litellm: LiteLLM unified interface (recommended) - supports 100+ providers
- zai: Z.AI GLM models (legacy)
- deepinfra: DeepInfra OpenAI-compatible API (legacy)

LiteLLM provider configuration:
    LLM_PROVIDER=litellm
    LITELLM_PROVIDER: Which backend (deepinfra, zai, openai, anthropic)
    LITELLM_MODEL: Model name
    LITELLM_API_KEY: API key
    LITELLM_API_BASE: Custom API base URL (optional)
"""

import os
from typing import Any

import structlog

from .base import BaseLLM
from .zai import ChatZAI
from .deepinfra import ChatDeepInfra
from .litellm_provider import ChatLiteLLM, LITELLM_AVAILABLE

logger = structlog.get_logger()


class LLMConfigurationError(Exception):
    """Raised when LLM is not properly configured."""
    pass


class LLMService:
    """Service for managing LLM instances.

    Handles provider selection and lazy initialization.

    Environment variables:
        LLM_PROVIDER: Provider to use (zai, deepinfra, mock, auto)
        ZAI_API_KEY: API key for Z.AI (REQUIRED unless using mock)
        ZAI_MODEL: Model name for Z.AI (default: GLM-4.7)
        ZAI_BASE_URL: Base URL for Z.AI API
        DEEPINFRA_API_KEY: API key for DeepInfra
        DEEPINFRA_MODEL: Model name for DeepInfra (default: Qwen/Qwen3-Next-80B-A3B-Instruct)
        DEEPINFRA_BASE_URL: Base URL for DeepInfra
    """

    def __init__(self):
        """Initialize LLM service."""
        self._llm: BaseLLM | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name.

        Raises:
            LLMConfigurationError: If no API key is configured and provider is not 'mock'
        """
        if self._provider is not None:
            return self._provider

        provider = os.getenv("LLM_PROVIDER", "auto").lower()
        litellm_key = os.getenv("LITELLM_API_KEY", "")
        zai_key = os.getenv("ZAI_API_KEY", "")
        deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")

        logger.debug(
            "llm_provider_detection",
            provider_env=provider,
            litellm_key_present=bool(litellm_key),
            zai_key_present=bool(zai_key),
            deepinfra_key_present=bool(deepinfra_key),
        )

        # Explicit provider selection
        if provider == "litellm":
            if not LITELLM_AVAILABLE:
                raise LLMConfigurationError(
                    "LLM_PROVIDER=litellm but litellm is not installed. "
                    "Install it with: pip install litellm"
                )
            if not litellm_key:
                raise LLMConfigurationError(
                    "LITELLM_API_KEY environment variable is required when LLM_PROVIDER=litellm. "
                    "Please set LITELLM_API_KEY in your .env file."
                )
            self._provider = "litellm"

        elif provider == "zai":
            if not zai_key:
                raise LLMConfigurationError(
                    "ZAI_API_KEY environment variable is required when LLM_PROVIDER=zai."
                )
            self._provider = "zai"

        elif provider == "deepinfra":
            if not deepinfra_key:
                raise LLMConfigurationError(
                    "DEEPINFRA_API_KEY environment variable is required when LLM_PROVIDER=deepinfra."
                )
            self._provider = "deepinfra"

        elif provider == "auto":
            # Auto-detect: prefer LiteLLM, then DeepInfra, then Z.AI
            if litellm_key and LITELLM_AVAILABLE:
                self._provider = "litellm"
            elif deepinfra_key:
                self._provider = "deepinfra"
            elif zai_key:
                self._provider = "zai"
            else:
                raise LLMConfigurationError(
                    "No LLM provider configured. Set one of: "
                    "LITELLM_API_KEY, DEEPINFRA_API_KEY, or ZAI_API_KEY"
                )
        else:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER: {provider}. "
                "Valid options: litellm, zai, deepinfra, auto"
            )

        logger.info("llm_provider_selected", provider=self._provider)
        return self._provider

    def get_llm(self) -> BaseLLM:
        """Get or create LLM client."""
        if self._llm is not None:
            return self._llm

        provider = self.get_provider()

        if provider == "litellm":
            self._llm = ChatLiteLLM(
                provider=os.getenv("LITELLM_PROVIDER", "deepinfra"),
                model=os.getenv("LITELLM_MODEL"),
                api_key=os.getenv("LITELLM_API_KEY"),
                api_base=os.getenv("LITELLM_API_BASE"),
                temperature=float(os.getenv("LITELLM_TEMPERATURE", "0.7")),
                max_tokens=int(os.getenv("LITELLM_MAX_TOKENS", "16384")),
                timeout=float(os.getenv("LITELLM_TIMEOUT", "300")),
                max_retries=int(os.getenv("LITELLM_MAX_RETRIES", "3")),
            )
            logger.info(
                "using_litellm",
                provider=self._llm.provider,
                model=self._llm.model,
                api_base=self._llm.api_base or "default",
            )

        elif provider == "deepinfra":
            max_tokens = int(os.getenv("DEEPINFRA_MAX_TOKENS", "16384"))
            self._llm = ChatDeepInfra(
                api_key=os.getenv("DEEPINFRA_API_KEY"),
                model=os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen3-Next-80B-A3B-Instruct"),
                base_url=os.getenv(
                    "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
                ),
                max_tokens=max_tokens,
            )
            logger.info(
                "using_deepinfra_llm",
                model=self._llm.model,
                base_url=self._llm.base_url,
                max_tokens=max_tokens,
            )

        else:
            # Default to Z.AI
            self._llm = ChatZAI(
                api_key=os.getenv("ZAI_API_KEY"),
                model=os.getenv("ZAI_MODEL", "GLM-4.7"),
                base_url=os.getenv(
                    "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
                ),
            )
            logger.info(
                "using_zai_llm",
                model=self._llm.model,
                base_url=self._llm.base_url,
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
