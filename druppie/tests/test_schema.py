"""Tests for testing framework Pydantic schemas."""

import pytest
from pydantic import ValidationError

from druppie.testing.schema import (
    CheckAssertion,
    CheckDefinition,
    CheckFile,
    CheckRef,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    AgentTestDefinition,
    AgentTestFile,
    ToolTestDefinition,
    ToolTestFile,
    ChainStep,
    ChainStepAssert,
    TestInput,
    VerifyCheck,
)


# --- Check Schema ---


def test_parse_minimal_check():
    cd = CheckDefinition(name="smoke-test")
    assert cd.name == "smoke-test"
    assert cd.description == ""
    assert cd.tags == []
    assert cd.assert_ == []
    assert cd.judge is None


def test_parse_full_check():
    cd = CheckDefinition(
        name="router-correct-intent",
        description="Router should call set_intent",
        tags=["router", "intent"],
        **{"assert": [
            CheckAssertion(agent="router", completed=True),
            CheckAssertion(agent="router", tool="builtin:set_intent"),
        ]},
        judge=["The router should classify correctly"],
    )
    assert cd.name == "router-correct-intent"
    assert len(cd.assert_) == 2
    assert cd.assert_[0].completed is True
    assert cd.assert_[1].tool == "builtin:set_intent"
    assert len(cd.judge) == 1


def test_check_file_wrapper():
    cf = CheckFile(check=CheckDefinition(name="test"))
    assert cf.check.name == "test"


def test_check_assertion_tool_field():
    ca = CheckAssertion(agent="router", tool="builtin:set_intent")
    assert ca.tool == "builtin:set_intent"
    assert ca.completed is None


# --- Profile Schema ---


def test_parse_hitl_profiles():
    hpf = HITLProfilesFile(profiles={
        "pm": HITLProfile(model="glm-5", prompt="You are a PM."),
        "dev": HITLProfile(model="glm-5", prompt="You are a dev."),
    })
    assert len(hpf.profiles) == 2
    assert hpf.profiles["pm"].provider == "zai"


def test_parse_judge_profiles():
    jpf = JudgeProfilesFile(profiles={
        "default": JudgeProfile(model="glm-5"),
    })
    assert jpf.profiles["default"].provider == "zai"


# --- Tool Test Schema ---


def test_parse_tool_test():
    tt = ToolTestDefinition(
        name="coding-list-dir",
        tags=["coding"],
        chain=[
            ChainStep(agent="router", tool="builtin:set_intent",
                      arguments={"intent": "create_project"}),
            ChainStep(agent="architect", tool="coding:list_dir",
                      arguments={"path": "."},
                      **{"assert": ChainStepAssert(completed=True, result=["not_empty"])}),
        ],
    )
    assert tt.name == "coding-list-dir"
    assert len(tt.chain) == 2
    assert tt.chain[1].assert_ is not None
    assert tt.chain[1].assert_.result == ["not_empty"]


def test_tool_test_with_setup_and_extends():
    tt = ToolTestDefinition(
        name="extended-test",
        setup=["weather-dashboard"],
        extends="coding-list-dir",
        chain=[ChainStep(agent="architect", tool="coding:read_file", arguments={"path": "README.md"})],
    )
    assert tt.setup == ["weather-dashboard"]
    assert tt.extends == "coding-list-dir"


def test_tool_test_with_mock():
    step = ChainStep(
        agent="architect", tool="coding:execute_coding_task",
        arguments={"task": "create file"},
        mock=True, mock_result='{"status": "ok"}',
    )
    assert step.mock is True
    assert step.mock_result == '{"status": "ok"}'


def test_tool_test_file_wrapper():
    data = {
        "tool-test": {
            "name": "test",
            "chain": [{"agent": "router", "tool": "builtin:done", "arguments": {}}],
        }
    }
    ttf = ToolTestFile(**data)
    assert ttf.tool_test.name == "test"


# --- Agent Test Schema ---


def test_parse_minimal_agent_test():
    at = AgentTestDefinition(name="smoke", message="hello")
    assert at.name == "smoke"
    assert at.message == "hello"
    assert at.agents == []
    assert at.setup == []
    assert at.assert_ == []
    assert at.judge is None
    assert at.hitl is None
    assert at.is_manual is False


def test_parse_full_agent_test():
    at = AgentTestDefinition(
        name="router-update",
        description="Router picks correct project",
        tags=["router"],
        setup=["weather-dashboard", "todo-app"],
        message="update the weather dashboard",
        agents=["router"],
        hitl="non-technical-pm",
        **{"assert": [
            CheckRef(check="router-correct-intent", expected={"intent": "update_project"}),
        ]},
        judge=["The router should pick the correct project"],
    )
    assert at.setup == ["weather-dashboard", "todo-app"]
    assert at.agents == ["router"]
    assert at.hitl == "non-technical-pm"
    assert len(at.assert_) == 1
    assert at.assert_[0].check == "router-correct-intent"
    assert at.assert_[0].expected["intent"] == "update_project"
    assert len(at.judge) == 1


def test_agent_test_with_extends():
    at = AgentTestDefinition(
        name="extended-agent",
        extends="coding-list-dir",
        message="review project",
        agents=["architect"],
    )
    assert at.extends == "coding-list-dir"


def test_manual_agent_test():
    at = AgentTestDefinition(
        name="manual-test",
        message="{{user_input}}",
        agents=["router"],
        inputs=[
            TestInput(name="user_input", label="Your message", type="textarea"),
        ],
    )
    assert at.is_manual is True
    assert len(at.inputs) == 1

    resolved = at.resolve_inputs({"user_input": "build me an app"})
    assert resolved.message == "build me an app"


def test_get_hitl_profiles():
    # None -> ["default"]
    at = AgentTestDefinition(name="t", message="m")
    assert at.get_hitl_profiles() == ["default"]

    # String -> [string]
    at = AgentTestDefinition(name="t", message="m", hitl="pm")
    assert at.get_hitl_profiles() == ["pm"]

    # List -> same
    at = AgentTestDefinition(name="t", message="m", hitl=["pm", "dev"])
    assert at.get_hitl_profiles() == ["pm", "dev"]


def test_agent_test_file_wrapper():
    data = {
        "agent-test": {
            "name": "test",
            "message": "hello",
            "agents": ["router"],
        }
    }
    atf = AgentTestFile(**data)
    assert atf.agent_test.name == "test"
    assert atf.agent_test.agents == ["router"]


def test_check_ref_expected_values():
    ref = CheckRef(
        check="router-correct-intent",
        expected={
            "intent": "update_project",
            "project_name": "*",
            "language": ["en", "nl"],
        },
    )
    assert ref.expected["intent"] == "update_project"
    assert ref.expected["project_name"] == "*"
    assert ref.expected["language"] == ["en", "nl"]


def test_verify_check():
    vc = VerifyCheck(file_exists="docs/fd.md")
    assert vc.file_exists == "docs/fd.md"
    assert vc.file_not_empty is None


# --- YAML parsing from actual files ---


def test_parse_check_yaml_file():
    """Parse an actual check YAML file."""
    import yaml
    from pathlib import Path

    check_path = Path(__file__).resolve().parents[2] / "testing" / "checks" / "router-correct-intent.yaml"
    if not check_path.exists():
        pytest.skip("check file not found")

    data = yaml.safe_load(check_path.read_text())
    cf = CheckFile(**data)
    assert cf.check.name == "router-correct-intent"
    assert len(cf.check.assert_) == 2
    assert len(cf.check.judge) >= 1


def test_parse_tool_test_yaml_file():
    """Parse an actual tool test YAML file."""
    import yaml
    from pathlib import Path

    tool_path = Path(__file__).resolve().parents[2] / "testing" / "tools" / "coding-list-dir.yaml"
    if not tool_path.exists():
        pytest.skip("tool test file not found")

    data = yaml.safe_load(tool_path.read_text())
    ttf = ToolTestFile(**data)
    assert ttf.tool_test.name == "coding-list-dir"
    assert len(ttf.tool_test.chain) >= 3


def test_parse_agent_test_yaml_file():
    """Parse an actual agent test YAML file."""
    import yaml
    from pathlib import Path

    agent_path = Path(__file__).resolve().parents[2] / "testing" / "agents" / "router-create-recipe.yaml"
    if not agent_path.exists():
        pytest.skip("agent test file not found")

    data = yaml.safe_load(agent_path.read_text())
    atf = AgentTestFile(**data)
    assert atf.agent_test.name == "router-create-recipe"
    assert atf.agent_test.agents == ["router"]
    assert len(atf.agent_test.assert_) >= 1
