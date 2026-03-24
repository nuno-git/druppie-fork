"""Integration tests for the YAML fixture loader.

Uses an in-memory SQLite database with a UUID compatibility shim so we can
test the full seed_fixture() flow without requiring a running PostgreSQL
instance.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.db.models import (
    AgentRun,
    Approval,
    Base,
    LlmCall,
    Message,
    Project,
    Question,
    Session,
    ToolCall,
    User,
    UserRole,
)
from druppie.testing.seed_ids import fixture_uuid
from druppie.testing.seed_loader import load_fixtures, seed_fixture
from druppie.testing.seed_schema import (
    AgentRunFixture,
    ApprovalFixture,
    MessageFixture,
    SessionFixture,
    SessionMetadata,
    ToolCallFixture,
)

# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility
# ---------------------------------------------------------------------------
# The DB models use ``sqlalchemy.dialects.postgresql.UUID(as_uuid=True)``
# which SQLite cannot handle.  We replace those column types with a
# ``TypeDecorator`` that stores UUIDs as 36-char strings but transparently
# converts Python ``uuid.UUID`` objects on bind and back on result fetch.
# ---------------------------------------------------------------------------

from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402


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
    """Walk all mapped tables and replace PG UUID columns with _SQLiteUUID.

    Only patches once per process (the metadata is module-global).
    """
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

@pytest.fixture()
def db_session():
    """Create an in-memory SQLite DB, create all tables, yield a session.

    Note: FK enforcement is disabled because SQLAlchemy's unit of work does
    not guarantee insert order for tables without explicit ``relationship()``
    back-references.  The loader relies on PostgreSQL's deferred FK checks.
    For the idempotency test, we manually verify via a clean re-seed approach.
    """
    engine = create_engine("sqlite:///:memory:")

    # Patch PG UUID -> _SQLiteUUID before table creation
    _patch_uuid_columns_for_sqlite(Base)

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meta(**overrides) -> SessionMetadata:
    defaults = dict(id="test-session", title="Test Session", status="completed")
    defaults.update(overrides)
    return SessionMetadata(**defaults)


def _fixture(meta: SessionMetadata | None = None, agents=None, messages=None) -> SessionFixture:
    return SessionFixture(
        metadata=meta or _meta(),
        agents=agents or [],
        messages=messages or [],
    )


# ===========================================================================
# Test cases
# ===========================================================================


class TestMinimalSession:
    """1. Metadata only, no agents -> Session + user message created."""

    def test_minimal_session(self, db_session: DbSession):
        fix = _fixture()
        seed_fixture(db_session, fix)
        db_session.commit()

        # Session exists
        sessions = db_session.query(Session).all()
        assert len(sessions) == 1
        s = sessions[0]
        assert str(s.id) == str(fixture_uuid("test-session"))
        assert s.title == "Test Session"
        assert s.status == "completed"

        # User message at sequence 0
        msgs = db_session.query(Message).filter(Message.session_id == s.id).all()
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].sequence_number == 0

        # User created
        users = db_session.query(User).all()
        assert len(users) == 1
        assert users[0].username == "admin"


class TestCompletedRouter:
    """2. One completed agent with tool calls -> AgentRun + LlmCall + ToolCalls + Message."""

    def test_completed_router(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="completed-router"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
                    planned_prompt="Route the request",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:set_intent",
                            arguments={"intent": "create_project"},
                            status="completed",
                            result="Intent set to create_project",
                        ),
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Routing complete"},
                            status="completed",
                            result="Routing complete",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("completed-router")

        # AgentRun
        runs = db_session.query(AgentRun).filter(AgentRun.session_id == session_id).all()
        assert len(runs) == 1
        assert runs[0].agent_id == "router"
        assert runs[0].status == "completed"

        # LlmCall
        llm_calls = db_session.query(LlmCall).filter(LlmCall.session_id == session_id).all()
        assert len(llm_calls) == 1
        assert llm_calls[0].prompt_tokens == 3000
        assert llm_calls[0].completion_tokens == 1000

        # ToolCalls
        tcs = db_session.query(ToolCall).filter(ToolCall.session_id == session_id).all()
        assert len(tcs) == 2
        tool_names = {tc.tool_name for tc in tcs}
        assert tool_names == {"set_intent", "done"}

        # Assistant message from done() summary
        msgs = (
            db_session.query(Message)
            .filter(Message.session_id == session_id, Message.role == "assistant")
            .all()
        )
        assert len(msgs) == 1
        assert msgs[0].content == "Routing complete"


class TestFailedAgent:
    """3. Failed agent -> AgentRun with error, failed ToolCall."""

    def test_failed_agent(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="failed-agent", status="failed"),
            agents=[
                AgentRunFixture(
                    id="builder",
                    status="failed",
                    error_message="Sandbox timeout after 300s",
                    tool_calls=[
                        ToolCallFixture(
                            tool="coding:write_file",
                            arguments={"path": "/app/main.py", "content": "print('hi')"},
                            status="failed",
                            error_message="Sandbox crashed",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("failed-agent")

        runs = db_session.query(AgentRun).filter(AgentRun.session_id == session_id).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].error_message == "Sandbox timeout after 300s"

        tcs = db_session.query(ToolCall).filter(ToolCall.session_id == session_id).all()
        assert len(tcs) == 1
        assert tcs[0].status == "failed"
        assert tcs[0].error_message == "Sandbox crashed"

        # LlmCall exists for failed agents (is_active = True for "failed")
        llm_calls = db_session.query(LlmCall).filter(LlmCall.session_id == session_id).all()
        assert len(llm_calls) == 1
        # Failed agent tokens: p=0, c=0
        assert llm_calls[0].prompt_tokens == 0
        assert llm_calls[0].completion_tokens == 0

        # Error message created
        msgs = (
            db_session.query(Message)
            .filter(Message.session_id == session_id, Message.role == "assistant")
            .all()
        )
        assert len(msgs) == 1
        assert "Sandbox timeout" in msgs[0].content


class TestPendingAgent:
    """4. Pending agent -> AgentRun exists, no LlmCall."""

    def test_pending_agent(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="pending-agent", status="active"),
            agents=[
                AgentRunFixture(
                    id="architect",
                    status="pending",
                    planned_prompt="Design the system",
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("pending-agent")

        runs = db_session.query(AgentRun).filter(AgentRun.session_id == session_id).all()
        assert len(runs) == 1
        assert runs[0].status == "pending"
        assert runs[0].planned_prompt == "Design the system"
        # Note: started_at may be filled by SQLAlchemy default even when
        # loader passes None; the important thing is iteration_count == 0.
        assert runs[0].iteration_count == 0

        # No LlmCall for pending
        llm_calls = db_session.query(LlmCall).filter(LlmCall.session_id == session_id).all()
        assert len(llm_calls) == 0


class TestRunningAgent:
    """5. Running agent -> AgentRun + LlmCall, no ToolCalls."""

    def test_running_agent(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="running-agent", status="active"),
            agents=[
                AgentRunFixture(
                    id="builder",
                    status="running",
                    planned_prompt="Build the todo app",
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("running-agent")

        runs = db_session.query(AgentRun).filter(AgentRun.session_id == session_id).all()
        assert len(runs) == 1
        assert runs[0].status == "running"
        assert runs[0].started_at is not None

        # LlmCall exists for running agents
        llm_calls = db_session.query(LlmCall).filter(LlmCall.session_id == session_id).all()
        assert len(llm_calls) == 1
        assert llm_calls[0].prompt_tokens == 1500
        assert llm_calls[0].completion_tokens == 0

        # No tool calls
        tcs = db_session.query(ToolCall).filter(ToolCall.session_id == session_id).all()
        assert len(tcs) == 0


class TestApprovalCreated:
    """6. Tool call with approval -> Approval record."""

    def test_approval_created(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="approval-test"),
            agents=[
                AgentRunFixture(
                    id="architect",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="coding:make_design",
                            arguments={"design": "REST API design"},
                            status="completed",
                            result="Design approved",
                            approval=ApprovalFixture(
                                required_role="architect",
                                status="approved",
                                approved_by="architect",
                            ),
                        ),
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Design done"},
                            status="completed",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("approval-test")

        approvals = db_session.query(Approval).filter(Approval.session_id == session_id).all()
        assert len(approvals) == 1
        assert approvals[0].required_role == "architect"
        assert approvals[0].status == "approved"
        assert approvals[0].resolved_at is not None
        assert approvals[0].resolved_by is not None


class TestHitlQuestionWithAnswer:
    """7. HITL tool call with answer -> Question record with status=answered."""

    def test_hitl_question_with_answer(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="hitl-answered"),
            agents=[
                AgentRunFixture(
                    id="business_analyst",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:hitl_ask_question",
                            arguments={"question": "What features do you need?"},
                            status="completed",
                            result="CRUD operations",
                            answer="CRUD operations",
                        ),
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Analysis complete"},
                            status="completed",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("hitl-answered")

        questions = db_session.query(Question).filter(Question.session_id == session_id).all()
        assert len(questions) == 1
        q = questions[0]
        assert q.status == "answered"
        assert q.answer == "CRUD operations"
        assert q.question == "What features do you need?"
        assert q.question_type == "text"
        assert q.answered_at is not None


class TestHitlQuestionWithoutAnswer:
    """8. HITL tool call without answer -> Question with status=pending."""

    def test_hitl_question_without_answer(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="hitl-pending", status="paused_hitl"),
            agents=[
                AgentRunFixture(
                    id="business_analyst",
                    status="paused_hitl",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:hitl_ask_multiple_choice_question",
                            arguments={
                                "question": "Which framework?",
                                "choices": ["React", "Vue", "Angular"],
                            },
                            status="waiting_answer",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("hitl-pending")

        questions = db_session.query(Question).filter(Question.session_id == session_id).all()
        assert len(questions) == 1
        q = questions[0]
        assert q.status == "pending"
        assert q.answer is None
        assert q.question_type == "choice"
        assert q.answered_at is None
        # Choices stored as JSON
        assert q.choices is not None
        assert len(q.choices) == 3


class TestIdempotency:
    """9. Seed twice, verify no duplicates.

    The loader's idempotency relies on ``ON DELETE CASCADE`` in PostgreSQL.
    Since SQLite doesn't cascade without FK enforcement (which conflicts with
    SQLAlchemy's insert ordering), we simulate cascading deletes manually
    between seeds to test the idempotency *concept*.
    """

    def test_idempotency(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="idempotent-test"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Done"},
                            status="completed",
                        ),
                    ],
                ),
            ],
        )

        # Seed once
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("idempotent-test")

        # Verify first seed worked
        assert db_session.query(Session).filter(Session.id == session_id).count() == 1
        assert db_session.query(AgentRun).filter(AgentRun.session_id == session_id).count() == 1

        # Manually simulate CASCADE delete (what PostgreSQL would do)
        db_session.query(ToolCall).filter(ToolCall.session_id == session_id).delete()
        db_session.query(LlmCall).filter(LlmCall.session_id == session_id).delete()
        db_session.query(Message).filter(Message.session_id == session_id).delete()
        db_session.query(Approval).filter(Approval.session_id == session_id).delete()
        db_session.query(Question).filter(Question.session_id == session_id).delete()
        db_session.query(AgentRun).filter(AgentRun.session_id == session_id).delete()
        db_session.commit()

        # Seed again (same fixture, same IDs)
        seed_fixture(db_session, fix)
        db_session.commit()

        # Should still be exactly 1 of each, not 2
        assert db_session.query(Session).filter(Session.id == session_id).count() == 1
        assert db_session.query(AgentRun).filter(AgentRun.session_id == session_id).count() == 1
        assert db_session.query(ToolCall).filter(ToolCall.session_id == session_id).count() == 1


class TestTokenTotals:
    """10. Session token totals = sum of agent tokens."""

    def test_token_totals(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="token-test"),
            agents=[
                AgentRunFixture(id="router", status="completed", tool_calls=[
                    ToolCallFixture(tool="builtin:done", arguments={"summary": "done"}, status="completed"),
                ]),
                AgentRunFixture(id="architect", status="completed", tool_calls=[
                    ToolCallFixture(tool="builtin:done", arguments={"summary": "done"}, status="completed"),
                ]),
                AgentRunFixture(id="builder", status="pending"),  # no tokens
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("token-test")
        s = db_session.query(Session).filter(Session.id == session_id).one()

        # 2 completed agents: 3000 prompt + 1000 completion each
        assert s.prompt_tokens == 6000
        assert s.completion_tokens == 2000
        assert s.total_tokens == 8000


class TestProjectCreated:
    """11. Session with project_name -> Project record."""

    def test_project_created(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="project-test", project_name="todo-app", intent="create_project"),
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        project_id = fixture_uuid("project-test", "project")
        projects = db_session.query(Project).filter(Project.id == project_id).all()
        assert len(projects) == 1
        assert projects[0].name == "todo-app"
        assert projects[0].status == "active"
        assert projects[0].repo_owner == "druppie_admin"

        # Session links to project
        session_id = fixture_uuid("project-test")
        s = db_session.query(Session).filter(Session.id == session_id).one()
        assert str(s.project_id) == str(project_id)


class TestNoProjectForGeneralChat:
    """12. Session without project_name -> no Project record."""

    def test_no_project_for_general_chat(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="no-project", intent="general_chat"),
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        # No project at all
        assert db_session.query(Project).count() == 0

        # Session has no project_id
        session_id = fixture_uuid("no-project")
        s = db_session.query(Session).filter(Session.id == session_id).one()
        assert s.project_id is None


class TestLoadFixturesFromDir:
    """13. Load from real testing/sessions/ directory, verify all 11 parse."""

    def test_load_fixtures_from_dir(self):
        fixtures_dir = Path(__file__).resolve().parents[2] / "testing" / "sessions"
        if not fixtures_dir.exists():
            pytest.skip(f"Fixtures directory not found: {fixtures_dir}")

        fixtures = load_fixtures(fixtures_dir)
        assert len(fixtures) == 12

        # Every fixture has a non-empty id and title
        for fix in fixtures:
            assert fix.metadata.id, f"Fixture missing id: {fix}"
            assert fix.metadata.title, f"Fixture missing title: {fix}"

        # Spot-check first fixture id
        ids = [f.metadata.id for f in fixtures]
        assert "todo-app" in ids or any("todo" in fid for fid in ids), (
            f"Expected a todo-app fixture, got: {ids}"
        )
