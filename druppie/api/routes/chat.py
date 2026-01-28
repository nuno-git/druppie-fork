"""Chat API routes.

Main endpoint for processing user messages.

Architecture:
    Route (this file)
      │
      └──▶ MainLoop ──▶ Agent execution
              (LangGraph workflow)

This is the entry point for all user interactions. The MainLoop handles:
- Session creation/continuation
- Agent routing
- Tool execution
- Workflow pausing for approvals/questions

When the workflow pauses (needs approval or HITL question), the response
includes the approval_id or question_id. The frontend then uses:
- POST /approvals/{id}/approve or /reject
- POST /questions/{id}/answer
"""

import asyncio
import uuid
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_optional_user, get_loop
from druppie.api.websocket import manager
from druppie.core.loop import MainLoop

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# HELPERS
# =============================================================================


def create_emit_event(session_id: str) -> Callable[[dict], None]:
    """Create an emit_event callback for real-time updates.

    Bridges sync callback interface with async WebSocket manager.
    Falls back to storing missed events for later retrieval.
    """
    async def _emit_with_fallback(event: dict) -> None:
        try:
            await manager.broadcast_to_session(session_id, event)
        except Exception as e:
            logger.warning(
                "websocket_broadcast_failed",
                session_id=session_id,
                event_type=event.get("type"),
                error=str(e),
            )
            manager.store_missed_event(session_id, event)

    def emit_event(event: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(_emit_with_fallback(event))
            task.add_done_callback(
                lambda t: logger.error(
                    "emit_event_task_error",
                    session_id=session_id,
                    error=str(t.exception()),
                ) if t.exception() else None
            )
        except RuntimeError:
            logger.warning(
                "emit_event_no_loop",
                session_id=session_id,
                event_type=event.get("type"),
            )
            manager.store_missed_event(session_id, event)

    return emit_event


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ChatRequest(BaseModel):
    """Request for chat endpoint."""

    message: str = Field(
        ...,
        description="The user's message",
        max_length=10000,
    )
    session_id: str | None = Field(
        None,
        description="Session ID to continue an existing conversation",
    )
    project_id: str | None = Field(
        None,
        description="Project ID to work on",
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    success: bool = Field(..., description="Whether the request succeeded")
    session_id: str = Field(..., description="Session ID")
    message: str | None = Field(None, description="AI response message")
    status: str = Field(
        ...,
        description="Session status: completed, paused_approval, paused_hitl",
    )
    approval_id: str | None = Field(
        None,
        description="Pending approval ID (if status=paused_approval)",
    )
    question_id: str | None = Field(
        None,
        description="Pending question ID (if status=paused_hitl)",
    )


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict | None = Depends(get_optional_user),
    loop: MainLoop = Depends(get_loop),
) -> ChatResponse:
    """Process a chat message.

    This is the main entry point for user interactions. Sends a message
    to the AI agent workflow which may:

    - Complete immediately with a response
    - Pause for approval (returns approval_id)
    - Pause for user input (returns question_id)

    When paused, use the approvals or questions endpoints to continue.

    Args:
        request: Chat message and optional session/project IDs

    Returns:
        Response with session status and any pending IDs
    """
    session_id = request.session_id or str(uuid.uuid4())

    logger.info(
        "chat_request",
        session_id=session_id,
        user_id=user.get("sub") if user else None,
        message_length=len(request.message),
    )

    try:
        emit_event = create_emit_event(session_id)

        result = await loop.process_message(
            message=request.message,
            session_id=session_id,
            user_id=user.get("sub") if user else None,
            project_id=request.project_id,
            emit_event=emit_event,
        )

        # Determine status from result
        status = "completed"
        approval_id = None
        question_id = None

        pending_approvals = result.get("pending_approvals", [])
        pending_questions = result.get("pending_questions", [])

        if pending_approvals:
            status = "paused_approval"
            approval_id = str(pending_approvals[0].get("id"))
        elif pending_questions:
            status = "paused_hitl"
            question_id = str(pending_questions[0].get("id"))
        elif result.get("status") == "paused":
            # Generic paused state
            status = result.get("waiting_for", "paused")

        return ChatResponse(
            success=result.get("success", True),
            session_id=result.get("session_id", session_id),
            message=result.get("response"),
            status=status,
            approval_id=approval_id,
            question_id=question_id,
        )

    except Exception as e:
        logger.error("chat_error", session_id=session_id, error=str(e), exc_info=True)

        return ChatResponse(
            success=False,
            session_id=session_id,
            message=f"Error: {str(e)}",
            status="error",
            approval_id=None,
            question_id=None,
        )
