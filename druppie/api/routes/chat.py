"""Chat API routes.

Main endpoint for processing user messages.

Architecture:
    POST /api/chat
      │
      ├── Create session (fast)
      ├── Spawn background task
      └── Return immediately with session_id

    Background task:
      └──▶ Orchestrator ──▶ Agent execution
              (router → planner → execute pending runs)

The endpoint returns immediately with session_id. The client polls
GET /api/sessions/{id} to track progress.

When the workflow pauses (needs approval or HITL question), the session
status changes. The frontend fetches SessionDetail to see pending
approvals/questions and uses:
- POST /approvals/{id}/approve or /reject
- POST /questions/{id}/answer
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_optional_user, get_session_repository
from druppie.repositories import SessionRepository
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
# BACKGROUND TASK
# =============================================================================


async def _run_orchestrator_background(
    message: str,
    user_id: UUID,
    session_id: UUID,
    project_id: UUID | None,
) -> None:
    """Run orchestrator in background with its own DB session.

    This task creates fresh repositories with a new DB session that lives
    for the duration of the task (not tied to the HTTP request lifecycle).
    """
    from druppie.db.database import SessionLocal
    from druppie.repositories import (
        SessionRepository,
        ExecutionRepository,
        ProjectRepository,
        QuestionRepository,
    )
    from druppie.execution import Orchestrator

    db = SessionLocal()
    try:
        # Create fresh repositories with background DB session
        session_repo = SessionRepository(db)
        execution_repo = ExecutionRepository(db)
        project_repo = ProjectRepository(db)
        question_repo = QuestionRepository(db)

        orchestrator = Orchestrator(
            session_repo=session_repo,
            execution_repo=execution_repo,
            project_repo=project_repo,
            question_repo=question_repo,
        )

        # Process the message (this does all the heavy work)
        await orchestrator.process_message(
            message=message,
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
        )

    except Exception as e:
        logger.error(
            "background_orchestrator_error",
            session_id=str(session_id),
            error=str(e),
            exc_info=True,
        )
        # Update session status to failed
        try:
            from druppie.repositories import SessionRepository as SR
            sr = SR(db)
            sr.update_status(session_id, SessionStatus.FAILED)
            db.commit()
        except Exception as update_error:
            logger.error(
                "failed_to_update_session_status",
                session_id=str(session_id),
                error=str(update_error),
            )
    finally:
        db.close()


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict | None = Depends(get_optional_user),
    session_repo: SessionRepository = Depends(get_session_repository),
) -> ChatResponse:
    """Process a chat message.

    Creates a session and starts processing in the background.
    Returns immediately with the session ID.

    The client should poll GET /api/sessions/{id} to track progress.
    Session status will be:
    - active: Processing in progress
    - completed: All agents finished
    - paused_approval: Waiting for tool approval
    - paused_hitl: Waiting for user answer
    - failed: Error occurred

    Args:
        request: Chat message and optional session/project IDs

    Returns:
        Response with session ID (processing continues in background)
    """
    # User ID is required for the orchestrator (to fetch projects)
    if not user or not user.get("sub"):
        return ChatResponse(
            success=False,
            session_id="",
            status="error",
            message="Authentication required",
        )

    user_id = UUID(user["sub"])
    project_id = UUID(request.project_id) if request.project_id else None
    session_id_param = UUID(request.session_id) if request.session_id else None

    logger.info(
        "chat_request",
        session_id=str(session_id_param) if session_id_param else "new",
        user_id=str(user_id),
        message_length=len(request.message),
    )

    try:
        # Step 1: Get or create session (fast, synchronous)
        if session_id_param:
            existing = session_repo.get_by_id(session_id_param)
            if not existing:
                return ChatResponse(
                    success=False,
                    session_id=str(session_id_param),
                    status="error",
                    message=f"Session {session_id_param} not found",
                )
            # Only allow continuing a completed session
            if existing.status != SessionStatus.COMPLETED.value:
                return ChatResponse(
                    success=False,
                    session_id=str(session_id_param),
                    status="error",
                    message=f"Cannot continue session: status is '{existing.status}', must be 'completed'",
                )
            current_session_id = session_id_param
        else:
            session = session_repo.create(
                user_id=user_id,
                project_id=project_id,
                title=request.message[:100] if request.message else "New Session",
            )
            session_repo.commit()
            current_session_id = session.id

        logger.info(
            "chat_session_created",
            session_id=str(current_session_id),
            is_new=session_id_param is None,
        )

        # Step 2: Spawn background task (does NOT block)
        asyncio.create_task(
            _run_orchestrator_background(
                message=request.message,
                user_id=user_id,
                session_id=current_session_id,
                project_id=project_id,
            )
        )

        # Step 3: Return immediately
        return ChatResponse(
            success=True,
            session_id=str(current_session_id),
            status=SessionStatus.ACTIVE.value,
            message="Processing started",
        )

    except Exception as e:
        logger.error(
            "chat_error",
            session_id=str(session_id_param) if session_id_param else "new",
            error=str(e),
            exc_info=True,
        )

        return ChatResponse(
            success=False,
            session_id=str(session_id_param) if session_id_param else "",
            status="error",
            message=f"Error: {str(e)}",
        )
