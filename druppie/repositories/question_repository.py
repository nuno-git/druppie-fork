"""Question repository for database access.

Questions allow agents to ask for user input (Human-in-the-Loop).
Questions can be text (free-form) or choice-based (single/multiple selection).

Design decision: Choices are stored as JSONB in questions.choices instead
of a separate table. See druppie/db/models/question.py for detailed rationale.
"""

from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any

from .base import BaseRepository
from ..domain import QuestionDetail, QuestionChoice, PendingQuestionList, QuestionStatus
from ..db.models import Question, Session as SessionModel


class QuestionRepository(BaseRepository):
    """Database access for questions.

    Questions are stored in the questions table. For choice questions,
    the available options are stored as JSONB in the `choices` column:
        [{"text": "Option A"}, {"text": "Option B"}]

    Selected choices are tracked in `selected_indices` as an array of indices:
        [0, 2] means first and third options were selected
    """

    def get_by_id(self, question_id: UUID) -> Question | None:
        """Get raw question model."""
        return self.db.query(Question).filter_by(id=question_id).first()

    def create(
        self,
        session_id: UUID,
        agent_run_id: UUID | None,
        agent_id: str,
        question: str,
        question_type: str = "text",
        choices: list[dict[str, str]] | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> QuestionDetail:
        """Create a new question.

        Args:
            session_id: Session this question belongs to
            agent_run_id: Agent run that asked the question
            agent_id: ID of the agent asking
            question: The question text
            question_type: "text", "single_choice", or "multiple_choice"
            choices: List of choice dicts [{"text": "Option A"}, ...]
            agent_state: Saved state for resumption after answer

        Returns:
            QuestionDetail domain object
        """
        question_model = Question(
            id=uuid4(),
            session_id=session_id,
            agent_run_id=agent_run_id,
            agent_id=agent_id,
            question=question,
            question_type=question_type,
            choices=choices,
            status=QuestionStatus.PENDING.value,
            agent_state=agent_state,
        )
        self.db.add(question_model)
        self.db.flush()
        return self._to_detail(question_model)

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get all pending questions for sessions owned by user.

        This is used for the "pending questions" notification/badge in the UI.
        Users can see and answer questions from any of their sessions.
        """
        questions = (
            self.db.query(Question)
            .join(SessionModel, Question.session_id == SessionModel.id)
            .filter(SessionModel.user_id == user_id)
            .filter(Question.status == QuestionStatus.PENDING.value)
            .order_by(Question.created_at)
            .all()
        )
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def update_answer(
        self,
        question_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
    ) -> None:
        """Update question with answer.

        For choice questions, selected_choices is a list of indices.
        These are stored in the selected_indices JSONB column.
        """
        updates = {
            "answer": answer,
            "status": QuestionStatus.ANSWERED.value,
            "answered_at": datetime.now(timezone.utc),
        }
        # Store selected indices as JSONB array
        # The model's to_dict() reconstructs is_selected for each choice
        if selected_choices is not None:
            updates["selected_indices"] = selected_choices

        self.db.query(Question).filter_by(id=question_id).update(updates)

    def update_agent_state(
        self,
        question_id: UUID,
        agent_state: dict[str, Any],
    ) -> None:
        """Update question with agent state for resumption.

        This is called after the agent pauses for a question. The agent_state
        contains everything needed to resume execution after the user answers.
        """
        self.db.query(Question).filter_by(id=question_id).update({
            "agent_state": agent_state,
        })

    def _to_detail(self, question: Question) -> QuestionDetail:
        """Convert question model to detail domain object.

        Choices are read from the JSONB `choices` column and combined with
        `selected_indices` to determine which choices were selected.
        """
        # Build choices list from JSONB column
        # Format in DB: [{"text": "Option A"}, {"text": "Option B"}]
        # selected_indices: [0, 2] (indices of selected choices)
        choices = []
        if question.choices:
            selected = question.selected_indices or []
            for idx, choice_data in enumerate(question.choices):
                choices.append(QuestionChoice(
                    index=idx,
                    text=choice_data.get("text", ""),
                    is_selected=idx in selected,
                ))

        return QuestionDetail(
            id=question.id,
            session_id=question.session_id,
            agent_run_id=question.agent_run_id,
            agent_id=question.agent_id or "",
            question=question.question,
            question_type=question.question_type or "text",
            choices=choices,
            status=QuestionStatus(question.status),
            answer=question.answer,
            answered_at=question.answered_at,
            created_at=question.created_at,
        )
