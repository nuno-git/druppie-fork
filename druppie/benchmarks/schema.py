"""Pydantic schema for benchmark scenario YAML definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

from druppie.fixtures.schema import ToolCallFixture


class ScenarioInput(BaseModel):
    """The initial user message and identity for a benchmark scenario."""
    user_message: str
    user: str = "admin"


class MockedAgent(BaseModel):
    """An agent whose behaviour is predetermined (not under test)."""
    agent_id: str
    status: str = "completed"
    tool_calls: list[ToolCallFixture] = Field(default_factory=list)
    planned_prompt: str | None = None
    error_message: str | None = None


class ScriptedAnswer(BaseModel):
    """Maps a question pattern to a canned answer for the user simulator."""
    question_contains: str
    answer: str


class UserSimulatorConfig(BaseModel):
    """Controls how HITL questions are answered during a benchmark run."""
    mode: Literal["scripted", "llm", "hybrid"] = "scripted"
    model: str | None = None
    persona: str | None = None
    scripted_answers: list[ScriptedAnswer] = Field(default_factory=list)
    default_answer: str = "Yes, that sounds good."
    max_interactions: int = 10


class ApprovalSimulationConfig(BaseModel):
    """Controls how tool-approval requests are handled during a benchmark run."""
    mode: Literal["auto_approve", "auto_reject", "selective"] = "auto_approve"


class Assertion(BaseModel):
    """A single assertion to verify after a scenario completes."""
    model_config = ConfigDict(populate_by_name=True)

    agent: str
    assert_type: str = Field(alias="assert")
    tool: str | None = None
    summary_contains: str | None = None


class ScenarioDefinition(BaseModel):
    """Root model for a benchmark scenario."""
    name: str
    description: str = ""
    input: ScenarioInput
    agents_under_test: list[str] = Field(default_factory=list)
    mocked_agents: list[MockedAgent] = Field(default_factory=list)
    evaluations: list[str] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    user_simulator: UserSimulatorConfig = Field(default_factory=UserSimulatorConfig)
    approval_simulation: ApprovalSimulationConfig = Field(
        default_factory=ApprovalSimulationConfig,
    )
    timeout_minutes: int = 30


class ScenarioFile(BaseModel):
    """Wrapper for the YAML file root (has 'scenario' key)."""
    scenario: ScenarioDefinition
