"""WebSocket event manager for session timeline updates.

Thread-safe manager that maintains WebSocket connections per session
and broadcasts events to all connected clients.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()


class SessionEventManager:
    """Manages WebSocket connections per session for real-time event streaming.

    Thread-safe: uses asyncio.Lock for connection list mutations.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

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
        """Send a JSON event to all connected clients for a session.

        Silently removes closed/stale connections.
        """
        async with self._lock:
            conns = self._connections.get(session_id)
            if not conns:
                return

            message = json.dumps(event, default=str)
            alive: list[WebSocket] = []

            for ws in conns:
                try:
                    await ws.send_text(message)
                    alive.append(ws)
                except Exception:
                    logger.debug(
                        "ws_send_failed_removing",
                        session_id=str(session_id),
                    )

            if len(alive) != len(conns):
                self._connections[session_id] = alive
                if not alive:
                    del self._connections[session_id]
                    logger.debug(
                        "ws_all_connections_dropped",
                        session_id=str(session_id),
                    )

    async def broadcast_message_created(
        self,
        session_id: UUID,
        message_id: UUID,
        sequence_number: int,
        role: str,
        agent_id: str | None = None,
    ) -> None:
        """Broadcast when a new message is created in the timeline."""
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": {
                "type": "message",
                "id": str(message_id),
                "sequence_number": sequence_number,
                "role": role,
                "agent_id": agent_id,
            },
        })

    async def broadcast_agent_run_created(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        agent_id: str,
        sequence_number: int,
        status: str,
        planned_prompt: str | None = None,
        parent_run_id: UUID | None = None,
    ) -> None:
        """Broadcast when a new agent run is created."""
        entry: dict[str, Any] = {
            "type": "agent_run",
            "id": str(agent_run_id),
            "sequence_number": sequence_number,
            "agent_id": agent_id,
            "status": status,
        }
        if planned_prompt:
            entry["planned_prompt"] = planned_prompt
        if parent_run_id:
            entry["parent_run_id"] = str(parent_run_id)
        await self.broadcast(session_id, {
            "type": "timeline_entry",
            "entry": entry,
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
