"""Tests for the WebSocket session events endpoint.

Covers first-message auth, access control, and basic connectivity.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from fastapi import FastAPI
from fastapi.testclient import TestClient

from druppie.api.routes.session_events import (
    router as events_router,
    MAX_CONNECTIONS_PER_SESSION,
    KEEPALIVE_TIMEOUT_SECONDS,
)
from druppie.core.session_event_manager import get_event_manager, reset_event_manager


@pytest.fixture(autouse=True)
def reset_event_mgr():
    """Reset the singleton event manager between tests."""
    reset_event_manager()
    yield
    reset_event_manager()


@pytest.fixture
def mock_auth_service():
    """Mock auth service that accepts/rejects tokens."""
    svc = MagicMock()
    svc.validate_request = MagicMock(return_value=None)
    return svc


@pytest.fixture
def mock_session_service():
    """Mock session service for access checks."""
    svc = MagicMock()
    svc.check_access = MagicMock(return_value=True)
    return svc


@pytest.fixture
def client(mock_auth_service, mock_session_service):
    app = FastAPI()
    app.include_router(events_router)

    with patch("druppie.api.routes.session_events.get_auth_service", return_value=mock_auth_service), \
         patch("druppie.api.routes.session_events.get_user_roles", return_value=["user"]), \
         patch("druppie.services.SessionService", return_value=mock_session_service), \
         patch("druppie.api.routes.session_events.SessionLocal"):
        yield TestClient(app)


class TestWebSocketAuth:
    """Test first-message authentication flow."""

    def test_valid_token_receives_auth_success(self, client, mock_auth_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(
            return_value={"sub": str(uuid4()), "realm_access": {"roles": ["user"]}}
        )

        with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "auth_success"

    def test_invalid_token_gets_4001(self, client, mock_auth_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(return_value=None)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": "invalid-token"}))
                ws.receive_text()
        assert exc_info.value.code == 4001

    def test_unauthorized_session_gets_4003(self, client, mock_auth_service, mock_session_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(
            return_value={"sub": str(uuid4()), "realm_access": {"roles": ["user"]}}
        )
        mock_session_service.check_access = MagicMock(return_value=False)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
                ws.receive_text()
        assert exc_info.value.code == 4003

    def test_missing_auth_message_times_out(self, client):
        """If no auth message is sent within the timeout window, server closes with 4001."""
        session_id = str(uuid4())
        with patch("druppie.api.routes.session_events.AUTH_TIMEOUT", 0.1):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
                    ws.receive_text()
        assert exc_info.value.code == 4001

    def test_malformed_auth_message_gets_4001(self, client):
        session_id = str(uuid4())
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
                ws.send_text("not-json")
                ws.receive_text()
        assert exc_info.value.code == 4001


class TestWebSocketPing:
    """Test ping/pong keepalive after auth."""

    def test_ping_receives_pong(self, client, mock_auth_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(
            return_value={"sub": str(uuid4()), "realm_access": {"roles": ["user"]}}
        )

        with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
            # consume auth_success
            ws.receive_text()
            # send ping
            ws.send_text("ping")
            msg = ws.receive_text()
            data = json.loads(msg)
            assert data["type"] == "pong"


class TestWebSocketConnectionCap:
    """Test per-session concurrent connection limit."""

    def test_too_many_connections_gets_rejected(self, client, mock_auth_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(
            return_value={"sub": str(uuid4()), "realm_access": {"roles": ["user"]}}
        )

        VALID = 2
        sockets = []
        for _ in range(VALID):
            ws = client.websocket_connect(f"/sessions/{session_id}/events")
            cm = ws.__enter__()
            cm.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
            cm.receive_text()
            sockets.append((ws, cm))

        for _ in range(MAX_CONNECTIONS_PER_SESSION - VALID):
            ws = client.websocket_connect(f"/sessions/{session_id}/events")
            cm = ws.__enter__()
            cm.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
            cm.receive_text()
            sockets.append((ws, cm))

        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws = client.websocket_connect(f"/sessions/{session_id}/events")
            cm = ws.__enter__()
            cm.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
            cm.receive_text()

        assert exc_info.value.code == 1013

        for ws, cm in sockets:
            try:
                cm.close()
            except Exception:
                pass
            ws.__exit__(None, None, None)


class TestWebSocketKeepalive:
    """Test server-side keepalive timeout."""

    def test_no_activity_closes_connection(self, client, mock_auth_service):
        session_id = str(uuid4())
        mock_auth_service.validate_request = MagicMock(
            return_value={"sub": str(uuid4()), "realm_access": {"roles": ["user"]}}
        )

        with patch("druppie.api.routes.session_events.KEEPALIVE_TIMEOUT_SECONDS", 0.1):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(f"/sessions/{session_id}/events") as ws:
                    ws.send_text(json.dumps({"type": "auth", "token": "valid-token"}))
                    ws.receive_text()
                    ws.receive_text()
            assert exc_info.value.code == 1001
