"""Session service for business logic."""

from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..domain import SessionDetail, SessionSummary
from ..domain.common import SessionStatus
from ..repositories import SessionRepository, QuestionRepository

logger = structlog.get_logger()


class SessionService:
    """Business logic for sessions."""

    def __init__(
        self,
        session_repo: SessionRepository,
        question_repo: QuestionRepository | None = None,
    ):
        self.session_repo = session_repo
        # Optional so existing call sites that don't need expert checks still work.
        self.question_repo = question_repo

    def _user_is_session_expert(
        self,
        session_id: UUID,
        user_roles: list[str],
    ) -> bool:
        """True if the user holds a role that this session has asked an expert
        question for. Used to grant read-only access to non-owner experts.
        """
        if not user_roles or self.question_repo is None:
            return False
        expert_session_ids = self.question_repo.list_session_ids_with_expert_role(user_roles)
        return session_id in expert_session_ids

    def get_detail(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> SessionDetail:
        """Get session detail with access check.

        Access rules:
          - Owner: full access
          - Admin: full access
          - Expert (a user holding a role this session has asked an expert
            question for): read-only access (the route does not let them
            answer owner-only HITL questions or control the session).
        """
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))

        is_owner = session.user_id == user_id
        is_admin = "admin" in user_roles
        is_expert = (
            not is_owner
            and not is_admin
            and self._user_is_session_expert(session_id, user_roles)
        )

        if not (is_owner or is_admin or is_expert):
            raise AuthorizationError("Cannot access this session")

        detail = self.session_repo.get_with_chat(session_id)
        if not detail:
            raise NotFoundError("session", str(session_id))

        return detail

    def list_for_user(
        self,
        user_id: UUID | None,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
        user_roles: list[str] | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user.

        If user_id is None, returns all sessions (admin view).
        Otherwise returns sessions owned by the user PLUS sessions where the
        user is involved as an expert (any expert question routed to one of
        their roles). The frontend uses the `username` field to flag
        expert-involved sessions in the sidebar.
        """
        offset = (page - 1) * limit
        extra_session_ids = None
        if user_id is not None and user_roles and self.question_repo is not None:
            extra_session_ids = self.question_repo.list_session_ids_with_expert_role(user_roles)
        return self.session_repo.list_for_user(
            user_id,
            limit,
            offset,
            status,
            extra_session_ids=extra_session_ids,
        )

    def delete(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Delete session (owner or admin only)."""
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))

        is_owner = session.user_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        self.session_repo.delete(session_id)
        self.session_repo.commit()
        logger.info("session_deleted", session_id=str(session_id), by_user=str(user_id))

    def require_owner_or_admin(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Ensure the user is the session owner or an admin.

        Used to gate session-control operations (retry, resume, delete)
        from non-owner experts who only have read access to the session.
        """
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))

        is_owner = session.user_id == user_id
        is_admin = "admin" in user_roles
        if not is_owner and not is_admin:
            raise AuthorizationError(
                "Only the session owner or an admin can control this session",
            )

    def lock_for_retry(self, session_id: UUID) -> None:
        """Atomically lock and transition session to ACTIVE for retry.

        Uses SELECT ... FOR UPDATE to prevent race conditions where two
        concurrent retry requests both read status=completed and both
        spawn background tasks.

        Raises:
            NotFoundError: Session not found
            ValueError: Session is already active (cannot retry)
        """
        session = self.session_repo.get_by_id_for_update(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        if session.status == SessionStatus.ACTIVE.value:
            raise ValueError("Cannot retry while session is active")

        session.status = SessionStatus.ACTIVE.value
        self.session_repo.commit()  # Lock released here

    def mark_failed(self, session_id: UUID, error_message: str) -> None:
        """Mark a session as FAILED. Used to revert status when task spawning fails."""
        self.session_repo.update_status(session_id, SessionStatus.FAILED, error_message)
        self.session_repo.commit()

    def lock_for_resume(self, session_id: UUID) -> None:
        """Atomically lock and transition session to ACTIVE for resume.

        Uses SELECT ... FOR UPDATE to prevent race conditions where two
        concurrent resume requests both read status=paused and both
        spawn background tasks.

        Allows both paused and failed sessions (failed sessions may have
        orphaned running agent runs after infrastructure crashes).

        Raises:
            NotFoundError: Session not found
            ValueError: Session is not paused or failed (cannot resume)
        """
        session = self.session_repo.get_by_id_for_update(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        resumable = {
            SessionStatus.PAUSED.value,
            SessionStatus.PAUSED_CRASHED.value,
            SessionStatus.FAILED.value,
        }
        if session.status not in resumable:
            raise ValueError(f"Cannot resume session with status '{session.status}'")

        session.status = SessionStatus.ACTIVE.value
        self.session_repo.commit()  # Lock released here
