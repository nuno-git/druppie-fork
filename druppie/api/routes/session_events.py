"""WebSocket route for session timeline event streaming.

Endpoint:
    GET /api/sessions/{session_id}/events?token=<jwt>

On connect, authenticates via the token query parameter, verifies session
access, and subscribes to real-time timeline events via a persistent
WebSocket connection.

Architecture:
    Client ──WebSocket──▶ FastAPI endpoint
                              │
                              ├─► authenticate via token
                              ├─► verify session access
                              └─► subscribe to SessionEventManager

The SessionEventManager broadcasts events from the orchestrator and
other services. The client receives JSON events like:
    {"type": "timeline_entry", "entry": {...}}
    {"type": "session_status", "session_id": "...", "status": "..."}
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from druppie.api.deps import get_user_roles
from druppie.core.auth import get_auth_service
from druppie.core.session_event_manager import get_event_manager
from druppie.db.database import SessionLocal
from druppie.repositories import SessionRepository

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/sessions/{session_id}/events")
async def session_events_ws(
    websocket: WebSocket,
    session_id: UUID,
    token: str = Query(..., description="JWT token (same Bearer token used for HTTP)"),
):
    """WebSocket endpoint for real-time session timeline events.

    Authentication:
        Pass the JWT token as the `token` query parameter.
        Same token as the Authorization: Bearer header used for HTTP endpoints.

    Events:
        timeline_entry — new or updated timeline entries (messages, agent runs)
        session_status — session status changes

    The connection stays open until the client disconnects or the session
    no longer exists. Clients should reconnect on disconnect.
    """
    user = None
    db = None
    try:
        # Step 1: Authenticate via token query parameter
        auth = get_auth_service()
        user = auth.validate_request(f"Bearer {token}")
        if not user:
            await websocket.close(code=4001, reason="Invalid or missing authentication token")
            return

        user_id = UUID(user["sub"])
        user_roles = get_user_roles(user)
        is_admin = "admin" in user_roles

        # Step 2: Verify session access via SessionService (DRY with REST routes)
        db = SessionLocal()
        try:
            from druppie.services import SessionService, SessionRepository, QuestionRepository
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

        # Step 3: Accept the WebSocket and subscribe
        await websocket.accept()
        logger.info(
            "ws_session_events_connected",
            session_id=str(session_id),
            user_id=str(user_id),
        )

        event_manager = get_event_manager()
        await event_manager.connect(session_id, websocket)

        try:
            # Keep the connection alive until the client disconnects
            while True:
                # Receive ping/pong or disconnect signals
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            logger.info(
                "ws_session_events_disconnected",
                session_id=str(session_id),
                user_id=str(user_id),
            )
        finally:
            await event_manager.disconnect(session_id, websocket)

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
