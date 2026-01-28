"""Question repository for HITL questions database access.

HITL (Human-in-the-Loop) questions allow agents to ask for user input.
Questions can be text (free-form) or choice-based (single/multiple selection).

Design decision: Choices are stored as JSONB in hitl_questions.choices instead
of a separate table. See druppie/db/models.py for detailed rationale.
"""

from uuid import UUID
from datetime import datetime, timezone

from .base import BaseRepository
from ..domain import QuestionDetail, QuestionChoice, PendingQuestionList, QuestionStatus
from ..db.models import HitlQuestion, Session as SessionModel


class QuestionRepository(BaseRepository):
    """Database access for HITL questions.

    Questions are stored in the hitl_questions table. For choice questions,
    the available options are stored as JSONB in the `choices` column:
        [{"text": "Option A"}, {"text": "Option B"}]

    Selected choices are tracked in `selected_indices` as an array of indices:
        [0, 2] means first and third options were selected
    """

    def get_by_id(self, question_id: UUID) -> HitlQuestion | None:
        """Get raw question model."""
        return self.db.query(HitlQuestion).filter_by(id=question_id).first()

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get all pending questions for sessions owned by user.

        This is used for the "pending questions" notification/badge in the UI.
        Users can see and answer questions from any of their sessions.
        """
        questions = (
            self.db.query(HitlQuestion)
            .join(SessionModel, HitlQuestion.session_id == SessionModel.id)
            .filter(SessionModel.user_id == user_id)
            .filter(HitlQuestion.status == QuestionStatus.PENDING.value)
            .order_by(HitlQuestion.created_at)
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

        self.db.query(HitlQuestion).filter_by(id=question_id).update(updates)

    def _to_detail(self, question: HitlQuestion) -> QuestionDetail:
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
