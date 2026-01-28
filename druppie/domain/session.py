"""Session domain models."""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import TokenUsage, SessionStatus
from .agent_run import AgentRunDetail
from .project import ProjectSummary


class ChatItem(BaseModel):
    """Single item in chat timeline."""
    type: str  # system_message, user_message, agent_run, assistant_message
    content: str | None = None
    agent_id: str | None = None
    timestamp: datetime
    # For agent_run type - nested structure
    agent_run: AgentRunDetail | None = None


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
