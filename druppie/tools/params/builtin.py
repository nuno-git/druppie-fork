"""Parameter models for builtin tools.

These define the parameter types for validation. Descriptions come from
builtin_tools.py - these models are purely for type-safe validation.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DoneParams(BaseModel):
    summary: str = Field(
        description=(
            "DETAILED summary including: (1) your own 'Agent [role]:' line with key outputs "
            "(URLs, branch names, container names, file paths). Previous agent summaries are "
            "auto-prepended by the system. NEVER write just 'Task completed'."
        )
    )


class HitlAskQuestionParams(BaseModel):
    question: str = Field(description="The question to ask the user")
    context: str | None = Field(default=None, description="Optional context explaining why this question is being asked")


class HitlAskMultipleChoiceQuestionParams(BaseModel):
    question: str = Field(description="The question to ask the user")
    choices: list[str] = Field(description="List of choices for the user to select from")
    allow_other: bool = Field(default=True, description="Whether to allow a custom 'Other' answer")
    allow_multiple: bool = Field(default=False, description="Whether to allow selecting multiple choices")
    context: str | None = Field(default=None, description="Optional context explaining why this question is being asked")


class SetIntentParams(BaseModel):
    intent: Literal["create_project", "update_project", "general_chat"] = Field(
        description="The type of user intent"
    )
    project_id: str | None = Field(default=None, description="For update_project: the ID of the project to update")
    project_name: str | None = Field(default=None, description="For create_project: the name for the new project")


class PlanStep(BaseModel):
    agent_id: str = Field(description="The agent to run (architect, developer, deployer)")
    prompt: str = Field(description="The task description for the agent")


class MakePlanParams(BaseModel):
    steps: list[PlanStep] = Field(description="List of steps to execute in order")


class CreateMessageParams(BaseModel):
    content: str = Field(description="The message content to display to the user")


class InvokeSkillParams(BaseModel):
    skill_name: str = Field(description="The name of the skill to invoke (e.g., 'code-review', 'git-workflow')")
