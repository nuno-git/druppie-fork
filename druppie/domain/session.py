"""Session domain models."""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from enum import Enum

from .common import TokenUsage, SessionStatus
from .agent_run import AgentRunSummary
from .project import ProjectSummary


class ChatItemType(str, Enum):
    """Type of chat item."""
    MESSAGE = "message"
    AGENT_RUN = "agent_run"


class MessageSummary(BaseModel):
    """A message in the chat timeline."""
    id: UUID
    role: str  # user, assistant, system
    content: str
    agent_id: str | None = None
    created_at: datetime


class ChatItem(BaseModel):
    """Single item in chat timeline - either a message or an agent run."""
    type: ChatItemType

    # For messages (user input, assistant response)
    message: MessageSummary | None = None

    # For agent runs (pending, running, completed, paused...)
    agent_run: AgentRunSummary | None = None

    # For ordering
    created_at: datetime


class SessionSummary(BaseModel):
    """Lightweight session for lists."""
    id: UUID
    title: str
    status: SessionStatus
    project_id: UUID | None
    token_usage: TokenUsage
    created_at: datetime
    updated_at: datetime | None


class SessionDetail(SessionSummary):
    """Full session with chat timeline. Inherits from SessionSummary."""
    user_id: UUID
    project: ProjectSummary | None
    chat: list[ChatItem]
