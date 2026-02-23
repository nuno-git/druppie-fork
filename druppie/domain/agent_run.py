"""Agent run domain models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from .approval import ApprovalSummary
from .common import AgentRunStatus, LLMMessage, TokenUsage, ToolCallStatus
from .tool import ToolType


class LLMRetryDetail(BaseModel):
    """A single retry attempt on an LLM call."""

    attempt: int
    error_type: str
    error_message: str | None = None
    delay_seconds: int | None = None


class NormalizationDetail(BaseModel):
    """A single field that was normalized in a tool call."""

    field_name: str
    original_value: str | None = None
    normalized_value: str | None = None


class ToolCallDetail(BaseModel):
    """A tool the LLM decided to call and its execution result.

    This represents a specific invocation of a tool, not the tool definition.
    Tool metadata (description, parameter schema) can be looked up via the
    ToolRegistry using the full_name field.
    """

    id: UUID
    index: int  # Order in the LLM response (0, 1, 2...)
    tool_type: ToolType  # ToolType.BUILTIN or ToolType.MCP
    mcp_server: str | None  # "coding", "docker" (None for builtin)
    tool_name: str  # "write_file", "done", "hitl_ask_question"
    full_name: str  # "coding_write_file" or "done" (for registry lookup)

    # Tool description (from ToolRegistry, for display convenience)
    description: str = ""

    # The actual arguments passed to this tool call
    arguments: dict

    # Execution result
    status: ToolCallStatus
    result: str | None
    error: str | None

    # For MCP tools that needed approval
    approval: ApprovalSummary | None = None

    # For HITL tools - the question that was created (for answering)
    question_id: UUID | None = None

    # Normalization audit trail
    normalizations: list[NormalizationDetail] = []

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

    # Tools that were available to the LLM for this call
    tools_provided: list[dict] | None = None

    # What the LLM returned (text + raw tool call requests)
    response_content: str | None = None
    response_tool_calls: list[dict] | None = None

    # Retry audit trail
    retries: list[LLMRetryDetail] = []

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
