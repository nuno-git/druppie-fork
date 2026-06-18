"""Core types for the agent runtime library. Zero external dependencies."""

from __future__ import annotations

import threading

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

@dataclass(frozen=True)
class AgentEvent:
    """Immutable event record emitted during agent execution."""
    type: str
    timestamp: datetime
    data: dict[str, Any]

    @classmethod
    def now(cls, event_type: str, data: dict[str, Any] | None = None) -> AgentEvent:
        """Create an event with the current UTC timestamp."""
        return cls(type=event_type, timestamp=datetime.now(timezone.utc), data=data or {})


@dataclass
class AgentResult:
    """Final result of an agent run."""
    status: Literal["completed", "error", "cancelled", "paused"]
    done_result: dict | None = None
    error: str | None = None
    events: list[AgentEvent] = field(default_factory=list)


@dataclass
class LoopConfig:
    """Configuration for the agent loop."""
    max_turns: int = 50
    max_retries: int = 3
    retry_base_delay: float = 1.0
    respect_retry_after: bool = True
    max_context_tokens: int = 150000
    max_subagent_depth: int = 10


@dataclass
class DoneResult:
    """Structured result from the done() tool."""
    summary: str
    variables: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequiredToolCall:
    """A tool call count requirement for completion preconditions."""
    tool_name: str
    min_calls: int = 1


@dataclass
class CompletionPrecondition:
    """Conditional tool call requirement checked when done() is called."""
    summary_contains: str | None = None
    unless_summary_contains: str | None = None
    required_tools: list[RequiredToolCall] = field(default_factory=list)
    error_message: str = ""


@dataclass
class CompletionSummaryRequirement:
    """Required status keywords that must appear in the done() summary."""
    one_of: list[str] = field(default_factory=list)
    error_message: str = ""


class CancellationToken:
    """Thread-safe cancellation primitive."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Mark as cancelled. Idempotent."""
        with self._lock:
            self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled


class SessionPauseToken(CancellationToken):
    """CancellationToken that polls the DB for session PAUSED status.

    Uses an in-memory registry so the cancel endpoint can signal the token
    directly — no DB poll delay. The poll loop is a safety net for race
    conditions (e.g. token registered after cancel endpoint runs).
    """

    _active_tokens: dict[str, set["SessionPauseToken"]] = {}
    _tokens_lock = threading.Lock()

    def __init__(self, db_session_factory, session_id, poll_interval: float = 5.0):
        super().__init__()
        self._db_factory = db_session_factory
        self._session_id = session_id
        self._poll_interval = poll_interval
        self._poll_task: asyncio.Task | None = None
        self._agent_task: asyncio.Task | None = None

    @classmethod
    def cancel_session(cls, session_id) -> bool:
        """Directly cancel all tokens for a running session (if any active).

        Returns True if at least one token was found and cancelled, False
        otherwise. Called by the cancel endpoint / LISTEN handler for
        zero-latency pause signalling.
        """
        with cls._tokens_lock:
            tokens = list(cls._active_tokens.get(str(session_id), set()))
        cancelled_any = False
        for token in tokens:
            if not token.is_cancelled:
                token.cancel()
                cancelled_any = True
        return cancelled_any

    def cancel(self) -> None:
        """Mark as cancelled AND interrupt the in-flight await (LLM call).

        task.cancel() schedules CancelledError on the event loop, which
        propagates up from whatever await point the agent is blocked on.
        Safe to call from any thread (sets _must_cancel flag only).
        """
        super().cancel()
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()

    def start_polling(self):
        if self._poll_task is None:
            with self._tokens_lock:
                self._active_tokens.setdefault(str(self._session_id), set()).add(self)
            self._agent_task = asyncio.current_task()
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        from druppie.domain.common import SessionStatus

        while not self._cancelled:
            await asyncio.sleep(self._poll_interval)
            if self._cancelled:
                break
            try:
                from druppie.db.database import SessionLocal
                from druppie.db.models.session import Session as SessionModel

                db = SessionLocal()
                try:
                    session = db.query(SessionModel).filter(SessionModel.id == self._session_id).first()
                    if session and session.status == SessionStatus.PAUSED.value:
                        self.cancel()
                        return
                finally:
                    db.close()
            except Exception:
                pass

    async def cleanup(self):
        with self._tokens_lock:
            bucket = self._active_tokens.get(str(self._session_id))
            if bucket is not None:
                bucket.discard(self)
                if not bucket:
                    self._active_tokens.pop(str(self._session_id), None)
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass


class AgentLoopError(Exception):
    """Base error for agent runtime failures."""
    pass


class AgentCancelledError(AgentLoopError):
    """Raised when agent execution is cancelled via CancellationToken."""
    pass
