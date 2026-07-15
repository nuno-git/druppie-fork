"""Agent definition parsing for the new agent runtime.

This is a NEW model separate from druppie/domain/agent_definition.py.
It supports the new YAML schema with role, done_variables, nested mcps, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


def parse_definition(data: dict[str, Any]) -> AgentDefinition:
    """Parse an agent definition from a dict (loaded from YAML).

    Args:
        data: Dict loaded from YAML with yaml.safe_load()

    Returns:
        AgentDefinition instance

    Raises:
        ValueError: If required fields are missing or values are invalid
    """
    for required_field in ("id", "name", "description"):
        if required_field not in data:
            raise ValueError(f"Missing required field: {required_field}")

    has_system_prompt = "system_prompt" in data
    has_system_prompts = "system_prompts" in data
    if not has_system_prompt and not has_system_prompts:
        raise ValueError("Either 'system_prompt' or 'system_prompts' must be provided")

    role_raw = data.get("role", "primary")
    valid_roles = ("primary", "subagent", "both")
    if role_raw not in valid_roles:
        raise ValueError(f"Invalid role '{role_raw}'. Must be one of: {valid_roles}")

    mcps_raw = data.get("mcps", {})
    mcps = _parse_mcps(mcps_raw)

    done_variables = data.get("done_variables")

    subagents = data.get("subagents", [])

    preconditions_raw = data.get("completion_preconditions", [])
    completion_preconditions = _parse_preconditions(preconditions_raw)

    summary_status_raw = data.get("required_summary_status")
    required_summary_status = _parse_summary_status(summary_status_raw)

    approval_overrides = data.get("approval_overrides", {})

    return AgentDefinition(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        role=role_raw,
        system_prompt=data.get("system_prompt"),
        system_prompts=data.get("system_prompts", []),
        temperature=data.get("temperature", 0.1),
        max_tokens=data.get("max_tokens", 4096),
        max_iterations=data.get("max_iterations", 20),
        llm_profile=data.get("llm_profile", "default"),
        skills=data.get("skills", []),
        subagents=subagents,
        required_summary_status=required_summary_status,
        completion_preconditions=completion_preconditions,
        done_variables=done_variables,
        mcps=mcps,
        approval_overrides=approval_overrides,
        extra_builtin_tools=data.get("extra_builtin_tools", []),
        excluded_builtin_tools=data.get("excluded_builtin_tools", []),
        sandbox_constraints=data.get("sandbox_constraints"),
        allowed_next_agents=data.get("allowed_next_agents", []),
        compression=data.get("compression"),
    )


def load_definition(yaml_path: str | Path) -> AgentDefinition:
    """Load an agent definition from a YAML file.

    Args:
        yaml_path: Path to the YAML file

    Returns:
        AgentDefinition instance

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the YAML is invalid
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Agent definition not found: {path}")

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML: expected dict, got {type(data).__name__}")

    return parse_definition(data)


def build_done_schema(definition: AgentDefinition) -> dict:
    """Generate the done() tool JSON Schema from an agent definition.

    summary is ALWAYS required. done_variables adds custom fields beyond summary.

    Args:
        definition: The agent definition

    Returns:
        JSON Schema dict for the done() tool
    """
    properties = {
        "summary": {
            "type": "string",
            "description": "Summary of what you accomplished",
        }
    }
    required = ["summary"]

    if definition.done_variables:
        for var_name, var_schema in definition.done_variables.items():
            properties[var_name] = var_schema
            if var_schema.get("required", False):
                required.append(var_name)

    if definition.allowed_next_agents:
        properties["next_agent"] = {
            "type": "string",
            "description": "The next agent to route to",
            "enum": definition.allowed_next_agents,
        }

    return {
        "name": "done",
        "description": "Signal completion. Provide a summary of what you accomplished.",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def _parse_mcps(mcps_raw: dict[str, Any]) -> dict[str, Any]:
    """Parse the mcps field from YAML.

    Format:
      sandbox:
        tools: [read_file, write_file]
        git: current_project
      core-tools: [hitl_ask_question, make_plan]
      docker: [build, run]
    """
    if not mcps_raw:
        return {}

    result = {}
    for server_name, server_config in mcps_raw.items():
        if isinstance(server_config, list):
            result[server_name] = {"tools": server_config}
        elif isinstance(server_config, dict):
            result[server_name] = server_config
        else:
            result[server_name] = {"tools": [server_config]}

    return result


def _parse_preconditions(preconditions_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse completion_preconditions from YAML."""
    result = []
    for pre in preconditions_raw:
        required_tools = []
        for tool in pre.get("required_tools", []):
            required_tools.append({
                "tool_name": tool["tool_name"],
                "min_calls": tool.get("min_calls", 1),
            })
        result.append({
            "summary_contains": pre.get("summary_contains"),
            "unless_summary_contains": pre.get("unless_summary_contains"),
            "required_tools": required_tools,
            "error_message": pre.get("error_message", ""),
        })
    return result


def _parse_summary_status(status_raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Parse required_summary_status from YAML."""
    if status_raw is None:
        return None
    return {
        "one_of": status_raw.get("one_of", []),
        "error_message": status_raw.get("error_message", ""),
    }


@dataclass
class AgentDefinition:
    """Agent definition parsed from YAML.

    This is a NEW model with the updated schema from the runtime spec.
    It does NOT replace druppie/domain/agent_definition.py.
    """
    id: str
    name: str
    description: str
    role: Literal["primary", "subagent", "both"] = "primary"

    system_prompt: str | None = None
    system_prompts: list[str] = field(default_factory=list)

    temperature: float = 0.1
    max_tokens: int = 4096
    max_iterations: int = 20
    llm_profile: str = "default"

    skills: list[str] = field(default_factory=list)
    subagents: list[str] = field(default_factory=list)

    required_summary_status: dict[str, Any] | None = None
    completion_preconditions: list[dict[str, Any]] = field(default_factory=list)
    done_variables: dict[str, dict[str, Any]] | None = None

    mcps: dict[str, Any] = field(default_factory=dict)

    approval_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    compression: dict[str, Any] | None = None

    # Legacy fields from old schema — kept for compatibility during migration
    extra_builtin_tools: list[str] = field(default_factory=list)
    excluded_builtin_tools: list[str] = field(default_factory=list)
    sandbox_constraints: dict[str, Any] | None = None
    allowed_next_agents: list[str] = field(default_factory=list)

    @property
    def has_subagents(self) -> bool:
        """Whether this agent can spawn subagents."""
        return len(self.subagents) > 0

    @property
    def allowed_mcp_tools(self) -> dict[str, list[str]]:
        """Get {server_name: [tool_names]} from mcps config."""
        result = {}
        for server_name, config in self.mcps.items():
            if isinstance(config, dict):
                result[server_name] = config.get("tools", [])
            else:
                result[server_name] = []
        return result

    @property
    def sandbox_git_scope(self) -> str | None:
        """Get the git scope from mcps.sandbox.git, or None."""
        sandbox_config = self.mcps.get("sandbox")
        if isinstance(sandbox_config, dict):
            return sandbox_config.get("git")
        return None

    @property
    def coding_networks(self) -> list[str]:
        coding_config = self.mcps.get("coding")
        if isinstance(coding_config, dict):
            return coding_config.get("networks", [])
        return []
