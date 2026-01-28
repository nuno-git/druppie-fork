"""HITL question domain models."""

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class QuestionChoice(BaseModel):
    """A choice in a multiple-choice question."""
    index: int
    text: str
    is_selected: bool = False


class QuestionDetail(BaseModel):
    """HITL question."""
    id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    agent_id: str
    question: str
    question_type: str  # text, multiple_choice
    choices: list[QuestionChoice] = []
    status: str  # pending, answered
    answer: str | None
    answered_at: datetime | None
    created_at: datetime


class PendingQuestionList(BaseModel):
    """Questions waiting for user answer."""
    items: list[QuestionDetail]
    total: int
