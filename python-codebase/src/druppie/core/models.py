"""Core data models for Druppie Governance Platform.

These models support the AI team in building solutions for end users.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class StepStatus(str, Enum):
    """Status of a step in an execution plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_INPUT = "waiting_input"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    """Status of an execution plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_INPUT = "waiting_input"


class AgentType(str, Enum):
    """Type of agent."""

    SPEC_AGENT = "spec_agent"  # Creates specifications/designs
    EXECUTION_AGENT = "execution_agent"  # Executes actions
    SUPPORT_AGENT = "support_agent"  # Provides support (compliance, review)


class IntentAction(str, Enum):
    """Possible actions from intent analysis."""

    CREATE_PROJECT = "create_project"
    UPDATE_PROJECT = "update_project"
    QUERY_REGISTRY = "query_registry"
    ORCHESTRATE_COMPLEX = "orchestrate_complex"
    GENERAL_CHAT = "general_chat"


# --- Token Usage ---


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


# --- Intent ---


class Intent(BaseModel):
    """Analyzed user intent from the Router.

    The Router analyzes user input and produces this structured intent
    that the Planner uses to generate an execution plan.
    """

    initial_prompt: str  # Original user input
    prompt: str  # Summarized intent
    action: IntentAction = IntentAction.GENERAL_CHAT
    category: str = "unknown"  # infrastructure, service, search, create_content
    content_type: str | None = None  # video, blog, code, image, audio
    language: str = "en"
    answer: str | None = None  # Direct answer if general_chat

    # Additional context extracted
    entities: dict[str, Any] = Field(default_factory=dict)


# --- Agent Definition ---


class AgentDefinition(BaseModel):
    """Definition of an agent that can execute steps.

    Agents are specialized roles that the AI team uses to build solutions.
    Examples: developer, architect, business_analyst, compliance
    """

    id: str
    name: str
    type: AgentType = AgentType.EXECUTION_AGENT
    description: str = ""
    instructions: str = ""  # System prompt for this agent

    # LLM configuration
    provider: str | None = None  # Override default LLM provider
    model: str | None = None  # Override default model

    # Capabilities
    skills: list[str] = Field(default_factory=list)  # Actions this agent can perform
    tools: list[str] = Field(default_factory=list)  # MCP tools this agent can use

    # Orchestration
    sub_agents: list[str] = Field(default_factory=list)  # Agents this orchestrates
    workflow: str | None = None  # Mermaid diagram of agent workflow

    # Prioritization
    priority: float = 1.0

    # Special actions
    final_actions: list[str] = Field(default_factory=list)  # Actions that end the plan

    # Access control
    auth_groups: list[str] = Field(default_factory=list)


# --- Step ---


class Step(BaseModel):
    """A single step in an execution plan.

    Steps are created by the Planner and executed by Executors.
    Each step is assigned to an agent and has a specific action.
    """

    id: int  # Sequential ID within the plan
    agent_id: str  # Which agent executes this step
    action: str  # Action to perform (e.g., "create_repo", "compliance_check")
    params: dict[str, Any] = Field(default_factory=dict)

    # Status tracking
    status: StepStatus = StepStatus.PENDING
    result: Any | None = None
    error: str | None = None

    # Dependencies
    depends_on: list[int] = Field(default_factory=list)  # Step IDs this depends on

    # Human-in-the-loop
    requires_approval: bool = False
    assigned_group: str | None = None
    approved_by: str | None = None

    # Token usage for this step
    usage: TokenUsage = Field(default_factory=TokenUsage)

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None


# --- Execution Plan ---


class Plan(BaseModel):
    """An execution plan created from user intent.

    The Planner creates plans from analyzed intent.
    The Task Manager executes plans step by step.
    """

    id: str
    name: str
    description: str | None = None

    # Status
    status: PlanStatus = PlanStatus.PENDING

    # Intent that created this plan
    intent: Intent | None = None

    # Steps to execute
    steps: list[Step] = Field(default_factory=list)

    # Agents selected for this plan
    selected_agents: list[str] = Field(default_factory=list)

    # Context
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)

    # Project context (if creating/updating a project)
    project_id: str | None = None
    project_path: str | None = None

    # Token usage totals
    total_usage: TokenUsage = Field(default_factory=TokenUsage)

    # Metadata
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Feedback
    feedback: list["FeedbackItem"] = Field(default_factory=list)


# --- Feedback ---


class FeedbackItem(BaseModel):
    """Feedback from users on plan execution."""

    id: str
    step_id: int | None = None
    feedback_type: str  # "correct", "incorrect", "partial"
    comment: str | None = None
    expected_output: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Workflow Definition ---


class WorkflowDefinition(BaseModel):
    """Definition of a reusable workflow.

    Workflows can be scheduled or triggered manually.
    They create Plans for each execution.
    """

    id: str
    name: str
    description: str | None = None
    version: str = "1.0.0"

    # Status for governance
    status: str = "draft"  # draft, review, approved, production, deprecated

    # Trigger configuration
    schedule: str | None = None  # Cron expression
    trigger_type: str = "manual"  # manual, schedule, webhook

    # The graph definition (LangGraph compatible)
    graph_definition: dict[str, Any] = Field(default_factory=dict)

    # MCP tools this workflow needs
    required_tools: list[str] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowRun(BaseModel):
    """A single execution of a workflow."""

    id: str
    workflow_id: str
    status: str = "running"  # running, completed, failed

    # All plans created during this run
    plan_ids: list[str] = Field(default_factory=list)

    # Input that triggered the run
    trigger_input: dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# --- Chat Message ---


class ChatMessage(BaseModel):
    """A message in a chat conversation."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatCompletionRequest(BaseModel):
    """Request for chat completion (OpenAI-compatible format)."""

    model: str = "default"
    messages: list[ChatMessage]
    stream: bool = False
    plan_id: str | None = None  # Continue existing plan


class ChatCompletionResponse(BaseModel):
    """Response from chat completion."""

    id: str
    plan_id: str
    content: str
    intent: Intent | None = None
    status: str  # "completed", "planning", "executing"


# Update forward references
Plan.model_rebuild()
