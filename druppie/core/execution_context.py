"""Execution context for tracking events and LLM calls during workflow execution.

This module provides a context object that collects:
- Workflow events (agent started, completed, tool calls, etc.)
- LLM calls with full request/response details
- Real-time event emission via callback
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
import time


@dataclass
class ExecutionContext:
    """Context for tracking execution events and LLM calls.

    Passed through the execution to collect data for the frontend.
    """
    session_id: str
    user_id: str | None = None

    # Event collection
    workflow_events: list[dict] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)

    # Real-time callback
    emit_event: Callable[[dict], None] | None = None

    # Timing
    start_time: float = field(default_factory=time.time)

    def emit(self, event_type: str, data: dict = None) -> None:
        """Emit an event and store it.

        Args:
            event_type: Type of event (agent_started, tool_call, etc.)
            data: Event data
        """
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": self.session_id,
            **(data or {}),
        }

        # Store event
        self.workflow_events.append(event)

        # Emit to WebSocket if callback is set
        if self.emit_event:
            try:
                self.emit_event({
                    "type": "workflow_event",
                    "session_id": self.session_id,
                    "event": event,
                })
            except Exception:
                pass  # Don't fail execution due to emit errors

    def add_llm_call(
        self,
        agent_id: str,
        iteration: int,
        messages: list[dict],
        response: Any,
        tools: list[dict] | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Record an LLM call.

        Args:
            agent_id: ID of the calling agent
            iteration: Iteration number
            messages: Messages sent to LLM
            response: LLM response
            tools: Tools provided to LLM
            duration_ms: Call duration in milliseconds
        """
        call = {
            "agent_id": agent_id,
            "iteration": iteration,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": duration_ms,
            "messages": messages,
            "tools": tools,
            "response": {
                "content": getattr(response, "content", str(response)),
                "tool_calls": getattr(response, "tool_calls", []),
            },
            "usage": getattr(response, "usage", {}),
        }

        self.llm_calls.append(call)

        # Emit LLM call event
        self.emit("llm_call", {
            "agent_id": agent_id,
            "iteration": iteration,
            "duration_ms": duration_ms,
            "has_tool_calls": bool(getattr(response, "tool_calls", [])),
        })

    def agent_started(self, agent_id: str, prompt: str) -> None:
        """Record agent started event."""
        self.emit("agent_started", {
            "agent_id": agent_id,
            "prompt_preview": prompt[:100] if prompt else "",
        })

    def agent_completed(self, agent_id: str, iterations: int, success: bool = True) -> None:
        """Record agent completed event."""
        self.emit("agent_completed", {
            "agent_id": agent_id,
            "iterations": iterations,
            "success": success,
        })

    def agent_error(self, agent_id: str, error: str) -> None:
        """Record agent error event."""
        self.emit("agent_error", {
            "agent_id": agent_id,
            "error": error,
        })

    def tool_call(self, agent_id: str, tool_name: str, args: dict = None) -> None:
        """Record tool call event."""
        self.emit("tool_call", {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "args_preview": str(args)[:100] if args else "",
        })

    def step_started(self, step_id: str, step_type: str, agent_id: str = None) -> None:
        """Record step started event."""
        self.emit("step_started", {
            "step_id": step_id,
            "step_type": step_type,
            "agent_id": agent_id,
        })

    def step_completed(self, step_id: str, success: bool = True) -> None:
        """Record step completed event."""
        self.emit("step_completed", {
            "step_id": step_id,
            "success": success,
        })

    def to_dict(self) -> dict:
        """Convert context to dict for storage/response."""
        return {
            "session_id": self.session_id,
            "workflow_events": self.workflow_events,
            "llm_calls": self.llm_calls,
            "duration_ms": int((time.time() - self.start_time) * 1000),
        }


# Thread-local context for current execution
_current_context: ExecutionContext | None = None


def set_current_context(ctx: ExecutionContext) -> None:
    """Set the current execution context."""
    global _current_context
    _current_context = ctx


def get_current_context() -> ExecutionContext | None:
    """Get the current execution context."""
    return _current_context


def clear_current_context() -> None:
    """Clear the current execution context."""
    global _current_context
    _current_context = None
