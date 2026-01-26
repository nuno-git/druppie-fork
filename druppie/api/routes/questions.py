"""Questions API routes.

Endpoints for listing and answering pending HITL questions for the current user.
Also includes internal endpoints for MCP servers to create questions.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user, get_db, verify_internal_api_key
from druppie.api.errors import NotFoundError, ConflictError, ExternalServiceError
from druppie.api.routes.chat import create_emit_event
from druppie.db import (
    list_pending_hitl_questions,
    get_hitl_question,
    answer_hitl_question,
    get_hitl_questions_for_session,
    create_hitl_question,
)

router = APIRouter()


class QuestionListResponse(BaseModel):
    """List of questions response."""

    questions: list[dict]


class AnswerRequest(BaseModel):
    """Request body for answering a question."""

    answer: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User's answer (1-10000 characters)",
    )


class CreateQuestionRequest(BaseModel):
    """Request body for creating a HITL question (from MCP server)."""

    question_id: str = Field(..., description="Unique question ID")
    session_id: str = Field(..., description="Session this question belongs to")
    agent_id: str = Field(..., description="Agent that asked the question")
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The question text (1-5000 characters)",
    )
    question_type: Literal["text", "choice"] = Field(
        default="text",
        description="Question type: text for free-form, choice for multiple choice",
    )
    choices: list[str] | None = Field(
        default=None,
        max_length=20,
        description="Available choices for choice questions (max 20 options)",
    )


@router.get("")
async def list_questions(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List pending HITL questions for the current user.

    Returns questions that agents have asked and are waiting for user response.
    """
    user_id = user.get("sub")  # Keycloak user ID
    questions = list_pending_hitl_questions(db, user_id=user_id)
    return {"questions": [q.to_dict() for q in questions]}


@router.get("/{question_id}")
async def get_question(
    question_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific HITL question by ID."""
    question = get_hitl_question(db, question_id)
    if not question:
        raise NotFoundError("question", question_id)
    return question.to_dict()


@router.post("/{question_id}/answer")
async def answer_question(
    question_id: str,
    request: AnswerRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Answer a pending HITL question and resume workflow.

    This submits the user's response to the agent's question and
    resumes the workflow execution with the provided answer.
    """
    from uuid import UUID
    from druppie.core.loop import get_main_loop
    import structlog
    logger = structlog.get_logger()

    logger.info("answering_question", question_id=question_id, answer_preview=request.answer[:50])

    # Convert string to UUID for database queries
    try:
        question_uuid = UUID(question_id)
    except ValueError:
        raise NotFoundError("question", question_id)

    question = get_hitl_question(db, question_uuid)
    if not question:
        raise NotFoundError("question", question_id)

    if question.status != "pending":
        raise ConflictError(f"Question {question_id} is already {question.status}")

    # Save the answer to database
    updated = answer_hitl_question(db, question_uuid, request.answer)
    if not updated:
        raise ExternalServiceError("database", "Failed to answer question")

    # Resume the workflow with the answer
    # Create emit_event callback for real-time updates
    session_id_str = str(question.session_id)
    emit_event = create_emit_event(session_id_str)

    logger.info("resuming_workflow", session_id=session_id_str, question_id=question_id)

    main_loop = get_main_loop()
    result = await main_loop.resume_from_question_answer(
        session_id=session_id_str,
        question_id=question_id,
        answer=request.answer,
        emit_event=emit_event,
    )

    logger.info("workflow_resumed", session_id=session_id_str, result_keys=list(result.keys()) if result else None)

    # Return both the answered question and the workflow result
    return {
        "question": updated.to_dict(),
        "workflow_result": result,
    }


@router.get("/session/{session_id}")
async def list_session_questions(
    session_id: str,
    status: str | None = None,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all HITL questions for a specific session.

    Optionally filter by status (pending, answered, expired).
    """
    questions = get_hitl_questions_for_session(db, session_id, status=status)
    return {"questions": [q.to_dict() for q in questions]}


# =============================================================================
# INTERNAL ENDPOINTS (for MCP servers)
# =============================================================================


@router.post("/internal/create")
async def create_question_internal(
    request: CreateQuestionRequest,
    _: bool = Depends(verify_internal_api_key),
    db: Session = Depends(get_db),
):
    """Create a HITL question (internal endpoint for MCP servers).

    This endpoint is called by the HITL MCP server when an agent asks
    a question. It persists the question to the database so it survives
    restarts and can be retrieved by the frontend.

    Requires X-Internal-API-Key header for authentication.
    """
    # Check if question already exists (idempotent)
    existing = get_hitl_question(db, request.question_id)
    if existing:
        return existing.to_dict()

    question = create_hitl_question(
        db=db,
        question_id=request.question_id,
        session_id=request.session_id,
        agent_id=request.agent_id,
        question=request.question,
        question_type=request.question_type,
        choices=request.choices,
    )
    return question.to_dict()
