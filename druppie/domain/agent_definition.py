"""Agent definition models for loading from YAML."""

from typing import Any

from pydantic import BaseModel, Field


class RequiredToolCall(BaseModel):
    """A tool that must have been called before completion is allowed."""

    tool_name: str
    min_calls: int = 1


class CompletionPrecondition(BaseModel):
    """Rule: require certain prior tool calls before done() succeeds.

    If summary_contains is set, the rule only applies when the summary matches.
    If summary_contains is omitted (None), the rule always applies.
    """

    summary_contains: str | None = None
    required_tools: list[RequiredToolCall]
    error_message: str = "Completion precondition not met."


class CompletionSummaryRequirement(BaseModel):
    """Require that done() summary contains one of the allowed status keywords.

    This enforces the agent's status protocol (e.g. DESIGN_APPROVED,
    DESIGN_REJECTED, NO_FD_CHANGE) regardless of what language the LLM uses.
    """

    one_of: list[str]
    error_message: str = "Summary must contain a required status keyword."


class ApprovalOverride(BaseModel):
    """Override for tool approval requirements.

    Used by agents to override the default approval rules from mcp_config.yaml.
    """

    requires_approval: bool = True
    required_role: str | None = None


class AgentDefinition(BaseModel):
    """Definition of an agent loaded from YAML.

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

    # Extra builtin tools beyond the defaults (done + hitl_ask_question + hitl_ask_multiple_choice_question)
    # These are ADDED to the defaults, e.g. ["make_plan"] gives this agent make_plan on top of defaults
    extra_builtin_tools: list[str] = Field(default_factory=list)

    # MCP servers this agent can use
    # Can be a simple list of MCP names: ["coding"]
    # Or a dict mapping MCP names to allowed tools: {"coding": ["read_file"]}
    mcps: list[str] | dict[str, list[str]] = Field(default_factory=list)

    # Approval overrides for specific tools
    # Key format: "mcp:tool_name" (e.g., "coding:write_file")
    approval_overrides: dict[str, ApprovalOverride] = Field(default_factory=dict)

    # Skills this agent can invoke (Druppie's own agent skill system)
    # List of skill names that match directories in druppie/skills/
    skills: list[str] = Field(default_factory=list)

    # System prompt fragments to include (from system_prompts/*.yaml)
    system_prompts: list[str] = Field(default_factory=list)

    # Direct routing: which agents this agent can route to via done(next_agent=...)
    # Empty list means no direct routing allowed (default — planner decides)
    allowed_next_agents: list[str] = Field(default_factory=list)

    # Completion preconditions: rules that must be satisfied before done() succeeds
    # If done()'s summary matches a rule's summary_contains, the required tools
    # must have been called (with status=completed) during this agent run.
    completion_preconditions: list[CompletionPrecondition] = Field(default_factory=list)

    # Require done() summary to contain one of the allowed status keywords.
    # Enforces the agent's status protocol regardless of LLM language drift.
    required_summary_status: CompletionSummaryRequirement | None = None

    # LLM settings
    llm_profile: str = "standard"
    temperature: float = 0.1
    max_tokens: int = 4096
    max_iterations: int = 10

    def get_mcp_names(self) -> list[str]:
        """Get list of MCP server names this agent can use."""
        if isinstance(self.mcps, dict):
            return list(self.mcps.keys())
        return self.mcps

    def get_allowed_tools(self, mcp_name: str) -> list[str] | None:
        """Get list of allowed tools for an MCP, or None if all tools allowed."""
        if isinstance(self.mcps, dict):
            return self.mcps.get(mcp_name)
        return None

    def get_approval_override(self, server: str, tool: str) -> ApprovalOverride | None:
        """Get approval override for a specific tool, if any."""
        key = f"{server}:{tool}"
        return self.approval_overrides.get(key)
