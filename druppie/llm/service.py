"""LLM Service for managing LLM instances.

Provides factory methods and singleton access to LLM providers.

Supported providers:
- zai: Z.AI GLM models (default)
- deepinfra: DeepInfra OpenAI-compatible API (Qwen, Llama, etc.)
- mock: Mock provider for testing
"""

import os
from typing import Any

import httpx
import structlog

from .base import BaseLLM
from .mock import ChatMock
from .zai import ChatZAI
from .deepinfra import ChatDeepInfra

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
        DEEPINFRA_BASE_URL: Base URL for DeepInfra API
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
        zai_key = os.getenv("ZAI_API_KEY", "")
        deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")

        if provider == "mock":
            self._provider = "mock"
        elif provider == "zai":
            if not zai_key:
                raise LLMConfigurationError(
                    "ZAI_API_KEY environment variable is required when LLM_PROVIDER=zai. "
                    "Please set ZAI_API_KEY in your .env file or environment."
                )
            self._provider = "zai"
        elif provider == "deepinfra":
            if not deepinfra_key:
                raise LLMConfigurationError(
                    "DEEPINFRA_API_KEY environment variable is required when LLM_PROVIDER=deepinfra. "
                    "Please set DEEPINFRA_API_KEY in your .env file or environment."
                )
            self._provider = "deepinfra"
        elif provider == "auto":
            # Auto-detect: prefer DeepInfra, then Z.AI
            if deepinfra_key:
                self._provider = "deepinfra"
            elif zai_key:
                self._provider = "zai"
            else:
                raise LLMConfigurationError(
                    "No LLM API key configured! Please set one of:\n"
                    "  - ZAI_API_KEY for Z.AI GLM models\n"
                    "  - DEEPINFRA_API_KEY for DeepInfra models\n"
                    "Or set LLM_PROVIDER=mock for testing (not recommended for production)."
                )
        else:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER: {provider}. "
                "Valid options: zai, deepinfra, mock, auto"
            )

        logger.info("llm_provider_selected", provider=self._provider)
        return self._provider

    def get_llm(self) -> BaseLLM:
        """Get or create the LLM client."""
        if self._llm is not None:
            return self._llm

        provider = self.get_provider()

        if provider == "mock":
            self._llm = ChatMock()
            logger.info("using_mock_llm")
        elif provider == "deepinfra":
            self._llm = ChatDeepInfra(
                api_key=os.getenv("DEEPINFRA_API_KEY"),
                model=os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen3-Next-80B-A3B-Instruct"),
                base_url=os.getenv(
                    "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
                ),
            )
            logger.info(
                "using_deepinfra_llm",
                model=self._llm.model,
                base_url=self._llm.base_url,
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
