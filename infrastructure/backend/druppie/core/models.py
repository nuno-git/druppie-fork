"""Core data models for Druppie Governance Platform.

Simplified architecture with autonomous agents and predefined workflows.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class TaskStatus(str, Enum):
    """Status of a task assigned to an agent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # Waiting on dependency


class PlanStatus(str, Enum):
    """Status of an execution plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(str, Enum):
    """Type of agent."""

    SPEC_AGENT = "spec_agent"  # Creates specifications/designs
    EXECUTION_AGENT = "execution_agent"  # Executes actions
    SUPPORT_AGENT = "support_agent"  # Provides support (compliance, review)


class IntentAction(str, Enum):
    """Possible actions from intent analysis - simplified to 3 options."""

    CREATE_PROJECT = "create_project"
    UPDATE_PROJECT = "update_project"
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

    The Router analyzes user input and classifies it as one of 3 actions:
    - CREATE_PROJECT: Build something new
    - UPDATE_PROJECT: Modify existing project
    - GENERAL_CHAT: Answer questions, no action needed
    """

    initial_prompt: str  # Original user input
    prompt: str  # Summarized intent
    action: IntentAction = IntentAction.GENERAL_CHAT
    language: str = "en"
    answer: str | None = None  # Direct answer if general_chat

    # Clarification support
    clarification_needed: bool = False
    clarification_question: str | None = None

    # Project context extracted from the prompt
    project_context: dict[str, Any] = Field(default_factory=dict)
    # e.g., {"repo_url": "...", "project_name": "...", "task_description": "..."}


# --- Agent Definition ---


class AgentDefinition(BaseModel):
    """Definition of an autonomous agent.

    Agents receive natural language tasks and use MCPs to complete them.
    They decide when they're done and report results back.
    """

    id: str
    name: str
    type: AgentType = AgentType.EXECUTION_AGENT
    description: str = ""
    system_prompt: str = ""  # Instructions for the agent

    # MCP servers this agent can use (references MCP registry IDs)
    mcps: list[str] = Field(default_factory=list)

    # LLM configuration
    provider: str | None = None  # Override default LLM provider
    model: str | None = None  # Override default model

    # Execution limits
    max_iterations: int = 10  # Max tool calls before stopping

    # Access control
    auth_groups: list[str] = Field(default_factory=list)


# --- Agent Task & Result ---


class AgentResult(BaseModel):
    """Result from an autonomous agent execution."""

    success: bool
    summary: str  # What the agent accomplished (or why it failed)
    artifacts: list[str] = Field(default_factory=list)  # Paths to created files
    data: dict[str, Any] = Field(default_factory=dict)  # Structured output
    error: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)  # Detailed LLM call records for debugging


class AgentTask(BaseModel):
    """A task assigned to an autonomous agent.

    Unlike old Steps with specific actions, tasks are natural language
    descriptions that agents interpret and execute autonomously.
    """

    id: str  # Unique task ID
    agent_id: str  # Which agent executes this task
    description: str  # Natural language description of what to do

    # Dependencies for parallel execution
    depends_on: list[str] = Field(default_factory=list)  # Task IDs

    # Context from previous tasks or workflow
    context: dict[str, Any] = Field(default_factory=dict)

    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    result: AgentResult | None = None

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None


# --- Workflow Step ---


class WorkflowStepType(str, Enum):
    """Type of workflow step."""

    MCP = "mcp"  # Direct MCP tool call
    AGENT = "agent"  # Agent task execution
    CONDITION = "condition"  # Conditional branching


class WorkflowStep(BaseModel):
    """A step in a predefined workflow.

    Workflows are sequences of steps that can be:
    - MCP calls (direct tool invocation)
    - Agent tasks (autonomous execution)
    - Conditional branches
    """

    id: str
    name: str
    type: WorkflowStepType = WorkflowStepType.AGENT

    # For MCP steps
    mcp_tool: str | None = None  # e.g., "git.clone"
    params: dict[str, str] = Field(default_factory=dict)  # Template with {var}

    # For Agent steps
    agent_id: str | None = None
    task_template: str | None = None  # Template for task description

    # Flow control
    on_success: str | None = None  # Next step ID
    on_failure: str | None = None  # Failure handler step ID

    # Retry logic
    retry_count: int = 0
    max_retries: int = 3


# --- Workflow Definition ---


class WorkflowDefinition(BaseModel):
    """Definition of a predefined workflow.

    Workflows are sequences of steps for complex operations like:
    - Coding: clone → branch → TDD → code → push → build → e2e
    - Deployment: build → test → deploy → verify
    """

    id: str
    name: str
    description: str = ""

    # Keywords that help the planner select this workflow
    trigger_keywords: list[str] = Field(default_factory=list)

    # MCP servers required by this workflow
    required_mcps: list[str] = Field(default_factory=list)

    # Step definitions
    entry_point: str  # ID of the first step
    steps: dict[str, WorkflowStep] = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowRun(BaseModel):
    """A single execution of a workflow."""

    id: str
    workflow_id: str
    status: str = "running"  # running, completed, failed

    # Context data accumulated during the run
    context: dict[str, Any] = Field(default_factory=dict)

    # Current step being executed
    current_step_id: str | None = None

    # Input that triggered the run
    trigger_input: dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# --- Plan ---


class PlanType(str, Enum):
    """Type of plan execution."""

    WORKFLOW = "workflow"  # Execute a predefined workflow
    AGENTS = "agents"  # Execute agent tasks directly


class Plan(BaseModel):
    """An execution plan created from user intent.

    Plans can be either:
    - Workflow-based: Execute a predefined workflow
    - Agent-based: Execute agent tasks directly
    """

    id: str
    name: str
    description: str | None = None

    # What type of plan
    plan_type: PlanType = PlanType.AGENTS

    # Status
    status: PlanStatus = PlanStatus.PENDING

    # Intent that created this plan
    intent: Intent | None = None

    # For workflow-based plans
    workflow_id: str | None = None
    workflow_run: WorkflowRun | None = None

    # For agent-based plans
    tasks: list[AgentTask] = Field(default_factory=list)

    # Project context
    project_context: dict[str, Any] = Field(default_factory=dict)

    # Token usage totals
    total_usage: TokenUsage = Field(default_factory=TokenUsage)

    # Metadata
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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
