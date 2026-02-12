"""LLM Service for managing LLM instances.

Provides factory methods and singleton access to LLM providers.

Supported providers:
- zai: Z.AI GLM models (default)
- deepinfra: DeepInfra OpenAI-compatible API (Qwen, Llama, etc.)
- deepseek: DeepSeek V3/Coder models (deepseek-chat, deepseek-coder)
"""

import os
from typing import Any

import httpx
import structlog

from .base import BaseLLM
from .zai import ChatZAI
from .deepinfra import ChatDeepInfra
from .deepseek import ChatDeepSeek

logger = structlog.get_logger()


class LLMConfigurationError(Exception):
    """Raised when LLM is not properly configured."""
    pass


class LLMService:
    """Service for managing LLM instances.

    Handles provider selection and lazy initialization.

    Environment variables:
        LLM_PROVIDER: Provider to use (zai, deepinfra, deepseek, mock, auto)
        ZAI_API_KEY: API key for Z.AI (REQUIRED unless using mock)
        ZAI_MODEL: Model name for Z.AI (default: GLM-4.7)
        ZAI_BASE_URL: Base URL for Z.AI API
        DEEPINFRA_API_KEY: API key for DeepInfra
        DEEPINFRA_MODEL: Model name for DeepInfra (default: Qwen/Qwen3-Next-80B-A3B-Instruct)
        DEEPINFRA_BASE_URL: Base URL for DeepInfra
        DEEPSEEK_API_KEY: API key for DeepSeek
        DEEPSEEK_MODEL: Model name for DeepSeek (default: deepseek-chat)
        DEEPSEEK_BASE_URL: Base URL for DeepSeek
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
            print(f"[LLM SERVICE] Cached provider: {self._provider}")
            return self._provider

        provider = os.getenv("LLM_PROVIDER", "auto").lower()
        zai_key = os.getenv("ZAI_API_KEY", "")
        deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")

        print(f"[LLM SERVICE] Environment LLM_PROVIDER: {provider}")
        print(f"[LLM SERVICE] ZAI_API_KEY present: {bool(zai_key)}")
        print(f"[LLM SERVICE] DEEPINFRA_API_KEY present: {bool(deepinfra_key)}")
        print(f"[LLM SERVICE] DEEPSEEK_API_KEY present: {bool(deepseek_key)}")

        if provider == "zai" and zai_key:
            self._provider = "zai"
        elif provider == "deepinfra":
            if not deepinfra_key:
                raise LLMConfigurationError(
                    "DEEPINFRA_API_KEY environment variable is required when LLM_PROVIDER=deepinfra. "
                    "Please set DEEPINFRA_API_KEY in your .env file or environment."
                )
            self._provider = "deepinfra"
        elif provider == "deepseek":
            if not deepseek_key:
                raise LLMConfigurationError(
                    "DEEPSEEK_API_KEY environment variable is required when LLM_PROVIDER=deepseek. "
                    "Please set DEEPSEEK_API_KEY in your .env file or environment."
                )
            self._provider = "deepseek"
        elif provider == "auto":
            # Auto-detect: prefer DeepSeek, then DeepInfra, then Z.AI
            if deepseek_key:
                self._provider = "deepseek"
            elif deepinfra_key:
                self._provider = "deepinfra"
            elif zai_key:
                self._provider = "zai"
            else:
                logger.error("no_llm_provider_configured")
                raise ValueError(
                    "No LLM provider configured. Please set either DEEPSEEK_API_KEY, DEEPINFRA_API_KEY, or ZAI_API_KEY environment variable."
                )
        else:
            # Fallback logic
            if deepseek_key:
                self._provider = "deepseek"
            elif deepinfra_key:
                self._provider = "deepinfra"
            elif zai_key:
                self._provider = "zai"
            else:
                logger.error("no_llm_provider_configured")
                raise ValueError(
                    "No LLM provider configured. Please set either DEEPSEEK_API_KEY, DEEPINFRA_API_KEY, or ZAI_API_KEY environment variable."
                )

        print(f"[LLM SERVICE] Selected provider: {self._provider}")
        logger.info("llm_provider_selected", provider=self._provider)
        return self._provider

    def get_llm(self) -> BaseLLM:
        """Get or create LLM client."""
        if self._llm is not None:
            return self._llm

        provider = self.get_provider()

        if provider == "deepseek":
            self._llm = ChatDeepSeek(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                base_url=os.getenv(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                ),
            )
            logger.info(
                "using_deepseek_llm",
                model=self._llm.model,
                base_url=self._llm.base_url,
            )
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
