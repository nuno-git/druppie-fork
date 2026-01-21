"""Questions API routes.

Endpoints for listing pending HITL questions for the current user.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from druppie.api.deps import get_current_user

router = APIRouter()


class QuestionListResponse(BaseModel):
    """List of questions response."""

    questions: list[dict]


@router.get("")
async def list_questions(
    user: dict = Depends(get_current_user),
):
    """List pending HITL questions for the current user.

    Returns questions that agents have asked and are waiting for user response.
    """
    # TODO: Implement when HITL questions are persisted to database
    # For now, questions are only tracked transiently via Redis during execution
    return {"questions": []}
