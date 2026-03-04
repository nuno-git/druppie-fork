"""Parameter models for registry MCP tools.

These define the parameter types for validation. Descriptions come from
mcp_config.yaml - these models are purely for type-safe validation.
"""

from pydantic import BaseModel, Field


class ListComponentsParams(BaseModel):
    category: str = Field(default="", description="Filter by category: agents, skills, mcps, builtin_tools (empty = all)")


class GetAgentParams(BaseModel):
    agent_id: str = Field(description="Agent identifier (e.g., architect, developer, planner)")


class GetSkillParams(BaseModel):
    skill_name: str = Field(description="Skill name (e.g., code-review, architecture-principles)")


class GetMcpServerParams(BaseModel):
    server_name: str = Field(description="MCP server name (e.g., coding, docker, archimate)")


class GetToolParams(BaseModel):
    server_name: str = Field(description="MCP server name")
    tool_name: str = Field(description="Tool name within the server")
