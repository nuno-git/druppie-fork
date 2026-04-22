"""HITL question domain models."""

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from .common import QuestionStatus


class QuestionChoice(BaseModel):
    """A choice in a multiple-choice question."""
    index: int
    text: str
    is_selected: bool = False


class QuestionDetail(BaseModel):
    """HITL or ask_expert question.

    When `expert_role` is set, the question is targeted at users with that
    Keycloak role (the `ask_expert` tool family). Otherwise it is a normal
    HITL question that only the session owner (or admin) can answer.
    """
    id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    agent_id: str
    question: str
    question_type: str  # text, multiple_choice
    choices: list[QuestionChoice] = []
    status: QuestionStatus
    answer: str | None
    answered_at: datetime | None
    answered_by: UUID | None = None
    # When set, only users with this role (plus admins) can answer.
    # The session owner cannot answer expert questions unless they hold the role.
    expert_role: str | None = None
    # Title of the session this question belongs to (for the Questions page).
    session_title: str | None = None
    # Username of the session owner (for the Questions page).
    session_owner_username: str | None = None
    created_at: datetime


class PendingQuestionList(BaseModel):
    """Questions waiting for user answer."""
    items: list[QuestionDetail]
    total: int
