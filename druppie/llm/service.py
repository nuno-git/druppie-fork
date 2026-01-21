"""LLM Service for managing LLM instances.

Provides factory methods and singleton access to LLM providers.
"""

import os
from typing import Any

import httpx
import structlog

from .base import BaseLLM
from .mock import ChatMock
from .zai import ChatZAI

logger = structlog.get_logger()


class LLMService:
    """Service for managing LLM instances.

    Handles provider selection and lazy initialization.
    """

    def __init__(self):
        """Initialize LLM service."""
        self._llm: BaseLLM | None = None
        self._provider: str | None = None

    def get_provider(self) -> str:
        """Get the configured LLM provider name."""
        if self._provider is not None:
            return self._provider

        provider = os.getenv("LLM_PROVIDER", "auto").lower()
        zai_key = os.getenv("ZAI_API_KEY", "")

        if provider == "mock":
            self._provider = "mock"
        elif provider == "zai" and zai_key:
            self._provider = "zai"
        elif provider == "auto":
            # Auto-detect: prefer Z.AI if key is set, otherwise mock
            if zai_key:
                self._provider = "zai"
            else:
                logger.warning("no_llm_provider_configured", using="mock")
                self._provider = "mock"
        else:
            # Default to mock if no Z.AI key
            self._provider = "mock" if not zai_key else "zai"

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
        else:
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
