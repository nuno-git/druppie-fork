"""Pydantic schema for YAML session fixtures."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class ApprovalFixture(BaseModel):
    """Approval metadata for a tool call."""
    required_role: str
    status: Literal["pending", "approved", "rejected"] = "approved"
    approved_by: str | None = None


class ToolCallFixture(BaseModel):
    """A single tool call within an agent run."""
    tool: str  # "builtin:set_intent", "coding:make_design", etc.
    arguments: dict = Field(default_factory=dict)
    status: Literal[
        "pending", "waiting_approval", "waiting_answer",
        "waiting_sandbox", "executing", "completed", "failed",
    ] = "completed"
    result: str | None = None
    error_message: str | None = None
    answer: str | None = None  # HITL: creates Question record if present
    approval: ApprovalFixture | None = None

    @property
    def mcp_server(self) -> str:
        return self.tool.split(":")[0]

    @property
    def tool_name(self) -> str:
        parts = self.tool.split(":", 1)
        return parts[1] if len(parts) > 1 else parts[0]


class AgentRunFixture(BaseModel):
    """A single agent run within a session."""
    id: str
    status: Literal[
        "pending", "running", "paused_tool", "paused_hitl",
        "paused_sandbox", "paused_user", "completed", "failed", "cancelled",
    ]
    error_message: str | None = None
    planned_prompt: str | None = None
    tool_calls: list[ToolCallFixture] = Field(default_factory=list)


class MessageFixture(BaseModel):
    """A message in the session timeline."""
    role: Literal["user", "assistant", "system"]
    content: str
    agent_id: str | None = None


class SessionMetadata(BaseModel):
    """Session-level metadata."""
    id: str
    title: str
    status: Literal[
        "active", "paused_approval", "paused_hitl", "paused_sandbox",
        "paused", "paused_crashed", "completed", "failed",
    ]
    user: str = "admin"
    intent: str | None = None
    project_name: str | None = None
    language: str = "en"
    hours_ago: float = 0


class SessionFixture(BaseModel):
    """Complete session fixture -- root model for each YAML file."""
    metadata: SessionMetadata
    agents: list[AgentRunFixture] = Field(default_factory=list)
    messages: list[MessageFixture] = Field(default_factory=list)
