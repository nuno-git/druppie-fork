"""WebSocket route for session timeline event streaming.

Endpoint:
    GET /api/sessions/{session_id}/events

On connect the server immediately accepts the WebSocket, then waits
(up to 10 s) for an authentication message of the form:
    {"type":"auth","token":"<jwt>"}

After the token is validated and session access verified, the client
receives real-time timeline events.

Authentication flow:
    Client ──WebSocket──▶ FastAPI endpoint
                         1. accept()
                         2. await auth message (≤10 s)
                         3. validate JWT
                         4. verify session access
                         5. subscribe to SessionEventManager

The SessionEventManager broadcasts events from the orchestrator and
other services. The client receives JSON events like:
    {"type": "timeline_entry", "entry": {...}}
    {"type": "session_status", "session_id": "...", "status": "..."}
"""

import asyncio
import json
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from druppie.api.deps import get_user_roles
from druppie.core.auth import get_auth_service
from druppie.core.session_event_manager import get_event_manager
from druppie.db.database import SessionLocal
from druppie.repositories import SessionRepository, QuestionRepository

logger = structlog.get_logger()

router = APIRouter()

# Seconds to wait for the client to send the auth message
AUTH_TIMEOUT = 10
MAX_CONNECTIONS_PER_SESSION = 10
KEEPALIVE_TIMEOUT_SECONDS = 60


@router.websocket("/sessions/{session_id}/events")
async def session_events_ws(
    websocket: WebSocket,
    session_id: UUID,
):
    """WebSocket endpoint for real-time session timeline events.

    Authentication:
        After the WebSocket is accepted, the client must send a JSON
        auth message within 10 seconds:
            {"type":"auth","token":"<jwt>"}

    Events:
        timeline_entry — new or updated timeline entries
        session_status — session status changes

    The connection stays open until the client disconnects.
    """
    user = None
    db = None

    try:
        # Step 1: Accept immediately (no auth yet)
        await websocket.accept()

        # Step 2: Wait for auth message with timeout
        token = None
        try:
            async with asyncio.timeout(AUTH_TIMEOUT):
                raw = await websocket.receive_text()
                data = json.loads(raw)

                # Support direct auth message or ping-before-auth
                if data.get("type") == "auth":
                    token = data.get("token")
                else:
                    # Client sent something else first (e.g., ping).
                    # Wait one more message for auth.
                    raw2 = await websocket.receive_text()
                    data2 = json.loads(raw2)
                    if data2.get("type") == "auth":
                        token = data2.get("token")

        except asyncio.TimeoutError:
            await websocket.close(
                code=4001,
                reason="Authentication timeout — send {'type':'auth','token':'<jwt>'} within 10s",
            )
            return
        except (json.JSONDecodeError, KeyError, TypeError):
            await websocket.close(
                code=4001,
                reason="Invalid auth message — expected {'type':'auth','token':'<jwt>'}",
            )
            return

        if not token:
            await websocket.close(
                code=4001,
                reason="Missing token — expected {'type':'auth','token':'<jwt>'}",
            )
            return

        # Step 3: Validate JWT
        auth = get_auth_service()
        user = auth.validate_request(f"Bearer {token}")
        if not user:
            await websocket.close(code=4001, reason="Invalid authentication token")
            return

        user_id = UUID(user["sub"])
        user_roles = get_user_roles(user)
        is_admin = "admin" in user_roles

        # Step 4: Verify session access
        db = SessionLocal()
        try:
            from druppie.services import SessionService
            session_service = SessionService(
                SessionRepository(db),
                QuestionRepository(db),
            )
            if not session_service.check_access(session_id, user_id, user_roles):
                await websocket.close(code=4003, reason="Not authorized to access this session")
                return
        finally:
            db.close()
            db = None

        # Step 5: Enforce per-session connection cap
        event_manager = get_event_manager()
        current_count = event_manager.connection_count(session_id)
        if current_count >= MAX_CONNECTIONS_PER_SESSION:
            await websocket.close(
                code=1013,
                reason=f"Too many connections for this session (max {MAX_CONNECTIONS_PER_SESSION})",
            )
            return

        await websocket.send_text(json.dumps({"type": "auth_success"}))

        logger.info(
            "ws_session_events_connected",
            session_id=str(session_id),
            user_id=str(user_id),
        )

        event_manager = get_event_manager()
        await event_manager.connect(session_id, websocket)

        try:
            while True:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=KEEPALIVE_TIMEOUT_SECONDS,
                )
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif data == "pong":
                    pass
                else:
                    # Ignore other client messages
                    pass
        except asyncio.TimeoutError:
            await websocket.close(code=1001, reason="Keepalive timeout")
            logger.info(
                "ws_session_events_timeout",
                session_id=str(session_id),
                user_id=str(user_id),
            )
        except WebSocketDisconnect:
            logger.info(
                "ws_session_events_disconnected",
                session_id=str(session_id),
                user_id=str(user_id),
            )
        finally:
            await event_manager.disconnect(session_id, websocket)

    except WebSocketDisconnect:
        # Client disconnected before auth completed or during normal operation
        logger.info(
            "ws_session_events_disconnected",
            session_id=str(session_id),
            user_id=str(user_id) if user else None,
        )
    except Exception as e:
        logger.error(
            "ws_session_events_error",
            session_id=str(session_id),
            error=str(e),
            exc_info=True,
        )
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass
    finally:
        if db is not None:
            db.close()
