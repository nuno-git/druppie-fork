"""WebSocket service for real-time updates.

Provides real-time communication for:
- Workflow events during execution
- Approval status updates
- Session state changes
- HITL question/answer flow
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()


class ConnectionManager:
    """Manages WebSocket connections and broadcasting."""

    # Maximum number of missed events to store per session
    MAX_MISSED_EVENTS_PER_SESSION = 100

    def __init__(self):
        # Map of session_id -> list of websockets
        self.session_connections: dict[str, list[WebSocket]] = defaultdict(list)
        # Map of role -> list of websockets (for approval broadcasts)
        self.role_connections: dict[str, list[WebSocket]] = defaultdict(list)
        # All active connections
        self.active_connections: list[WebSocket] = []
        # Buffer for missed events (when WebSocket broadcast fails)
        # Map of session_id -> list of events
        self.missed_events: dict[str, list[dict]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, session_id: str | None = None):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        if session_id:
            self.session_connections[session_id].append(websocket)
        logger.info("websocket_connected", total_connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket, session_id: str | None = None):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if session_id and websocket in self.session_connections[session_id]:
            self.session_connections[session_id].remove(websocket)
        # Remove from all role connections
        for role in list(self.role_connections.keys()):
            if websocket in self.role_connections[role]:
                self.role_connections[role].remove(websocket)
        logger.info("websocket_disconnected", total_connections=len(self.active_connections))

    def join_session(self, websocket: WebSocket, session_id: str):
        """Join a session room for targeted updates."""
        if websocket not in self.session_connections[session_id]:
            self.session_connections[session_id].append(websocket)
        logger.debug("websocket_joined_session", session_id=session_id)

    def join_approval_rooms(self, websocket: WebSocket, roles: list[str]):
        """Join approval rooms for the given roles."""
        for role in roles:
            if websocket not in self.role_connections[role]:
                self.role_connections[role].append(websocket)
        logger.debug("websocket_joined_roles", roles=roles)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error("websocket_send_error", error=str(e), exc_info=True)

    async def broadcast_to_session(self, session_id: str, message: dict):
        """Broadcast a message to all connections in a session.

        If no connections exist or all broadcasts fail, the event is stored
        in the missed events buffer for later retrieval.
        """
        connections = self.session_connections.get(session_id, [])
        if not connections:
            # No connections - store for later retrieval
            self.store_missed_event(session_id, message)
            return

        success_count = 0
        for websocket in connections:
            try:
                await websocket.send_json(message)
                success_count += 1
            except Exception as e:
                logger.error("websocket_broadcast_session_error", session_id=session_id, error=str(e), exc_info=True)

        # If all broadcasts failed, store the event
        if success_count == 0:
            self.store_missed_event(session_id, message)

    async def broadcast_to_roles(self, roles: list[str], message: dict):
        """Broadcast a message to all connections with the given roles."""
        sent_to = set()  # Avoid duplicates
        for role in roles:
            for websocket in self.role_connections.get(role, []):
                if id(websocket) not in sent_to:
                    try:
                        await websocket.send_json(message)
                        sent_to.add(id(websocket))
                    except Exception as e:
                        logger.error("websocket_broadcast_role_error", role=role, error=str(e), exc_info=True)

    async def broadcast_all(self, message: dict):
        """Broadcast a message to all active connections."""
        for websocket in self.active_connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error("websocket_broadcast_all_error", error=str(e), exc_info=True)

    def store_missed_event(self, session_id: str, event: dict):
        """Store an event that failed to broadcast for later retrieval.

        Events are stored in a bounded buffer (MAX_MISSED_EVENTS_PER_SESSION)
        to prevent memory exhaustion.
        """
        events = self.missed_events[session_id]
        if len(events) >= self.MAX_MISSED_EVENTS_PER_SESSION:
            # Remove oldest event to make room
            events.pop(0)
            logger.warning(
                "missed_events_buffer_full",
                session_id=session_id,
                action="dropping_oldest",
            )
        events.append(event)
        logger.debug(
            "missed_event_stored",
            session_id=session_id,
            total_events=len(events),
        )

    def get_missed_events(self, session_id: str, clear: bool = True) -> list[dict]:
        """Retrieve missed events for a session.

        Args:
            session_id: The session to get events for
            clear: If True, clear the events after retrieval (default: True)

        Returns:
            List of missed events
        """
        events = list(self.missed_events.get(session_id, []))
        if clear and session_id in self.missed_events:
            del self.missed_events[session_id]
        return events

    def clear_missed_events(self, session_id: str):
        """Clear all missed events for a session."""
        if session_id in self.missed_events:
            del self.missed_events[session_id]

    def cleanup_stale_sessions(self) -> int:
        """Clean up stale session data with no active connections.

        Removes:
        - Session connection entries with empty connection lists
        - Missed events for sessions with no connections

        Returns:
            Number of sessions cleaned up
        """
        cleaned = 0

        # Clean empty session connections
        empty_sessions = [
            session_id
            for session_id, connections in self.session_connections.items()
            if not connections
        ]
        for session_id in empty_sessions:
            del self.session_connections[session_id]
            cleaned += 1

        # Clean missed events for sessions that no longer exist
        # and have been orphaned (no active connections)
        orphaned_missed = [
            session_id
            for session_id in self.missed_events.keys()
            if session_id not in self.session_connections
        ]
        for session_id in orphaned_missed:
            event_count = len(self.missed_events[session_id])
            del self.missed_events[session_id]
            logger.info(
                "cleaned_orphaned_missed_events",
                session_id=session_id,
                event_count=event_count,
            )

        if cleaned > 0:
            logger.info("cleanup_stale_sessions", cleaned_count=cleaned)

        return cleaned

    def get_stats(self) -> dict:
        """Get connection manager statistics for monitoring.

        Returns:
            Dictionary with connection and buffer statistics
        """
        total_missed_events = sum(
            len(events) for events in self.missed_events.values()
        )
        return {
            "active_connections": len(self.active_connections),
            "session_count": len(self.session_connections),
            "role_room_count": len(self.role_connections),
            "missed_events_sessions": len(self.missed_events),
            "missed_events_total": total_missed_events,
            "max_missed_per_session": self.MAX_MISSED_EVENTS_PER_SESSION,
        }


# Singleton connection manager
manager = ConnectionManager()


# Event types
class EventType:
    """WebSocket event types."""

    # Connection events
    CONNECTED = "connected"

    # Session events
    SESSION_UPDATED = "session_updated"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    SESSION_PAUSED = "session_paused"

    # Workflow events (during execution)
    WORKFLOW_EVENT = "workflow_event"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"

    # Agent events
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    # HITL events
    QUESTION_PENDING = "question_pending"
    QUESTION_ANSWERED = "question_answered"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"

    # Legacy event types (for backwards compatibility)
    TASK_APPROVED = "task_approved"
    TASK_REJECTED = "task_rejected"
    PLAN_UPDATED = "plan_updated"


async def handle_websocket(websocket: WebSocket, session_id: str | None = None):
    """Handle a WebSocket connection.

    This is the main entry point for WebSocket connections.
    Clients can send JSON messages to:
    - join_session: {"type": "join_session", "session_id": "xxx"}
    - join_approvals: {"type": "join_approvals", "roles": ["admin", "developer"]}
    """
    await manager.connect(websocket, session_id)

    try:
        # Send confirmation
        await manager.send_personal(
            websocket,
            {
                "type": EventType.CONNECTED,
                "message": "Connected to Druppie WebSocket",
                "session_id": session_id,
            },
        )

        # Handle incoming messages
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "join_session":
                new_session_id = data.get("session_id")
                if new_session_id:
                    manager.join_session(websocket, new_session_id)
                    await manager.send_personal(
                        websocket,
                        {"type": "joined_session", "session_id": new_session_id},
                    )

            elif msg_type == "join_approvals":
                roles = data.get("roles", [])
                if roles:
                    manager.join_approval_rooms(websocket, roles)
                    await manager.send_personal(
                        websocket,
                        {"type": "joined_approvals", "roles": roles},
                    )

            elif msg_type == "ping":
                await manager.send_personal(websocket, {"type": "pong"})

            else:
                logger.warning("websocket_unknown_message_type", msg_type=msg_type)

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error("websocket_error", session_id=session_id, error=str(e), exc_info=True)
        manager.disconnect(websocket, session_id)


# Helper functions for broadcasting events
async def emit_workflow_event(session_id: str, event: dict):
    """Emit a workflow event to session subscribers."""
    await manager.broadcast_to_session(
        session_id,
        {
            "type": EventType.WORKFLOW_EVENT,
            "session_id": session_id,
            "event": event,
        },
    )


async def emit_session_update(session_id: str, status: str, data: dict | None = None):
    """Emit a session status update."""
    await manager.broadcast_to_session(
        session_id,
        {
            "type": EventType.SESSION_UPDATED,
            "session_id": session_id,
            "status": status,
            "data": data or {},
        },
    )


async def emit_approval_request(
    approval_id: str,
    session_id: str,
    tool_name: str,
    required_roles: list[str],
    details: dict,
):
    """Emit an approval request to relevant role subscribers."""
    message = {
        "type": EventType.APPROVAL_REQUESTED,
        "approval_id": approval_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "required_roles": required_roles,
        "details": details,
    }
    # Broadcast to session
    await manager.broadcast_to_session(session_id, message)
    # Also broadcast to role rooms
    await manager.broadcast_to_roles(required_roles, message)


async def emit_approval_decision(
    approval_id: str,
    session_id: str,
    approved: bool,
    approver_id: str,
    approver_role: str,
):
    """Emit an approval decision."""
    event_type = EventType.APPROVAL_APPROVED if approved else EventType.APPROVAL_REJECTED
    # Also emit legacy event type for backwards compatibility
    legacy_type = EventType.TASK_APPROVED if approved else EventType.TASK_REJECTED

    message = {
        "type": event_type,
        "approval_id": approval_id,
        "session_id": session_id,
        "approved": approved,
        "approver_id": approver_id,
        "approver_role": approver_role,
    }

    await manager.broadcast_to_session(session_id, message)

    # Send legacy event
    await manager.broadcast_to_session(
        session_id,
        {
            "type": legacy_type,
            "id": approval_id,
            "status": "approved" if approved else "rejected",
            "approver_id": approver_id,
            "approver_role": approver_role,
        },
    )


async def emit_question_pending(
    question_id: str,
    session_id: str,
    question: str,
    options: list[str] | None = None,
):
    """Emit a pending question event."""
    await manager.broadcast_to_session(
        session_id,
        {
            "type": EventType.QUESTION_PENDING,
            "question_id": question_id,
            "session_id": session_id,
            "question": question,
            "options": options,
        },
    )


async def emit_question_answered(question_id: str, session_id: str, answer: str):
    """Emit a question answered event."""
    await manager.broadcast_to_session(
        session_id,
        {
            "type": EventType.QUESTION_ANSWERED,
            "question_id": question_id,
            "session_id": session_id,
            "answer": answer,
        },
    )


# Get the manager for external use
def get_manager() -> ConnectionManager:
    """Get the connection manager singleton."""
    return manager
