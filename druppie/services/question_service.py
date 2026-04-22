"""Question service for HITL questions business logic.

This service handles database operations for HITL (Human-in-the-Loop) questions.
It does NOT handle workflow resumption - that's the WorkflowService's job.

Architecture:
    Route
      │
      ├──▶ QuestionService (this) ──▶ QuestionRepository ──▶ Database
      │         (DB operations)
      │
      └──▶ WorkflowService ──▶ MainLoop
              (resumption)

The route coordinates both services:
1. QuestionService.answer() - saves the answer to DB
2. WorkflowService.resume_from_question() - resumes the workflow

Note: There is no "list questions" or "get question" endpoint. Pending questions
are shown in the session detail view as part of the chat timeline.
"""

from uuid import UUID
import structlog

from ..repositories import QuestionRepository, SessionRepository
from ..domain import QuestionDetail, QuestionStatus, PendingQuestionList
from ..api.errors import NotFoundError, AuthorizationError, ConflictError

logger = structlog.get_logger()


class QuestionService:
    """Business logic for HITL questions.

    This service handles recording answers in the database.

    It does NOT handle workflow resumption. After calling answer(),
    the route should call WorkflowService.resume_from_question().
    """

    def __init__(
        self,
        question_repo: QuestionRepository,
        session_repo: SessionRepository,
    ):
        self.question_repo = question_repo
        self.session_repo = session_repo

    def get_pending_for_user(
        self,
        user_id: UUID,
        user_roles: list[str],
        is_admin: bool = False,
    ) -> PendingQuestionList:
        """List pending questions the user can answer.

        Combines:
            - Regular HITL questions for sessions the user owns.
            - Expert questions targeted at any of the user's roles.
            - Admin: every pending question.
        """
        return self.question_repo.get_pending_for_user_or_expert(
            user_id=user_id,
            user_roles=user_roles,
            is_admin=is_admin,
        )

    def answer(
        self,
        question_id: UUID,
        user_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
        is_admin: bool = False,
        user_roles: list[str] | None = None,
    ) -> QuestionDetail:
        """Record an answer to a question.

        This method ONLY saves the answer to the database. It does NOT
        resume the workflow - that's handled by WorkflowService.

        Args:
            question_id: The question to answer
            user_id: The user answering (must own the session)
            answer: The answer text
            selected_choices: For choice questions, indices of selected options

        Returns:
            Updated QuestionDetail with the answer recorded

        Raises:
            NotFoundError: Question doesn't exist
            AuthorizationError: User doesn't own the session
            ConflictError: Question already answered

        Usage in route:
            # 1. Save answer to DB
            question = question_service.answer(question_id, user_id, answer)

            # 2. Resume workflow (separate concern)
            result = await workflow_service.resume_from_question(
                session_id=question.session_id,
                question_id=question_id,
                answer=answer,
            )
        """
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("question", str(question_id))

        session = self.session_repo.get_by_id(question.session_id)
        if not session:
            raise NotFoundError("session", str(question.session_id))

        # Authorization rules
        # - Admin can always answer
        # - Expert question (expert_role set): only users with that role
        # - Regular HITL: only the session owner
        if not is_admin:
            if question.expert_role:
                if not user_roles or question.expert_role not in user_roles:
                    raise AuthorizationError(
                        f"Only users with the '{question.expert_role}' role can answer this question",
                        required_roles=[question.expert_role],
                    )
            else:
                if session.user_id != user_id:
                    raise AuthorizationError(
                        "Only the session owner can answer this question",
                    )

        # Check not already answered
        if question.status != QuestionStatus.PENDING.value:
            raise ConflictError(f"Question already {question.status}")

        # Update answer in database
        self.question_repo.update_answer(
            question_id=question_id,
            answer=answer,
            selected_choices=selected_choices,
            answered_by=user_id,
        )
        self.question_repo.commit()

        logger.info(
            "question_answered",
            question_id=str(question_id),
            by_user=str(user_id),
        )

        # Return the updated question
        # Need to re-fetch to get the updated status and answer
        updated = self.question_repo.get_by_id(question_id)
        return self.question_repo._to_detail(updated)
