"""FallbackLLM — wrapper that asks the user before switching to a fallback LLM.

When the primary provider fails, raises FallbackAvailableError so the agent
loop can pause and ask the user whether to switch. If the user approves
(tracked per-session via approve_fallback()), subsequent calls go straight
to the fallback without asking again.
"""

from typing import Any

import structlog

from .base import BaseLLM, FallbackAvailableError, LLMError

logger = structlog.get_logger()


class FallbackLLM(BaseLLM):
    """LLM wrapper that offers a fallback when the primary fails.

    Instead of silently switching, raises FallbackAvailableError so the
    caller can ask the user. Call approve_fallback(session_id) after
    the user confirms; subsequent calls then use the fallback directly.

    Two approval levels:
    - Per-agent: approve_fallback_for_agent(session_id, agent_id) — only
      this agent type auto-switches in this session
    - Session-wide: approve_fallback(session_id) — all agents auto-switch
    """

    _approved_sessions: set[str] = set()
    _approved_agents: set[tuple[str, str]] = set()

    def __init__(
        self, primary: BaseLLM, fallback: BaseLLM,
        session_id: str | None = None, agent_id: str | None = None,
    ):
        self._primary = primary
        self._fallback = fallback
        self._session_id = session_id
        self._agent_id = agent_id

    @classmethod
    def approve_fallback(cls, session_id: str) -> None:
        """Mark a session as approved for fallback (all agents)."""
        cls._approved_sessions.add(session_id)

    @classmethod
    def approve_fallback_for_agent(cls, session_id: str, agent_id: str) -> None:
        """Mark a specific agent as approved for fallback in this session."""
        cls._approved_agents.add((session_id, agent_id))

    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """Remove all approval state for a session."""
        cls._approved_sessions.discard(session_id)
        cls._approved_agents = {
            (sid, aid) for sid, aid in cls._approved_agents if sid != session_id
        }

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
    def fallback_provider(self) -> str:
        return self._fallback.provider_name

    @property
    def fallback_model(self) -> str:
        return self._fallback.model

    # ------------------------------------------------------------------
    # Chat methods
    # ------------------------------------------------------------------

    def _is_approved(self) -> bool:
        if not self._session_id:
            return False
        if self._session_id in self._approved_sessions:
            return True
        if self._agent_id and (self._session_id, self._agent_id) in self._approved_agents:
            return True
        return False

    def _raise_fallback_available(self, error: Exception) -> None:
        raise FallbackAvailableError(
            message=f"Primary provider {self._primary.provider_name} failed: {error}",
            primary_provider=self._primary.provider_name,
            primary_model=self._primary.model,
            fallback_provider=self._fallback.provider_name,
            fallback_model=self._fallback.model,
            error_type=type(error).__name__,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        if self._is_approved():
            return self._fallback.chat(messages, tools)

        try:
            return self._primary.chat(messages, tools)
        except LLMError as e:
            logger.warning(
                "llm_primary_failed_fallback_available",
                primary_provider=self._primary.provider_name,
                fallback_provider=self._fallback.provider_name,
                error_type=type(e).__name__,
                error=str(e)[:200],
            )
            self._raise_fallback_available(e)

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ):
        if self._is_approved():
            return await self._fallback.achat(messages, tools, max_tokens)

        try:
            return await self._primary.achat(messages, tools, max_tokens)
        except LLMError as e:
            logger.warning(
                "llm_primary_failed_fallback_available",
                primary_provider=self._primary.provider_name,
                fallback_provider=self._fallback.provider_name,
                error_type=type(e).__name__,
                error=str(e)[:200],
            )
            self._raise_fallback_available(e)

    # ------------------------------------------------------------------
    # History — concatenate both
    # ------------------------------------------------------------------

    def get_call_history(self) -> list[dict[str, Any]]:
        return self._primary.get_call_history() + self._fallback.get_call_history()

    def clear_call_history(self) -> None:
        self._primary.clear_call_history()
        self._fallback.clear_call_history()
