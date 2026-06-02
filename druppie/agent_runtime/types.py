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
    """CancellationToken that polls the DB for session PAUSED status."""

    def __init__(self, db_session_factory, session_id, poll_interval: float = 2.0):
        super().__init__()
        self._db_factory = db_session_factory
        self._session_id = session_id
        self._poll_interval = poll_interval
        self._poll_task: asyncio.Task | None = None

    def start_polling(self):
        """Start background polling task."""
        if self._poll_task is None:
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
                pass  # Don't crash the polling loop

    async def cleanup(self):
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
