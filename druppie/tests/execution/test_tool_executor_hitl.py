"""Tests for HITL question attachment linking in ToolExecutor.

Covers the attachment_ids handling in _execute_hitl_tool added to support
PDF download chips inside HITL questions.
"""

from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

import pytest

from druppie.domain.common import ToolCallStatus
from druppie.execution.tool_executor import ToolExecutor


@pytest.fixture(autouse=True, scope="function")
def _patch_translation():
    """Stub out the translation and session lookup in _execute_hitl_tool.

    Without this fixture, SessionRepository.get_by_id returns a MagicMock
    that looks like a non-English session, causing the method to enter the
    (slow / external) translation block.
    """
    session = MagicMock()
    session.language = "en"
    with patch("druppie.repositories.SessionRepository") as MockSR:
        MockSR.return_value.get_by_id.return_value = session
        yield


def _make_executor(db=None) -> ToolExecutor:
    """Build a ToolExecutor with mocked MCP dependencies."""
    return ToolExecutor(
        db=db or MagicMock(),
        mcp_http=MagicMock(),
        mcp_config=MagicMock(),
    )


def _make_tool_call(**overrides):
    """Return a mock ToolCall with sensible defaults for HITL."""
    defaults = {
        "id": uuid4(),
        "session_id": uuid4(),
        "agent_run_id": uuid4(),
        "tool_name": "hitl_ask_question",
        "arguments": {"question": "Your PDF is ready"},
        "status": "pending",
    }
    defaults.update(overrides)
    tc = MagicMock()
    for k, v in defaults.items():
        setattr(tc, k, v)
    return tc


class TestExecuteHitlToolAttachmentLinking:
    """Attachment linking in _execute_hitl_tool."""

    @pytest.mark.asyncio
    async def test_attachment_ids_linked_to_question(self):
        """When attachment_ids are provided, they are linked to the Question."""
        executor = _make_executor()

        att_id_1, att_id_2 = str(uuid4()), str(uuid4())
        tool_call = _make_tool_call(
            arguments={"question": "Ready?", "attachment_ids": [att_id_1, att_id_2]},
        )

        mock_question = MagicMock()
        mock_question.id = uuid4()
        executor._question_repo = MagicMock()
        executor._question_repo.create.return_value = mock_question
        executor._execution_repo = MagicMock()

        mock_att_repo = MagicMock()

        with patch(
            "druppie.repositories.AttachmentRepository",
            return_value=mock_att_repo,
        ):
            result = await executor._execute_hitl_tool(tool_call)

        assert result == ToolCallStatus.WAITING_ANSWER
        assert executor._question_repo.create.called

        validate_call = mock_att_repo.validate_ownership.call_args
        assert validate_call is not None
        att_ids_passed, session_id_passed = validate_call[0]
        assert len(att_ids_passed) == 2
        assert all(isinstance(a, UUID) for a in att_ids_passed)
        assert session_id_passed == tool_call.session_id

        mock_att_repo.link_to_question.assert_called_once_with(
            att_ids_passed, mock_question.id, tool_call.session_id
        )

    @pytest.mark.asyncio
    async def test_bad_uuid_logs_warning_but_question_created(self):
        """Invalid attachment_ids UUID: warn, but the Question is still created."""
        executor = _make_executor()

        tool_call = _make_tool_call(
            arguments={"question": "Ready?", "attachment_ids": ["not-a-uuid"]},
        )

        mock_question = MagicMock()
        mock_question.id = uuid4()
        executor._question_repo = MagicMock()
        executor._question_repo.create.return_value = mock_question
        executor._execution_repo = MagicMock()

        with patch("druppie.execution.tool_executor.logger") as mock_logger:
            result = await executor._execute_hitl_tool(tool_call)

        assert result == ToolCallStatus.WAITING_ANSWER
        mock_logger.warning.assert_called_once()
        assert "hitl_attachment_invalid_uuid" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_validate_ownership_failure_propagates(self):
        """validate_ownership failure is NOT swallowed — it propagates to the caller."""
        executor = _make_executor()

        tool_call = _make_tool_call(
            arguments={"question": "Ready?", "attachment_ids": [str(uuid4())]},
        )

        mock_question = MagicMock()
        mock_question.id = uuid4()
        executor._question_repo = MagicMock()
        executor._question_repo.create.return_value = mock_question
        executor._execution_repo = MagicMock()

        mock_att_repo = MagicMock()
        mock_att_repo.validate_ownership.side_effect = ValueError(
            "Ownership validation failed",
        )

        with patch(
            "druppie.repositories.AttachmentRepository",
            return_value=mock_att_repo,
        ):
            with pytest.raises(ValueError, match="Ownership validation failed"):
                await executor._execute_hitl_tool(tool_call)

    @pytest.mark.asyncio
    async def test_link_failure_logs_warning_but_question_created(self):
        """link_to_question failure: warn, but the Question is still created."""
        executor = _make_executor()

        tool_call = _make_tool_call(
            arguments={"question": "Ready?", "attachment_ids": [str(uuid4())]},
        )

        mock_question = MagicMock()
        mock_question.id = uuid4()
        executor._question_repo = MagicMock()
        executor._question_repo.create.return_value = mock_question
        executor._execution_repo = MagicMock()

        mock_att_repo = MagicMock()
        mock_att_repo.link_to_question.side_effect = RuntimeError("DB busy")

        with patch(
            "druppie.repositories.AttachmentRepository",
            return_value=mock_att_repo,
        ):
            with patch("druppie.execution.tool_executor.logger") as mock_logger:
                result = await executor._execute_hitl_tool(tool_call)

        assert result == ToolCallStatus.WAITING_ANSWER
        mock_att_repo.link_to_question.assert_called_once()
        mock_logger.warning.assert_called_once()
        assert "hitl_attachment_link_failed" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_no_attachment_ids_no_repo_touched(self):
        """When no attachment_ids are provided, AttachmentRepository is never instantiated."""
        executor = _make_executor()

        tool_call = _make_tool_call(arguments={"question": "Ready?"})

        mock_question = MagicMock()
        mock_question.id = uuid4()
        executor._question_repo = MagicMock()
        executor._question_repo.create.return_value = mock_question
        executor._execution_repo = MagicMock()

        with patch("druppie.repositories.AttachmentRepository") as MockAttRepo:
            result = await executor._execute_hitl_tool(tool_call)

        assert result == ToolCallStatus.WAITING_ANSWER
        MockAttRepo.assert_not_called()
