"""Tests for druppie.agent_runtime.types."""

from datetime import datetime, timezone

import pytest

from druppie.agent_runtime.types import (
    AgentCancelledError,
    AgentEvent,
    AgentLoopError,
    AgentResult,
    CancellationToken,
    CompletionPrecondition,
    CompletionSummaryRequirement,
    DoneResult,
    LoopConfig,
    RequiredToolCall,
)


class TestAgentEvent:
    def test_agent_event_creation(self):
        ts = datetime.now(timezone.utc)
        event = AgentEvent(type="turn_start", timestamp=ts, data={"turn_number": 1})
        assert event.type == "turn_start"
        assert event.timestamp == ts
        assert event.data == {"turn_number": 1}

    def test_agent_event_immutable(self):
        event = AgentEvent.now("test")
        with pytest.raises(AttributeError):
            event.type = "changed"

    def test_agent_event_now_auto_timestamp(self):
        event = AgentEvent.now("test", {"key": "value"})
        assert event.type == "test"
        assert event.data == {"key": "value"}
        assert isinstance(event.timestamp, datetime)
        assert event.timestamp.tzinfo is not None

    def test_agent_event_now_no_data(self):
        event = AgentEvent.now("test")
        assert event.data == {}


class TestAgentResult:
    def test_agent_result_completed(self):
        result = AgentResult(status="completed", done_result={"summary": "done", "variables": {}})
        assert result.status == "completed"
        assert result.done_result == {"summary": "done", "variables": {}}

    def test_agent_result_error(self):
        result = AgentResult(status="error", error="Something failed")
        assert result.status == "error"
        assert result.error == "Something failed"
        assert result.done_result is None

    def test_agent_result_cancelled(self):
        result = AgentResult(status="cancelled")
        assert result.status == "cancelled"

    def test_agent_result_paused(self):
        result = AgentResult(status="paused")
        assert result.status == "paused"
        assert result.done_result is None

    def test_agent_result_events_list(self):
        result = AgentResult(status="completed")
        assert result.events == []
        event = AgentEvent.now("test")
        result.events.append(event)
        assert len(result.events) == 1


class TestLoopConfig:
    def test_loop_config_defaults(self):
        config = LoopConfig()
        assert config.max_turns == 50
        assert config.max_retries == 3
        assert config.retry_base_delay == 1.0
        assert config.respect_retry_after is True
        assert config.max_context_tokens == 150000
        assert config.max_subagent_depth == 10
        assert config.sandbox_pool_size == 3
        assert config.sandbox_pool_recycle_s == 3600

    def test_loop_config_custom(self):
        config = LoopConfig(
            max_turns=10,
            max_retries=5,
            retry_base_delay=2.0,
            respect_retry_after=False,
            max_context_tokens=100000,
            max_subagent_depth=5,
            sandbox_pool_size=5,
            sandbox_pool_recycle_s=1800,
        )
        assert config.max_turns == 10
        assert config.max_retries == 5
        assert config.retry_base_delay == 2.0
        assert config.respect_retry_after is False
        assert config.max_context_tokens == 100000
        assert config.max_subagent_depth == 5
        assert config.sandbox_pool_size == 5
        assert config.sandbox_pool_recycle_s == 1800


class TestDoneResult:
    def test_done_result_creation(self):
        result = DoneResult(summary="Task complete", variables={"key": "value"})
        assert result.summary == "Task complete"
        assert result.variables == {"key": "value"}

    def test_done_result_variables_default(self):
        result = DoneResult(summary="Done")
        assert result.variables == {}


class TestCompletionPrecondition:
    def test_completion_precondition_defaults(self):
        pre = CompletionPrecondition()
        assert pre.summary_contains is None
        assert pre.unless_summary_contains is None
        assert pre.required_tools == []
        assert pre.error_message == ""

    def test_completion_precondition_full(self):
        pre = CompletionPrecondition(
            summary_contains="DESIGN_APPROVED",
            unless_summary_contains="EXCEPTION",
            required_tools=[RequiredToolCall(tool_name="make_design", min_calls=1)],
            error_message="Must call make_design",
        )
        assert pre.summary_contains == "DESIGN_APPROVED"
        assert pre.unless_summary_contains == "EXCEPTION"
        assert len(pre.required_tools) == 1
        assert pre.error_message == "Must call make_design"


class TestRequiredToolCall:
    def test_required_tool_call_defaults(self):
        rtc = RequiredToolCall(tool_name="some_tool")
        assert rtc.tool_name == "some_tool"
        assert rtc.min_calls == 1

    def test_required_tool_call_custom(self):
        rtc = RequiredToolCall(tool_name="some_tool", min_calls=3)
        assert rtc.min_calls == 3


class TestCompletionSummaryRequirement:
    def test_completion_summary_requirement(self):
        req = CompletionSummaryRequirement(
            one_of=["STATUS_ONE", "STATUS_TWO"],
            error_message="Must contain a status",
        )
        assert req.one_of == ["STATUS_ONE", "STATUS_TWO"]
        assert req.error_message == "Must contain a status"

    def test_completion_summary_requirement_defaults(self):
        req = CompletionSummaryRequirement()
        assert req.one_of == []
        assert req.error_message == ""


class TestCancellationToken:
    def test_cancellation_token_initial(self):
        token = CancellationToken()
        assert token.is_cancelled is False

    def test_cancellation_token_cancel(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancellation_token_idempotent(self):
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled is True


class TestErrors:
    def test_agent_cancelled_error(self):
        err = AgentCancelledError("cancelled")
        assert isinstance(err, AgentLoopError)
        assert str(err) == "cancelled"

    def test_agent_loop_error(self):
        err = AgentLoopError("base error")
        assert isinstance(err, Exception)
        assert str(err) == "base error"
