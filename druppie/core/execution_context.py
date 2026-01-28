"""Execution context for tracking events and LLM calls during workflow execution.

This module provides a context object that collects:
- Workflow events (agent started, completed, tool calls, etc.)
- LLM calls with full request/response details
- Real-time event emission via callback
- Persists events to session_events table
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID
import time

import structlog

logger = structlog.get_logger()


def _persist_event(session_id: str, event_type: str, data: dict | None = None) -> None:
    """Persist event to session_events table."""
    try:
        from druppie.db.database import get_db
        from druppie.repositories import SessionRepository

        db = next(get_db())
        try:
            session_repo = SessionRepository(db)
            session_repo.create_event(
                session_id=UUID(session_id),
                event_type=event_type,
                agent_id=data.get("agent_id") if data else None,
                title=data.get("title") if data else None,
                tool_name=data.get("tool_name") if data else None,
                event_data=data,
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("persist_event_failed", error=str(e), session_id=session_id)


class CancelledException(Exception):
    """Raised when execution is cancelled by user."""
    pass


# Registry of active executions by session ID
_active_executions: dict[str, "ExecutionContext"] = {}


@dataclass
class ExecutionContext:
    """Context for tracking execution events and LLM calls.

    Passed through the execution to collect data for the frontend.
    """
    session_id: str
    user_id: str | None = None

    # Workspace context (set after workspace initialization)
    workspace_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None  # Friendly name like "to-do-app"
    workspace_path: str | None = None
    branch: str | None = None

    # Current execution tracking (used by loop.py)
    current_agent_run_id: str | None = None
    current_workflow_id: str | None = None

    # Event collection
    workflow_events: list[dict] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)

    # Conversation history (stored in session state)
    messages: list[dict] = field(default_factory=list)

    # Real-time callback
    emit_event: Callable[[dict], None] | None = None

    # Cached tool results from approved executions
    # Used when resuming after MCP tool approval to avoid re-executing
    completed_tool_results: dict[str, Any] = field(default_factory=dict)

    # HITL clarifications from user
    # Used when resuming after HITL question to pass user's answer to agents
    hitl_clarifications: list[dict] = field(default_factory=list)

    # Timing
    start_time: float = field(default_factory=time.time)

    # Cancellation flag
    _cancelled: bool = field(default=False, repr=False)

    # Token usage tracking (aggregated from all LLM calls)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def cancel(self) -> None:
        """Mark this execution as cancelled."""
        self._cancelled = True
        self.emit("execution_cancelled", {"reason": "User requested cancellation"})
        logger.info("execution_cancelled", session_id=self.session_id)

    def check_cancelled(self) -> None:
        """Check if execution was cancelled and raise if so.

        Call this at checkpoints during execution (before LLM calls, before tool execution, etc.)
        to allow graceful cancellation.
        """
        if self._cancelled:
            raise CancelledException(f"Execution cancelled for session {self.session_id}")

    @property
    def is_cancelled(self) -> bool:
        """Check if execution is cancelled."""
        return self._cancelled

    def emit(self, event_type: str, data: dict = None) -> None:
        """Emit an event, store it, and persist to database.

        Args:
            event_type: Type of event (agent_started, tool_call, etc.)
            data: Event data
        """
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            **(data or {}),
        }

        # Store event in memory
        self.workflow_events.append(event)

        # Persist to database
        _persist_event(self.session_id, event_type, data)

        # Emit to WebSocket if callback is set
        if self.emit_event:
            try:
                self.emit_event({
                    "type": "workflow_event",
                    "session_id": self.session_id,
                    "event": event,
                })
            except Exception as e:
                logger.warning("emit_event_failed", error=str(e), session_id=self.session_id)

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
        # Extract token usage from response
        prompt_tokens = getattr(response, "prompt_tokens", 0)
        completion_tokens = getattr(response, "completion_tokens", 0)
        response_total_tokens = getattr(response, "total_tokens", 0)

        # Extract model info from response (for transparency)
        model = getattr(response, "model", "")
        provider = getattr(response, "provider", "")

        # Aggregate token usage
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += response_total_tokens

        call = {
            "agent_id": agent_id,
            "iteration": iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "messages": messages,
            "tools": tools,
            "response": {
                "content": getattr(response, "content", str(response)),
                "tool_calls": getattr(response, "tool_calls", []),
            },
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": response_total_tokens,
            },
            "model": model,
            "provider": provider,
        }

        self.llm_calls.append(call)

        # Emit LLM call event with token info and model transparency
        self.emit("llm_call", {
            "agent_id": agent_id,
            "iteration": iteration,
            "duration_ms": duration_ms,
            "has_tool_calls": bool(getattr(response, "tool_calls", [])),
            "tokens": response_total_tokens,
            "model": model,
            "provider": provider,
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

    def agent_paused(self, agent_id: str, iterations: int, reason: str) -> None:
        """Record agent paused event (waiting for HITL or approval)."""
        self.emit("agent_paused", {
            "agent_id": agent_id,
            "iterations": iterations,
            "reason": reason,
        })

    def tool_call(self, agent_id: str, tool_name: str, args: dict = None) -> None:
        """Record tool call event."""
        self.emit("tool_call", {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "args_preview": str(args)[:100] if args else "",
        })

    def tool_error(self, agent_id: str, tool_name: str, error: str) -> None:
        """Record tool error event.

        Args:
            agent_id: ID of the calling agent
            tool_name: Name of the tool that failed
            error: Error message
        """
        self.emit("tool_error", {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "error": error[:500] if error else "",  # Truncate long errors
        })

    def app_running(
        self,
        container_name: str,
        url: str,
        port: int,
        image_name: str | None = None,
    ) -> None:
        """Record app running event.

        Args:
            container_name: Name of the running container
            url: URL where the app is accessible
            port: Port the app is running on
            image_name: Docker image name
        """
        self.emit("app_running", {
            "container_name": container_name,
            "url": url,
            "port": port,
            "image_name": image_name,
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
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "workspace_path": self.workspace_path,
            "branch": self.branch,
            "workflow_events": self.workflow_events,
            "llm_calls": self.llm_calls,
            "messages": self.messages,
            "duration_ms": int((time.time() - self.start_time) * 1000),
            "token_usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }

    def get_state(self) -> dict:
        """Get state for saving during MCP tool approval.

        This includes workspace context and HITL clarifications needed
        to properly resume the agent after approval.

        Returns:
            Dict containing context and clarifications for resumption
        """
        return {
            "context": {
                "workspace_id": self.workspace_id,
                "project_id": self.project_id,
                "project_name": self.project_name,
                "workspace_path": self.workspace_path,
                "branch": self.branch,
            },
            "hitl_clarifications": self.hitl_clarifications,
        }

    def set_workspace(
        self,
        workspace_id: str,
        project_id: str | None,
        workspace_path: str,
        branch: str,
        project_name: str | None = None,
        repo_url: str | None = None,
    ) -> None:
        """Set workspace context after initialization.

        Args:
            workspace_id: Workspace ID
            project_id: Project ID
            workspace_path: Local path to workspace
            branch: Current git branch
            project_name: Friendly project name (e.g., "to-do-app")
            repo_url: Repository URL for the project
        """
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.project_name = project_name
        self.workspace_path = workspace_path
        self.branch = branch
        self.emit("workspace_initialized", {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "project_name": project_name,
            "branch": branch,
            "repo_url": repo_url,
        })


# Thread-local context for current execution
_current_context: ExecutionContext | None = None


def set_current_context(ctx: ExecutionContext) -> None:
    """Set the current execution context and register it for cancellation."""
    global _current_context
    _current_context = ctx
    # Register in active executions for cancellation support
    _active_executions[ctx.session_id] = ctx


def get_current_context() -> ExecutionContext | None:
    """Get the current execution context."""
    return _current_context


def clear_current_context() -> None:
    """Clear the current execution context and remove from registry."""
    global _current_context
    if _current_context:
        # Remove from active executions
        _active_executions.pop(_current_context.session_id, None)
    _current_context = None


def get_active_execution(session_id: str) -> ExecutionContext | None:
    """Get an active execution context by session ID.

    Used for cancellation support.

    Args:
        session_id: Session ID to look up

    Returns:
        ExecutionContext if found, None otherwise
    """
    return _active_executions.get(session_id)


def cancel_execution(session_id: str) -> bool:
    """Cancel an active execution by session ID.

    Args:
        session_id: Session ID to cancel

    Returns:
        True if execution was found and cancelled, False otherwise
    """
    ctx = _active_executions.get(session_id)
    if ctx:
        ctx.cancel()
        return True
    return False


def list_active_sessions() -> list[str]:
    """List all active session IDs.

    Returns:
        List of session IDs with active executions
    """
    return list(_active_executions.keys())
