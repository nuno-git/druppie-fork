"""Consolidated API response schemas.

All Pydantic models for API responses in one place.
This reduces duplication and ensures consistency across endpoints.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


# =============================================================================
# GENERIC WRAPPERS
# =============================================================================


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int
    page: int = 1
    limit: int = 20


class ListResponse(BaseModel, Generic[T]):
    """Generic list response wrapper (no pagination)."""

    items: list[T]
    count: int


# =============================================================================
# COMMON MODELS
# =============================================================================


class TokenUsage(BaseModel):
    """Token usage for LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class FileInfo(BaseModel):
    """File information for workspace/project browsing."""

    name: str
    path: str
    type: str  # file, directory
    size: int | None = None
    sha: str | None = None  # Git SHA for project files


class UserInfo(BaseModel):
    """Basic user information."""

    id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = []


# =============================================================================
# PROJECT MODELS
# =============================================================================


class ProjectSummary(BaseModel):
    """Compact project info for embedding in other responses."""

    id: str
    name: str
    repo_name: str | None = None
    repo_url: str | None = None
    app_url: str | None = None  # Running app URL


class BuildInfo(BaseModel):
    """Build/deployment information."""

    id: str
    project_id: str
    branch: str = "main"
    status: str  # pending, building, built, running, stopped, failed
    is_preview: bool = False
    port: int | None = None
    container_name: str | None = None
    app_url: str | None = None
    created_at: str | None = None


class ProjectDetail(BaseModel):
    """Full project details."""

    id: str
    name: str
    description: str | None = None
    repo_name: str
    repo_url: str | None = None
    clone_url: str | None = None
    owner_id: str | None = None
    owner_username: str | None = None
    status: str = "active"
    # Build info
    main_build: BuildInfo | None = None
    preview_builds: list[BuildInfo] = []
    is_running: bool = False
    app_url: str | None = None
    # Token usage aggregated from sessions
    token_usage: TokenUsage | None = None
    created_at: str | None = None
    updated_at: str | None = None


# =============================================================================
# WORKFLOW MODELS
# =============================================================================


class WorkflowStepInfo(BaseModel):
    """A step in the execution workflow."""

    id: str
    step_index: int
    agent_id: str
    description: str | None = None
    status: str  # pending, running, waiting_approval, completed, failed, skipped
    result_summary: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class WorkflowInfo(BaseModel):
    """Execution workflow created by the planner."""

    id: str
    name: str | None = None
    status: str  # pending, running, paused, completed, failed
    current_step: int = 0
    steps: list[WorkflowStepInfo] = []
    created_at: str | None = None


# =============================================================================
# AGENT & TOOL MODELS
# =============================================================================


class LLMCallInfo(BaseModel):
    """Full LLM call information for debugging."""

    id: str
    agent_id: str | None = None
    agent_run_id: str | None = None
    provider: str
    model: str
    token_usage: "TokenUsage"
    duration_ms: int | None = None
    # Full request/response for debugging
    request_messages: list[dict] | None = None
    response_content: str | None = None
    response_tool_calls: list[dict] | None = None
    tools_provided: list[dict] | None = None
    created_at: str | None = None


class ToolCallInfo(BaseModel):
    """Information about an MCP tool call."""

    id: str
    agent_run_id: str | None = None
    mcp_server: str
    tool_name: str
    arguments: dict[str, Any] = {}
    status: str  # pending, executing, completed, failed
    result: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    executed_at: str | None = None


class ApprovalInfo(BaseModel):
    """Approval request information."""

    id: str
    session_id: str
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    workflow_step_id: str | None = None
    approval_type: str  # tool_call, workflow_step
    mcp_server: str | None = None
    tool_name: str | None = None
    title: str | None = None
    description: str | None = None
    required_roles: list[str] = []
    danger_level: str | None = None
    status: str  # pending, approved, rejected
    arguments: dict[str, Any] | None = None
    resolved_by: str | None = None
    resolved_by_username: str | None = None
    resolved_at: str | None = None
    rejection_reason: str | None = None
    agent_id: str | None = None
    created_at: str | None = None


class HITLChoiceInfo(BaseModel):
    """A choice for a HITL question."""

    index: int
    text: str
    is_selected: bool = False


class HITLQuestionInfo(BaseModel):
    """HITL question from an agent."""

    id: str
    session_id: str
    agent_run_id: str | None = None
    agent_id: str | None = None
    question: str
    question_type: str = "text"  # text, single_choice, multiple_choice
    choices: list[HITLChoiceInfo] = []
    status: str  # pending, answered
    answer: str | None = None
    created_at: str | None = None
    answered_at: str | None = None


class AgentRunInfo(BaseModel):
    """Information about an agent execution with all nested data."""

    id: str
    agent_id: str
    workflow_step_id: str | None = None
    parent_run_id: str | None = None
    status: str  # running, paused_tool, paused_hitl, completed, failed
    iteration_count: int = 0
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    started_at: str | None = None
    completed_at: str | None = None
    # Nested data for this agent run
    llm_calls: list[LLMCallInfo] = []
    tool_calls: list[ToolCallInfo] = []
    approvals: list[ApprovalInfo] = []
    hitl_questions: list[HITLQuestionInfo] = []


# =============================================================================
# MESSAGE MODELS
# =============================================================================


class MessageInfo(BaseModel):
    """A message in the conversation."""

    id: str
    role: str  # user, assistant, system, tool
    content: str
    agent_id: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    sequence_number: int
    created_at: str | None = None


# =============================================================================
# SESSION EVENT MODELS
# =============================================================================


class SessionEventInfo(BaseModel):
    """An event in the session timeline."""

    id: str
    event_type: str
    agent_id: str | None = None
    title: str | None = None
    tool_name: str | None = None
    event_data: dict[str, Any] | None = None
    timestamp: str | None = None
    # References for drill-down
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    hitl_question_id: str | None = None


# =============================================================================
# WORKSPACE MODELS
# =============================================================================


class WorkspaceInfo(BaseModel):
    """Workspace information."""

    id: str
    session_id: str
    project_id: str | None = None
    branch: str = "main"
    local_path: str | None = None
    created_at: str | None = None


# =============================================================================
# SESSION MODELS (COMPREHENSIVE)
# =============================================================================


class SessionSummary(BaseModel):
    """Compact session summary for listing."""

    id: str
    title: str | None = None
    status: str
    project_id: str | None = None
    project_name: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created_at: str | None = None
    updated_at: str | None = None


class SessionDetail(BaseModel):
    """Complete session with ALL data.

    This is the single comprehensive response for GET /sessions/{id}.
    It includes everything needed to reconstruct the full execution.
    """

    # Basic info
    id: str
    user_id: str | None = None
    title: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None

    # Token usage (aggregated)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    # Per-agent token breakdown
    tokens_by_agent: dict[str, int] = {}

    # Project & workspace
    project: ProjectSummary | None = None
    workspace: WorkspaceInfo | None = None

    # Execution plan (from router -> planner)
    workflow: WorkflowInfo | None = None

    # All agent runs (router, planner, architect, developer, etc.)
    agent_runs: list[AgentRunInfo] = []

    # Full message history
    messages: list[MessageInfo] = []

    # All tool calls
    tool_calls: list[ToolCallInfo] = []

    # All LLM calls (raw data for debugging)
    llm_calls: list[LLMCallInfo] = []

    # All approvals (pending and resolved)
    approvals: list[ApprovalInfo] = []

    # All HITL questions (pending and answered)
    hitl_questions: list[HITLQuestionInfo] = []

    # Timeline events
    events: list[SessionEventInfo] = []


# =============================================================================
# ERROR MODELS
# =============================================================================


class ErrorInfo(BaseModel):
    """Error information for API responses."""

    message: str
    error_type: str | None = None
    retryable: bool = False
    retry_after: int | None = None
    provider: str | None = None


class APIError(BaseModel):
    """Standard API error response."""

    success: bool = False
    error: ErrorInfo


# =============================================================================
# MCP MODELS
# =============================================================================


class MCPToolInfo(BaseModel):
    """MCP tool information."""

    id: str  # server:tool_name
    name: str
    description: str | None = None
    requires_approval: bool = False
    required_roles: list[str] = []
    danger_level: str | None = None


class MCPServerInfo(BaseModel):
    """MCP server information."""

    id: str
    name: str
    description: str | None = None
    url: str
    status: str | None = None  # For health check
    tools: list[MCPToolInfo] = []


# =============================================================================
# AGENT MODELS
# =============================================================================


class AgentConfigInfo(BaseModel):
    """Agent configuration information."""

    id: str
    name: str
    description: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_iterations: int | None = None
    mcps: list[str] = []
    category: str | None = None


# =============================================================================
# RUNNING APP MODELS
# =============================================================================


class RunningAppInfo(BaseModel):
    """Information about a running application."""

    build_id: str
    project_id: str
    project_name: str
    container_name: str
    app_url: str
    port: int
    branch: str = "main"
    is_preview: bool = False
    owner_id: str | None = None
    owner_username: str | None = None
    started_at: str | None = None
