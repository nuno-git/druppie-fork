"""Chat API routes.

Main endpoint for processing user messages.

Architecture:
    Route (this file)
      │
      └──▶ Orchestrator ──▶ Agent execution
              (router → planner → execute pending runs)

This is the entry point for all user interactions. The Orchestrator handles:
- Session creation/continuation
- Running router and planner agents
- Executing pending agent runs (the plan)
- Pausing for approvals/HITL questions

When the workflow pauses (needs approval or HITL question), the response
includes the session status. The frontend fetches SessionDetail to see
pending approvals/questions and uses:
- POST /approvals/{id}/approve or /reject
- POST /questions/{id}/answer
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_optional_user, get_orchestrator
from druppie.core.orchestrator import Orchestrator
from druppie.db.models import Session
from druppie.domain.common import SessionStatus

logger = structlog.get_logger()

router = APIRouter()


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
    status: str = Field(
        ...,
        description="Session status: active, completed, paused_approval, paused_hitl, failed",
    )
    message: str | None = Field(None, description="Status message")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict | None = Depends(get_optional_user),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    """Process a chat message.

    This is the main entry point for user interactions. Sends a message
    to the AI agent workflow which may:

    - Complete immediately
    - Pause for approval (session status = paused_approval)
    - Pause for user input (session status = paused_hitl)

    When paused, fetch SessionDetail to see pending approvals/questions,
    then use the approvals or questions endpoints to continue.

    Args:
        request: Chat message and optional session/project IDs

    Returns:
        Response with session ID and status
    """
    user_id = UUID(user["sub"]) if user and user.get("sub") else None
    project_id = UUID(request.project_id) if request.project_id else None
    session_id = UUID(request.session_id) if request.session_id else None

    logger.info(
        "chat_request",
        session_id=str(session_id) if session_id else "new",
        user_id=str(user_id) if user_id else None,
        message_length=len(request.message),
    )

    try:
        # Process message through orchestrator
        result_session_id = await orchestrator.process_message(
            message=request.message,
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
        )

        # Get session status from database
        session = orchestrator.db.query(Session).filter(Session.id == result_session_id).first()
        status = session.status if session else SessionStatus.ACTIVE.value

        return ChatResponse(
            success=True,
            session_id=str(result_session_id),
            status=status,
            message=f"Session {status}",
        )

    except Exception as e:
        logger.error(
            "chat_error",
            session_id=str(session_id) if session_id else "new",
            error=str(e),
            exc_info=True,
        )

        return ChatResponse(
            success=False,
            session_id=str(session_id) if session_id else "",
            status="error",
            message=f"Error: {str(e)}",
        )
