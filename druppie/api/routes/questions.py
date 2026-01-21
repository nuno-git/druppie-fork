"""Questions API routes.

Endpoints for listing and answering pending HITL questions for the current user.
Also includes internal endpoints for MCP servers to create questions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user, get_db, verify_internal_api_key
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

    answer: str


class CreateQuestionRequest(BaseModel):
    """Request body for creating a HITL question (from MCP server)."""

    question_id: str
    session_id: str
    agent_id: str
    question: str
    question_type: str = "text"  # "text" or "choice"
    choices: list[str] | None = None


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
        raise HTTPException(status_code=404, detail="Question not found")
    return question.to_dict()


@router.post("/{question_id}/answer")
async def answer_question(
    question_id: str,
    request: AnswerRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Answer a pending HITL question.

    This submits the user's response to the agent's question.
    """
    question = get_hitl_question(db, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Question is already {question.status}",
        )

    updated = answer_hitl_question(db, question_id, request.answer)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to answer question")

    return updated.to_dict()


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
