"""Tests for the LLM-as-Judge evaluation engine."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from druppie.db.models import (
    AgentRun,
    Base,
    BenchmarkRun,
    EvaluationResult,
    LlmCall,
    Message,
    Session,
    ToolCall,
    User,
)
from druppie.testing.eval_judge import JudgeEngine


# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as test_fixture_loader)
# ---------------------------------------------------------------------------


class _SQLiteUUID(TypeDecorator):
    """Store Python uuid.UUID as a String(36) in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


_patched = False


def _patch_uuid_columns_for_sqlite(base):
    global _patched
    if _patched:
        return
    for table in base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, PG_UUID):
                col.type = _SQLiteUUID()
    _patched = True


# ---------------------------------------------------------------------------
# Fixtures (pytest)
# ---------------------------------------------------------------------------

EVALUATIONS_DIR = Path(__file__).resolve().parents[2] / "testing" / "evaluations"


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite DB, create all tables, yield a session."""
    engine = create_engine("sqlite:///:memory:")
    _patch_uuid_columns_for_sqlite(Base)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def engine():
    """Return a JudgeEngine pointing at the real evaluations/ directory."""
    return JudgeEngine(evaluations_dir=EVALUATIONS_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed UUIDs for test data
_SESSION_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()
_AGENT_RUN_ID = uuid.uuid4()
_BENCHMARK_RUN_ID = uuid.uuid4()
_LLM_CALL_ID = uuid.uuid4()


def _seed_session(db: DbSession) -> None:
    """Seed a minimal session with a completed architect agent run + LLM call + tool calls."""
    user = User(id=_USER_ID, username="admin", email="admin@test.com")
    db.add(user)
    db.flush()

    session = Session(
        id=_SESSION_ID,
        user_id=_USER_ID,
        title="Test Session",
        status="completed",
        intent="create_project",
    )
    db.add(session)
    db.flush()

    agent_run = AgentRun(
        id=_AGENT_RUN_ID,
        session_id=_SESSION_ID,
        agent_id="architect",
        status="completed",
        sequence_number=0,
        planned_prompt="Design the system",
        iteration_count=1,
    )
    db.add(agent_run)
    db.flush()

    llm_call = LlmCall(
        id=_LLM_CALL_ID,
        session_id=_SESSION_ID,
        agent_run_id=_AGENT_RUN_ID,
        provider="zai",
        model="glm-4.7",
        prompt_tokens=3000,
        completion_tokens=1000,
        total_tokens=4000,
    )
    db.add(llm_call)
    db.flush()

    # Tool call: coding:make_design
    tc1 = ToolCall(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        agent_run_id=_AGENT_RUN_ID,
        llm_call_id=_LLM_CALL_ID,
        mcp_server="coding",
        tool_name="make_design",
        tool_call_index=0,
        arguments={"design": "REST API design document"},
        status="completed",
        result="Design document created successfully",
    )
    db.add(tc1)

    # Tool call: builtin:done
    tc2 = ToolCall(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        agent_run_id=_AGENT_RUN_ID,
        llm_call_id=_LLM_CALL_ID,
        mcp_server="builtin",
        tool_name="done",
        tool_call_index=1,
        arguments={"summary": "Architecture complete"},
        status="completed",
        result="Architecture complete",
    )
    db.add(tc2)

    # User message
    msg = Message(
        id=uuid.uuid4(),
        session_id=_SESSION_ID,
        agent_run_id=None,
        role="user",
        content="Build a todo app with REST API",
        sequence_number=0,
    )
    db.add(msg)

    db.flush()


# ===========================================================================
# Test cases
# ===========================================================================


class TestRenderPrompt:
    """1. Verify {{variable}} replacement works."""

    def test_render_prompt(self, engine: JudgeEngine):
        template = "User asked: {{request}}\nDesign: {{design}}"
        context = {"request": "Build a todo app", "design": "REST API with CRUD"}
        result = engine._render_prompt(template, context)
        assert result == "User asked: Build a todo app\nDesign: REST API with CRUD"

    def test_render_prompt_no_variables(self, engine: JudgeEngine):
        template = "No variables here"
        result = engine._render_prompt(template, {})
        assert result == "No variables here"

    def test_render_prompt_missing_variable(self, engine: JudgeEngine):
        template = "Value: {{missing}}"
        result = engine._render_prompt(template, {})
        assert result == "Value: {{missing}}"


class TestParseScoreBinary:
    """2-3. Parse binary scores."""

    def test_parse_score_binary_pass(self, engine: JudgeEngine):
        response = '{"pass": true, "reasoning": "good"}'
        score_binary, score_graded, max_score, reasoning = engine._parse_score(
            response, "binary"
        )
        assert score_binary is True
        assert score_graded is None
        assert max_score is None
        assert reasoning == "good"

    def test_parse_score_binary_fail(self, engine: JudgeEngine):
        response = '{"pass": false, "reasoning": "bad"}'
        score_binary, score_graded, max_score, reasoning = engine._parse_score(
            response, "binary"
        )
        assert score_binary is False
        assert score_graded is None
        assert max_score is None
        assert reasoning == "bad"


class TestParseScoreGraded:
    """4. Parse graded scores."""

    def test_parse_score_graded(self, engine: JudgeEngine):
        response = '{"score": 4, "reasoning": "solid"}'
        score_binary, score_graded, max_score, reasoning = engine._parse_score(
            response, "graded"
        )
        assert score_binary is None
        assert score_graded == 4.0
        assert max_score == 5.0
        assert reasoning == "solid"


class TestParseScoreMalformedJson:
    """5. Invalid JSON returns None scores with error reasoning."""

    def test_parse_score_malformed_json(self, engine: JudgeEngine):
        response = "not valid json at all"
        score_binary, score_graded, max_score, reasoning = engine._parse_score(
            response, "binary"
        )
        assert score_binary is None
        assert score_graded is None
        assert max_score is None
        assert "Failed to parse" in reasoning


class TestParseScoreMarkdownWrapped:
    """6. Response wrapped in ```json ... ``` parses correctly."""

    def test_parse_score_markdown_wrapped(self, engine: JudgeEngine):
        response = '```json\n{"score": 3, "reasoning": "decent"}\n```'
        score_binary, score_graded, max_score, reasoning = engine._parse_score(
            response, "graded"
        )
        assert score_binary is None
        assert score_graded == 3.0
        assert max_score == 5.0
        assert reasoning == "decent"


class TestEvaluateCreatesResults:
    """7. Full evaluate() flow with mocked judge."""

    def test_evaluate_creates_results(
        self, db_session: DbSession, engine: JudgeEngine
    ):
        _seed_session(db_session)

        # Create a benchmark run
        benchmark_run = BenchmarkRun(
            id=_BENCHMARK_RUN_ID,
            name="test-bench",
            run_type="manual",
            judge_model="claude-sonnet-4-6",
        )
        db_session.add(benchmark_run)
        db_session.flush()

        # Mock judge function
        def mock_judge(prompt, model):
            return '{"score": 4, "reasoning": "good design"}', 100, 500

        results = engine.evaluate(
            db=db_session,
            session_id=_SESSION_ID,
            evaluation_name="architect_design_quality",
            benchmark_run_id=_BENCHMARK_RUN_ID,
            call_judge_fn=mock_judge,
        )

        # The design_quality.yaml has 2 rubrics: requirement_coverage + language_compliance
        assert len(results) == 2

        # Verify results are in the DB
        db_results = db_session.query(EvaluationResult).all()
        assert len(db_results) == 2

        # Check common fields on all results
        for r in results:
            assert r.benchmark_run_id == _BENCHMARK_RUN_ID
            assert r.session_id == _SESSION_ID
            assert r.agent_run_id == _AGENT_RUN_ID
            assert r.agent_id == "architect"
            assert r.evaluation_name == "architect_design_quality"
            assert r.judge_response == '{"score": 4, "reasoning": "good design"}'
            assert r.judge_duration_ms == 100
            assert r.judge_tokens_used == 500
            assert r.llm_model == "glm-4.7"
            assert r.llm_provider == "zai"

        # Check rubric names
        rubric_names = {r.rubric_name for r in results}
        assert rubric_names == {"requirement_coverage", "language_compliance"}

        # The mock always returns {"score": 4, ...} so:
        # - requirement_coverage (graded): score_graded=4.0, max_score=5.0
        # - language_compliance (binary): score_binary is parsed from "score", not "pass"
        #   so it falls through to the graded path — but actually scoring="binary"
        #   so it looks for "pass" key which is absent, defaults to False
        for r in results:
            if r.rubric_name == "requirement_coverage":
                assert r.score_type == "graded"
                assert r.score_graded == 4.0
                assert r.max_score == 5.0
            elif r.rubric_name == "language_compliance":
                assert r.score_type == "binary"
                # Mock returns {"score": 4, ...} which has no "pass" key,
                # so binary scoring defaults to False
                assert r.score_binary is False

        # Verify judge prompt contains rendered context
        for r in results:
            # The prompt should NOT contain raw {{variable}} placeholders
            # (though some might remain if context extraction returned empty)
            assert r.judge_prompt is not None
            assert len(r.judge_prompt) > 0


class TestEvaluateUnknownEvaluation:
    """8. Unknown evaluation raises KeyError."""

    def test_evaluate_unknown_evaluation(
        self, db_session: DbSession, engine: JudgeEngine
    ):
        with pytest.raises(KeyError, match="Unknown evaluation"):
            engine.evaluate(
                db=db_session,
                session_id=_SESSION_ID,
                evaluation_name="nonexistent_evaluation",
                benchmark_run_id=_BENCHMARK_RUN_ID,
            )


class TestEvaluateNoCompletedRun:
    """9. No completed run for target agent raises ValueError."""

    def test_evaluate_no_completed_run(
        self, db_session: DbSession, engine: JudgeEngine
    ):
        # Create a session with no agent runs
        user = User(id=_USER_ID, username="admin", email="admin@test.com")
        db_session.add(user)
        db_session.flush()

        session = Session(
            id=_SESSION_ID,
            user_id=_USER_ID,
            title="Empty Session",
            status="active",
        )
        db_session.add(session)
        db_session.flush()

        with pytest.raises(ValueError, match="No completed run"):
            engine.evaluate(
                db=db_session,
                session_id=_SESSION_ID,
                evaluation_name="architect_design_quality",
                benchmark_run_id=_BENCHMARK_RUN_ID,
            )


class TestAvailableEvaluations:
    """10. Lists loaded evaluation names."""

    def test_available_evaluations(self, engine: JudgeEngine):
        names = engine.available_evaluations
        assert isinstance(names, list)
        assert len(names) > 0
        assert "architect_design_quality" in names
        # Verify sorted
        assert names == sorted(names)
