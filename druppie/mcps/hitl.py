"""Human-in-the-Loop (HITL) MCP Server.

Provides tools for agent-to-human interaction:
- hitl:ask - Ask a question (pauses execution via LangGraph interrupt)
- hitl:approve - Request approval (pauses execution)
- hitl:progress - Send progress updates (non-blocking)

Key insight: hitl:ask calls LangGraph's interrupt() internally,
so the orchestrator doesn't need any special handling.
"""

from datetime import datetime
from typing import Any, Callable

import structlog
from langgraph.types import interrupt

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================


HITL_TOOLS = [
    MCPTool(
        id="hitl:ask",
        name="Ask User",
        description="Ask the user a question and wait for their response. Execution pauses until the user responds.",
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
        description="Request user approval before performing an action. Execution pauses until approved or rejected.",
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
        approval_type=ApprovalType.NONE,
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
]


# =============================================================================
# HITL STATE (for event emission)
# =============================================================================


class HITLState:
    """Manages HITL state and callbacks.

    Used for emitting events to the frontend.
    """

    def __init__(self):
        self.emit_event: Callable[[dict], None] | None = None
        self.session_id: str | None = None

    def configure(
        self,
        emit_event: Callable[[dict], None] | None,
        session_id: str,
    ) -> None:
        """Configure HITL state for current execution."""
        self.emit_event = emit_event
        self.session_id = session_id


# Global HITL state
_hitl_state = HITLState()


def configure_hitl(
    emit_event: Callable[[dict], None] | None,
    session_id: str,
) -> None:
    """Configure HITL for current execution."""
    _hitl_state.configure(emit_event, session_id)


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================


async def ask(
    question: str,
    options: list[str] | None = None,
    context: str | None = None,
    session_id: str | None = None,
) -> str:
    """Ask the user a question.

    This calls LangGraph's interrupt() to pause execution.
    When the user responds, execution resumes and this function
    returns the user's answer.

    Args:
        question: The question to ask
        options: Optional list of suggested answers
        context: Additional context

    Returns:
        The user's response (string)
    """
    session_id = session_id or _hitl_state.session_id

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

    logger.info("hitl_asking_user", question=question[:100], session=session_id)

    # This is the magic - interrupt() pauses LangGraph execution
    # and returns the payload to the caller. When graph.invoke(Command(resume=...))
    # is called, the resume value becomes the return value of interrupt().
    user_response = interrupt({
        "type": "question",
        "question": question,
        "options": options or [],
        "context": context,
        "session_id": session_id,
    })

    logger.info("hitl_user_responded", response=str(user_response)[:100])

    # Return the user's response directly to the agent
    return user_response


async def approve(
    action: str,
    details: dict[str, Any] | None = None,
    danger_level: str = "medium",
    session_id: str | None = None,
) -> bool:
    """Request approval for an action.

    This pauses execution until the user approves or rejects.

    Args:
        action: Description of the action
        details: Additional details
        danger_level: low, medium, high, or critical

    Returns:
        True if approved, False if rejected
    """
    session_id = session_id or _hitl_state.session_id

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

    logger.info(
        "hitl_requesting_approval",
        action=action,
        danger_level=danger_level,
        session=session_id,
    )

    # Pause for approval
    approval_response = interrupt({
        "type": "approval",
        "action": action,
        "details": details or {},
        "danger_level": danger_level,
        "session_id": session_id,
    })

    # approval_response should be True/False or {"approved": true/false}
    if isinstance(approval_response, bool):
        approved = approval_response
    elif isinstance(approval_response, dict):
        approved = approval_response.get("approved", False)
    else:
        approved = str(approval_response).lower() in ("true", "yes", "approved")

    logger.info("hitl_approval_result", approved=approved)

    return approved


async def progress(
    message: str,
    percent: int | None = None,
    step: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Send a progress update.

    This is non-blocking - execution continues immediately.

    Args:
        message: Progress message
        percent: Optional percentage (0-100)
        step: Optional step name

    Returns:
        Acknowledgment dict
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
        "acknowledged": True,
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

    registry.register_server(server)
