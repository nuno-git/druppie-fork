"""Unified Pydantic models for Druppie platform.

All models used across the system are defined here for consistency.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================


class SessionStatus(str, Enum):
    """Status of a session."""

    ACTIVE = "active"
    PAUSED = "paused"  # Waiting for user input (question/approval)
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(str, Enum):
    """Status of execution state."""

    RUNNING = "running"
    PAUSED = "paused"  # Waiting for HITL
    COMPLETED = "completed"
    FAILED = "failed"


class IntentAction(str, Enum):
    """Possible actions from intent analysis."""

    CREATE_PROJECT = "create_project"
    UPDATE_PROJECT = "update_project"
    DEPLOY_PROJECT = "deploy_project"
    GENERAL_CHAT = "general_chat"


class PlanType(str, Enum):
    """Type of plan execution."""

    WORKFLOW = "workflow"
    AGENTS = "agents"


class PlanStatus(str, Enum):
    """Status of an execution plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StepType(str, Enum):
    """Type of execution step."""

    AGENT = "agent"
    MCP = "mcp"


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# =============================================================================
# TOKEN USAGE
# =============================================================================


class TokenUsage(BaseModel):
    """Token usage tracking for LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def add(self, other: "TokenUsage") -> None:
        """Add another usage to this one."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.cost += other.cost


# =============================================================================
# INTENT
# =============================================================================


class Intent(BaseModel):
    """Analyzed user intent from the Router agent."""

    initial_prompt: str
    prompt: str  # Summarized intent
    action: IntentAction = IntentAction.GENERAL_CHAT
    answer: str | None = None  # Direct answer for general_chat

    # Clarification
    clarification_needed: bool = False
    clarification_question: str | None = None

    # Project context
    project_context: dict[str, Any] = Field(default_factory=dict)
    deploy_context: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# EXECUTION STEPS
# =============================================================================


class Step(BaseModel):
    """A step in an execution plan."""

    id: str
    type: StepType
    status: str = "pending"  # pending, running, completed, failed, waiting

    # For agent steps
    agent_id: str | None = None
    prompt: str | None = None

    # For MCP steps
    tool: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)

    # Output
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    # Dependencies
    depends_on: list[str] = Field(default_factory=list)


# =============================================================================
# PLAN
# =============================================================================


class Plan(BaseModel):
    """An execution plan created from user intent."""

    id: str
    name: str
    description: str = ""
    plan_type: PlanType = PlanType.AGENTS
    status: PlanStatus = PlanStatus.PENDING

    # Intent that created this plan
    intent: Intent | None = None

    # For workflow-based plans
    workflow_id: str | None = None

    # Steps to execute
    steps: list[Step] = Field(default_factory=list)

    # Context accumulated during execution
    context: dict[str, Any] = Field(default_factory=dict)

    # Token usage
    total_usage: TokenUsage = Field(default_factory=TokenUsage)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# HITL (Human-in-the-Loop)
# =============================================================================


class QuestionRequest(BaseModel):
    """A question from an agent to the user."""

    id: str
    session_id: str
    question: str
    options: list[str] = Field(default_factory=list)
    context: str | None = None
    agent_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Response
    response: str | None = None
    responded_at: datetime | None = None


class ApprovalRequest(BaseModel):
    """An approval request for a sensitive action."""

    id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    required_roles: list[str] = Field(default_factory=list)
    approvals_received: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    danger_level: str = "low"
    description: str | None = None


# =============================================================================
# EXECUTION STATE
# =============================================================================


class ExecutionState(BaseModel):
    """State of execution for a session."""

    plan: Plan | None = None
    current_index: int = 0
    status: ExecutionStatus = ExecutionStatus.RUNNING
    context: dict[str, Any] = Field(default_factory=dict)

    # HITL pauses
    pending_approval: ApprovalRequest | None = None
    pending_question: QuestionRequest | None = None

    # Results
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


# =============================================================================
# AGENT DEFINITIONS (for loading from YAML)
# =============================================================================


class ApprovalOverride(BaseModel):
    """Override for tool approval requirements.

    Used by agents to override the default approval rules from mcp_config.yaml.
    Per goal.md: Uses required_role (singular) instead of required_roles (array).
    """

    requires_approval: bool = True
    required_role: str | None = None  # Single role, not array (per goal.md)


class AgentDefinition(BaseModel):
    """Definition of an agent loaded from YAML.

    LAYERED APPROVAL SYSTEM (per goal.md):
    - mcp_config.yaml defines GLOBAL defaults for all agents
    - Each agent can OVERRIDE defaults via approval_overrides
    - Uses required_role (singular) not required_roles (array)

    Example in architect.yaml:
        approval_overrides:
          coding:write_file:
            requires_approval: true
            required_role: architect
    """

    id: str
    name: str
    description: str = ""
    system_prompt: str = ""

    # MCP servers this agent can use
    # Can be a simple list of MCP names: ["coding", "hitl"]
    # Or a dict mapping MCP names to allowed tools: {"coding": ["read_file"], "hitl": ["ask_question"]}
    mcps: list[str] | dict[str, list[str]] = Field(default_factory=list)

    # Approval overrides for specific tools (per goal.md layered system)
    # Key format: "mcp:tool_name" (e.g., "coding:write_file")
    # Value: ApprovalOverride with requires_approval and required_role
    approval_overrides: dict[str, ApprovalOverride] = Field(default_factory=dict)

    # LLM settings
    model: str | None = None
    temperature: float = 0.1
    max_tokens: int = 4096
    max_iterations: int = 10  # Max tool-calling iterations

    def get_mcp_names(self) -> list[str]:
        """Get list of MCP server names this agent can use."""
        if isinstance(self.mcps, dict):
            return list(self.mcps.keys())
        return self.mcps

    def get_allowed_tools(self, mcp_name: str) -> list[str] | None:
        """Get list of allowed tools for an MCP, or None if all tools allowed."""
        if isinstance(self.mcps, dict):
            return self.mcps.get(mcp_name)
        return None  # All tools allowed when using simple list format

    def get_approval_override(self, server: str, tool: str) -> ApprovalOverride | None:
        """Get approval override for a specific tool, if any.

        Args:
            server: MCP server name (e.g., "coding")
            tool: Tool name (e.g., "write_file")

        Returns:
            ApprovalOverride if override exists, None otherwise
        """
        key = f"{server}:{tool}"
        return self.approval_overrides.get(key)


class AgentResult(BaseModel):
    """Result from running an agent."""

    success: bool
    summary: str
    artifacts: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# WORKFLOW DEFINITIONS (for loading from YAML)
# =============================================================================


class WorkflowStep(BaseModel):
    """A step in a workflow definition."""

    id: str
    type: StepType = StepType.AGENT

    # For agent steps
    agent_id: str | None = None
    prompt: str | None = None

    # For MCP steps
    tool: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)

    # Flow control
    on_success: str | None = None
    on_failure: str | None = None

    class Config:
        extra = "allow"  # Allow extra fields from YAML


class WorkflowDefinition(BaseModel):
    """Definition of a workflow loaded from YAML."""

    id: str
    name: str
    description: str = ""
    entry_point: str
    steps: dict[str, Any] = Field(default_factory=dict)  # Allow flexible step format
    inputs: list[str] = Field(default_factory=list)

    class Config:
        extra = "allow"  # Allow extra fields from YAML


# =============================================================================
# LLM RESPONSE
# =============================================================================


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    done: bool = False  # True if agent called done() tool
    result: dict[str, Any] = Field(default_factory=dict)
