"""Skill domain models.

Skills are markdown files that get injected into agent conversations when invoked.
They provide reusable prompts/instructions for common tasks.
"""

from pydantic import BaseModel


class SkillSummary(BaseModel):
    """Lightweight skill for lists and discovery."""
    name: str
    description: str


class SkillDetail(SkillSummary):
    """Full skill with prompt content. Inherits from SkillSummary."""
    prompt_content: str  # The markdown body (instructions)
