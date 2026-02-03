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

    # For HITL tools - the question that was created (for answering)
    question_id: UUID | None = None

    # For execute_agent - the spawned child run
    child_run: "AgentRunDetail | None" = None


class LLMRawResponse(BaseModel):
    """Raw response from the LLM API - for debugging."""
    content: str | None = None  # Text content (may include XML tool calls)
    tool_calls: list[dict] | None = None  # Tool calls as returned by LLM (before execution)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallDetail(BaseModel):
    """One round-trip to the LLM."""
    id: UUID
    model: str
    provider: str
    token_usage: TokenUsage
    duration_ms: int | None

    # The full prompt sent to the LLM (structured messages)
    messages: list[LLMMessage]

    # Raw request/response for debugging - full JSON as sent/received
    raw_request: dict | None = None  # The exact request sent to LLM API (messages + tools)
    raw_response: LLMRawResponse | None = None  # What the LLM returned

    # Executed tools with their results (what we did with the LLM's decisions)
    tool_calls: list[ToolCallDetail]


class AgentRunSummary(BaseModel):
    """Lightweight agent run for chat timeline."""
    id: UUID
    agent_id: str
    status: AgentRunStatus
    error_message: str | None = None

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
