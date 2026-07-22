"""FallbackLLM — wrapper that asks the user before switching to a fallback LLM.

When the primary provider fails, raises FallbackAvailableError so the agent
loop can pause and ask the user whether to switch. If the user approves
(tracked per-session in the DB via approve_fallback()), subsequent calls go
straight to the fallback without asking again.
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

    Approval state is stored in the ``fallback_approvals`` DB table so it
    is shared across all backend workers.
    """

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
        from druppie.db.database import SessionLocal
        from druppie.db.models.fallback_approval import FallbackApproval

        db = SessionLocal()
        try:
            existing = (
                db.query(FallbackApproval)
                .filter(FallbackApproval.session_id == session_id, FallbackApproval.agent_id.is_(None))
                .first()
            )
            if not existing:
                db.add(FallbackApproval(session_id=session_id, agent_id=None))
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def approve_fallback_for_agent(cls, session_id: str, agent_id: str) -> None:
        """Mark a specific agent as approved for fallback in this session."""
        from druppie.db.database import SessionLocal
        from druppie.db.models.fallback_approval import FallbackApproval

        db = SessionLocal()
        try:
            existing = (
                db.query(FallbackApproval)
                .filter(FallbackApproval.session_id == session_id, FallbackApproval.agent_id == agent_id)
                .first()
            )
            if not existing:
                db.add(FallbackApproval(session_id=session_id, agent_id=agent_id))
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def is_approved(cls, session_id: str, agent_id: str | None = None) -> bool:
        """Check if a session (optionally for a specific agent) is approved for fallback."""
        if not session_id:
            return False
        from druppie.db.database import SessionLocal
        from druppie.db.models.fallback_approval import FallbackApproval

        db = SessionLocal()
        try:
            # Check session-wide approval first
            session_wide = (
                db.query(FallbackApproval.id)
                .filter(FallbackApproval.session_id == session_id, FallbackApproval.agent_id.is_(None))
                .first()
            )
            if session_wide:
                return True
            # Check per-agent approval
            if agent_id:
                agent_approved = (
                    db.query(FallbackApproval.id)
                    .filter(FallbackApproval.session_id == session_id, FallbackApproval.agent_id == agent_id)
                    .first()
                )
                if agent_approved:
                    return True
            return False
        finally:
            db.close()

    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """Remove all approval state for a session."""
        from druppie.db.database import SessionLocal
        from druppie.db.models.fallback_approval import FallbackApproval

        db = SessionLocal()
        try:
            db.query(FallbackApproval).filter(FallbackApproval.session_id == session_id).delete(
                synchronize_session="fetch"
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

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
        return self.__class__.is_approved(self._session_id, self._agent_id)

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
        except LLMError as e:  # ChatLiteLLM._convert_exception wraps all exceptions as LLMError subtypes
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
        except LLMError as e:  # ChatLiteLLM._convert_exception wraps all exceptions as LLMError subtypes
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