"""Tests for the UserSimulator — scripted mode only, no real LLM calls."""

import pytest

from druppie.benchmarks.schema import ScriptedAnswer, UserSimulatorConfig
from druppie.benchmarks.user_simulator import UserSimulator


def _make_simulator(
    scripted_answers: list[ScriptedAnswer] | None = None,
    default_answer: str = "Yes, that sounds good.",
    max_interactions: int = 10,
    mode: str = "scripted",
    model: str | None = None,
) -> UserSimulator:
    """Helper to build a UserSimulator with the given config."""
    config = UserSimulatorConfig(
        mode=mode,
        scripted_answers=scripted_answers or [],
        default_answer=default_answer,
        max_interactions=max_interactions,
        model=model,
    )
    return UserSimulator(config)


class TestScriptedMatch:
    """Matching question returns the scripted answer."""

    def test_scripted_match(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(
                    question_contains="project name",
                    answer="My Awesome Project",
                ),
            ],
        )
        result = sim.answer("What is the project name?")
        assert result == "My Awesome Project"

    def test_scripted_match_partial(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="color", answer="blue"),
            ],
        )
        result = sim.answer("What is your favorite color today?")
        assert result == "blue"


class TestScriptedNoMatch:
    """Non-matching question returns the default answer."""

    def test_scripted_no_match_uses_default(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="banana", answer="yellow"),
            ],
            default_answer="I don't know",
        )
        result = sim.answer("What is the weather?")
        assert result == "I don't know"

    def test_empty_scripted_answers_uses_default(self) -> None:
        sim = _make_simulator(default_answer="Sure thing!")
        result = sim.answer("Anything at all?")
        assert result == "Sure thing!"


class TestScriptedCaseInsensitive:
    """Question matching is case-insensitive."""

    def test_scripted_case_insensitive(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(
                    question_contains="Project Name",
                    answer="My Project",
                ),
            ],
        )
        result = sim.answer("please enter your PROJECT NAME here")
        assert result == "My Project"

    def test_pattern_uppercase_question_lowercase(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="DATABASE", answer="PostgreSQL"),
            ],
        )
        result = sim.answer("which database do you want?")
        assert result == "PostgreSQL"


class TestMaxInteractions:
    """RuntimeError after max_interactions is exceeded."""

    def test_max_interactions_enforced(self) -> None:
        sim = _make_simulator(max_interactions=2)

        sim.answer("Q1")
        sim.answer("Q2")

        with pytest.raises(RuntimeError, match="Exceeded max_interactions"):
            sim.answer("Q3")

    def test_exactly_at_limit_succeeds(self) -> None:
        sim = _make_simulator(max_interactions=1)
        result = sim.answer("Q1")
        assert result == "Yes, that sounds good."


class TestHistoryTracked:
    """History contains all Q&A pairs."""

    def test_history_tracked(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="name", answer="Alice"),
            ],
            default_answer="dunno",
        )

        sim.answer("What is your name?")
        sim.answer("How old are you?")

        history = sim.history
        assert len(history) == 2

        assert history[0].question == "What is your name?"
        assert history[0].answer == "Alice"
        assert history[0].mode_used == "scripted"
        assert history[0].interaction_number == 1

        assert history[1].question == "How old are you?"
        assert history[1].answer == "dunno"
        assert history[1].mode_used == "default"
        assert history[1].interaction_number == 2

    def test_history_is_copy(self) -> None:
        """Mutating the returned history list does not affect the simulator."""
        sim = _make_simulator()
        sim.answer("Q1")

        history = sim.history
        history.clear()

        assert len(sim.history) == 1


class TestInteractionCount:
    """Interaction count increments correctly."""

    def test_interaction_count(self) -> None:
        sim = _make_simulator()
        assert sim.interaction_count == 0

        sim.answer("Q1")
        assert sim.interaction_count == 1

        sim.answer("Q2")
        assert sim.interaction_count == 2

        sim.answer("Q3")
        assert sim.interaction_count == 3


class TestLlmModeRequiresModel:
    """ValueError if llm/hybrid mode has no model set."""

    def test_llm_mode_requires_model(self) -> None:
        sim = _make_simulator(mode="llm", model=None)
        with pytest.raises(ValueError, match="requires 'model'"):
            sim.answer("Hello?")

    def test_hybrid_mode_requires_model_when_no_scripted_match(self) -> None:
        sim = _make_simulator(mode="hybrid", model=None)
        with pytest.raises(ValueError, match="requires 'model'"):
            sim.answer("Something unmatched")


class TestMultipleScriptedAnswers:
    """First matching pattern wins."""

    def test_multiple_scripted_answers(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="name", answer="First match"),
                ScriptedAnswer(question_contains="name", answer="Second match"),
            ],
        )
        result = sim.answer("What is your name?")
        assert result == "First match"

    def test_second_pattern_matches(self) -> None:
        sim = _make_simulator(
            scripted_answers=[
                ScriptedAnswer(question_contains="color", answer="blue"),
                ScriptedAnswer(question_contains="food", answer="pizza"),
            ],
        )
        result = sim.answer("What is your favorite food?")
        assert result == "pizza"
