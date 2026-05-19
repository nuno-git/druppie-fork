"""Event tracking and real-time callback dispatch for agent execution."""

from __future__ import annotations

from typing import Callable

from druppie.agent_runtime.types import AgentEvent


class EventEmitter:
    """Collects events in memory and fires real-time callbacks.

    Events are stored in order and can be retrieved after execution.
    Callbacks fire synchronously when emit() is called.
    """

    def __init__(self) -> None:
        self._events: list[AgentEvent] = []
        self._callbacks: list[Callable[[AgentEvent], None]] = []

    def on(self, callback: Callable[[AgentEvent], None]) -> None:
        """Register a real-time callback. Called on every emit()."""
        self._callbacks.append(callback)

    def off(self, callback: Callable[[AgentEvent], None]) -> None:
        """Unregister a callback. No-op if not registered."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def emit(self, event: AgentEvent) -> None:
        """Record event and dispatch to all registered callbacks.

        Callbacks are called in registration order. If a callback raises,
        it is caught and the remaining callbacks still fire.
        """
        self._events.append(event)
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception:
                pass

    def get_events(self) -> list[AgentEvent]:
        """Return a copy of all collected events in emission order."""
        return list(self._events)
