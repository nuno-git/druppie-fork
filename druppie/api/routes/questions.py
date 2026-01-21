"""Questions API routes.

Endpoints for listing and answering pending HITL questions for the current user.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user, get_db
from druppie.db import (
    list_pending_hitl_questions,
    get_hitl_question,
    answer_hitl_question,
    get_hitl_questions_for_session,
)

router = APIRouter()


class QuestionListResponse(BaseModel):
    """List of questions response."""

    questions: list[dict]


class AnswerRequest(BaseModel):
    """Request body for answering a question."""

    answer: str


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
