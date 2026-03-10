"""Questions API routes.

HITL (Human-in-the-Loop) questions allow agents to ask users for input.
This API provides a single endpoint for answering questions.

Note: There is no "list questions" or "get question" endpoint. Pending questions
are shown in the session detail view (GET /sessions/{id}) as part of the chat
timeline. The frontend gets question details from there.

Architecture:
    POST /questions/{id}/answer
      │
      ├── Save answer to DB (fast)
      ├── Spawn background task
      └── Return immediately

    Background task:
      └──▶ Orchestrator.resume_after_answer()
              (continues workflow with the answer)

The endpoint returns immediately. The client polls
GET /api/sessions/{id} to track progress.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_current_user, get_question_service, get_user_roles
from druppie.services import QuestionService
from druppie.domain import QuestionDetail
from druppie.core.background_tasks import create_session_task, run_session_task, SessionTaskConflict

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class AnswerRequest(BaseModel):
    """Request body for answering a question."""

    answer: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User's answer (1-10000 characters)",
    )
    selected_choices: list[int] | None = Field(
        default=None,
        description="For choice questions, indices of selected options",
    )


class AnswerResponse(BaseModel):
    """Response after answering a question."""

    question: QuestionDetail
    message: str = "Processing started"


# =============================================================================
# BACKGROUND TASK
# =============================================================================


async def _resume_workflow_after_answer(
    session_id: UUID,
    question_id: UUID,
    answer: str,
) -> None:
    """Resume workflow in background using run_session_task for DB lifecycle."""

    async def task(ctx):
        await ctx.orchestrator.resume_after_answer(
            session_id=session_id,
            question_id=question_id,
            answer=answer,
        )

    await run_session_task(session_id, task, "resume_after_answer")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/{question_id}/answer")
async def answer_question(
    question_id: UUID,
    request: AnswerRequest,
    question_service: QuestionService = Depends(get_question_service),
    user: dict = Depends(get_current_user),
) -> AnswerResponse:
    """Answer a pending HITL question and resume the workflow.

    Saves the answer and starts workflow resumption in the background.
    Returns immediately - poll GET /api/sessions/{id} for progress.

    For choice questions, provide both `answer` (text) and `selected_choices`
    (list of indices into the choices array).

    Args:
        question_id: The question to answer
        request: The answer details

    Returns:
        The updated question (workflow continues in background)

    Raises:
        NotFoundError: Question doesn't exist
        AuthorizationError: User doesn't own the session
        ConflictError: Question already answered
    """
    user_id = UUID(user["sub"])

    logger.info(
        "answering_question",
        question_id=str(question_id),
        user_id=str(user_id),
        answer_preview=request.answer[:50] if request.answer else "",
    )

    # Step 1: Save answer to database (fast)
    roles = get_user_roles(user)
    question = question_service.answer(
        question_id=question_id,
        user_id=user_id,
        answer=request.answer,
        selected_choices=request.selected_choices,
        is_admin="admin" in roles,
    )

    # Step 2: Spawn background task to resume workflow
    try:
        create_session_task(
            question.session_id,
            _resume_workflow_after_answer(
                session_id=question.session_id,
                question_id=question_id,
                answer=request.answer,
            ),
            name=f"resume-answer-{question_id}",
        )
    except SessionTaskConflict:
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )

    logger.info(
        "answer_recorded_resuming_in_background",
        question_id=str(question_id),
        session_id=str(question.session_id),
    )

    return AnswerResponse(
        question=question,
        message="Answered - workflow resuming",
    )
