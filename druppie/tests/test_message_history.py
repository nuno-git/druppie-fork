"""Tests for druppie.agents.message_history.reconstruct_from_db."""

from __future__ import annotations

import json
from types import SimpleNamespace

from druppie.agents.message_history import reconstruct_from_db


def _make_llm_call(
    request_messages=None,
    response_tool_calls=None,
    response_content=None,
    tool_calls=None,
):
    return SimpleNamespace(
        request_messages=request_messages,
        response_tool_calls=response_tool_calls or [],
        response_content=response_content,
        tool_calls=tool_calls or [],
    )


def _make_tool_call_db(result=None, error_message=None):
    return SimpleNamespace(result=result, error_message=error_message)


class TestReconstructFromDb:
    def test_empty_calls(self):
        assert reconstruct_from_db([], None) == []

    def test_uses_last_call_request_messages(self):
        """Should use the last LLM call's request_messages as the base."""
        call1 = _make_llm_call(
            request_messages=[
                {"role": "system", "content": "sys prompt"},
                {"role": "user", "content": "task"},
            ],
            response_tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}],
            tool_calls=[_make_tool_call_db(result="file contents")],
        )
        call2 = _make_llm_call(
            request_messages=[
                {"role": "system", "content": "sys prompt"},
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": "file contents"},
            ],
            response_tool_calls=[{"id": "c2", "name": "write_file", "args": {"path": "b.py"}}],
            tool_calls=[_make_tool_call_db(result="written")],
        )

        messages = reconstruct_from_db([call1, call2], None)

        # Should be: last call's 4 request_messages + assistant + tool
        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert messages[-2]["role"] == "assistant"
        assert messages[-1]["role"] == "tool"

    def test_compressed_history_survives(self):
        """If the last LLM call has compressed history in its request_messages,
        that should be preserved rather than replaying full history."""
        call = _make_llm_call(
            request_messages=[
                {"role": "system", "content": "sys prompt"},
                {"role": "user", "content": "[COMPRESSED HISTORY]\nread_file(a.py)->ok\n[END COMPRESSED HISTORY]"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "c10", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "b.py"}'}}
                ]},
                {"role": "tool", "tool_call_id": "c10", "content": "contents of b"},
            ],
            response_tool_calls=[{"id": "c11", "name": "done", "args": {"summary": "done"}}],
            tool_calls=[_make_tool_call_db(result='{"success": true}')],
        )

        messages = reconstruct_from_db([call], None)
        assert "COMPRESSED HISTORY" in str(messages)
        assert len(messages) == 6  # 4 request + 1 assistant + 1 tool

    def test_fallback_to_full_replay(self):
        """Falls back to full replay if last call has no request_messages."""
        call1 = _make_llm_call(
            request_messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "task"},
            ],
            response_content="text response",
        )
        call2 = _make_llm_call(
            request_messages=None,
            response_content="another response",
        )

        messages = reconstruct_from_db([call1, call2], None)
        # Full replay: call1 request_messages + call1 response + call2 response
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
