"""Pydantic schema for evaluation YAML definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class ContextSource(BaseModel):
    """Declarative context extraction directive."""
    model_config = ConfigDict(populate_by_name=True)

    source: str  # "all_tool_calls", "session_messages", "agent_definition",
                 # "tool_call_result", "tool_call_arguments"
    tool: str | None = None      # Filter by tool name, e.g. "coding:make_design"
    role: str | None = None      # Filter messages by role
    field: str | None = None     # Extract specific field from source
    as_name: str = Field(alias="as")  # Template variable name


class RubricDefinition(BaseModel):
    """A single rubric (scoring dimension) within an evaluation."""
    name: str
    scoring: Literal["binary", "graded"]
    prompt: str  # Template with {{variable}} placeholders
    context_extra: list[ContextSource] = Field(default_factory=list)


class EvaluationDefinition(BaseModel):
    """Root model for an evaluation definition."""
    name: str
    description: str = ""
    target_agent: str
    judge_model: str = "glm-5"
    context: list[ContextSource] = Field(default_factory=list)
    rubrics: list[RubricDefinition]


class EvaluationFile(BaseModel):
    """Wrapper for the YAML file root (has 'evaluation' key)."""
    evaluation: EvaluationDefinition
