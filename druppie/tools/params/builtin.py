"""Parameter models for builtin tools.

These are tools that are built into the agent runtime and do not require
an MCP server. They handle agent lifecycle, planning, and user interaction.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DoneParams(BaseModel):
    """Signal task completion with a summary.

    The summary is the ONLY way to pass information to the next agent in the pipeline.
    """

    summary: str = Field(
        description=(
            "DETAILED summary including: (1) your own 'Agent [role]:' line with key outputs "
            "(URLs, branch names, container names, file paths). Previous agent summaries are "
            "auto-prepended by the system. NEVER write just 'Task completed'."
        )
    )


class HitlAskQuestionParams(BaseModel):
    """Ask the user a free-form text question.

    Use this when you need clarification or input from the user.
    The workflow will pause until the user responds.
    """

    question: str = Field(description="The question to ask the user")
    context: str | None = Field(default=None, description="Optional context explaining why this question is being asked")


class HitlAskMultipleChoiceQuestionParams(BaseModel):
    """Ask the user a multiple choice question.

    Use this when you want the user to select from predefined options.
    Can optionally allow a custom 'Other' answer.
    """

    question: str = Field(description="The question to ask the user")
    choices: list[str] = Field(description="List of choices for the user to select from")
    allow_other: bool = Field(default=True, description="Whether to allow a custom 'Other' answer")
    context: str | None = Field(default=None, description="Optional context explaining why this question is being asked")


class SetIntentParams(BaseModel):
    """Set the intent for this session.

    Call this to declare what the user wants to do. This must be called before done().
    """

    intent: Literal["create_project", "update_project", "general_chat"] = Field(
        description="The type of user intent"
    )
    project_id: str | None = Field(default=None, description="For update_project: the ID of the project to update")
    project_name: str | None = Field(default=None, description="For create_project: the name for the new project")


class PlanStep(BaseModel):
    """A single step in an execution plan."""

    agent_id: str = Field(description="The agent to run (architect, developer, deployer)")
    prompt: str = Field(description="The task description for the agent")


class MakePlanParams(BaseModel):
    """Create an execution plan.

    Call this to define which agents should run and in what order.
    Each step specifies an agent and the prompt/task for that agent.
    """

    steps: list[PlanStep] = Field(description="List of steps to execute in order")


class CreateMessageParams(BaseModel):
    """Create a visible message in the chat timeline.

    Use this to provide a human-friendly summary of what was accomplished.
    """

    content: str = Field(description="The message content to display to the user")
