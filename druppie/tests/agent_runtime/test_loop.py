"""Tests for druppie.agent_runtime.loop.AgentLoop."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.types import (
    CancellationToken,
    LoopConfig,
)


def _make_done_response(summary="Task complete", variables=None):
    args = {"summary": summary}
    if variables:
        args.update(variables)
    return {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_done_1",
                        "type": "function",
                        "function": {"name": "done", "arguments": json.dumps(args)},
                    }
                ],
            }
        }],
        "usage": {},
    }


def _make_text_response(text="I'm thinking..."):
    return {
        "choices": [{
            "message": {"content": text, "tool_calls": None}
        }],
        "usage": {},
    }


def _make_tool_response(tool_name, tool_args, call_id="call_1"):
    return {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }
                ],
            }
        }],
        "usage": {},
    }


def _make_tool_responses_seq(responses):
    return [_make_tool_response(r[0], r[1], r[2] if len(r) > 2 else f"call_{i}")
            for i, r in enumerate(responses)]


class MockToolProvider:
    def __init__(self, tools=None, tool_results=None):
        self._tools = tools or []
        self._tool_results = tool_results or {}
        self._list_calls = 0

    async def list_tools(self):
        self._list_calls += 1
        return list(self._tools)

    async def execute(self, tool_name, arguments):
        if tool_name in self._tool_results:
            result = self._tool_results[tool_name]
            if callable(result):
                return result(arguments)
            return result
        return {"success": True, "data": f"executed {tool_name}"}

    async def close(self):
        pass


def _defn(**kwargs) -> AgentDefinition:
    defaults = {
        "id": "test_agent",
        "name": "Test Agent",
        "description": "A test agent",
        "system_prompt": "You are a test agent.",
        "mcps": {},
    }
    defaults.update(kwargs)
    return AgentDefinition(**defaults)


def _defn_with_mcps() -> AgentDefinition:
    return _defn(
        mcps={
            "sandbox": {"tools": ["read_file", "write_file"]},
            "core-tools": {"tools": ["make_plan"]},
        },
    )


def _defn_with_subagents() -> AgentDefinition:
    return _defn(
        subagents=["coding_planner"],
        mcps={
            "sandbox": {"tools": ["read_file"]},
        },
    )


def _tool_schema(name, description="A tool"):
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


SANDBOX_TOOLS = [_tool_schema("read_file"), _tool_schema("write_file")]
CORE_TOOLS = [_tool_schema("make_plan")]
ALL_MCP_TOOLS = SANDBOX_TOOLS + CORE_TOOLS


def _get_tool_name(t):
    if "function" in t:
        return t["function"]["name"]
    return t.get("name", "")


async def _run_loop(
    definition,
    mock_llm,
    tool_provider=None,
    prompt="Do something",
    initial_messages=None,
    config=None,
    cancellation_token=None,
    agent_loader=None,
    sandbox_resolver=None,
    event_callbacks=None,
):
    from druppie.agent_runtime.loop import AgentLoop

    loop = AgentLoop()
    tp = tool_provider or MockToolProvider()
    cfg = config or LoopConfig(max_turns=10, max_retries=3, retry_base_delay=0.01)
    kwargs = {
        "agent": definition,
        "agent_loader": agent_loader or (lambda name: _defn(id=name)),
        "tool_provider": tp,
        "llm": mock_llm,
        "sandbox_resolver": sandbox_resolver or AsyncMock(),
        "config": cfg,
    }
    if prompt is not None:
        kwargs["prompt"] = prompt
    if initial_messages is not None:
        kwargs["initial_messages"] = initial_messages
    if cancellation_token is not None:
        kwargs["cancellation_token"] = cancellation_token
    if event_callbacks is not None:
        kwargs["event_callbacks"] = event_callbacks

    return await loop.run(**kwargs)


class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_run_basic_done(self):
        llm = MagicMock()
        llm.call_count = 0
        llm.responses = [_make_done_response()]
        llm._idx = 0

        async def _llm(messages, tools=None, **kw):
            llm.call_count += 1
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm)
        assert result.status == "completed"
        assert result.done_result is not None
        assert result.done_result["summary"] == "Task complete"

    @pytest.mark.asyncio
    async def test_run_tool_then_done(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("read_file")],
            tool_results={"read_file": {"success": True, "data": "file contents"}},
        )
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("read_file", {"path": "/tmp/test.txt"}),
            _make_done_response("Read the file"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn_with_mcps(), llm, tool_provider=tool_provider)
        assert result.status == "completed"
        assert result.done_result["summary"] == "Read the file"

    @pytest.mark.asyncio
    async def test_run_multiple_turns(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("read_file"), _tool_schema("write_file")],
            tool_results={
                "read_file": {"success": True, "data": "content"},
                "write_file": {"success": True, "data": "written"},
            },
        )
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("read_file", {"path": "/a"}),
            _make_tool_response("write_file", {"path": "/b", "content": "x"}),
            _make_done_response("Did multiple things"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn_with_mcps(), llm, tool_provider=tool_provider)
        assert result.status == "completed"
        assert llm._idx == 3

    @pytest.mark.asyncio
    async def test_run_with_prompt(self):
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Prompt received")]
        llm.captured_messages = None

        async def _llm(messages, tools=None, **kw):
            if llm._idx == 0:
                llm.captured_messages = messages
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm, prompt="Hello agent")
        assert result.status == "completed"
        assert llm.captured_messages is not None
        user_msgs = [m for m in llm.captured_messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        assert "Hello agent" in user_msgs[-1].get("content", "")

    @pytest.mark.asyncio
    async def test_run_with_initial_messages(self):
        initial = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Thinking..."},
            {"role": "user", "content": "Continue"},
        ]
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Resumed")]
        llm.captured_messages = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_messages = messages
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(
            _defn(), llm, prompt=None, initial_messages=initial
        )
        assert result.status == "completed"
        assert len(llm.captured_messages) >= len(initial)

    @pytest.mark.asyncio
    async def test_run_requires_prompt_or_messages(self):
        with pytest.raises((ValueError, TypeError)):
            await _run_loop(_defn(), MagicMock(), prompt=None, initial_messages=None)


class TestDoneEnforcement:
    @pytest.mark.asyncio
    async def test_enforcement_text_response(self):
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_text_response("Just thinking out loud"),
            _make_done_response("Now actually done"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm)
        assert result.status == "completed"
        assert llm._idx == 2

    @pytest.mark.asyncio
    async def test_enforcement_max_retries_reached(self):
        config = LoopConfig(max_turns=5, max_retries=2, retry_base_delay=0.01)
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_text_response("No"),
            _make_text_response("Still no"),
        ]

        async def _llm(messages, tools=None, **kw):
            idx = llm._idx
            llm._idx += 1
            if idx < len(llm.responses):
                return llm.responses[idx]
            return _make_text_response("Keep refusing")

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm, config=config)
        assert result.status == "completed"
        assert result.done_result is not None

    @pytest.mark.asyncio
    async def test_enforcement_emits_event(self):
        collected = []
        def callback(e):
            collected.append(e)

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_text_response("No done"),
            _make_done_response("Final"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(_defn(), llm, event_callbacks=[callback])
        enforcement_events = [e for e in collected if e.type == "enforcement_retry"]
        assert len(enforcement_events) >= 1

    @pytest.mark.asyncio
    async def test_done_validates_preconditions(self):
        defn = _defn(
            completion_preconditions=[{
                "summary_contains": "COMPLETE",
                "required_tools": [{"tool_name": "must_call", "min_calls": 1}],
                "error_message": "Must call must_call first",
            }],
        )
        tool_provider = MockToolProvider(tools=[_tool_schema("must_call")])

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_done_response("COMPLETE"),
            _make_tool_response("must_call", {}),
            _make_done_response("COMPLETE"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[min(llm._idx, len(llm.responses) - 1)]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(defn, llm, tool_provider=tool_provider)
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_done_accepts_valid(self):
        defn = _defn(
            done_variables={
                "next_agent": {"type": "string", "enum": ["a", "b"], "required": True},
            },
        )
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_done_response("Done", variables={"next_agent": "a"}),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(defn, llm)
        assert result.status == "completed"
        assert result.done_result["variables"]["next_agent"] == "a"


class TestToolFiltering:
    @pytest.mark.asyncio
    async def test_tool_filtering_by_mcps(self):
        defn = _defn_with_mcps()
        tool_provider = MockToolProvider(tools=ALL_MCP_TOOLS)

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]
        llm.captured_tools = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_tools = tools
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(defn, llm, tool_provider=tool_provider)
        tool_names = [_get_tool_name(t) for t in (llm.captured_tools or [])]
        assert "done" in tool_names
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "make_plan" in tool_names

    @pytest.mark.asyncio
    async def test_done_always_included(self):
        tool_provider = MockToolProvider(tools=[])
        defn = _defn(mcps={})

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]
        llm.captured_tools = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_tools = tools
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(defn, llm, tool_provider=tool_provider)
        tool_names = [_get_tool_name(t) for t in (llm.captured_tools or [])]
        assert "done" in tool_names

    @pytest.mark.asyncio
    async def test_subagents_included_when_configured(self):
        defn = _defn_with_subagents()
        tool_provider = MockToolProvider(tools=[_tool_schema("read_file")])

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]
        llm.captured_tools = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_tools = tools
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(defn, llm, tool_provider=tool_provider)
        tool_names = [_get_tool_name(t) for t in (llm.captured_tools or [])]
        assert "subagents" in tool_names

    @pytest.mark.asyncio
    async def test_subagents_excluded_when_not_configured(self):
        defn = _defn()
        tool_provider = MockToolProvider(tools=[])

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]
        llm.captured_tools = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_tools = tools
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(defn, llm, tool_provider=tool_provider)
        tool_names = [_get_tool_name(t) for t in (llm.captured_tools or [])]
        assert "subagents" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_list_rebuilt_each_turn(self):
        tool_provider = MockToolProvider(tools=[_tool_schema("read_file")])

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("read_file", {"path": "/a"}),
            _make_done_response("Done"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(_defn_with_mcps(), llm, tool_provider=tool_provider)
        assert tool_provider._list_calls >= 2


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_on_pending(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("ask_question")],
            tool_results={
                "ask_question": {
                    "success": True,
                    "_pending": True,
                    "resume_id": "hitl_abc123",
                    "message": "Question sent",
                },
            },
        )
        defn = _defn(mcps={"core-tools": {"tools": ["ask_question"]}})

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("ask_question", {"question": "Continue?"}),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(defn, llm, tool_provider=tool_provider)
        assert result.status == "paused"

    @pytest.mark.asyncio
    async def test_pause_preserves_events(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("ask_question")],
            tool_results={
                "ask_question": {
                    "success": True,
                    "_pending": True,
                    "resume_id": "hitl_abc123",
                },
            },
        )
        defn = _defn(mcps={"core-tools": {"tools": ["ask_question"]}})

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("ask_question", {"question": "Continue?"}),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(defn, llm, tool_provider=tool_provider)
        assert len(result.events) >= 1
        event_types = [e.type for e in result.events]
        assert "turn_start" in event_types or "tool_call" in event_types

    @pytest.mark.asyncio
    async def test_resume_continues_from_messages(self):
        initial = [
            {"role": "user", "content": "Start"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "ask_question", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"_pending": True, "resume_id": "hitl_abc"})},
            {"role": "user", "content": "User answered: yes"},
        ]

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Resumed and done")]
        llm.captured_messages = None

        async def _llm(messages, tools=None, **kw):
            llm.captured_messages = messages
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm, prompt=None, initial_messages=initial)
        assert result.status == "completed"
        assert llm.captured_messages is not None


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_llm_retry_on_error(self):
        collected = []

        llm = MagicMock()
        llm._idx = 0

        async def _llm(messages, tools=None, **kw):
            idx = llm._idx
            llm._idx += 1
            if idx == 0:
                raise RuntimeError("Temporary API error")
            return _make_done_response("Recovered")

        llm.side_effect = _llm

        config = LoopConfig(max_turns=5, max_retries=3, retry_base_delay=0.01)
        await _run_loop(
            _defn(), llm, config=config, event_callbacks=[lambda e: collected.append(e)]
        )
        retry_events = [e for e in collected if e.type == "llm_retry"]
        assert len(retry_events) >= 1

    @pytest.mark.asyncio
    async def test_llm_retry_exhausted(self):
        llm = MagicMock()
        llm._idx = 0

        async def _llm(messages, tools=None, **kw):
            llm._idx += 1
            raise RuntimeError("Permanent API error")

        llm.side_effect = _llm

        config = LoopConfig(max_turns=5, max_retries=2, retry_base_delay=0.01)
        result = await _run_loop(_defn(), llm, config=config)
        assert result.status == "error"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_tool_error_continues(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("failing_tool")],
            tool_results={
                "failing_tool": {"success": False, "error": "Tool crashed"},
            },
        )
        defn = _defn(mcps={"sandbox": {"tools": ["failing_tool"]}})

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("failing_tool", {}),
            _make_done_response("Handled error"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[min(llm._idx, len(llm.responses) - 1)]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(defn, llm, tool_provider=tool_provider)
        assert result.status == "completed"
        assert result.done_result["summary"] == "Handled error"


class TestContextOverflow:
    @pytest.mark.asyncio
    async def test_context_overflow_forces_done(self):
        config = LoopConfig(max_context_tokens=50, max_turns=10, retry_base_delay=0.01)

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Context overflow exit")]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[min(llm._idx, len(llm.responses) - 1)]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        long_prompt = "x " * 5000
        result = await _run_loop(_defn(), llm, prompt=long_prompt, config=config)
        assert result.status == "completed"
        assert result.done_result is not None


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancellation_between_turns(self):
        token = CancellationToken()
        tool_provider = MockToolProvider(
            tools=[_tool_schema("read_file")],
            tool_results={"read_file": {"success": True, "data": "ok"}},
        )
        defn = _defn(mcps={"sandbox": {"tools": ["read_file"]}})

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("read_file", {}),
            _make_done_response("Should not reach"),
        ]

        async def _llm(messages, tools=None, **kw):
            if llm._idx == 0:
                llm._idx += 1
                return llm.responses[0]
            token.cancel()
            llm._idx += 1
            return llm.responses[1]

        llm.side_effect = _llm

        result = await _run_loop(defn, llm, tool_provider=tool_provider, cancellation_token=token)
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancellation_before_start(self):
        token = CancellationToken()
        token.cancel()

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Should not reach")]

        async def _llm(messages, tools=None, **kw):
            llm._idx += 1
            return llm.responses[0]

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm, cancellation_token=token)
        assert result.status == "cancelled"
        assert llm._idx == 0


class TestEvents:
    @pytest.mark.asyncio
    async def test_event_turn_start_end(self):
        collected = []

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(_defn(), llm, event_callbacks=[lambda e: collected.append(e)])
        turn_starts = [e for e in collected if e.type == "turn_start"]
        turn_ends = [e for e in collected if e.type == "turn_end"]
        assert len(turn_starts) >= 1
        assert len(turn_ends) >= 1

    @pytest.mark.asyncio
    async def test_event_tool_call_result(self):
        tool_provider = MockToolProvider(
            tools=[_tool_schema("read_file")],
            tool_results={"read_file": {"success": True, "data": "contents"}},
        )
        defn = _defn(mcps={"sandbox": {"tools": ["read_file"]}})
        collected = []

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [
            _make_tool_response("read_file", {"path": "/test"}),
            _make_done_response("Done"),
        ]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(
            defn, llm, tool_provider=tool_provider, event_callbacks=[lambda e: collected.append(e)]
        )
        tool_calls = [e for e in collected if e.type == "tool_call"]
        tool_results = [e for e in collected if e.type == "tool_result"]
        assert len(tool_calls) >= 1
        assert len(tool_results) >= 1
        assert tool_calls[0].data["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_event_done(self):
        collected = []

        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("All done")]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        await _run_loop(_defn(), llm, event_callbacks=[lambda e: collected.append(e)])
        done_events = [e for e in collected if e.type == "done"]
        assert len(done_events) >= 1
        assert done_events[0].data["summary"] == "All done"

    @pytest.mark.asyncio
    async def test_events_in_result(self):
        llm = MagicMock()
        llm._idx = 0
        llm.responses = [_make_done_response("Done")]

        async def _llm(messages, tools=None, **kw):
            r = llm.responses[llm._idx]
            llm._idx += 1
            return r

        llm.side_effect = _llm

        result = await _run_loop(_defn(), llm)
        assert isinstance(result.events, list)
        assert len(result.events) >= 1
        event_types = [e.type for e in result.events]
        assert "turn_start" in event_types
        assert "turn_end" in event_types
        assert "done" in event_types
