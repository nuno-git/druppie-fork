"""Agent run domain models."""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import TokenUsage, LLMMessage, AgentRunStatus, ToolCallStatus
from .approval import ApprovalSummary


class ToolCallDetail(BaseModel):
    """A tool the LLM decided to call and its execution result."""
    id: UUID
    index: int  # Order in the LLM response (0, 1, 2...)
    tool_type: str  # "builtin" or "mcp"
    mcp_server: str | None  # "coding", "docker" (None for builtin)
    tool_name: str  # "write_file", "done", "hitl_ask_question", "execute_agent"
    arguments: dict

    # Execution result
    status: ToolCallStatus
    result: str | None
    error: str | None

    # For MCP tools that needed approval
    approval: ApprovalSummary | None = None

    # For execute_agent - the spawned child run
    child_run: "AgentRunDetail | None" = None


class LLMCallDetail(BaseModel):
    """One round-trip to the LLM."""
    id: UUID
    model: str
    provider: str
    token_usage: TokenUsage
    duration_ms: int | None

    # The full prompt sent to the LLM (structured messages)
    messages: list[LLMMessage]

    # What the LLM decided
    response_content: str | None  # Text output
    tool_calls: list[ToolCallDetail]  # Decisions to execute tools (ordered by index)


class AgentRunSummary(BaseModel):
    """Lightweight agent run for chat timeline."""
    id: UUID
    agent_id: str
    status: AgentRunStatus

    # For pending runs (created by planner)
    planned_prompt: str | None = None
    sequence_number: int | None = None

    # For completed runs
    token_usage: TokenUsage
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentRunDetail(AgentRunSummary):
    """Full agent run - sequence of LLM calls. Inherits from AgentRunSummary."""

    # The execution trace - each LLM call includes its tool executions
    llm_calls: list[LLMCallDetail] = []
