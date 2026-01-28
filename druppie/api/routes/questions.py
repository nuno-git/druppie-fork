"""Questions API routes.

HITL (Human-in-the-Loop) questions allow agents to ask users for input.
This API provides a single endpoint for answering questions.

Note: There is no "list questions" or "get question" endpoint. Pending questions
are shown in the session detail view (GET /sessions/{id}) as part of the chat
timeline. The frontend gets question details from there.

Architecture:
    Route (this file)
      │
      ├──▶ QuestionService ──▶ QuestionRepository ──▶ Database
      │         (DB operations: answer)
      │
      └──▶ WorkflowService ──▶ MainLoop
              (resume workflow after answer)

The route coordinates both services:
1. QuestionService.answer() - saves the answer to DB
2. WorkflowService.resume_from_question() - resumes the paused workflow
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import (
    get_current_user,
    get_question_service,
    get_workflow_service,
)
from druppie.services import QuestionService, WorkflowService
from druppie.domain import QuestionDetail

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
    workflow_resumed: bool
    workflow_result: dict | None = None


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/{question_id}/answer")
async def answer_question(
    question_id: UUID,
    request: AnswerRequest,
    question_service: QuestionService = Depends(get_question_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    user: dict = Depends(get_current_user),
) -> AnswerResponse:
    """Answer a pending HITL question and resume the workflow.

    This endpoint does two things:
    1. Records the answer in the database (QuestionService)
    2. Resumes the paused workflow with the answer (WorkflowService)

    For choice questions, provide both `answer` (text) and `selected_choices`
    (list of indices into the choices array).

    Args:
        question_id: The question to answer
        request: The answer details

    Returns:
        The updated question and workflow resumption result

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

    # Step 1: Save answer to database
    question = question_service.answer(
        question_id=question_id,
        user_id=user_id,
        answer=request.answer,
        selected_choices=request.selected_choices,
    )

    # Step 2: Resume the workflow
    try:
        workflow_result = await workflow_service.resume_from_question(
            session_id=question.session_id,
            question_id=question_id,
            answer=request.answer,
        )
        workflow_resumed = True
    except Exception as e:
        # Log but don't fail - the answer was saved successfully
        logger.error(
            "workflow_resume_failed",
            question_id=str(question_id),
            session_id=str(question.session_id),
            error=str(e),
        )
        workflow_result = {"error": str(e)}
        workflow_resumed = False

    logger.info(
        "question_answered",
        question_id=str(question_id),
        workflow_resumed=workflow_resumed,
    )

    return AnswerResponse(
        question=question,
        workflow_resumed=workflow_resumed,
        workflow_result=workflow_result,
    )
