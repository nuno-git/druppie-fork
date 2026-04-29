"""Custom agent domain models."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class CustomAgentSummary(BaseModel):
    """Lightweight custom agent for lists."""

    id: UUID
    agent_id: str
    name: str
    description: str
    category: str
    kind: str = "prompt"
    llm_profile: str
    is_active: bool
    deployment_status: str | None
    is_dirty: bool = False
    created_at: datetime


class CustomAgentDetail(CustomAgentSummary):
    """Full custom agent with all configuration."""

    system_prompt: str
    workflow_yaml: str | None = None
    system_prompts: list[str]
    druppie_runtime_tools: list[str]
    mcps: list[str] | dict[str, list[str]]
    approval_overrides: dict[str, dict]  # tool_key -> {requires_approval, required_role}
    skills: list[str]
    foundry_tools: list[str]  # Foundry-native tools: code_interpreter, file_search, bing_grounding
    foundry_tool_configs: dict[str, dict] = {}  # per-tool config: {"file_search": {"vector_store_ids": [...]}, ...}
    temperature: float
    max_tokens: int
    max_iterations: int
    owner_id: UUID
    deployed_at: datetime | None
    deployed_version: str | None = None
    deployed_spec_hash: str | None = None
    foundry_agent_id: str | None = None
    updated_at: datetime


class CustomAgentCreate(BaseModel):
    """Input model for creating a custom agent."""

    agent_id: str  # kebab-case, validated
    name: str
    description: str = ""
    category: str = "execution"
    system_prompt: str = ""
    system_prompts: list[str] = []
    druppie_runtime_tools: list[str] = []
    mcps: list[str] | dict[str, list[str]] = []
    approval_overrides: dict[str, dict] = {}
    skills: list[str] = []
    foundry_tools: list[str] = []
    llm_profile: str = "standard"
    temperature: float = 0.1
    max_tokens: int = 4096
    max_iterations: int = 10

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9-]*$", v):
            raise ValueError(
                "agent_id must be kebab-case: start with lowercase letter, "
                "followed by lowercase letters, digits, or hyphens"
            )
        return v


class CustomAgentUpdate(BaseModel):
    """Input model for updating a custom agent. All fields optional."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    system_prompt: str | None = None
    system_prompts: list[str] | None = None
    druppie_runtime_tools: list[str] | None = None
    mcps: list[str] | dict[str, list[str]] | None = None
    approval_overrides: dict[str, dict] | None = None
    skills: list[str] | None = None
    foundry_tools: list[str] | None = None
    foundry_tool_configs: dict[str, dict] | None = None
    llm_profile: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_iterations: int | None = None
    is_active: bool | None = None
