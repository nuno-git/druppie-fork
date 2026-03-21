"""Tests for benchmark scenario YAML schema validation."""

import pytest
from pydantic import ValidationError

from druppie.benchmarks.schema import (
    Assertion,
    ApprovalSimulationConfig,
    MockedAgent,
    ScenarioDefinition,
    ScenarioFile,
    ScenarioInput,
    ScriptedAnswer,
    UserSimulatorConfig,
)
from druppie.fixtures.schema import ToolCallFixture


def test_minimal_scenario():
    """Name and input are sufficient for a valid scenario."""
    sd = ScenarioDefinition(
        name="smoke",
        input=ScenarioInput(user_message="Build me a todo app"),
    )
    assert sd.name == "smoke"
    assert sd.input.user_message == "Build me a todo app"
    assert sd.input.user == "admin"


def test_full_scenario():
    """Scenario with all fields populated parses correctly."""
    sd = ScenarioDefinition(
        name="full_e2e",
        description="End-to-end project creation benchmark",
        input=ScenarioInput(user_message="Create a REST API", user="developer"),
        agents_under_test=["planner", "architect"],
        mocked_agents=[
            MockedAgent(
                agent_id="builder",
                status="completed",
                tool_calls=[
                    ToolCallFixture(tool="coding:write_file", arguments={"path": "main.py"}),
                ],
                planned_prompt="Build the project",
            ),
        ],
        evaluations=["design_quality", "plan_completeness"],
        assertions=[
            Assertion(agent="architect", **{"assert": "called_tool"}, tool="coding:make_design"),
            Assertion(
                agent="planner",
                **{"assert": "summary_contains"},
                summary_contains="REST API",
            ),
        ],
        user_simulator=UserSimulatorConfig(
            mode="scripted",
            scripted_answers=[
                ScriptedAnswer(question_contains="language", answer="Python"),
            ],
            default_answer="Approved.",
            max_interactions=5,
        ),
        approval_simulation=ApprovalSimulationConfig(mode="selective"),
        timeout_minutes=60,
    )
    assert sd.description == "End-to-end project creation benchmark"
    assert sd.input.user == "developer"
    assert len(sd.agents_under_test) == 2
    assert len(sd.mocked_agents) == 1
    assert sd.mocked_agents[0].agent_id == "builder"
    assert len(sd.mocked_agents[0].tool_calls) == 1
    assert sd.mocked_agents[0].planned_prompt == "Build the project"
    assert len(sd.evaluations) == 2
    assert len(sd.assertions) == 2
    assert sd.assertions[0].assert_type == "called_tool"
    assert sd.assertions[0].tool == "coding:make_design"
    assert sd.assertions[1].assert_type == "summary_contains"
    assert sd.assertions[1].summary_contains == "REST API"
    assert sd.user_simulator.mode == "scripted"
    assert len(sd.user_simulator.scripted_answers) == 1
    assert sd.approval_simulation.mode == "selective"
    assert sd.timeout_minutes == 60


def test_assert_alias():
    """The 'assert' YAML key maps to 'assert_type' in Python."""
    # Using the alias (as YAML would provide)
    a = Assertion(agent="planner", **{"assert": "called_tool"})
    assert a.assert_type == "called_tool"

    # Using the field name directly
    a2 = Assertion(agent="planner", assert_type="called_tool")
    assert a2.assert_type == "called_tool"


def test_invalid_simulator_mode():
    """User simulator mode must be 'scripted', 'llm', or 'hybrid'."""
    with pytest.raises(ValidationError):
        UserSimulatorConfig(mode="random")


def test_mocked_agent_reuses_tool_call_fixture():
    """ToolCallFixture works inside MockedAgent with full fidelity."""
    tc = ToolCallFixture(
        tool="builtin:done",
        arguments={"summary": "All done"},
        status="completed",
        result="success",
    )
    ma = MockedAgent(agent_id="builder", tool_calls=[tc])
    assert ma.tool_calls[0].tool == "builtin:done"
    assert ma.tool_calls[0].mcp_server == "builtin"
    assert ma.tool_calls[0].tool_name == "done"
    assert ma.tool_calls[0].arguments == {"summary": "All done"}
    assert ma.tool_calls[0].result == "success"


def test_defaults():
    """user_simulator, approval_simulation, and timeout default correctly."""
    sd = ScenarioDefinition(
        name="defaults_check",
        input=ScenarioInput(user_message="Hello"),
    )
    assert sd.user_simulator.mode == "scripted"
    assert sd.user_simulator.default_answer == "Yes, that sounds good."
    assert sd.user_simulator.max_interactions == 10
    assert sd.user_simulator.model is None
    assert sd.user_simulator.persona is None
    assert sd.user_simulator.scripted_answers == []
    assert sd.approval_simulation.mode == "auto_approve"
    assert sd.timeout_minutes == 30
    assert sd.description == ""
    assert sd.agents_under_test == []
    assert sd.mocked_agents == []
    assert sd.evaluations == []
    assert sd.assertions == []


def test_scripted_answer():
    """ScriptedAnswer parses question_contains and answer."""
    sa = ScriptedAnswer(question_contains="preferred language", answer="Python")
    assert sa.question_contains == "preferred language"
    assert sa.answer == "Python"


def test_scenario_file_wrapper():
    """ScenarioFile wraps ScenarioDefinition under 'scenario' key."""
    sf = ScenarioFile(
        scenario=ScenarioDefinition(
            name="wrapper_test",
            input=ScenarioInput(user_message="Test message"),
        ),
    )
    assert sf.scenario.name == "wrapper_test"
    assert sf.scenario.input.user_message == "Test message"
