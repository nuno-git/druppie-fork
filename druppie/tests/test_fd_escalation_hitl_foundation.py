"""Phase 0 foundation tests for FD-escalation/HITL feature.

Verifies that all new enum members, Pydantic fields, and ORM columns
exist with the correct types and defaults. No behavior is tested here.
"""
from __future__ import annotations

import uuid

from druppie.db.models.session import Session
from druppie.domain.agent_definition import AgentDefinition
from druppie.domain.common import SessionStatus
from druppie.domain.session import SessionDetail

# ---------------------------------------------------------------------------
# Tests: SessionStatus enum
# ---------------------------------------------------------------------------

class TestSessionStatusNewMembers:
    """SessionStatus has the three new escalation/HITL/termination members."""

    def test_paused_ba_hitl_exists(self) -> None:
        assert hasattr(SessionStatus, "PAUSED_BA_HITL")

    def test_paused_ba_hitl_value(self) -> None:
        assert SessionStatus.PAUSED_BA_HITL.value == "paused_ba_hitl"

    def test_paused_architect_hitl_exists(self) -> None:
        assert hasattr(SessionStatus, "PAUSED_ARCHITECT_HITL")

    def test_paused_architect_hitl_value(self) -> None:
        assert SessionStatus.PAUSED_ARCHITECT_HITL.value == "paused_architect_hitl"

    def test_terminated_exists(self) -> None:
        assert hasattr(SessionStatus, "TERMINATED")

    def test_terminated_value(self) -> None:
        assert SessionStatus.TERMINATED.value == "terminated"


# ---------------------------------------------------------------------------
# Tests: AgentDefinition escalation_threshold
# ---------------------------------------------------------------------------

class TestAgentDefinitionEscalationThreshold:
    """AgentDefinition carries an optional escalation_threshold field."""

    def test_default_is_none(self) -> None:
        agent = AgentDefinition(id="test", name="Test")
        assert agent.escalation_threshold is None

    def test_settable(self) -> None:
        agent = AgentDefinition(id="test", name="Test", escalation_threshold=3)
        assert agent.escalation_threshold == 3


# ---------------------------------------------------------------------------
# Tests: Session ORM columns (instantiate without DB round-trip)
# ---------------------------------------------------------------------------

class TestSessionNewColumns:
    """Session ORM model has fd_rejection_count, fd_escalation_mode,
    fd_post_hitl_rejection_count columns declared with correct defaults.

    Note: SQLAlchemy Column(default=...) only fires via DB/flush, not via
    Python __init__. Without a DB round-trip the attribute is None until
    flushed. We verify the columns exist and are settable.
    """

    def test_columns_exist(self) -> None:
        row = Session(id=uuid.uuid4(), status="active", title="test")
        assert hasattr(row, "fd_rejection_count")
        assert hasattr(row, "fd_escalation_mode")
        assert hasattr(row, "fd_post_hitl_rejection_count")

    def test_fd_rejection_count_settable(self) -> None:
        row = Session(id=uuid.uuid4(), status="active", title="test")
        row.fd_rejection_count = 5
        assert row.fd_rejection_count == 5

    def test_fd_escalation_mode_settable(self) -> None:
        row = Session(id=uuid.uuid4(), status="active", title="test")
        row.fd_escalation_mode = True
        assert row.fd_escalation_mode is True

    def test_fd_post_hitl_rejection_count_settable(self) -> None:
        row = Session(id=uuid.uuid4(), status="active", title="test")
        row.fd_post_hitl_rejection_count = 3
        assert row.fd_post_hitl_rejection_count == 3


# ---------------------------------------------------------------------------
# Tests: SessionDetail exposes new fields
# ---------------------------------------------------------------------------

class TestSessionDetailNewFields:
    """SessionDetail Pydantic model exposes the new escalation fields."""

    def test_detail_accepts_new_fields(self) -> None:
        detail = SessionDetail(
            id=uuid.uuid4(),
            title="test",
            status=SessionStatus.ACTIVE,
            project_id=None,
            updated_at=None,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            created_at="2025-01-01T00:00:00",
            user_id=None,
            project=None,
            fd_escalation_mode=True,
            fd_rejection_count=5,
            fd_post_hitl_rejection_count=2,
            timeline=[],
        )
        assert detail.fd_escalation_mode is True
        assert detail.fd_rejection_count == 5
        assert detail.fd_post_hitl_rejection_count == 2

    def test_detail_defaults(self) -> None:
        detail = SessionDetail(
            id=uuid.uuid4(),
            title="test",
            status=SessionStatus.ACTIVE,
            project_id=None,
            updated_at=None,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            created_at="2025-01-01T00:00:00",
            user_id=None,
            project=None,
            timeline=[],
        )
        assert detail.fd_escalation_mode is False
        assert detail.fd_rejection_count == 0
        assert detail.fd_post_hitl_rejection_count == 0
