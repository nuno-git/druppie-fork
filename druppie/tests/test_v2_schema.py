"""Tests for v2 testing framework Pydantic schemas."""

import pytest
from pydantic import ValidationError

from druppie.testing.v2_schema import (
    EvalAssertion,
    EvalDefinition,
    EvalFile,
    EvalJudge,
    HITLProfile,
    HITLProfilesFile,
    JudgeProfile,
    JudgeProfilesFile,
    TestDefinition,
    TestEvalRef,
    TestFile,
    TestInlineEvaluate,
    TestInlineJudge,
    TestRun,
)


# --- Eval Schema ---


def test_parse_minimal_eval():
    """Eval with just a name is valid."""
    ed = EvalDefinition(name="smoke-test")
    assert ed.name == "smoke-test"
    assert ed.description == ""
    assert ed.tags == []
    assert ed.assertions == []
    assert ed.judge is None


def test_parse_full_eval_with_assertions_and_judge():
    """Eval with assertions, judge checks, and tags parses correctly."""
    ed = EvalDefinition(
        name="router-correct-intent",
        description="Router should call set_intent with the correct intent",
        tags=["router", "intent-classification"],
        assertions=[
            EvalAssertion(agent="router", completed=True),
            EvalAssertion(agent="router", tool_called="builtin:set_intent"),
        ],
        judge=EvalJudge(
            checks=[
                "The router should classify the intent correctly",
                "The router should identify the correct project",
            ],
        ),
    )
    assert ed.name == "router-correct-intent"
    assert ed.description == "Router should call set_intent with the correct intent"
    assert ed.tags == ["router", "intent-classification"]
    assert len(ed.assertions) == 2
    assert ed.assertions[0].agent == "router"
    assert ed.assertions[0].completed is True
    assert ed.assertions[0].tool_called is None
    assert ed.assertions[1].tool_called == "builtin:set_intent"
    assert ed.assertions[1].completed is None
    assert ed.judge is not None
    assert len(ed.judge.checks) == 2


def test_eval_file_wrapper():
    """EvalFile wraps EvalDefinition under 'eval' key."""
    ef = EvalFile(
        eval=EvalDefinition(name="test-eval"),
    )
    assert ef.eval.name == "test-eval"


# --- Profile Schema ---


def test_parse_hitl_profiles_file():
    """HITLProfilesFile parses a dict of named profiles."""
    hpf = HITLProfilesFile(
        profiles={
            "non-technical-pm": HITLProfile(
                model="claude-sonnet-4-6",
                provider="zai",
                prompt="You are a non-technical PM.",
            ),
            "developer": HITLProfile(
                model="claude-haiku-4-5",
                prompt="You are a senior developer.",
            ),
        },
    )
    assert len(hpf.profiles) == 2
    assert hpf.profiles["non-technical-pm"].model == "claude-sonnet-4-6"
    assert hpf.profiles["non-technical-pm"].provider == "zai"
    assert "non-technical" in hpf.profiles["non-technical-pm"].prompt
    assert hpf.profiles["developer"].provider == "deepinfra"  # default


def test_parse_judge_profiles_file():
    """JudgeProfilesFile parses a dict of named profiles."""
    jpf = JudgeProfilesFile(
        profiles={
            "strict-opus": JudgeProfile(model="claude-opus-4-6"),
            "fast-sonnet": JudgeProfile(model="claude-sonnet-4-6", provider="zai"),
        },
    )
    assert len(jpf.profiles) == 2
    assert jpf.profiles["strict-opus"].model == "claude-opus-4-6"
    assert jpf.profiles["strict-opus"].provider == "deepinfra"  # default
    assert jpf.profiles["fast-sonnet"].model == "claude-sonnet-4-6"


# --- Test Schema ---


def test_parse_minimal_test():
    """Test with name and run is valid."""
    td = TestDefinition(
        name="smoke",
        run=TestRun(message="hello"),
    )
    assert td.name == "smoke"
    assert td.run.message == "hello"
    assert td.sessions == []
    assert td.run.real_agents == []
    assert td.hitl is None
    assert td.judge is None
    assert td.judges is None
    assert td.evals == []
    assert td.evaluate is None
    assert td.description == ""


def test_parse_full_test_with_evals_and_profiles():
    """Test with sessions, evals, expected values, and profiles parses correctly."""
    td = TestDefinition(
        name="router-update-weather",
        description="Router picks weather-dashboard from 5 existing projects",
        sessions=["weather-dashboard", "todo-app", "calculator"],
        run=TestRun(
            message="update the weather dashboard to add dark mode",
            real_agents=["router"],
        ),
        hitl="non-technical-pm",
        judge="strict-opus",
        evals=[
            TestEvalRef(
                eval="router-correct-intent",
                expected={
                    "intent": "update_project",
                    "project_name": "weather-dashboard",
                },
            ),
        ],
    )
    assert td.name == "router-update-weather"
    assert td.description == "Router picks weather-dashboard from 5 existing projects"
    assert len(td.sessions) == 3
    assert td.run.message == "update the weather dashboard to add dark mode"
    assert td.run.real_agents == ["router"]
    assert td.hitl == "non-technical-pm"
    assert td.judge == "strict-opus"
    assert len(td.evals) == 1
    assert td.evals[0].eval == "router-correct-intent"
    assert td.evals[0].expected["intent"] == "update_project"
    assert td.evals[0].expected["project_name"] == "weather-dashboard"


def test_get_hitl_profiles_normalization():
    """get_hitl_profiles normalizes various hitl field types to list of names."""
    # None -> ["default"]
    td_none = TestDefinition(name="t", run=TestRun(message="m"), hitl=None)
    assert td_none.get_hitl_profiles() == ["default"]

    # Single string -> [string]
    td_str = TestDefinition(name="t", run=TestRun(message="m"), hitl="non-technical-pm")
    assert td_str.get_hitl_profiles() == ["non-technical-pm"]

    # List of strings -> same list
    td_list = TestDefinition(
        name="t",
        run=TestRun(message="m"),
        hitl=["non-technical-pm", "developer"],
    )
    assert td_list.get_hitl_profiles() == ["non-technical-pm", "developer"]

    # Inline HITLProfile -> ["inline"]
    td_inline = TestDefinition(
        name="t",
        run=TestRun(message="m"),
        hitl=HITLProfile(model="claude-sonnet-4-6", prompt="You are helpful."),
    )
    assert td_inline.get_hitl_profiles() == ["inline"]


def test_get_judge_profiles_normalization():
    """get_judge_profiles normalizes judge/judges fields to list of names."""
    # Neither set -> ["default"]
    td_none = TestDefinition(name="t", run=TestRun(message="m"))
    assert td_none.get_judge_profiles() == ["default"]

    # Single judge -> [judge]
    td_single = TestDefinition(name="t", run=TestRun(message="m"), judge="strict-opus")
    assert td_single.get_judge_profiles() == ["strict-opus"]

    # Multiple judges -> same list
    td_multi = TestDefinition(
        name="t",
        run=TestRun(message="m"),
        judges=["strict-opus", "fast-sonnet"],
    )
    assert td_multi.get_judge_profiles() == ["strict-opus", "fast-sonnet"]

    # judges takes precedence over judge
    td_both = TestDefinition(
        name="t",
        run=TestRun(message="m"),
        judge="cheap-haiku",
        judges=["strict-opus", "fast-sonnet"],
    )
    assert td_both.get_judge_profiles() == ["strict-opus", "fast-sonnet"]


def test_expected_values_exact_wildcard_list():
    """Expected values support exact match, wildcard, and any-of list."""
    ref = TestEvalRef(
        eval="router-correct-intent",
        expected={
            "intent": "update_project",           # exact
            "project_name": "*",                   # wildcard
            "language": ["en", "nl"],              # any-of list
        },
    )
    assert ref.expected["intent"] == "update_project"
    assert ref.expected["project_name"] == "*"
    assert ref.expected["language"] == ["en", "nl"]


def test_inline_evaluate_block():
    """TestDefinition can have an inline evaluate block."""
    td = TestDefinition(
        name="inline-test",
        run=TestRun(message="test message"),
        evaluate=TestInlineEvaluate(
            assertions=[
                EvalAssertion(agent="router", completed=True),
            ],
            judge=TestInlineJudge(
                checks=["Router should not ask the user which project to update"],
            ),
        ),
    )
    assert td.evaluate is not None
    assert len(td.evaluate.assertions) == 1
    assert td.evaluate.assertions[0].agent == "router"
    assert td.evaluate.assertions[0].completed is True
    assert td.evaluate.judge is not None
    assert len(td.evaluate.judge.checks) == 1


def test_test_file_wrapper():
    """TestFile wraps TestDefinition under 'test' key."""
    tf = TestFile(
        test=TestDefinition(
            name="wrapper-test",
            run=TestRun(message="hello"),
        ),
    )
    assert tf.test.name == "wrapper-test"
    assert tf.test.run.message == "hello"


def test_eval_assertion_no_arguments():
    """EvalAssertion does not have an arguments field -- tests provide expected values."""
    ea = EvalAssertion(agent="router", tool_called="builtin:set_intent")
    assert ea.agent == "router"
    assert ea.tool_called == "builtin:set_intent"
    assert ea.completed is None
    assert not hasattr(ea, "arguments")


def test_test_run_empty_real_agents_means_all():
    """Empty real_agents means all agents run for real."""
    tr = TestRun(message="full e2e test")
    assert tr.real_agents == []
