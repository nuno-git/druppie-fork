"""Skill domain models.

Skills are markdown files that get injected into agent conversations when invoked.
They provide reusable prompts/instructions for common tasks.
"""

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    """Lightweight skill for lists and discovery."""
    name: str
    description: str


class SkillDetail(SkillSummary):
    """Full skill with prompt content. Inherits from SkillSummary."""
    prompt_content: str  # The markdown body (instructions)
    # Allowed tools: mcp_name -> list of tool names
    # e.g. {"coding": ["read_file", "write_file"], "docker": ["build"]}
    allowed_tools: dict[str, list[str]] = Field(default_factory=dict)
