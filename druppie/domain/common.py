"""Common domain models shared across entities."""

from enum import Enum
from pydantic import BaseModel
from datetime import datetime
from typing import Any


# =============================================================================
# STATUS ENUMS
# =============================================================================

class SessionStatus(str, Enum):
    """Session execution status."""
    ACTIVE = "active"
    PAUSED_APPROVAL = "paused_approval"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"  # Waiting for user answer
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(str, Enum):
    """Agent run execution status."""
    PENDING = "pending"  # Created by planner, not started yet
    RUNNING = "running"
    PAUSED_TOOL = "paused_tool"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"  # Waiting for user answer
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCallStatus(str, Enum):
    """Tool call execution status."""
    PENDING = "pending"  # Not yet executed
    WAITING_APPROVAL = "waiting_approval"  # Needs approval before execution
    EXECUTING = "executing"  # Currently running
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    """Approval resolution status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QuestionStatus(str, Enum):
    """HITL question status."""
    PENDING = "pending"
    ANSWERED = "answered"


class DeploymentStatus(str, Enum):
    """Deployment/container status."""
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


# =============================================================================
# COMMON MODELS
# =============================================================================

class TokenUsage(BaseModel):
    """Token usage tracking."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TimestampMixin(BaseModel):
    """Mixin for timestamp fields."""
    created_at: datetime
    updated_at: datetime | None = None


class LLMMessage(BaseModel):
    """A single message in the LLM conversation."""
    role: str  # system, user, assistant, tool
    content: str | None = None
    # For assistant messages with tool calls
    tool_calls: list[dict[str, Any]] | None = None
    # For tool response messages
    tool_call_id: str | None = None
    name: str | None = None  # Tool name for tool responses
