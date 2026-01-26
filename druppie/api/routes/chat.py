"""Chat API routes.

Main endpoint for processing user messages.
"""

import asyncio
from typing import Any, Callable
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from sqlalchemy.orm import Session as DBSession

from druppie.api.deps import get_current_user, get_db, get_loop, get_optional_user
from druppie.api.errors import NotFoundError
from druppie.api.websocket import manager
from druppie.core.loop import MainLoop

logger = structlog.get_logger()


def create_emit_event(session_id: str) -> Callable[[dict], None]:
    """Create an emit_event callback for ExecutionContext.

    This bridges the sync callback interface expected by ExecutionContext
    with the async WebSocket manager.

    If WebSocket broadcast fails, events are stored in the manager's
    missed_events buffer for later retrieval via GET /events/{session_id}.
    """
    async def _emit_with_fallback(event: dict) -> None:
        """Async helper that broadcasts and stores on failure."""
        try:
            await manager.broadcast_to_session(session_id, event)
        except Exception as e:
            logger.warning(
                "websocket_broadcast_failed",
                session_id=session_id,
                event_type=event.get("type"),
                error=str(e),
            )
            # Store event for later retrieval
            manager.store_missed_event(session_id, event)

    def emit_event(event: dict) -> None:
        """Emit event to WebSocket (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            # Schedule the coroutine and handle errors properly
            task = asyncio.create_task(_emit_with_fallback(event))
            # Add error handler to catch any unhandled exceptions
            task.add_done_callback(
                lambda t: logger.error(
                    "emit_event_task_error",
                    session_id=session_id,
                    error=str(t.exception()),
                ) if t.exception() else None
            )
        except RuntimeError:
            # No running loop - shouldn't happen in FastAPI but log it
            logger.warning(
                "emit_event_no_loop",
                session_id=session_id,
                event_type=event.get("type"),
            )
            # Store event for later retrieval since we can't broadcast
            manager.store_missed_event(session_id, event)

    return emit_event

router = APIRouter()


def _extract_provider(error_str: str) -> str | None:
    """Extract LLM provider name from error string."""
    error_lower = error_str.lower()
    if "z.ai" in error_lower or "zai" in error_lower:
        return "zai"
    elif "deepinfra" in error_lower:
        return "deepinfra"
    elif "openai" in error_lower:
        return "openai"
    return None


import re


def _extract_project_name(message: str) -> str:
    """Extract a project name from the user's message.

    Looks for patterns like:
    - "build a todo app" -> "todo-app"
    - "create a greeting page" -> "greeting-page"
    - "make a simple counter" -> "simple-counter"

    Returns a slugified name suitable for git repos.
    """
    message_lower = message.lower()

    # Common patterns for project descriptions
    patterns = [
        r"(?:build|create|make|develop)\s+(?:a|an|the)?\s*(?:simple|basic)?\s*(.+?)(?:\s+(?:with|using|in|for|that)\s|$)",
        r"(?:todo|counter|calculator|notes?|weather|greeting|hello)\s*(?:app|page|application)?",
    ]

    # Try to extract from common patterns
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            # Use the first captured group if available, otherwise the whole match
            name = match.group(1) if match.lastindex else match.group(0)
            break
    else:
        # Fallback: use first few meaningful words
        words = re.findall(r'\b[a-z]+\b', message_lower)
        # Remove common stop words
        stop_words = {'a', 'an', 'the', 'build', 'create', 'make', 'please', 'can', 'you', 'me', 'i', 'want', 'to'}
        meaningful = [w for w in words[:6] if w not in stop_words and len(w) > 2]
        name = ' '.join(meaningful[:3]) if meaningful else "new-project"

    # Slugify the name
    # Remove special chars, replace spaces with hyphens
    slug = re.sub(r'[^a-z0-9\s-]', '', name.strip())
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)  # Remove multiple hyphens
    slug = slug.strip('-')

    # Ensure it's not too long and not empty
    slug = slug[:50] if slug else "new-project"

    return slug


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ChatMessage(BaseModel):
    """A message in conversation history."""

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"role": "user", "content": "Create a todo app with React"},
                {"role": "assistant", "content": "I'll help you create a todo app..."},
            ]
        }
    }


class ChatRequest(BaseModel):
    """Request for chat endpoint.

    Send a message to start or continue a conversation with Druppie.
    """

    message: str = Field(
        ...,
        description="The user's message describing what they want to build or do",
        max_length=5000,
    )
    session_id: str | None = Field(
        None,
        description="Session ID to continue an existing conversation",
    )
    project_id: str | None = Field(
        None,
        description="Existing project ID to work on",
    )
    project_name: str | None = Field(
        None,
        description="Name for new project (used if project_id not provided)",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        max_length=100,
    )
    conversation_history: list[ChatMessage] = Field(
        default_factory=list,
        description="Previous conversation messages for context",
    )
    user_projects: list[dict] = Field(
        default_factory=list,
        description="User's existing projects for context",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Create a simple todo app with React",
                    "project_name": "my-todo-app",
                },
                {
                    "message": "Add dark mode support",
                    "session_id": "abc-123",
                    "project_id": "proj-456",
                },
            ]
        }
    }


class ErrorInfo(BaseModel):
    """Detailed error information for frontend display."""

    message: str = Field(..., description="Human-readable error message")
    error_type: str = Field(..., description="Type of error: rate_limit, auth, server, or general")
    retryable: bool = Field(..., description="Whether the operation can be retried")
    retry_after: int | None = Field(None, description="Seconds to wait before retry (if known)")
    provider: str | None = Field(None, description="LLM provider that returned the error")


class ChatResponse(BaseModel):
    """Response from chat endpoint.

    Contains the result of processing a chat message including any
    AI response, questions for the user, and execution status.
    """

    success: bool = Field(..., description="Whether the request was processed successfully")
    type: str = Field(
        ...,
        description="Response type: chat, question, result, paused, or error",
    )
    response: str | None = Field(None, description="AI response message")
    question: str | None = Field(None, description="Question for the user (if type=question)")
    intent: dict | None = Field(None, description="Detected intent from the message")
    plan: dict | None = Field(None, description="Execution plan if generated")
    session_id: str = Field(..., description="Session ID for this conversation")
    plan_id: str | None = Field(None, description="Alias for session_id (deprecated)")
    # Workspace info (git-first architecture)
    workspace_id: str | None = Field(None, description="Workspace ID if initialized")
    project_id: str | None = Field(None, description="Project ID if assigned")
    project_name: str | None = Field(None, description="Friendly project name (e.g., 'to-do-app')")
    branch: str | None = Field(None, description="Git branch name")
    status: str | None = Field(None, description="Session status: active, paused, completed")
    waiting_for: str | None = Field(None, description="What the session is waiting for")
    total_usage: dict | None = Field(None, description="Token usage statistics")
    llm_calls: list[dict] = Field(default_factory=list, description="LLM call history")
    workflow_events: list[dict] = Field(default_factory=list, description="Workflow events")
    pending_approvals: list[dict] = Field(default_factory=list, description="Pending approval requests")
    pending_questions: list[dict] = Field(default_factory=list, description="Pending HITL questions")
    # Error details for retryable errors
    error_info: ErrorInfo | None = Field(None, description="Detailed error information")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "type": "chat",
                    "response": "I'll help you create a todo app. Let me set up the project...",
                    "session_id": "abc-123",
                    "workspace_id": "ws-456",
                    "project_id": "proj-789",
                    "status": "active",
                },
                {
                    "success": True,
                    "type": "question",
                    "question": "Which database would you like to use: PostgreSQL, MySQL, or SQLite?",
                    "session_id": "abc-123",
                    "status": "paused",
                    "waiting_for": "user_input",
                },
            ]
        }
    }


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

        # Note: conversation_history from request is ignored
        # Messages are stored in the database and retrieved automatically

        # Auto-generate project name from message if not provided
        project_name = request.project_name
        # Check if this is a new session (session_id may be provided by frontend but not yet in DB)
        is_new_session = True
        if request.session_id:
            from druppie.db.crud import get_session
            from druppie.db.database import get_db
            # Use get_db generator to check if session exists
            db = next(get_db())
            try:
                existing_session = get_session(db, session_id)
                is_new_session = existing_session is None
            finally:
                db.close()

        if not project_name and not request.project_id and is_new_session:
            # New session without existing project - extract name from message
            project_name = _extract_project_name(request.message)
            if project_name and project_name != "new-project":
                logger.info(
                    "auto_generated_project_name",
                    project_name=project_name,
                    message_preview=request.message[:50],
                )

        result = await loop.process_message(
            message=request.message,
            session_id=session_id,
            user_id=user.get("sub") if user else None,
            project_id=request.project_id,
            project_name=project_name,
            emit_event=emit_event,
        )

        result_session_id = result.get("session_id", session_id)

        # Check if there's an error in the result and extract error info
        error_info = None
        error_str = result.get("error", "")

        if error_str and not result.get("success", True):
            # Parse error string to detect error type
            error_lower = error_str.lower()
            if "rate limit" in error_lower or "429" in error_str or "too many" in error_lower:
                error_info = ErrorInfo(
                    message="Rate limit exceeded. Please wait a moment and try again.",
                    error_type="rate_limit",
                    retryable=True,
                    provider=_extract_provider(error_str),
                )
            elif "api key" in error_lower or "401" in error_str or "authentication" in error_lower:
                error_info = ErrorInfo(
                    message="Authentication failed. Please check the API configuration.",
                    error_type="auth",
                    retryable=False,
                    provider=_extract_provider(error_str),
                )
            elif "server error" in error_lower or "500" in error_str or "502" in error_str:
                error_info = ErrorInfo(
                    message="Server error. Please try again.",
                    error_type="server",
                    retryable=True,
                    provider=_extract_provider(error_str),
                )

        return ChatResponse(
            success=result.get("success", False),
            type=result.get("type", "error") if not error_str else "error",
            response=result.get("response") or error_str,
            question=result.get("question"),
            intent=result.get("intent"),
            plan=result.get("plan"),
            session_id=result_session_id,
            plan_id=result_session_id,  # Backwards compatibility
            workspace_id=result.get("workspace_id"),
            project_id=result.get("project_id"),
            project_name=result.get("project_name"),  # Friendly name like "to-do-app"
            branch=result.get("branch"),
            status=result.get("status"),
            waiting_for=result.get("waiting_for"),
            total_usage=result.get("total_usage"),
            llm_calls=result.get("llm_calls", []),
            workflow_events=result.get("workflow_events", []),
            pending_approvals=result.get("pending_approvals", []),
            pending_questions=result.get("pending_questions", []),
            error_info=error_info,
        )

    except Exception as e:
        logger.error("chat_error", session_id=session_id, error=str(e), exc_info=True)

        # Check for LLM-specific errors
        from druppie.llm import LLMError, RateLimitError, AuthenticationError, ServerError

        error_info = None
        error_message = str(e)

        if isinstance(e, RateLimitError):
            error_info = ErrorInfo(
                message="Rate limit exceeded. Please wait a moment and try again.",
                error_type="rate_limit",
                retryable=True,
                retry_after=e.retry_after,
                provider=e.provider,
            )
            error_message = str(e)
        elif isinstance(e, AuthenticationError):
            error_info = ErrorInfo(
                message="Authentication failed. Please check the API key configuration.",
                error_type="auth",
                retryable=False,
                provider=e.provider,
            )
            error_message = str(e)
        elif isinstance(e, ServerError):
            error_info = ErrorInfo(
                message="Server error. Please try again in a moment.",
                error_type="server",
                retryable=True,
                provider=e.provider,
            )
            error_message = str(e)
        elif isinstance(e, LLMError):
            error_info = ErrorInfo(
                message=str(e),
                error_type="llm",
                retryable=e.retryable,
                provider=e.provider,
            )
            error_message = str(e)

        return ChatResponse(
            success=False,
            type="error",
            response=f"Error processing request: {error_message}",
            session_id=session_id,
            plan_id=session_id,
            error_info=error_info,
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
        logger.error("chat_resume_error", session_id=session_id, error=str(e), exc_info=True)

        # Check for LLM-specific errors
        from druppie.llm import LLMError, RateLimitError, AuthenticationError, ServerError

        error_info = None
        error_message = str(e)

        if isinstance(e, RateLimitError):
            error_info = ErrorInfo(
                message="Rate limit exceeded. Please wait a moment and try again.",
                error_type="rate_limit",
                retryable=True,
                retry_after=e.retry_after,
                provider=e.provider,
            )
        elif isinstance(e, AuthenticationError):
            error_info = ErrorInfo(
                message="Authentication failed. Please check the API key configuration.",
                error_type="auth",
                retryable=False,
                provider=e.provider,
            )
        elif isinstance(e, ServerError):
            error_info = ErrorInfo(
                message="Server error. Please try again in a moment.",
                error_type="server",
                retryable=True,
                provider=e.provider,
            )
        elif isinstance(e, LLMError):
            error_info = ErrorInfo(
                message=str(e),
                error_type="llm",
                retryable=e.retryable,
                provider=e.provider,
            )

        return ChatResponse(
            success=False,
            type="error",
            response=f"Error resuming session: {error_message}",
            session_id=session_id,
            plan_id=session_id,
            error_info=error_info,
        )


@router.get("/chat/{session_id}/status")
async def get_chat_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: "DBSession" = Depends(get_db),
):
    """Get the status of a chat session.

    Returns session state including:
    - Session status (active, paused, completed, failed)
    - Current agent (if any)
    - Pending approval (if any)
    - Pending HITL questions (if any)
    - Last activity timestamp
    """
    from druppie.db.crud import (
        get_session,
        list_pending_approvals,
        get_hitl_questions_for_session,
    )

    session = get_session(db, session_id)

    if not session:
        raise NotFoundError("session", session_id)

    # Get pending approvals for this session
    pending_approvals = list_pending_approvals(db, session_id=session_id)

    # Get pending HITL questions for this session
    pending_questions = get_hitl_questions_for_session(db, session_id, status="pending")

    # Extract current agent from state if available
    current_agent = None
    if session.state:
        # Check for current step info in workflow events
        workflow_events = session.state.get("workflow_events", [])
        for event in reversed(workflow_events):
            if event.get("type") == "step_started" and event.get("data", {}).get("agent_id"):
                current_agent = event["data"]["agent_id"]
                break

    return {
        "session_id": session_id,
        "status": session.status,
        "current_agent": current_agent,
        "has_pending_approval": len(pending_approvals) > 0,
        "has_pending_question": len(pending_questions) > 0,
        "pending_approvals": [a.to_dict() for a in pending_approvals],
        "pending_questions": [q.to_dict() for q in pending_questions],
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.get("/chat/{session_id}/events")
async def get_missed_events(
    session_id: str,
    clear: bool = True,
    user: dict = Depends(get_current_user),
):
    """Get missed events for a session.

    Events that failed to deliver via WebSocket are stored for later retrieval.
    Use this endpoint to poll for missed events when WebSocket is unavailable.

    Args:
        session_id: The session ID to get events for
        clear: If True (default), clear events after retrieval

    Returns:
        List of missed events
    """
    events = manager.get_missed_events(session_id, clear=clear)
    return {
        "session_id": session_id,
        "events": events,
        "count": len(events),
    }


@router.post("/chat/{session_id}/cancel")
async def cancel_chat_execution(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Cancel an ongoing execution for a session.

    This will attempt to gracefully stop the current execution.
    The execution may complete its current step before stopping.

    Args:
        session_id: The session ID to cancel

    Returns:
        Status of cancellation attempt
    """
    from druppie.core.execution_context import cancel_execution, get_active_execution
    from druppie.db.crud import get_session, update_session

    logger.info("cancel_execution_request", session_id=session_id, user_id=user.get("sub"))

    # Check if session exists
    session = get_session(db, session_id)
    if not session:
        raise NotFoundError("session", session_id)

    # Check if there's an active execution
    active_ctx = get_active_execution(session_id)
    if not active_ctx:
        # No active execution - might already be completed or not started
        return {
            "session_id": session_id,
            "cancelled": False,
            "reason": "No active execution found for this session",
            "session_status": session.status,
        }

    # Cancel the execution
    cancelled = cancel_execution(session_id)

    if cancelled:
        # Update session status
        update_session(db, session_id, status="cancelled")
        db.commit()

        # Emit cancellation event via WebSocket
        try:
            await manager.broadcast_to_session(session_id, {
                "type": "execution_cancelled",
                "session_id": session_id,
                "message": "Execution was cancelled by user",
            })
        except Exception as e:
            logger.warning("cancel_broadcast_failed", session_id=session_id, error=str(e))

        logger.info("execution_cancelled", session_id=session_id)

    return {
        "session_id": session_id,
        "cancelled": cancelled,
        "message": "Execution cancellation requested" if cancelled else "Failed to cancel execution",
    }
