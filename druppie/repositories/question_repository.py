"""Question repository for database access.

Questions allow agents to ask for user input (Human-in-the-Loop).
Questions can be text (free-form) or choice-based (single/multiple selection).

Design decision: Choices are stored as JSONB in questions.choices instead
of a separate table. See druppie/db/models/question.py for detailed rationale.
"""

from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, and_

from .base import BaseRepository
from ..domain import QuestionDetail, QuestionChoice, PendingQuestionList, QuestionStatus
from ..db.models import Question, Session as SessionModel
from ..db.models.user import User as UserModel


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
        agent_run_id: UUID,
        tool_call_id: UUID,
        question: str,
        question_type: str = "text",
        choices: list[dict[str, str]] | None = None,
        agent_id: str | None = None,
        expert_role: str | None = None,
    ) -> Question:
        """Create a new question.

        Args:
            session_id: Session this question belongs to
            agent_run_id: Agent run that asked the question
            tool_call_id: ToolCall this question is for
            question: The question text
            question_type: "text" or "choice"
            choices: List of choice dicts [{"text": "Option A"}, ...]
            agent_id: ID of the agent asking (optional)
            expert_role: When set, route the question to users with this
                Keycloak role instead of the session owner. Used by the
                ask_expert tool family.

        Returns:
            Created Question model
        """
        question_model = Question(
            id=uuid4(),
            session_id=session_id,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            agent_id=agent_id,
            question=question,
            question_type=question_type,
            choices=choices,
            status=QuestionStatus.PENDING.value,
            expert_role=expert_role,
        )
        self.db.add(question_model)
        self.db.flush()
        return question_model

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
            .filter(Question.expert_role.is_(None))
            .order_by(Question.created_at)
            .all()
        )
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def get_pending_for_user_or_expert(
        self,
        user_id: UUID,
        user_roles: list[str],
        is_admin: bool = False,
    ) -> PendingQuestionList:
        """Get pending questions the user can answer.

        Returns:
            - Regular HITL questions (expert_role is NULL) from sessions the
              user owns.
            - Expert questions whose expert_role matches one of the user's
              Keycloak roles.
            - Admin: every pending question, regardless of role/ownership.
        """
        query = (
            self.db.query(Question)
            .filter(Question.status == QuestionStatus.PENDING.value)
        )

        if not is_admin:
            owner_filter = and_(
                Question.expert_role.is_(None),
                Question.session_id.in_(
                    self.db.query(SessionModel.id).filter(SessionModel.user_id == user_id)
                ),
            )
            conditions = [owner_filter]
            if user_roles:
                conditions.append(Question.expert_role.in_(list(user_roles)))
            query = query.filter(or_(*conditions))

        questions = query.order_by(Question.created_at).all()
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def list_session_ids_with_expert_role(
        self,
        user_roles: list[str],
    ) -> list[UUID]:
        """Return session IDs that ever had an expert question for one of
        the given roles. Used to grant read-only session access to experts.
        """
        if not user_roles:
            return []
        rows = (
            self.db.query(Question.session_id)
            .filter(Question.expert_role.in_(list(user_roles)))
            .distinct()
            .all()
        )
        return [r[0] for r in rows if r[0] is not None]

    def update_answer(
        self,
        question_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
        answered_by: UUID | None = None,
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
        if answered_by is not None:
            updates["answered_by"] = answered_by
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

        # Hydrate session metadata so the Questions page can render context
        # without a follow-up call. One join is cheap; the alternative is N+1.
        session_title = None
        session_owner_username = None
        if question.session_id:
            row = (
                self.db.query(SessionModel.title, UserModel.username)
                .outerjoin(UserModel, SessionModel.user_id == UserModel.id)
                .filter(SessionModel.id == question.session_id)
                .first()
            )
            if row:
                session_title = row[0]
                session_owner_username = row[1]

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
            answered_by=question.answered_by,
            expert_role=question.expert_role,
            session_title=session_title,
            session_owner_username=session_owner_username,
            created_at=question.created_at,
        )
