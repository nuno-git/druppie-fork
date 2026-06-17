"""Tests for druppie.agent_runtime.compaction."""

from __future__ import annotations

import json

import pytest

from druppie.agent_runtime.compaction import (
    CompactionConfig,
    CompactionState,
    MessageCompactor,
)


def _msg(role, content="", **kwargs):
    m = {"role": role, "content": content}
    m.update(kwargs)
    return m


def _assistant_with_tool(tool_name, args, call_id="call_1", content=""):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(args),
            },
        }],
    }


def _tool_result(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _build_conversation(num_turns, tool_result_size=100):
    messages = [
        _msg("system", "You are a developer agent."),
        _msg("user", "Implement the feature."),
    ]
    for i in range(num_turns):
        cid = f"call_{i}"
        messages.append(_assistant_with_tool(
            "coding_read_file", {"path": f"src/file_{i}.py"}, call_id=cid,
        ))
        messages.append(_tool_result(cid, "x" * tool_result_size))
    return messages


def _make_agent():
    from druppie.agent_runtime.definition import AgentDefinition
    return AgentDefinition(
        id="test",
        name="Test Agent",
        description="Test",
        system_prompt="Test prompt",
        llm_profile="standard",
    )


def _mock_llm(summary_text="Summary of conversation."):
    async def llm(**kwargs):
        return {
            "choices": [{
                "message": {"content": summary_text},
            }],
        }
    return llm


class TestEstimateTokens:
    def test_plain_text(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "Hello world")]
        tokens = compactor.estimate_tokens(msgs)
        assert tokens > 0
        assert tokens == len("Hello world") // 4 + 4

    def test_no_double_counting_tool_calls(self):
        compactor = MessageCompactor()
        msg = _assistant_with_tool("read_file", {"path": "/a/b/c.py"})
        tokens_structured = compactor.estimate_tokens([msg])

        flat = _msg("assistant", str(msg))
        tokens_flat = compactor.estimate_tokens([flat])

        assert tokens_structured < tokens_flat

    def test_tool_result_counted(self):
        compactor = MessageCompactor()
        short = [_tool_result("c1", "ok")]
        long = [_tool_result("c1", "x" * 1000)]
        assert compactor.estimate_tokens(long) > compactor.estimate_tokens(short)


class TestCalibrate:
    def test_skips_small_token_count(self):
        compactor = MessageCompactor()
        old_ratio = compactor.state.calibration_ratio
        compactor.calibrate(50, [_msg("user", "hi")])
        assert compactor.state.calibration_ratio == old_ratio

    def test_adjusts_ratio(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "a" * 1000)]
        compactor.calibrate(200, msgs)
        assert compactor.state.calibration_ratio != 4.0
        assert compactor.state.calibration_samples == 1

    def test_ratio_clamped(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "a" * 100)]
        compactor.calibrate(10000, msgs)
        assert compactor.state.calibration_ratio >= 2.5

        compactor2 = MessageCompactor()
        msgs2 = [_msg("user", "a" * 10000)]
        compactor2.calibrate(101, msgs2)
        assert compactor2.state.calibration_ratio <= 6.0

    def test_ema_convergence(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "a" * 400)]
        for _ in range(20):
            compactor.calibrate(100, msgs)
        assert abs(compactor.state.calibration_ratio - 4.0) < 0.5


class TestSplitHeaderBody:
    def test_basic_split(self):
        msgs = [
            _msg("system", "sys"),
            _msg("user", "task"),
            _assistant_with_tool("read", {}, call_id="c1"),
            _tool_result("c1", "result"),
        ]
        header, body = MessageCompactor._split_header_body(msgs)
        assert len(header) == 2
        assert len(body) == 2
        assert header[0]["role"] == "system"
        assert header[1]["role"] == "user"

    def test_no_body(self):
        msgs = [_msg("system", "sys"), _msg("user", "task")]
        header, body = MessageCompactor._split_header_body(msgs)
        assert len(header) == 2
        assert len(body) == 0

    def test_assistant_first(self):
        msgs = [_msg("assistant", "hello")]
        header, body = MessageCompactor._split_header_body(msgs)
        assert len(header) == 0
        assert len(body) == 1


class TestCompress:
    @pytest.mark.asyncio
    async def test_skip_under_threshold(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=1_000_000,
        ))
        msgs = _build_conversation(5, tool_result_size=100)
        result = await compactor.compress(msgs, None, _make_agent(), None)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_full_replacement_with_llm(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            summarization_threshold=0.05,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        result = await compactor.compress(msgs, _mock_llm("Did stuff."), _make_agent(), None)
        text = str(result)
        assert "[CONVERSATION SUMMARY]" in text
        assert "Did stuff." in text
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_header_preserved(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            summarization_threshold=0.05,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        result = await compactor.compress(msgs, _mock_llm("Summary."), _make_agent(), None)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "Implement the feature."
        assert result[2]["role"] == "user"
        assert "[CONVERSATION SUMMARY]" in result[2]["content"]

    @pytest.mark.asyncio
    async def test_emits_event_on_summarize(self):
        events = []

        class MockEmitter:
            def emit(self, event):
                events.append(event)

        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            summarization_threshold=0.05,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        await compactor.compress(msgs, _mock_llm("Summary."), _make_agent(), MockEmitter())

        assert len(events) == 1
        assert events[0].type == "context_compressed"
        assert events[0].data["phase"] == "summarized"
        assert events[0].data["tokens_before"] > 0
        assert "summary_text" in events[0].data

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        async def failing_llm(**kwargs):
            raise RuntimeError("API error")

        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            summarization_threshold=0.05,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        result = await compactor.compress(msgs, failing_llm, _make_agent(), None)
        text = str(result)
        assert "[CONVERSATION SUMMARY" in text
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_fallback_when_no_llm(self):
        events = []

        class MockEmitter:
            def emit(self, event):
                events.append(event)

        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            summarization_threshold=0.05,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        result = await compactor.compress(msgs, None, _make_agent(), MockEmitter())

        assert len(events) == 1
        assert events[0].data["phase"] == "summarized_fallback"
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_no_body_unchanged(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=10,
            summarization_threshold=0.01,
        ))
        msgs = [_msg("system", "sys"), _msg("user", "task")]
        result = await compactor.compress(msgs, _mock_llm(), _make_agent(), None)
        assert result == msgs


class TestSerializeBody:
    def test_includes_all_roles(self):
        compactor = MessageCompactor()
        body = [
            _msg("assistant", "hello"),
            _tool_result("c1", "result"),
            _msg("assistant", "world"),
        ]
        text = compactor._serialize_body(body)
        assert "[assistant]" in text
        assert "[tool]" in text
        assert "hello" in text
        assert "result" in text

    def test_caps_at_max_input_chars(self):
        compactor = MessageCompactor(CompactionConfig(max_input_chars=50))
        body = [_msg("user", "x" * 500)]
        text = compactor._serialize_body(body)
        assert len(text) <= 50


class TestTruncateToolResult:
    def test_short_content_unchanged(self):
        assert MessageCompactor.truncate_tool_result("hello") == "hello"

    def test_long_content_truncated(self):
        content = "x" * 20000
        result = MessageCompactor.truncate_tool_result(content)
        assert len(result) < len(content)
        assert "truncated" in result

    def test_very_long_content(self):
        content = "x" * 60000
        result = MessageCompactor.truncate_tool_result(content)
        assert len(result) < 10000
