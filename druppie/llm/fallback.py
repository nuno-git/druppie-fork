"""FallbackLLM — thin wrapper that retries on a fallback LLM when the primary fails.

ANY LLMError from the primary triggers fallback, including AuthenticationError.
This is correct for cross-provider fallback: if provider A's auth fails,
provider B (a completely different service) may work fine.

Interaction with existing retry layers:
    AgentLoop._call_llm() retry loop (3 attempts, exponential backoff)
      -> FallbackLLM.achat()
           -> primary ChatLiteLLM.achat() (litellm internal retries: num_retries=3)
           -> (any LLMError after all litellm retries)
           -> fallback ChatLiteLLM.achat() (litellm internal retries: num_retries=3)
"""

from typing import Any

import structlog

from .base import BaseLLM, LLMError, LLMResponse

logger = structlog.get_logger()


class FallbackLLM(BaseLLM):
    """LLM wrapper that falls back to a secondary LLM on any error."""

    def __init__(self, primary: BaseLLM, fallback: BaseLLM):
        self._primary = primary
        self._fallback = fallback
        self._active: BaseLLM = primary

    # ------------------------------------------------------------------
    # Properties — delegate to primary
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._primary.model

    @property
    def model_name(self) -> str:
        return self._primary.model_name

    @property
    def provider_name(self) -> str:
        return self._primary.provider_name

    @property
    def supports_native_tools(self) -> bool:
        return self._primary.supports_native_tools

    @property
    def active_llm(self) -> BaseLLM:
        """Return whichever LLM last served a request."""
        return self._active

    # ------------------------------------------------------------------
    # Chat methods — primary with fallback
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            response = self._primary.chat(messages, tools)
            self._active = self._primary
            return response
        except LLMError as e:
            logger.warning(
                "llm_fallback_activated",
                primary_provider=self._primary.provider_name,
                fallback_provider=self._fallback.provider_name,
                error_type=type(e).__name__,
                error=str(e)[:200],
            )
            response = self._fallback.chat(messages, tools)
            self._active = self._fallback
            return response

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        try:
            response = await self._primary.achat(messages, tools, max_tokens)
            self._active = self._primary
            return response
        except LLMError as e:
            logger.warning(
                "llm_fallback_activated",
                primary_provider=self._primary.provider_name,
                fallback_provider=self._fallback.provider_name,
                error_type=type(e).__name__,
                error=str(e)[:200],
            )
            response = await self._fallback.achat(messages, tools, max_tokens)
            self._active = self._fallback
            return response

    # ------------------------------------------------------------------
    # History — concatenate both
    # ------------------------------------------------------------------

    def get_call_history(self) -> list[dict[str, Any]]:
        return self._primary.get_call_history() + self._fallback.get_call_history()

    def clear_call_history(self) -> None:
        self._primary.clear_call_history()
        self._fallback.clear_call_history()
