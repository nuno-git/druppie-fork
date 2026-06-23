"""Tests for druppie.agent_runtime.events."""

from unittest.mock import MagicMock

from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.types import AgentEvent


class TestEventEmitter:
    def test_emit_records_event(self):
        emitter = EventEmitter()
        event = AgentEvent.now("test", {"key": "value"})
        emitter.emit(event)
        assert len(emitter.get_events()) == 1
        assert emitter.get_events()[0] is event

    def test_emit_fires_callbacks(self):
        emitter = EventEmitter()
        callback = MagicMock()
        emitter.on(callback)
        event = AgentEvent.now("test")
        emitter.emit(event)
        callback.assert_called_once_with(event)

    def test_emit_multiple_callbacks(self):
        emitter = EventEmitter()
        cb1 = MagicMock()
        cb2 = MagicMock()
        emitter.on(cb1)
        emitter.on(cb2)
        event = AgentEvent.now("test")
        emitter.emit(event)
        cb1.assert_called_once_with(event)
        cb2.assert_called_once_with(event)

    def test_emit_no_callbacks(self):
        emitter = EventEmitter()
        event = AgentEvent.now("test")
        emitter.emit(event)
        assert len(emitter.get_events()) == 1

    def test_get_events_returns_all(self):
        emitter = EventEmitter()
        e1 = AgentEvent.now("event1")
        e2 = AgentEvent.now("event2")
        e3 = AgentEvent.now("event3")
        emitter.emit(e1)
        emitter.emit(e2)
        emitter.emit(e3)
        events = emitter.get_events()
        assert len(events) == 3
        assert events[0] is e1
        assert events[1] is e2
        assert events[2] is e3

    def test_get_events_immutable(self):
        emitter = EventEmitter()
        emitter.emit(AgentEvent.now("test"))
        returned = emitter.get_events()
        returned.clear()
        assert len(emitter.get_events()) == 1

    def test_on_registers_callback(self):
        emitter = EventEmitter()
        cb = MagicMock()
        emitter.on(cb)
        assert cb in emitter._callbacks

    def test_off_removes_callback(self):
        emitter = EventEmitter()
        cb = MagicMock()
        emitter.on(cb)
        emitter.off(cb)
        assert cb not in emitter._callbacks

    def test_off_nonexistent_callback(self):
        emitter = EventEmitter()
        emitter.off(lambda e: None)

    def test_callback_exception_isolation(self):
        emitter = EventEmitter()
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        good_cb = MagicMock()
        emitter.on(bad_cb)
        emitter.on(good_cb)
        event = AgentEvent.now("test")
        emitter.emit(event)
        bad_cb.assert_called_once_with(event)
        good_cb.assert_called_once_with(event)

    def test_event_ordering(self):
        emitter = EventEmitter()
        types = ["a", "b", "c", "d"]
        for t in types:
            emitter.emit(AgentEvent.now(t))
        events = emitter.get_events()
        assert [e.type for e in events] == types
