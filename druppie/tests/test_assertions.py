"""Tests for the assertion matcher.

Uses an in-memory SQLite database with a UUID compatibility shim (same pattern
as test_bench_assertions.py) to verify assertion logic without PostgreSQL.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.testing.assertions import AssertionResult, match_assertions
from druppie.testing.schema import CheckAssertion
from druppie.db.models import AgentRun, Base, Project, Session, ToolCall, User

# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as other test files)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_session(
    db: DbSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> None:
    """Insert a minimal Session row."""
    db.add(Session(id=session_id, title="Test", status="completed", user_id=user_id))
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


def _assertion(**kwargs) -> CheckAssertion:
    """Build an CheckAssertion."""
    return CheckAssertion(**kwargs)


# ===========================================================================
# Test cases
# ===========================================================================


class TestCompletedAssertion:
    """completed: true/false assertions."""

    def test_completed_assertion_passes(self, db_session: DbSession):
        """Agent completed, assert completed=true -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
            status="completed",
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", completed=True)],
            {},
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert "completed" in results[0].message

    def test_completed_assertion_fails(self, db_session: DbSession):
        """Agent failed, assert completed=true -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="builder",
            status="failed",
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="builder", completed=True)],
            {},
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "failed" in results[0].message


class TestToolCalled:
    """tool assertions."""

    def test_tool_passes(self, db_session: DbSession):
        """Tool exists -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project", "project_name": "todo-app"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {},
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_tool_fails_missing_tool(self, db_session: DbSession):
        """Tool missing -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {},
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "not found" in results[0].message


class TestToolCalledExactMatch:
    """Exact argument matching."""

    def test_tool_exact_match(self, db_session: DbSession):
        """Exact argument match -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "update_project", "project_name": "weather-dashboard"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"intent": "update_project", "project_name": "weather-dashboard"},
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_tool_exact_mismatch(self, db_session: DbSession):
        """Exact argument mismatch -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project", "project_name": "todo-app"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"intent": "update_project"},
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "intent" in results[0].message


class TestToolCalledWildcard:
    """Wildcard (*) argument matching."""

    def test_tool_wildcard(self, db_session: DbSession):
        """Wildcard '*' matches any non-None value -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project", "project_name": "anything-goes"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"intent": "create_project", "project_name": "*"},
        )
        assert len(results) == 1
        assert results[0].passed is True


class TestToolCalledAnyOf:
    """Any-of list argument matching."""

    def test_tool_any_of_match(self, db_session: DbSession):
        """Value in list -> pass."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project", "project_name": "recipe-app"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"project_name": ["recipe-app", "recipe-application", "recipe-website"]},
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_tool_any_of_mismatch(self, db_session: DbSession):
        """Value not in list -> fail."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project", "project_name": "cooking-helper"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"project_name": ["recipe-app", "recipe-application", "recipe-website"]},
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "project_name" in results[0].message


class TestMissingAgent:
    """No agent run found -> fail gracefully."""

    def test_missing_agent(self, db_session: DbSession):
        """Missing agent returns fail, not an exception."""
        sid = uuid.uuid4()
        _seed_session(db_session, sid)

        # Test for completed assertion
        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="nonexistent", completed=True)],
            {},
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "No agent run found" in results[0].message

        # Test for tool assertion
        results2 = match_assertions(
            db_session,
            sid,
            [_assertion(agent="nonexistent", tool="builtin:done")],
            {},
        )
        assert len(results2) == 1
        assert results2[0].passed is False
        assert "No agent run found" in results2[0].message


# ---------------------------------------------------------------------------
# Helpers for project reference tests
# ---------------------------------------------------------------------------


def _seed_user(db: DbSession, user_id: uuid.UUID, username: str = "testuser") -> User:
    """Insert a minimal User row."""
    user = User(
        id=user_id,
        username=username,
        email=f"{username}@test.local",
        display_name=username,
    )
    db.add(user)
    db.flush()
    return user


def _seed_project(
    db: DbSession,
    project_id: uuid.UUID,
    name: str,
    owner_id: uuid.UUID,
) -> Project:
    """Insert a minimal Project row."""
    project = Project(
        id=project_id,
        name=name,
        owner_id=owner_id,
        status="active",
    )
    db.add(project)
    db.flush()
    return project


class TestProjectReference:
    """@project:<name> reference resolution in expected values."""

    def test_project_reference_resolved(self, db_session: DbSession):
        """@project:name resolves to actual project UUID and matches."""
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        sid = uuid.uuid4()
        rid = uuid.uuid4()

        _seed_user(db_session, user_id)
        _seed_project(db_session, project_id, "weather-dashboard", user_id)
        _seed_session(db_session, sid, user_id=user_id)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={
                "intent": "update_project",
                "project_id": str(project_id),
            },
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {
                "intent": "update_project",
                "project_id": "@project:weather-dashboard",
            },
        )
        assert len(results) == 1
        assert results[0].passed is True

    def test_project_reference_wrong_project(self, db_session: DbSession):
        """@project:name resolves but doesn't match the wrong project UUID."""
        user_id = uuid.uuid4()
        weather_id = uuid.uuid4()
        todo_id = uuid.uuid4()
        sid = uuid.uuid4()
        rid = uuid.uuid4()

        _seed_user(db_session, user_id)
        _seed_project(db_session, weather_id, "weather-dashboard", user_id)
        _seed_project(db_session, todo_id, "todo-app", user_id)
        _seed_session(db_session, sid, user_id=user_id)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        # Router picked the wrong project (todo-app instead of weather-dashboard)
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={
                "intent": "update_project",
                "project_id": str(todo_id),
            },
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {
                "intent": "update_project",
                "project_id": "@project:weather-dashboard",
            },
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert "project_id" in results[0].name

    def test_project_reference_not_found(self, db_session: DbSession):
        """@project:nonexistent leaves value as-is and fails."""
        user_id = uuid.uuid4()
        sid = uuid.uuid4()
        rid = uuid.uuid4()

        _seed_user(db_session, user_id)
        _seed_session(db_session, sid, user_id=user_id)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={
                "intent": "update_project",
                "project_id": str(uuid.uuid4()),
            },
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {
                "intent": "update_project",
                "project_id": "@project:nonexistent",
            },
        )
        assert len(results) == 1
        assert results[0].passed is False

    def test_no_references_skips_resolution(self, db_session: DbSession):
        """Expected values without @project: references pass through unchanged."""
        sid = uuid.uuid4()
        rid = uuid.uuid4()
        _seed_session(db_session, sid)
        _seed_agent_run(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            agent_id="router",
        )
        _seed_tool_call(
            db_session,
            agent_run_id=rid,
            session_id=sid,
            mcp_server="builtin",
            tool_name="set_intent",
            arguments={"intent": "create_project"},
        )

        results = match_assertions(
            db_session,
            sid,
            [_assertion(agent="router", tool="builtin:set_intent")],
            {"intent": "create_project"},
        )
        assert len(results) == 1
        assert results[0].passed is True
