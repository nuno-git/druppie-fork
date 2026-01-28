"""Question repository for HITL questions database access."""

from uuid import UUID
from datetime import datetime, timezone

from .base import BaseRepository
from ..domain import QuestionDetail, QuestionChoice, PendingQuestionList
from ..db.models import HitlQuestion, HitlQuestionChoice, Session as SessionModel


class QuestionRepository(BaseRepository):
    """Database access for HITL questions."""

    def get_by_id(self, question_id: UUID) -> HitlQuestion | None:
        """Get raw question model."""
        return self.db.query(HitlQuestion).filter_by(id=question_id).first()

    def get_pending_for_session(self, session_id: UUID) -> PendingQuestionList:
        """Get pending questions for a session."""
        questions = (
            self.db.query(HitlQuestion)
            .filter_by(session_id=session_id, status="pending")
            .order_by(HitlQuestion.created_at)
            .all()
        )
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get all pending questions for sessions owned by user."""
        questions = (
            self.db.query(HitlQuestion)
            .join(SessionModel, HitlQuestion.session_id == SessionModel.id)
            .filter(SessionModel.user_id == user_id)
            .filter(HitlQuestion.status == "pending")
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
        """Update question with answer."""
        self.db.query(HitlQuestion).filter_by(id=question_id).update({
            "answer": answer,
            "status": "answered",
            "answered_at": datetime.now(timezone.utc),
        })
        if selected_choices:
            for idx in selected_choices:
                self.db.query(HitlQuestionChoice).filter_by(
                    question_id=question_id,
                    choice_index=idx,
                ).update({"is_selected": True})

    def _to_detail(self, question: HitlQuestion) -> QuestionDetail:
        """Convert question model to detail domain object."""
        choices = (
            self.db.query(HitlQuestionChoice)
            .filter_by(question_id=question.id)
            .order_by(HitlQuestionChoice.choice_index)
            .all()
        )
        return QuestionDetail(
            id=question.id,
            session_id=question.session_id,
            agent_run_id=question.agent_run_id,
            agent_id=question.agent_id or "",
            question=question.question,
            question_type=question.question_type or "text",
            choices=[
                QuestionChoice(
                    index=c.choice_index,
                    text=c.choice_text,
                    is_selected=c.is_selected or False,
                )
                for c in choices
            ],
            status=question.status,
            answer=question.answer,
            answered_at=question.answered_at,
            created_at=question.created_at,
        )
