"""Chat API routes.

Main endpoint for processing user messages.
"""

import asyncio
from typing import Any, Callable
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_current_user, get_loop, get_optional_user
from druppie.api.websocket import manager
from druppie.core.loop import MainLoop

logger = structlog.get_logger()


def create_emit_event(session_id: str) -> Callable[[dict], None]:
    """Create an emit_event callback for ExecutionContext.

    This bridges the sync callback interface expected by ExecutionContext
    with the async WebSocket manager.
    """
    def emit_event(event: dict) -> None:
        """Emit event to WebSocket (sync wrapper)."""
        try:
            # Get the current event loop or create a new one
            try:
                loop = asyncio.get_running_loop()
                # If we're in an async context, schedule the coroutine
                asyncio.create_task(
                    manager.broadcast_to_session(session_id, event)
                )
            except RuntimeError:
                # No running loop - this shouldn't happen in FastAPI but handle it
                pass
        except Exception as e:
            logger.debug("emit_event_error", error=str(e))

    return emit_event

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ChatMessage(BaseModel):
    """A message in conversation history."""

    role: str  # user, assistant, system
    content: str


class ChatRequest(BaseModel):
    """Request for chat endpoint."""

    message: str = Field(..., description="The user's message")
    session_id: str | None = Field(None, description="Session ID to continue")
    project_id: str | None = Field(None, description="Existing project ID to work on")
    project_name: str | None = Field(None, description="Name for new project (used if project_id not provided)")
    conversation_history: list[ChatMessage] = Field(
        default_factory=list,
        description="Previous conversation messages",
    )
    user_projects: list[dict] = Field(
        default_factory=list,
        description="User's existing projects for context",
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    success: bool
    type: str  # chat, question, result, paused, error
    response: str | None = None
    question: str | None = None
    intent: dict | None = None
    plan: dict | None = None
    session_id: str
    plan_id: str | None = None  # Alias for session_id (backwards compatibility)
    # Workspace info (git-first architecture)
    workspace_id: str | None = None
    project_id: str | None = None
    branch: str | None = None
    status: str | None = None  # Session status
    waiting_for: str | None = None
    total_usage: dict | None = None
    llm_calls: list[dict] = Field(default_factory=list)
    workflow_events: list[dict] = Field(default_factory=list)
    pending_approvals: list[dict] = Field(default_factory=list)
    pending_questions: list[dict] = Field(default_factory=list)


class ResumeRequest(BaseModel):
    """Request to resume a paused session."""

    answer: str | None = Field(None, description="Answer to a question")
    approved: bool | None = Field(None, description="Approval decision")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict | None = Depends(get_optional_user),
    loop: MainLoop = Depends(get_loop),
):
    """Process a chat message.

    This is the main entry point for user interactions.
    """
    session_id = request.session_id or str(uuid.uuid4())

    logger.info(
        "chat_request",
        session_id=session_id,
        user_id=user.get("sub") if user else None,
        message_length=len(request.message),
    )

    try:
        # Create emit_event callback for real-time updates
        emit_event = create_emit_event(session_id)

        result = await loop.process_message(
            message=request.message,
            session_id=session_id,
            user_id=user.get("sub") if user else None,
            project_id=request.project_id,
            project_name=request.project_name,
            emit_event=emit_event,
        )

        result_session_id = result.get("session_id", session_id)
        return ChatResponse(
            success=result.get("success", False),
            type=result.get("type", "error"),
            response=result.get("response"),
            question=result.get("question"),
            intent=result.get("intent"),
            plan=result.get("plan"),
            session_id=result_session_id,
            plan_id=result_session_id,  # Backwards compatibility
            workspace_id=result.get("workspace_id"),
            project_id=result.get("project_id"),
            branch=result.get("branch"),
            status=result.get("status"),
            waiting_for=result.get("waiting_for"),
            total_usage=result.get("total_usage"),
            llm_calls=result.get("llm_calls", []),
            workflow_events=result.get("workflow_events", []),
            pending_approvals=result.get("pending_approvals", []),
            pending_questions=result.get("pending_questions", []),
        )

    except Exception as e:
        logger.error("chat_error", session_id=session_id, error=str(e))
        return ChatResponse(
            success=False,
            type="error",
            response=f"Error processing request: {str(e)}",
            session_id=session_id,
            plan_id=session_id,
        )


@router.post("/chat/{session_id}/resume", response_model=ChatResponse)
async def resume_chat(
    session_id: str,
    request: ResumeRequest,
    user: dict = Depends(get_current_user),
    loop: MainLoop = Depends(get_loop),
):
    """Resume a paused chat session.

    Used when a session is waiting for user input (question or approval).
    """
    logger.info(
        "chat_resume",
        session_id=session_id,
        user_id=user.get("sub"),
        has_answer=request.answer is not None,
        has_approval=request.approved is not None,
    )

    try:
        # Create emit_event callback for real-time updates
        emit_event = create_emit_event(session_id)

        # Determine the response value based on what's provided
        if request.approved is not None:
            response_value = {"approved": request.approved}
        else:
            response_value = request.answer

        result = await loop.resume_session(
            session_id=session_id,
            response=response_value,
            emit_event=emit_event,
        )

        return ChatResponse(
            success=result.get("success", False),
            type=result.get("type", "error"),
            response=result.get("response"),
            question=result.get("question"),
            intent=result.get("intent"),
            plan=result.get("plan"),
            session_id=session_id,
            plan_id=session_id,  # Backwards compatibility
            status=result.get("status"),
            waiting_for=result.get("waiting_for"),
            workflow_events=result.get("workflow_events", []),
            pending_approvals=result.get("pending_approvals", []),
            pending_questions=result.get("pending_questions", []),
            llm_calls=result.get("llm_calls", []),
        )

    except Exception as e:
        logger.error("chat_resume_error", session_id=session_id, error=str(e))
        return ChatResponse(
            success=False,
            type="error",
            response=f"Error resuming session: {str(e)}",
            session_id=session_id,
            plan_id=session_id,
        )


@router.get("/chat/{session_id}/status")
async def get_chat_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    loop: MainLoop = Depends(get_loop),
):
    """Get the status of a chat session."""
    state = loop._state_manager.get_state(session_id)

    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "status": state.status.value,
        "current_index": state.current_index,
        "has_pending_question": state.pending_question is not None,
        "has_pending_approval": state.pending_approval is not None,
    }
