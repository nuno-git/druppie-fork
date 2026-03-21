"""Tests for evaluation context extraction.

Uses an in-memory SQLite database with the UUID compatibility shim from
test_fixture_loader.py. Seeds test data via seed_fixture() and verifies
that extract_context() returns correctly formatted strings.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from druppie.db.models import Base
from druppie.evaluation.context import extract_context
from druppie.evaluation.schema import ContextSource
from druppie.fixtures.ids import fixture_uuid
from druppie.fixtures.loader import seed_fixture
from druppie.fixtures.schema import (
    AgentRunFixture,
    MessageFixture,
    SessionFixture,
    SessionMetadata,
    ToolCallFixture,
)

# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as test_fixture_loader)
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


def _meta(**overrides) -> SessionMetadata:
    defaults = dict(id="eval-ctx-test", title="Eval Context Test", status="completed")
    defaults.update(overrides)
    return SessionMetadata(**defaults)


def _fixture(meta=None, agents=None, messages=None) -> SessionFixture:
    return SessionFixture(
        metadata=meta or _meta(),
        agents=agents or [],
        messages=messages or [],
    )


def _ctx(source: str, **kwargs) -> ContextSource:
    """Build a ContextSource; 'as' maps to as_name via alias."""
    data = {"source": source, **kwargs}
    # 'as' is the alias for as_name in the schema
    if "as" not in data and "as_name" not in data:
        data["as"] = source  # default template var name = source name
    return ContextSource(**data)


# ===========================================================================
# Test cases
# ===========================================================================


class TestAllToolCalls:
    """Extract all tool calls from an agent run as formatted string."""

    def test_all_tool_calls(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="tc-all"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
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

        session_id = fixture_uuid("tc-all")
        run_id = fixture_uuid("tc-all", "run", 0)

        result = extract_context(
            db=db_session,
            agent_run_id=run_id,
            session_id=session_id,
            agent_id="router",
            sources=[_ctx("all_tool_calls", **{"as": "tool_calls"})],
        )

        text = result["tool_calls"]
        assert "builtin:set_intent" in text
        assert "builtin:done" in text
        assert "create_project" in text
        assert "Routing complete" in text
        # Check ordering: set_intent [0] before done [1]
        assert text.index("[0]") < text.index("[1]")


class TestSessionMessages:
    """Extract session messages in order."""

    def test_session_messages(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="msg-all"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Done routing"},
                            status="completed",
                        ),
                    ],
                ),
            ],
            messages=[
                MessageFixture(role="user", content="Build me a todo app"),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("msg-all")
        run_id = fixture_uuid("msg-all", "run", 0)

        result = extract_context(
            db=db_session,
            agent_run_id=run_id,
            session_id=session_id,
            agent_id="router",
            sources=[_ctx("session_messages", **{"as": "messages"})],
        )

        text = result["messages"]
        assert "[user]" in text
        assert "Build me a todo app" in text
        assert "[assistant]" in text
        assert "Done routing" in text
        # User message at seq 0 should come before assistant message
        user_pos = text.index("[user]")
        assistant_pos = text.index("[assistant]")
        assert user_pos < assistant_pos


class TestSessionMessagesFilteredByRole:
    """Filter messages to user-only."""

    def test_session_messages_filtered_by_role(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="msg-filtered"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Done routing"},
                            status="completed",
                        ),
                    ],
                ),
            ],
            messages=[
                MessageFixture(role="user", content="Build me a todo app"),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("msg-filtered")
        run_id = fixture_uuid("msg-filtered", "run", 0)

        result = extract_context(
            db=db_session,
            agent_run_id=run_id,
            session_id=session_id,
            agent_id="router",
            sources=[_ctx("session_messages", role="user", **{"as": "user_messages"})],
        )

        text = result["user_messages"]
        assert "[user]" in text
        assert "Build me a todo app" in text
        # No assistant messages
        assert "[assistant]" not in text


class TestAgentDefinition:
    """Load agent definition and return system_prompt."""

    def test_agent_definition(self, db_session: DbSession):
        # No DB data needed; reads from YAML files on disk
        result = extract_context(
            db=db_session,
            agent_run_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            agent_id="architect",
            sources=[_ctx("agent_definition", **{"as": "definition"})],
        )

        text = result["definition"]
        # The architect system prompt contains these strings
        assert "Architect" in text
        assert len(text) > 100  # non-trivial content


class TestAgentDefinitionWithField:
    """Load specific field from agent definition."""

    def test_agent_definition_with_field(self, db_session: DbSession):
        result = extract_context(
            db=db_session,
            agent_run_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            agent_id="architect",
            sources=[_ctx("agent_definition", field="mcps", **{"as": "mcp_config"})],
        )

        text = result["mcp_config"]
        # The architect mcps section includes coding and registry servers
        assert "coding" in text
        assert "read_file" in text
        assert "make_design" in text


class TestToolCallResult:
    """Extract the result of a specific tool call."""

    def test_tool_call_result(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="tc-result"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
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

        session_id = fixture_uuid("tc-result")
        run_id = fixture_uuid("tc-result", "run", 0)

        result = extract_context(
            db=db_session,
            agent_run_id=run_id,
            session_id=session_id,
            agent_id="router",
            sources=[_ctx("tool_call_result", tool="builtin:set_intent", **{"as": "intent_result"})],
        )

        assert result["intent_result"] == "Intent set to create_project"


class TestToolCallArguments:
    """Extract the arguments of a specific tool call."""

    def test_tool_call_arguments(self, db_session: DbSession):
        fix = _fixture(
            meta=_meta(id="tc-args"),
            agents=[
                AgentRunFixture(
                    id="router",
                    status="completed",
                    tool_calls=[
                        ToolCallFixture(
                            tool="builtin:set_intent",
                            arguments={"intent": "create_project"},
                            status="completed",
                            result="Intent set",
                        ),
                        ToolCallFixture(
                            tool="builtin:done",
                            arguments={"summary": "Done"},
                            status="completed",
                        ),
                    ],
                ),
            ],
        )
        seed_fixture(db_session, fix)
        db_session.commit()

        session_id = fixture_uuid("tc-args")
        run_id = fixture_uuid("tc-args", "run", 0)

        result = extract_context(
            db=db_session,
            agent_run_id=run_id,
            session_id=session_id,
            agent_id="router",
            sources=[_ctx("tool_call_arguments", tool="builtin:set_intent", **{"as": "intent_args"})],
        )

        parsed = json.loads(result["intent_args"])
        assert parsed["intent"] == "create_project"


class TestUnknownSourceRaises:
    """ValueError for unknown source type."""

    def test_unknown_source_raises(self, db_session: DbSession):
        with pytest.raises(ValueError, match="Unknown context source"):
            extract_context(
                db=db_session,
                agent_run_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                agent_id="router",
                sources=[_ctx("nonexistent_source", **{"as": "x"})],
            )
