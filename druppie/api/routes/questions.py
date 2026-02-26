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

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import (
    get_current_user,
    get_question_service,
)
from druppie.services import QuestionService
from druppie.domain import QuestionDetail
from druppie.domain.common import SessionStatus

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
    """Resume workflow in background with its own DB session."""
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

        await orchestrator.resume_after_answer(
            session_id=session_id,
            question_id=question_id,
            answer=answer,
        )

        logger.info(
            "workflow_resumed_from_answer",
            session_id=str(session_id),
            question_id=str(question_id),
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(
            "background_answer_resume_error",
            session_id=str(session_id),
            question_id=str(question_id),
            error=error_msg,
            exc_info=True,
        )
        try:
            db.rollback()
            session_repo.update_status(
                session_id,
                SessionStatus.FAILED,
                error_message=error_msg[:2000],
            )
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
    question = question_service.answer(
        question_id=question_id,
        user_id=user_id,
        answer=request.answer,
        selected_choices=request.selected_choices,
    )

    # Step 2: Spawn background task to resume workflow
    asyncio.create_task(
        _resume_workflow_after_answer(
            session_id=question.session_id,
            question_id=question_id,
            answer=request.answer,
        )
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
