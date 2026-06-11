"""Tests for druppie.agent_runtime.compaction."""

from __future__ import annotations

import json

import pytest

from druppie.agent_runtime.compaction import (
    CompactionConfig,
    CompactionState,
    MessageCompactor,
    ToolResultMeta,
    _extract_code_structures,
    _extract_test_summary,
)


# ------------------------------------------------------------------
# Fixtures and helpers
# ------------------------------------------------------------------


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
    """Build a conversation with system + user + N tool turns."""
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


# ------------------------------------------------------------------
# Token estimation
# ------------------------------------------------------------------


class TestEstimateTokens:
    def test_plain_text(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "Hello world")]
        tokens = compactor.estimate_tokens(msgs)
        assert tokens > 0
        assert tokens == len("Hello world") // 4 + 4

    def test_no_double_counting_tool_calls(self):
        compactor = MessageCompactor()
        args_str = json.dumps({"path": "/a/b/c.py"})
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


# ------------------------------------------------------------------
# Calibration
# ------------------------------------------------------------------


class TestCalibrate:
    def test_skips_small_token_count(self):
        compactor = MessageCompactor()
        old_ratio = compactor.state.calibration_ratio
        compactor.calibrate(50, [_msg("user", "hi")])
        assert compactor.state.calibration_ratio == old_ratio

    def test_adjusts_ratio(self):
        compactor = MessageCompactor()
        msgs = [_msg("user", "a" * 1000)]
        compactor.calibrate(250, msgs)
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


# ------------------------------------------------------------------
# Content-aware summarization
# ------------------------------------------------------------------


class TestContentAwareSummarization:
    def test_file_read_preserves_structures(self):
        compactor = MessageCompactor()
        content = """import os
from flask import Flask

class App:
    pass

def create_app():
    pass

@app.route('/api/users')
def get_users():
    pass
""" + "# padding\n" * 100
        result = compactor._summarize_file_read(content, "src/app.py")
        assert "src/app.py" in result
        assert "class App" in result
        assert "def create_app" in result

    def test_bash_preserves_errors(self):
        compactor = MessageCompactor()
        lines = ["$ npm test"] + ["ok line"] * 50 + ["ERROR: test_auth failed"] + ["ok"] * 10 + ["Tests: 9 passed, 1 failed"]
        content = "\n".join(lines)
        result = compactor._summarize_bash(content)
        assert "ERROR" in result or "error" in result.lower()
        assert "Last lines:" in result

    def test_search_keeps_first_results(self):
        compactor = MessageCompactor()
        lines = [f"src/file_{i}.py:10: match" for i in range(30)]
        content = "\n".join(lines)
        result = compactor._summarize_search(content)
        assert "30 result lines" in result
        assert "15 more results" in result

    def test_write_short_passes_through(self):
        compactor = MessageCompactor()
        content = '{"success": true}'
        result = compactor._summarize_write(content)
        assert result == content

    def test_blind_truncate_fallback(self):
        result = MessageCompactor._blind_truncate("a" * 1000, 100, 50)
        assert len(result) < 1000
        assert "truncated" in result


# ------------------------------------------------------------------
# Code structure extraction
# ------------------------------------------------------------------


class TestCodeStructures:
    def test_python(self):
        code = "class Foo:\n    pass\ndef bar():\n    pass\nimport os"
        structs = _extract_code_structures(code, "app.py")
        assert "class Foo" in structs
        assert "def bar" in structs

    def test_javascript(self):
        code = "export default class App {}\nfunction helper() {}\nimport React from 'react'"
        structs = _extract_code_structures(code, "app.tsx")
        assert any("App" in s for s in structs)

    def test_json_keys(self):
        code = json.dumps({"name": "test", "version": "1.0", "scripts": {}})
        structs = _extract_code_structures(code, "package.json")
        assert any("name" in s for s in structs)

    def test_routes(self):
        code = "@app.route('/api/users')\ndef get_users(): pass"
        structs = _extract_code_structures(code, "app.py")
        assert any("/api/users" in s for s in structs)


# ------------------------------------------------------------------
# Test summary extraction
# ------------------------------------------------------------------


class TestTestSummary:
    def test_passed_failed(self):
        content = "some output\n10 passed, 2 failed\n"
        result = _extract_test_summary(content)
        assert "10" in result and "2" in result

    def test_passing_only(self):
        content = "output\n5 tests passed\n"
        result = _extract_test_summary(content)
        assert "5" in result

    def test_no_match(self):
        result = _extract_test_summary("no test output here")
        assert result == ""


# ------------------------------------------------------------------
# Phase 2: Rich condensed summaries
# ------------------------------------------------------------------


class TestCondenseTurnGroup:
    def test_basic_tool_call(self):
        compactor = MessageCompactor()
        group = [
            _assistant_with_tool("read_file", {"path": "src/app.py"}, call_id="c1"),
            _tool_result("c1", '{"success": true, "data": "file contents"}'),
        ]
        line = compactor._condense_turn_group(group)
        assert "read_file(src/app.py)" in line
        assert "→ok" in line

    def test_error_detection(self):
        compactor = MessageCompactor()
        group = [
            _assistant_with_tool("bash", {"command": "npm test"}, call_id="c1"),
            _tool_result("c1", '{"success": false, "error": "tests failed"}'),
        ]
        line = compactor._condense_turn_group(group)
        assert "→err" in line

    def test_with_metadata_annotation(self):
        compactor = MessageCompactor()
        compactor.state.tool_result_metadata["c1"] = ToolResultMeta(
            tool_name="read_file",
            line_count=120,
            structures=["class App", "def create_app"],
        )
        group = [
            _assistant_with_tool("read_file", {"path": "src/app.py"}, call_id="c1"),
            _tool_result("c1", "file contents"),
        ]
        line = compactor._condense_turn_group(group)
        assert "120 lines" in line
        assert "class App" in line

    def test_user_message(self):
        compactor = MessageCompactor()
        line = compactor._condense_turn_group([_msg("user", "Do something")])
        assert "[user]" in line

    def test_system_nudge_skipped(self):
        compactor = MessageCompactor()
        line = compactor._condense_turn_group([_msg("user", "[SYSTEM] Call done()")])
        assert line is None


# ------------------------------------------------------------------
# Adaptive keep_recent
# ------------------------------------------------------------------


class TestAdaptiveKeepRecent:
    def test_low_pressure(self):
        compactor = MessageCompactor(CompactionConfig(keep_recent=6, adaptive_recent=True))
        result = compactor._compute_keep_recent(total_groups=20, token_ratio=0.3)
        assert result == 10  # base + 4

    def test_medium_pressure(self):
        compactor = MessageCompactor(CompactionConfig(keep_recent=6, adaptive_recent=True))
        result = compactor._compute_keep_recent(total_groups=20, token_ratio=0.7)
        assert result == 6  # base

    def test_high_pressure(self):
        compactor = MessageCompactor(CompactionConfig(keep_recent=6, adaptive_recent=True))
        result = compactor._compute_keep_recent(total_groups=20, token_ratio=0.9)
        assert result == 4  # max(3, base-2)

    def test_disabled(self):
        compactor = MessageCompactor(CompactionConfig(keep_recent=6, adaptive_recent=False))
        result = compactor._compute_keep_recent(total_groups=20, token_ratio=0.3)
        assert result == 6

    def test_clamped_to_total(self):
        compactor = MessageCompactor(CompactionConfig(keep_recent=6, adaptive_recent=True))
        result = compactor._compute_keep_recent(total_groups=5, token_ratio=0.3)
        assert result == 3  # min(10, 5-2)


# ------------------------------------------------------------------
# Full compression pipeline
# ------------------------------------------------------------------


class TestCompress:
    @pytest.mark.asyncio
    async def test_no_compression_under_threshold(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=1_000_000,
        ))
        msgs = _build_conversation(5, tool_result_size=100)
        result = await compactor.compress(msgs, None, _make_agent(), None)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_phase1_triggers(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            phase1_threshold=0.1,
            phase2_threshold=0.99,
        ))
        msgs = _build_conversation(10, tool_result_size=200)
        result = await compactor.compress(msgs, None, _make_agent(), None)
        assert len(str(result)) < len(str(msgs))

    @pytest.mark.asyncio
    async def test_phase2_triggers(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=300,
            phase1_threshold=0.01,
            phase2_threshold=0.02,
            phase3_threshold=0.99,
        ))
        msgs = _build_conversation(15, tool_result_size=200)
        result = await compactor.compress(msgs, None, _make_agent(), None)
        text = str(result)
        assert "COMPRESSED HISTORY" in text

    @pytest.mark.asyncio
    async def test_metadata_persists(self):
        compactor = MessageCompactor(CompactionConfig(
            max_context_tokens=500,
            phase1_threshold=0.01,
            phase2_threshold=0.99,
            content_aware=True,
        ))
        python_content = "class Foo:\n    pass\n" + "# line\n" * 100
        msgs = [
            _msg("system", "system prompt"),
            _msg("user", "do task"),
        ]
        for i in range(10):
            cid = f"call_{i}"
            msgs.append(_assistant_with_tool("coding_read_file", {"path": f"file_{i}.py"}, call_id=cid))
            msgs.append(_tool_result(cid, python_content))
        await compactor.compress(msgs, None, _make_agent(), None)
        assert len(compactor.state.tool_result_metadata) > 0


# ------------------------------------------------------------------
# Tool result truncation (static)
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Group into turns
# ------------------------------------------------------------------


class TestGroupIntoTurns:
    def test_basic_grouping(self):
        msgs = [
            _msg("system", "sys"),
            _msg("user", "task"),
            _assistant_with_tool("read", {}, call_id="c1"),
            _tool_result("c1", "result"),
        ]
        groups = MessageCompactor._group_into_turns(msgs)
        assert len(groups) == 3  # system, user, assistant+tool

    def test_standalone_messages(self):
        msgs = [_msg("user", "hello"), _msg("user", "world")]
        groups = MessageCompactor._group_into_turns(msgs)
        assert len(groups) == 2


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_agent():
    from druppie.agent_runtime.definition import AgentDefinition
    return AgentDefinition(
        id="test",
        name="Test Agent",
        description="Test",
        system_prompt="Test prompt",
        llm_profile="standard",
    )
