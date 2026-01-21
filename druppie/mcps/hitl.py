"""Human-in-the-Loop (HITL) MCP Server.

Provides tools for agent-to-human interaction:
- Asking questions
- Requesting approval
- Sending progress updates
"""

from datetime import datetime
from typing import Any, Callable

import structlog

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

HITL_TOOLS = [
    MCPTool(
        id="hitl:ask",
        name="Ask User",
        description="Ask the user a question and wait for their response. Use this when you need clarification or input to proceed.",
        category="hitl",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of suggested answers",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context about why this question is needed",
                },
            },
            "required": ["question"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="hitl:approve",
        name="Request Approval",
        description="Request user approval before performing a potentially dangerous action. Execution pauses until approved or rejected.",
        category="hitl",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Description of the action requiring approval",
                },
                "details": {
                    "type": "object",
                    "description": "Details about the action",
                },
                "danger_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "How dangerous is this action",
                    "default": "medium",
                },
            },
            "required": ["action"],
        },
        approval_type=ApprovalType.NONE,  # The tool itself handles approval
    ),
    MCPTool(
        id="hitl:progress",
        name="Send Progress",
        description="Send a progress update to the user. Does not pause execution.",
        category="hitl",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Progress message"},
                "percent": {
                    "type": "integer",
                    "description": "Progress percentage (0-100)",
                    "minimum": 0,
                    "maximum": 100,
                },
                "step": {
                    "type": "string",
                    "description": "Current step name",
                },
            },
            "required": ["message"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="hitl:done",
        name="Signal Completion",
        description="Signal that the task is complete and return results to the user.",
        category="hitl",
        input_schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of what was accomplished",
                },
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of created/modified files",
                },
                "data": {
                    "type": "object",
                    "description": "Structured output data",
                },
            },
            "required": ["summary"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="hitl:fail",
        name="Signal Failure",
        description="Signal that the task has failed with an error.",
        category="hitl",
        input_schema={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the task failed",
                },
                "recoverable": {
                    "type": "boolean",
                    "description": "Whether the failure is recoverable",
                    "default": False,
                },
            },
            "required": ["reason"],
        },
        approval_type=ApprovalType.NONE,
    ),
]


# =============================================================================
# HITL STATE (shared across handlers)
# =============================================================================


class HITLState:
    """Manages HITL state and callbacks.

    This is set by the main loop when starting execution.
    """

    def __init__(self):
        self.emit_event: Callable[[dict], None] | None = None
        self.state_manager = None
        self.session_id: str | None = None

    def configure(
        self,
        emit_event: Callable[[dict], None] | None,
        state_manager,
        session_id: str,
    ) -> None:
        """Configure HITL state for current execution."""
        self.emit_event = emit_event
        self.state_manager = state_manager
        self.session_id = session_id


# Global HITL state
_hitl_state = HITLState()


def configure_hitl(
    emit_event: Callable[[dict], None] | None,
    state_manager,
    session_id: str,
) -> None:
    """Configure HITL for current execution."""
    _hitl_state.configure(emit_event, state_manager, session_id)


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================


async def ask(
    question: str,
    options: list[str] | None = None,
    context: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Ask the user a question.

    This pauses execution and returns a special status.
    The main loop will resume when the user responds.
    """
    session_id = session_id or _hitl_state.session_id

    if not session_id:
        return {
            "success": False,
            "error": "No session ID for HITL operation",
        }

    # Emit event for frontend
    if _hitl_state.emit_event:
        _hitl_state.emit_event({
            "event_type": "question",
            "question": question,
            "options": options or [],
            "context": context,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    # Create question in state manager if available
    if _hitl_state.state_manager:
        _hitl_state.state_manager.pause_for_question(
            session_id=session_id,
            question=question,
            options=options,
        )

    logger.info("hitl_question_asked", question=question[:100], session=session_id)

    # Return waiting status - main loop will handle pause
    return {
        "success": True,
        "status": "waiting",
        "waiting_for": "question",
        "question": question,
        "options": options,
    }


async def approve(
    action: str,
    details: dict[str, Any] | None = None,
    danger_level: str = "medium",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Request approval for an action.

    This pauses execution until the user approves or rejects.
    """
    session_id = session_id or _hitl_state.session_id

    if not session_id:
        return {
            "success": False,
            "error": "No session ID for HITL operation",
        }

    # Emit event for frontend
    if _hitl_state.emit_event:
        _hitl_state.emit_event({
            "event_type": "approval_request",
            "action": action,
            "details": details or {},
            "danger_level": danger_level,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    # Create approval in state manager
    if _hitl_state.state_manager:
        _hitl_state.state_manager.pause_for_approval(
            session_id=session_id,
            tool_name=action,
            arguments=details or {},
            danger_level=danger_level,
        )

    logger.info(
        "hitl_approval_requested",
        action=action,
        danger_level=danger_level,
        session=session_id,
    )

    return {
        "success": True,
        "status": "waiting",
        "waiting_for": "approval",
        "action": action,
        "danger_level": danger_level,
    }


async def progress(
    message: str,
    percent: int | None = None,
    step: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Send a progress update.

    This is non-blocking - execution continues.
    """
    session_id = session_id or _hitl_state.session_id

    # Emit event for frontend
    if _hitl_state.emit_event:
        _hitl_state.emit_event({
            "event_type": "progress",
            "message": message,
            "percent": percent,
            "step": step,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    logger.debug(
        "hitl_progress",
        message=message[:100],
        percent=percent,
        step=step,
    )

    return {
        "success": True,
        "status": "acknowledged",
    }


async def done(
    summary: str,
    artifacts: list[str] | None = None,
    data: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Signal task completion.

    Agents should call this when they've completed their task.
    """
    session_id = session_id or _hitl_state.session_id

    # Emit event for frontend
    if _hitl_state.emit_event:
        _hitl_state.emit_event({
            "event_type": "done",
            "summary": summary,
            "artifacts": artifacts or [],
            "data": data or {},
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    logger.info(
        "hitl_done",
        summary=summary[:100],
        artifacts_count=len(artifacts) if artifacts else 0,
    )

    return {
        "success": True,
        "status": "done",
        "summary": summary,
        "artifacts": artifacts or [],
        "data": data or {},
    }


async def fail(
    reason: str,
    recoverable: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Signal task failure.

    Agents should call this when they cannot complete the task.
    """
    session_id = session_id or _hitl_state.session_id

    # Emit event for frontend
    if _hitl_state.emit_event:
        _hitl_state.emit_event({
            "event_type": "fail",
            "reason": reason,
            "recoverable": recoverable,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    # Update state manager
    if _hitl_state.state_manager and session_id:
        _hitl_state.state_manager.fail(session_id, reason)

    logger.error(
        "hitl_fail",
        reason=reason[:200],
        recoverable=recoverable,
    )

    return {
        "success": True,
        "status": "failed",
        "reason": reason,
        "recoverable": recoverable,
    }


# =============================================================================
# REGISTRATION
# =============================================================================


def register(registry: MCPRegistry) -> None:
    """Register the HITL MCP server."""
    server = MCPServer(
        id="hitl",
        name="Human-in-the-Loop",
        description="Tools for agent-to-human interaction",
        tools=HITL_TOOLS,
    )

    # Register handlers
    server.register_handler("ask", ask)
    server.register_handler("approve", approve)
    server.register_handler("progress", progress)
    server.register_handler("done", done)
    server.register_handler("fail", fail)

    registry.register_server(server)
