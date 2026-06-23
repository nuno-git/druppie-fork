"""FallbackLLM — thin wrapper that retries on a fallback LLM when the primary fails.

ANY LLMError from the primary triggers fallback, including AuthenticationError.
This is correct for cross-provider fallback: if provider A's auth fails,
provider B (a completely different service) may work fine.

Sticky degraded mode: after the first fallback in a session, subsequent calls
try the primary once (no litellm retries) and fall back instantly on any error.
Within the same agent run, the primary is skipped entirely after a failure.
On a new agent run (same session), the primary gets one more chance.

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
    """LLM wrapper that falls back to a secondary LLM on any error.

    Tracks degraded state per session so that once a fallback occurs,
    subsequent calls avoid slow retries on the broken primary.
    """

    _degraded_sessions: set[str] = set()

    def __init__(self, primary: BaseLLM, fallback: BaseLLM, session_id: str | None = None):
        self._primary = primary
        self._fallback = fallback
        self._active: BaseLLM = primary
        self._session_id = session_id
        self._degraded = session_id in self._degraded_sessions if session_id else False
        self._primary_failed_this_run = False

    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """Remove degraded state for a session (e.g. when session ends)."""
        cls._degraded_sessions.discard(session_id)

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

    @property
    def degraded(self) -> bool:
        return self._degraded

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enter_degraded(self) -> None:
        self._degraded = True
        self._primary_failed_this_run = True
        if self._session_id:
            self._degraded_sessions.add(self._session_id)

    def _try_primary_no_retries(self, call, *args):
        """Call primary with litellm retries disabled. Returns response or raises."""
        saved = getattr(self._primary, "max_retries", None)
        if saved is not None:
            self._primary.max_retries = 0
        try:
            return call(*args)
        finally:
            if saved is not None:
                self._primary.max_retries = saved

    async def _atry_primary_no_retries(self, call, *args):
        """Async version of _try_primary_no_retries."""
        saved = getattr(self._primary, "max_retries", None)
        if saved is not None:
            self._primary.max_retries = 0
        try:
            return await call(*args)
        finally:
            if saved is not None:
                self._primary.max_retries = saved

    # ------------------------------------------------------------------
    # Chat methods — primary with fallback
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self._primary_failed_this_run:
            response = self._fallback.chat(messages, tools)
            self._active = self._fallback
            return response

        if self._degraded:
            try:
                response = self._try_primary_no_retries(
                    self._primary.chat, messages, tools,
                )
                self._active = self._primary
                return response
            except LLMError as e:
                logger.warning(
                    "llm_degraded_fallback",
                    primary_provider=self._primary.provider_name,
                    fallback_provider=self._fallback.provider_name,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                )
                self._primary_failed_this_run = True
                response = self._fallback.chat(messages, tools)
                self._active = self._fallback
                return response

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
            self._enter_degraded()
            try:
                response = self._fallback.chat(messages, tools)
                self._active = self._fallback
                return response
            except LLMError as fallback_error:
                logger.error(
                    "llm_fallback_also_failed",
                    primary_error=f"{type(e).__name__}: {str(e)[:200]}",
                    fallback_error=f"{type(fallback_error).__name__}: {str(fallback_error)[:200]}",
                )
                raise e from fallback_error

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if self._primary_failed_this_run:
            response = await self._fallback.achat(messages, tools, max_tokens)
            self._active = self._fallback
            return response

        if self._degraded:
            try:
                response = await self._atry_primary_no_retries(
                    self._primary.achat, messages, tools, max_tokens,
                )
                self._active = self._primary
                return response
            except LLMError as e:
                logger.warning(
                    "llm_degraded_fallback",
                    primary_provider=self._primary.provider_name,
                    fallback_provider=self._fallback.provider_name,
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                )
                self._primary_failed_this_run = True
                response = await self._fallback.achat(messages, tools, max_tokens)
                self._active = self._fallback
                return response

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
            self._enter_degraded()
            try:
                response = await self._fallback.achat(messages, tools, max_tokens)
                self._active = self._fallback
                return response
            except LLMError as fallback_error:
                logger.error(
                    "llm_fallback_also_failed",
                    primary_error=f"{type(e).__name__}: {str(e)[:200]}",
                    fallback_error=f"{type(fallback_error).__name__}: {str(fallback_error)[:200]}",
                )
                raise e from fallback_error

    # ------------------------------------------------------------------
    # History — concatenate both
    # ------------------------------------------------------------------

    def get_call_history(self) -> list[dict[str, Any]]:
        return self._primary.get_call_history() + self._fallback.get_call_history()

    def clear_call_history(self) -> None:
        self._primary.clear_call_history()
        self._fallback.clear_call_history()
