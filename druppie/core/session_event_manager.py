"""WebSocket event manager for session timeline updates.

Manages WebSocket connections per session and broadcasts real-time events.
Uses Redis pub/sub for cross-process broadcasting so events reach clients
connected to any backend replica.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from fastapi import WebSocket

if TYPE_CHECKING:
    from druppie.domain.agent_run import AgentRunSummary
    from druppie.domain.session import Message

logger = structlog.get_logger()

# Redis connection settings (optional — falls back to in-process-only if absent)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


try:
    import redis.asyncio as redis

    _redis_available = True
except ImportError:
    _redis_available = False
    redis = None  # type: ignore[assignment]


class SessionEventManager:
    """Manages WebSocket connections per session for real-time event streaming.

    Broadcasts events locally and, when Redis is available, publishes to a
    Redis channel so all backend replicas receive the event and can
    broadcast it to their local WebSocket clients.
    """

    def __init__(self) -> None:
        self._instance_id: str = str(uuid4())
        self._connections: dict[UUID, list[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._subscriber_task: asyncio.Task | None = None

    async def _ensure_redis(self) -> None:
        """Lazy-connect to Redis on first broadcast.

        Connection failures are logged but not fatal — the manager falls
        back to local-only broadcasting.
        """
        if self._redis is not None or not _redis_available:
            return
        try:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            self._subscriber_task = asyncio.create_task(
                self._redis_subscriber_loop(), name="redis-event-subscriber"
            )
            logger.info("redis_event_manager_connected", url=REDIS_URL)
        except Exception as exc:
            logger.warning("redis_connect_failed", error=str(exc))
            self._redis = None

    async def _redis_subscriber_loop(self) -> None:
        """Background task: receive Redis messages and broadcast locally."""
        if self._pubsub is None:
            return
        try:
            async with self._pubsub as ps:
                await ps.psubscribe("session:*")
                async for message in ps.listen():
                    if message["type"] != "pmessage":
                        continue
                    try:
                        data = json.loads(message["data"])
                        # Skip messages that originated from this instance —
                        # broadcast() already called _broadcast_local() for
                        # those.  Other replicas (different instance_id) still
                        # process the message normally.
                        if data.get("origin_instance_id") == self._instance_id:
                            continue
                        session_id = UUID(data["session_id"])
                        event = data["event"]
                        await self._broadcast_local(session_id, event)
                    except (json.JSONDecodeError, KeyError, TypeError) as exc:
                        logger.warning("redis_malformed_message", error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("redis_subscriber_error", error=str(exc))
        finally:
            self._redis = None
            self._pubsub = None
            logger.info("redis_subscriber_stopped_cleared_state")

    async def shutdown(self) -> None:
        """Graceful shutdown: cancel subscriber task and close Redis."""
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self._pubsub = None

    async def _broadcast_local(
        self, session_id: UUID, event: dict[str, Any]
    ) -> None:
        """Send event to locally-connected WebSocket clients only.

        Copies the connection list under the lock, then sends outside it
        so one slow client can't stall delivery to other sessions.
        """
        async with self._lock:
            conns = list(self._connections.get(session_id) or [])

        if not conns:
            return

        message = json.dumps(event, default=str)
        alive_ids: set[int] = set()

        for ws in conns:
            try:
                await ws.send_text(message)
                alive_ids.add(id(ws))
            except Exception:
                logger.debug(
                    "ws_send_failed_removing",
                    session_id=str(session_id),
                )

        async with self._lock:
            current = self._connections.get(session_id)
            if current:
                new_current = [ws for ws in current if id(ws) in alive_ids]
                if new_current:
                    self._connections[session_id] = new_current
                else:
                    del self._connections[session_id]
                    logger.debug(
                        "ws_all_connections_dropped",
                        session_id=str(session_id),
                    )

    def connection_count(self, session_id: UUID) -> int:
        """Return the number of WebSocket connections for a session."""
        return len(self._connections.get(session_id) or [])

    async def connect(self, session_id: UUID, websocket: WebSocket) -> None:
        """Register a WebSocket connection for a session."""
        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = []
            self._connections[session_id].append(websocket)
            logger.debug(
                "ws_connected",
                session_id=str(session_id),
                total_connections=len(self._connections[session_id]),
            )

    async def disconnect(self, session_id: UUID, websocket: WebSocket) -> None:
        """Remove a WebSocket connection for a session."""
        async with self._lock:
            conns = self._connections.get(session_id)
            if conns:
                conns[:] = [ws for ws in conns if ws is not websocket]
                if not conns:
                    del self._connections[session_id]
                    logger.debug(
                        "ws_last_disconnected",
                        session_id=str(session_id),
                    )

    async def broadcast(self, session_id: UUID, event: dict[str, Any]) -> None:
        """Broadcast an event to all clients for a session.

        Sends to locally-connected clients immediately and publishes
        the event to Redis so other backend replicas can also broadcast
        to their clients.
        """
        await self._ensure_redis()
        await self._broadcast_local(session_id, event)

        if self._redis is not None:
            try:
                await self._redis.publish(
                    f"session:{session_id}",
                    json.dumps(
                        {
                            "session_id": str(session_id),
                            "event": event,
                            "origin_instance_id": self._instance_id,
                        },
                        default=str,
                    ),
                )
            except Exception as exc:
                logger.warning("redis_publish_failed", error=str(exc))

    async def broadcast_message_created(
        self,
        session_id: UUID,
        message: "Message",  # type: ignore # noqa: F821
    ) -> None:
        """Broadcast when a new message is created in the timeline."""
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": {
                "type": "message",
                "sequence_number": message.sequence_number,
                "timestamp": message.created_at or datetime.now(timezone.utc),
                "message": {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "agent_id": message.agent_id,
                    "agent_run_id": str(message.agent_run_id) if message.agent_run_id else None,
                    "sequence_number": message.sequence_number,
                    "created_at": message.created_at or datetime.now(timezone.utc),
                    "attachments": [],
                },
            },
        })

    async def broadcast_agent_run_created(
        self,
        session_id: UUID,
        agent_run: "AgentRunSummary",  # type: ignore # noqa: F821
    ) -> None:
        """Broadcast when a new agent run is created."""
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": {
                "type": "agent_run",
                "sequence_number": agent_run.sequence_number,
                "timestamp": agent_run.started_at or datetime.now(timezone.utc),
                "agent_run": agent_run.model_dump(),
            },
        })

    async def broadcast_agent_run_updated(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Broadcast when an agent run status changes."""
        entry: dict[str, Any] = {
            "type": "agent_run_update",
            "id": str(agent_run_id),
            "status": status,
        }
        if error_message:
            entry["error_message"] = error_message
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": entry,
        })

    async def broadcast_approval_created(
        self,
        session_id: UUID,
        approval_id: UUID,
        tool_name: str,
        required_role: str,
    ) -> None:
        """Broadcast when a new approval is created."""
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": {
                "type": "approval",
                "id": str(approval_id),
                "tool_name": tool_name,
                "required_role": required_role,
            },
        })

    async def broadcast_question_created(
        self,
        session_id: UUID,
        question_id: UUID,
        question_text: str,
        question_type: str = "text",
    ) -> None:
        """Broadcast when a new HITL question is created."""
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": {
                "type": "question",
                "id": str(question_id),
                "question": question_text,
                "question_type": question_type,
            },
        })

    async def broadcast_session_status(
        self,
        session_id: UUID,
        status: str,
    ) -> None:
        """Broadcast when session status changes."""
        await self.broadcast(session_id, {
            "type": "session_status",
            "session_id": str(session_id),
            "status": status,
        })


# Singleton instance
_event_manager: SessionEventManager | None = None


def get_event_manager() -> SessionEventManager:
    """Get the singleton SessionEventManager instance."""
    global _event_manager
    if _event_manager is None:
        _event_manager = SessionEventManager()
    return _event_manager


def reset_event_manager() -> None:
    """Reset the singleton for test isolation.

    Clears all connection state so tests don't leak WebSocket
    connections between test cases. Mirrors the pattern used by
    reset_tool_registry().
    """
    global _event_manager
    _event_manager = None
