"""Agent run domain models."""

from __future__ import annotations

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import TokenUsage
from .approval import ApprovalSummary
from .question import QuestionDetail


class LLMCallDetail(BaseModel):
    """Single LLM API call."""
    id: UUID
    model: str
    provider: str
    token_usage: TokenUsage
    duration_ms: int | None
    tools_decided: list[str]


class ToolExecutionDetail(BaseModel):
    """Single tool execution."""
    id: UUID
    tool: str  # "coding:write_file" or "builtin:done"
    tool_type: str  # "mcp" or "builtin"
    arguments: dict
    status: str  # pending, executing, completed, failed
    result: str | None
    error: str | None
    approval: ApprovalSummary | None  # Embedded if approval was needed


class AgentRunStep(BaseModel):
    """A step in an agent run (LLM call or tool execution)."""
    type: str  # "llm_call" or "tool_execution" or "hitl_question"
    llm_call: LLMCallDetail | None = None
    tool_execution: ToolExecutionDetail | None = None
    question: QuestionDetail | None = None


class AgentRunDetail(BaseModel):
    """Full agent run with steps."""
    id: UUID
    agent_id: str
    status: str
    token_usage: TokenUsage
    started_at: datetime
    completed_at: datetime | None
    steps: list[AgentRunStep]
    # Nested runs (from execute_agent)
    child_runs: list[AgentRunDetail] = []
