"""Tests for the benchmark assertion checker.

Uses an in-memory SQLite database with a UUID compatibility shim (same pattern
as test_fixture_loader.py) to verify assertion logic without PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.testing.bench_assertions import AssertionResult, check_assertions
from druppie.testing.bench_schema import Assertion
from druppie.db.models import AgentRun, Base, Session, ToolCall

# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as test_fixture_loader.py)
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

SESSION_ID = uuid.uuid4()
AGENT_RUN_ID = uuid.uuid4()


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


def _make_assertion(**kwargs) -> Assertion:
    """Helper to build an Assertion using the 'assert' alias."""
    return Assertion.model_validate(kwargs)


def _seed_session(db: DbSession, session_id: uuid.UUID) -> None:
    """Insert a minimal Session row."""
    db.add(Session(id=session_id, title="Test", status="completed"))
    db.flush()


def _seed_agent_run(
    db: DbSession,
    *,
    agent_run_id: uuid.UUID,
    session_id: uuid.UUID,
    agent_id: str,
    status: str = "completed",
    sequence_number: int = 0,
) -> AgentRun:
    run = AgentRun(
        id=agent_run_id,
        session_id=session_id,
        agent_id=agent_id,
        status=status,
        sequence_number=sequence_number,
    )
    db.add(run)
    db.flush()
    return run


def _seed_tool_call(
    db: DbSession,
    *,
    agent_run_id: uuid.UUID,
    session_id: uuid.UUID,
    mcp_server: str,
    tool_name: str,
    arguments: dict | None = None,
    result: str | None = None,
) -> ToolCall:
    tc = ToolCall(
        id=uuid.uuid4(),
        agent_run_id=agent_run_id,
        session_id=session_id,
        mcp_server=mcp_server,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
    )
    db.add(tc)
    db.flush()
    return tc


# ===========================================================================
# Test cases
# ===========================================================================


class TestCompletedAssertion:
    """1. Agent completed, assert completed -> pass."""

    def test_completed_assertion_passes(self, db_session: DbSession):
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router", status="completed")

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="router", **{"assert": "completed"})],
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert "completed" in results[0].message

    def test_completed_assertion_fails(self, db_session: DbSession):
        """2. Agent failed, assert completed -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="builder", status="failed")

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="builder", **{"assert": "completed"})],
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "failed" in results[0].message


class TestFailedAssertion:
    """3. Failed agent, assert failed -> pass."""

    def test_failed_assertion(self, db_session: DbSession):
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="builder", status="failed")

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="builder", **{"assert": "failed"})],
        )
        assert len(results) == 1
        assert results[0].passed is True


class TestToolCalled:
    """4-5. Tool called assertions."""

    def test_tool_called_passes(self, db_session: DbSession):
        """4. Tool exists -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router")
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
        )

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="router", tool="builtin:set_intent", **{"assert": "tool_called"})],
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_tool_called_fails(self, db_session: DbSession):
        """5. Tool missing -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router")

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="router", tool="builtin:set_intent", **{"assert": "tool_called"})],
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "not found" in results[0].message


class TestSummaryContains:
    """6-7. Tool called with summary_contains."""

    def test_summary_contains(self, db_session: DbSession):
        """6. Tool exists with matching content -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router")
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project"},
            result="Intent set to create_project",
        )

        results = check_assertions(
            db_session,
            sid,
            [
                _make_assertion(
                    agent="router",
                    tool="builtin:set_intent",
                    summary_contains="create_project",
                    **{"assert": "tool_called"},
                )
            ],
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_summary_contains_not_found(self, db_session: DbSession):
        """7. Tool exists but content doesn't match -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router")
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "general_chat"},
            result="Intent set to general_chat",
        )

        results = check_assertions(
            db_session,
            sid,
            [
                _make_assertion(
                    agent="router",
                    tool="builtin:set_intent",
                    summary_contains="create_project",
                    **{"assert": "tool_called"},
                )
            ],
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "not in content" in results[0].message


class TestMissingAgent:
    """8. No agent run found -> fail (not exception)."""

    def test_missing_agent(self, db_session: DbSession):
        sid = uuid.uuid4()
        _seed_session(db_session, sid)

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="nonexistent", **{"assert": "completed"})],
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "No agent run found" in results[0].message


class TestUnknownAssertType:
    """9. Unknown assert type -> returns fail (not exception)."""

    def test_unknown_assert_type(self, db_session: DbSession):
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(db_session, agent_run_id=rid, session_id=sid, agent_id="router")

        results = check_assertions(
            db_session,
            sid,
            [_make_assertion(agent="router", **{"assert": "bogus_type"})],
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "Unknown assertion type" in results[0].message
