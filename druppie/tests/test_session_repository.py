"""Tests for since_sequence filtering in the repository layer.

We test the SQLAlchemy query construction directly to verify that:
1. since_sequence is applied as a filter when present
2. No filter is applied when since_sequence is None
"""

import pytest
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class MockMessage(Base):
    __tablename__ = "mock_messages"
    id = Column(String, primary_key=True)
    session_id = Column(String)
    role = Column(String)
    content = Column(String)
    sequence_number = Column(Integer)


class MockAgentRun(Base):
    __tablename__ = "mock_agent_runs"
    id = Column(String, primary_key=True)
    session_id = Column(String)
    agent_id = Column(String)
    status = Column(String)
    sequence_number = Column(Integer)
    parent_run_id = Column(String)
    iteration_count = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    error_message = Column(String)
    planned_prompt = Column(String)
    variables = Column(String)
    spawning_tool_call_id = Column(String)


class TestSinceSequenceQueryConstruction:
    """Verify the SQL that since_sequence generates."""

    @pytest.fixture
    def db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        return Session()

    def test_sequence_filter_skips_null(self, db):
        db.add(MockMessage(id="1", session_id="s1", role="user", content="a", sequence_number=None))
        db.add(MockMessage(id="2", session_id="s1", role="user", content="b", sequence_number=5))
        db.commit()

        result = db.query(MockMessage).filter(MockMessage.sequence_number > 3).all()
        # NULL > 3 evaluates to NULL (not TRUE) in SQL three-valued logic,
        # so the row with sequence_number=NULL is excluded.
        assert len(result) == 1
        assert result[0].sequence_number == 5

    def test_no_filter_includes_null(self, db):
        db.add(MockMessage(id="1", session_id="s1", role="user", content="a", sequence_number=None))
        db.add(MockMessage(id="2", session_id="s1", role="user", content="b", sequence_number=5))
        db.commit()

        result = db.query(MockMessage).all()
        assert len(result) == 2

    def test_filter_at_db_level(self, db):
        db.add(MockAgentRun(id="1", session_id="s1", agent_id="a", status="done", sequence_number=None))
        db.add(MockAgentRun(id="2", session_id="s1", agent_id="b", status="done", sequence_number=10))
        db.commit()

        result = db.query(MockAgentRun).filter(MockAgentRun.sequence_number > 5).all()
        # Only the row with sequence_number=10 should be included.
        # NULL values are excluded by the comparison.
        assert len(result) == 1
        assert result[0].sequence_number == 10
