"""Lightweight tests for escalation and session-termination primitives.

Covers:
- terminate_session builtin tool behaviour
- SessionStatus.TERMINATED enum value
- AgentDefinition.escalation_threshold field
- Session.fd_rejection_count DB column
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# The fastmcp library has a pydantic compatibility issue in this Python
# environment.  The import chain druppie.agents.__init__ -> runtime -> loop
# -> execution -> mcp_http -> fastmcp triggers a crash.  We pre-seed
# sys.modules with stubs so that importing builtin_tools succeeds.
# ---------------------------------------------------------------------------
for _mod_name in ("fastmcp", "fastmcp.settings", "fastmcp.client"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = ModuleType(_mod_name)

if "druppie.execution.mcp_http" not in sys.modules:
    _mcp_stub = ModuleType("druppie.execution.mcp_http")
    _mcp_stub.MCPHttp = MagicMock  # type: ignore[attr-defined]
    _mcp_stub.MCPHttpError = type("MCPHttpError", (Exception,), {})  # type: ignore[attr-defined]
    sys.modules["druppie.execution.mcp_http"] = _mcp_stub


# ---------------------------------------------------------------------------
# Test 1: terminate_session tool
# ---------------------------------------------------------------------------


class TestTerminateSessionTool:
    """Verify that the terminate_session builtin tool sets session status,
    cancels pending runs, and returns the expected dict."""

    @pytest.mark.asyncio
    async def test_sets_status_cancels_pending_and_returns_result(self):
        from druppie.agents.builtin_tools import terminate_session
        from druppie.domain.common import SessionStatus

        session_id = uuid4()
        agent_run_id = uuid4()
        reason = "Escalation threshold exceeded"

        # -- mocks --
        mock_session_repo = MagicMock()

        pending_run_1 = MagicMock()
        pending_run_1.id = uuid4()
        pending_run_2 = MagicMock()
        pending_run_2.id = uuid4()

        mock_execution_repo = MagicMock()
        mock_execution_repo.get_pending_runs.return_value = [
            pending_run_1,
            pending_run_2,
        ]
        mock_execution_repo.db = MagicMock()

        with patch(
            "druppie.repositories.SessionRepository",
            return_value=mock_session_repo,
        ):
            result = await terminate_session(
                reason=reason,
                session_id=session_id,
                agent_run_id=agent_run_id,
                execution_repo=mock_execution_repo,
            )

        # Session status updated to terminated
        mock_session_repo.update_status.assert_called_once_with(
            session_id,
            SessionStatus.TERMINATED.value,
            error_message=reason,
        )

        # Pending runs cancelled
        assert mock_execution_repo.cancel_agent_run.call_count == 2
        cancelled_ids = {
            call.args[0]
            for call in mock_execution_repo.cancel_agent_run.call_args_list
        }
        assert cancelled_ids == {pending_run_1.id, pending_run_2.id}

        # DB flushed
        mock_execution_repo.db.flush.assert_called_once()

        # Return value
        assert result == {"status": "terminated", "reason": reason}

    @pytest.mark.asyncio
    async def test_no_pending_runs_still_terminates(self):
        """When there are zero pending runs the session is still terminated."""
        from druppie.agents.builtin_tools import terminate_session

        session_id = uuid4()
        agent_run_id = uuid4()

        mock_session_repo = MagicMock()

        mock_execution_repo = MagicMock()
        mock_execution_repo.get_pending_runs.return_value = []
        mock_execution_repo.db = MagicMock()

        with patch(
            "druppie.repositories.SessionRepository",
            return_value=mock_session_repo,
        ):
            result = await terminate_session(
                reason="done",
                session_id=session_id,
                agent_run_id=agent_run_id,
                execution_repo=mock_execution_repo,
            )

        mock_session_repo.update_status.assert_called_once()
        mock_execution_repo.cancel_agent_run.assert_not_called()
        assert result["status"] == "terminated"


# ---------------------------------------------------------------------------
# Test 2: SessionStatus.TERMINATED enum value
# ---------------------------------------------------------------------------


class TestTerminatedSessionStatusEnum:
    """SessionStatus.TERMINATED must exist with value 'terminated'."""

    def test_terminated_value(self):
        from druppie.domain.common import SessionStatus

        assert hasattr(SessionStatus, "TERMINATED")
        assert SessionStatus.TERMINATED.value == "terminated"

    def test_terminated_is_str_enum(self):
        from druppie.domain.common import SessionStatus

        # SessionStatus inherits from str, so the member is usable as a string
        assert isinstance(SessionStatus.TERMINATED, str)


# ---------------------------------------------------------------------------
# Test 3: AgentDefinition accepts escalation_threshold
# ---------------------------------------------------------------------------


class TestEscalationThresholdInAgentDefinition:
    """AgentDefinition should accept an optional escalation_threshold field."""

    def test_default_is_none(self):
        from druppie.domain.agent_definition import AgentDefinition

        defn = AgentDefinition(
            id="test-agent",
            name="test-agent",
            system_prompt="You are a test agent.",
        )
        assert defn.escalation_threshold is None

    def test_accepts_integer_value(self):
        from druppie.domain.agent_definition import AgentDefinition

        defn = AgentDefinition(
            id="test-agent",
            name="test-agent",
            system_prompt="You are a test agent.",
            escalation_threshold=3,
        )
        assert defn.escalation_threshold == 3


# ---------------------------------------------------------------------------
# Test 4: Session DB model has fd_rejection_count column
# ---------------------------------------------------------------------------


class TestFdRejectionCountColumn:
    """The Session ORM model must expose fd_rejection_count."""

    def test_column_exists(self):
        from druppie.db.models.session import Session

        assert hasattr(Session, "fd_rejection_count")

    def test_column_is_integer_type(self):
        from sqlalchemy import Integer
        from druppie.db.models.session import Session

        col = Session.__table__.columns["fd_rejection_count"]
        assert isinstance(col.type, Integer)

    def test_column_default_is_zero(self):
        from druppie.db.models.session import Session

        col = Session.__table__.columns["fd_rejection_count"]
        assert col.server_default is not None
        assert col.server_default.arg == "0"
