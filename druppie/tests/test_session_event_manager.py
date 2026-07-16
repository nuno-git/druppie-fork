"""Tests for SessionEventManager.

Covers local fan-out, Redis pub/sub integration, and graceful fallback.
"""

import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

import pytest

from druppie.core.session_event_manager import SessionEventManager, get_event_manager, reset_event_manager


@pytest.fixture(autouse=True)
def fresh_event_manager():
    """Reset singleton between tests."""
    reset_event_manager()
    yield
    reset_event_manager()


@pytest.fixture
def event_manager():
    return get_event_manager()


@pytest.fixture
def mock_ws():
    """Return a mock WebSocket with async send_text."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.accept = AsyncMock()
    return ws


class TestLocalFanout:
    """Broadcast to locally-connected clients."""

    @pytest.mark.asyncio
    async def test_broadcast_to_single_client(self, event_manager, mock_ws):
        session_id = uuid4()
        await event_manager.connect(session_id, mock_ws)
        await event_manager.broadcast(session_id, {"type": "test", "val": 1})
        mock_ws.send_text.assert_awaited_once()
        sent = json.loads(mock_ws.send_text.await_args[0][0])
        assert sent["type"] == "test"

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self, event_manager):
        session_id = uuid4()
        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        await event_manager.connect(session_id, ws1)
        await event_manager.connect(session_id, ws2)
        await event_manager.broadcast(session_id, {"type": "test"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, event_manager, mock_ws):
        session_id = uuid4()
        await event_manager.connect(session_id, mock_ws)
        await event_manager.disconnect(session_id, mock_ws)
        await event_manager.broadcast(session_id, {"type": "test"})
        mock_ws.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_noop(self, event_manager, mock_ws):
        session_id = uuid4()
        # No connection was ever added
        await event_manager.disconnect(session_id, mock_ws)

    @pytest.mark.asyncio
    async def test_broadcast_drops_stale_connections(self, event_manager):
        session_id = uuid4()
        good = MagicMock()
        good.send_text = AsyncMock()
        bad = MagicMock()
        bad.send_text = AsyncMock(side_effect=RuntimeError("closed"))

        await event_manager.connect(session_id, good)
        await event_manager.connect(session_id, bad)
        await event_manager.broadcast(session_id, {"type": "test"})

        # good still receives despite bad failing
        good.send_text.assert_awaited_once()

        # bad should have been removed; next broadcast doesn't include it
        bad.send_text.reset_mock()
        await event_manager.broadcast(session_id, {"type": "test2"})
        bad.send_text.assert_not_awaited()


class TestRedisPublish:
    """Redis pub/sub integration."""

    @pytest.mark.asyncio
    async def test_publishes_to_redis_when_available(self, event_manager):
        with patch("druppie.core.session_event_manager.redis") as mock_redis_mod:
            mock_redis = AsyncMock()
            mock_redis_mod.from_url = MagicMock(return_value=mock_redis)
            mock_pubsub = AsyncMock()
            mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

            session_id = uuid4()
            ws = MagicMock()
            ws.send_text = AsyncMock()

            await event_manager.connect(session_id, ws)
            await event_manager.broadcast(session_id, {"type": "test"})

            # Ensure Redis publish was called with the right channel
            mock_redis.publish.assert_awaited_once()
            channel = mock_redis.publish.await_args[0][0]
            payload = json.loads(mock_redis.publish.await_args[0][1])
            assert channel == f"session:{session_id}"
            assert payload["session_id"] == str(session_id)
            assert payload["event"]["type"] == "test"

    @pytest.mark.asyncio
    async def test_graceful_fallback_when_redis_import_fails(self, event_manager):
        """If redis module is unavailable, broadcast still works locally."""
        with patch("druppie.core.session_event_manager._redis_available", False):
            session_id = uuid4()
            ws = MagicMock()
            ws.send_text = AsyncMock()
            await event_manager.connect(session_id, ws)
            await event_manager.broadcast(session_id, {"type": "test"})
            ws.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_publish_failure_logs_warning(self, event_manager):
        with patch("druppie.core.session_event_manager.redis") as mock_redis_mod:
            mock_redis = AsyncMock()
            mock_redis.publish = AsyncMock(side_effect=ConnectionError("redis down"))
            mock_redis_mod.from_url = MagicMock(return_value=mock_redis)
            mock_pubsub = AsyncMock()
            mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

            session_id = uuid4()
            ws = MagicMock()
            ws.send_text = AsyncMock()
            await event_manager.connect(session_id, ws)

            # Should not raise — local broadcast still succeeds
            await event_manager.broadcast(session_id, {"type": "test"})
            ws.send_text.assert_awaited_once()


class TestResetEventManager:
    """Test isolation helper used by other tests."""

    @pytest.mark.asyncio
    async def test_reset_clears_connections(self):
        mgr = get_event_manager()
        session_id = uuid4()
        ws = MagicMock()
        ws.send_text = AsyncMock()
        await mgr.connect(session_id, ws)

        reset_event_manager()

        mgr2 = get_event_manager()
        assert mgr2 is not mgr
        await mgr2.broadcast(session_id, {"type": "test"})
        ws.send_text.assert_not_awaited()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()
        await mgr2.connect(session_id, ws2)
        await mgr2.broadcast(session_id, {"type": "test2"})
        ws2.send_text.assert_awaited_once()
