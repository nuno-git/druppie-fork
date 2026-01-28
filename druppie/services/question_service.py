"""Question service for HITL questions business logic."""

from uuid import UUID
import structlog

from ..repositories import QuestionRepository, SessionRepository
from ..domain import QuestionDetail, PendingQuestionList
from ..api.errors import NotFoundError, AuthorizationError, ConflictError

logger = structlog.get_logger()


class QuestionService:
    """Business logic for HITL questions."""

    def __init__(
        self,
        question_repo: QuestionRepository,
        session_repo: SessionRepository,
    ):
        self.question_repo = question_repo
        self.session_repo = session_repo

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get pending questions for user's sessions."""
        return self.question_repo.get_pending_for_user(user_id)

    def get_detail(
        self,
        question_id: UUID,
        user_id: UUID,
    ) -> QuestionDetail:
        """Get question detail with ownership check."""
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("question", str(question_id))

        session = self.session_repo.get_by_id(question.session_id)
        if not session or session.user_id != user_id:
            raise AuthorizationError("Can only answer questions in your own sessions")

        return self.question_repo._to_detail(question)

    async def answer(
        self,
        question_id: UUID,
        user_id: UUID,
        main_loop,  # MainLoop instance for resumption
        answer: str,
        selected_choices: list[int] | None = None,
    ) -> dict:
        """Answer a question and resume execution."""
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("question", str(question_id))

        session = self.session_repo.get_by_id(question.session_id)
        if not session or session.user_id != user_id:
            raise AuthorizationError("Can only answer questions in your own sessions")

        if question.status != "pending":
            raise ConflictError(f"Question already {question.status}")

        # Update answer
        self.question_repo.update_answer(
            question_id=question_id,
            answer=answer,
            selected_choices=selected_choices,
        )
        self.question_repo.commit()

        logger.info(
            "question_answered",
            question_id=str(question_id),
            by_user=str(user_id),
        )

        # Resume execution
        result = await main_loop.resume_from_question_answer(
            session_id=str(question.session_id),
            question_id=str(question_id),
            answer=answer,
        )

        return {
            "success": True,
            "status": "answered",
            "result": result,
        }
