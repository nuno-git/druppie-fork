"""Simplified Agent-to-Agent (A2A) communication protocol.

Provides a simple pub/sub mechanism for agents to communicate.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class AgentMessage(BaseModel):
    """Message passed between agents."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: str  # Source agent ID
    to_agent: str | None = None  # Target agent ID, None = broadcast
    message_type: str  # "request", "response", "notification"
    content: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None  # For request/response pairs
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class A2AProtocol:
    """Simple pub/sub protocol for agent communication.

    Use cases:
    - Agent requests help from another agent
    - Agent notifies others of completed work
    - Agent broadcasts status updates

    This is a simplified implementation for single-process use.
    For distributed systems, this would be replaced with a message queue.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[AgentMessage], Any]]] = {}
        self._pending_requests: dict[str, asyncio.Future[AgentMessage]] = {}
        self.logger = logger.bind(component="a2a")

    def subscribe(
        self,
        agent_id: str,
        callback: Callable[[AgentMessage], Any],
    ) -> None:
        """Subscribe an agent to receive messages.

        Args:
            agent_id: The agent's ID
            callback: Function to call when message is received
        """
        if agent_id not in self._subscribers:
            self._subscribers[agent_id] = []
        self._subscribers[agent_id].append(callback)
        self.logger.debug(f"Agent {agent_id} subscribed")

    def unsubscribe(self, agent_id: str) -> None:
        """Unsubscribe an agent from receiving messages."""
        self._subscribers.pop(agent_id, None)
        self.logger.debug(f"Agent {agent_id} unsubscribed")

    async def send(self, message: AgentMessage) -> None:
        """Send a message to a specific agent or broadcast.

        Args:
            message: The message to send
        """
        self.logger.debug(
            "Sending message",
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            message_type=message.message_type,
        )

        if message.to_agent:
            # Direct message
            callbacks = self._subscribers.get(message.to_agent, [])
            for callback in callbacks:
                await self._call_callback(callback, message)
        else:
            # Broadcast to all except sender
            for agent_id, callbacks in self._subscribers.items():
                if agent_id != message.from_agent:
                    for callback in callbacks:
                        await self._call_callback(callback, message)

        # Handle response to pending request
        if message.message_type == "response" and message.correlation_id:
            future = self._pending_requests.pop(message.correlation_id, None)
            if future and not future.done():
                future.set_result(message)

    async def request(
        self,
        message: AgentMessage,
        timeout: float = 30.0,
    ) -> AgentMessage:
        """Send a request and wait for response.

        Args:
            message: The request message
            timeout: Timeout in seconds

        Returns:
            The response message

        Raises:
            asyncio.TimeoutError: If no response within timeout
        """
        # Create future for response
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AgentMessage] = loop.create_future()
        self._pending_requests[message.id] = future

        # Send request
        message.message_type = "request"
        message.correlation_id = message.id
        await self.send(message)

        # Wait for response
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(message.id, None)
            raise

    async def respond(
        self,
        original: AgentMessage,
        content: dict[str, Any],
        from_agent: str,
    ) -> None:
        """Send a response to a request.

        Args:
            original: The original request message
            content: Response content
            from_agent: The responding agent's ID
        """
        response = AgentMessage(
            from_agent=from_agent,
            to_agent=original.from_agent,
            message_type="response",
            content=content,
            correlation_id=original.correlation_id or original.id,
        )
        await self.send(response)

    async def notify(
        self,
        from_agent: str,
        content: dict[str, Any],
        to_agent: str | None = None,
    ) -> None:
        """Send a notification (fire-and-forget).

        Args:
            from_agent: Source agent ID
            content: Notification content
            to_agent: Target agent (None for broadcast)
        """
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type="notification",
            content=content,
        )
        await self.send(message)

    async def _call_callback(
        self,
        callback: Callable[[AgentMessage], Any],
        message: AgentMessage,
    ) -> None:
        """Call a callback, handling both sync and async."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(message)
            else:
                callback(message)
        except Exception as e:
            self.logger.error(f"Callback error: {e}")
