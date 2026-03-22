"""Session domain models.

Session contains a timeline of events:
- User messages
- Agent runs (which contain LLM calls, tool calls, etc.)

The TimelineEntry model provides a unified view for the frontend.
"""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from enum import Enum
from typing import Literal

from .common import TokenUsage, SessionStatus
from .agent_run import AgentRunSummary, AgentRunDetail
from .project import ProjectSummary


class TimelineEntryType(str, Enum):
    """Type of timeline entry."""
    MESSAGE = "message"
    AGENT_RUN = "agent_run"


class Message(BaseModel):
    """A message in the session (user, assistant, or system).

    Maps 1:1 to the messages table.
    """
    id: UUID
    role: str  # user, assistant, system
    content: str
    agent_id: str | None = None
    sequence_number: int = 0
    created_at: datetime


class TimelineEntry(BaseModel):
    """Single entry in session timeline - either a message or an agent run.

    This provides a unified, chronologically sorted view of the session
    for the frontend to render.
    """
    type: TimelineEntryType
    timestamp: datetime

    # For messages (user input, assistant response)
    message: Message | None = None

    # For agent runs (includes full detail: llm_calls, tool_calls, approvals)
    agent_run: AgentRunDetail | None = None


class SessionSummary(BaseModel):
    """Lightweight session for lists.

    Maps 1:1 to the sessions table (summary fields only).
    """
    id: UUID
    title: str
    status: SessionStatus
    error_message: str | None = None
    project_id: UUID | None
    username: str | None = None
    token_usage: TokenUsage
    created_at: datetime
    updated_at: datetime | None


class SessionDetail(SessionSummary):
    """Full session with timeline.

    Includes the complete timeline of messages and agent runs,
    sorted chronologically.
    """
    user_id: UUID
    project: ProjectSummary | None
    timeline: list[TimelineEntry]


# Backward compatibility aliases
ChatItemType = TimelineEntryType
ChatItem = TimelineEntry
MessageSummary = Message
