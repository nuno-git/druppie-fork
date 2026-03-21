"""Tests for evaluation YAML schema validation."""

import pytest
from pydantic import ValidationError
from druppie.testing.eval_schema import (
    ContextSource,
    RubricDefinition,
    EvaluationDefinition,
    EvaluationFile,
)


def test_minimal_evaluation():
    """Name, target_agent, and one rubric are sufficient."""
    ev = EvaluationDefinition(
        name="basic_eval",
        target_agent="architect",
        rubrics=[
            RubricDefinition(
                name="quality",
                scoring="binary",
                prompt="Is the output good? {{design_document}}",
            ),
        ],
    )
    assert ev.name == "basic_eval"
    assert ev.target_agent == "architect"
    assert len(ev.rubrics) == 1
    assert ev.rubrics[0].name == "quality"


def test_full_evaluation():
    """Evaluation with description, judge_model, context sources, multiple rubrics."""
    ev = EvaluationDefinition(
        name="architect_design_quality",
        description="Evaluates technical design documents",
        target_agent="architect",
        judge_model="claude-opus-4-6",
        context=[
            ContextSource(
                source="tool_call_result",
                tool="coding:make_design",
                **{"as": "design_document"},
            ),
            ContextSource(
                source="session_messages",
                role="user",
                **{"as": "original_request"},
            ),
        ],
        rubrics=[
            RubricDefinition(
                name="requirement_coverage",
                scoring="graded",
                prompt="Score the design: {{design_document}}",
            ),
            RubricDefinition(
                name="language_check",
                scoring="binary",
                prompt="Is it in Dutch? {{design_document}}",
            ),
        ],
    )
    assert ev.description == "Evaluates technical design documents"
    assert ev.judge_model == "claude-opus-4-6"
    assert len(ev.context) == 2
    assert len(ev.rubrics) == 2
    assert ev.context[0].as_name == "design_document"
    assert ev.context[1].role == "user"


def test_context_source_alias():
    """The 'as' YAML key maps to 'as_name' in Python."""
    # Using the alias (as YAML would provide)
    cs = ContextSource(source="all_tool_calls", **{"as": "tool_calls"})
    assert cs.as_name == "tool_calls"

    # Using the field name directly
    cs2 = ContextSource(source="all_tool_calls", as_name="tool_calls")
    assert cs2.as_name == "tool_calls"


def test_invalid_scoring_rejected():
    """Scoring must be 'binary' or 'graded'."""
    with pytest.raises(ValidationError):
        RubricDefinition(
            name="bad_rubric",
            scoring="percentage",
            prompt="Score this.",
        )


def test_missing_rubrics_rejected():
    """Rubrics list is required."""
    with pytest.raises(ValidationError):
        EvaluationDefinition(
            name="no_rubrics",
            target_agent="architect",
        )


def test_rubric_with_context_extra():
    """A rubric can add its own context sources."""
    rubric = RubricDefinition(
        name="with_extra_context",
        scoring="graded",
        prompt="Evaluate: {{extra_data}}",
        context_extra=[
            ContextSource(
                source="tool_call_arguments",
                tool="builtin:done",
                **{"as": "extra_data"},
            ),
        ],
    )
    assert len(rubric.context_extra) == 1
    assert rubric.context_extra[0].source == "tool_call_arguments"
    assert rubric.context_extra[0].tool == "builtin:done"
    assert rubric.context_extra[0].as_name == "extra_data"


def test_evaluation_file_wrapper():
    """EvaluationFile wraps EvaluationDefinition under 'evaluation' key."""
    ef = EvaluationFile(
        evaluation=EvaluationDefinition(
            name="wrapper_test",
            target_agent="builder",
            rubrics=[
                RubricDefinition(
                    name="basic",
                    scoring="binary",
                    prompt="Pass or fail?",
                ),
            ],
        ),
    )
    assert ef.evaluation.name == "wrapper_test"
    assert ef.evaluation.target_agent == "builder"


def test_defaults():
    """Judge model defaults to claude-sonnet-4-6, description to empty string."""
    ev = EvaluationDefinition(
        name="defaults_test",
        target_agent="planner",
        rubrics=[
            RubricDefinition(
                name="r",
                scoring="binary",
                prompt="check",
            ),
        ],
    )
    assert ev.judge_model == "claude-sonnet-4-6"
    assert ev.description == ""
    assert ev.context == []
