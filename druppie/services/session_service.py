"""Session service for business logic."""

from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..domain import SessionDetail, SessionSummary
from ..domain.common import SessionStatus
from ..repositories import SessionRepository

logger = structlog.get_logger()


class SessionService:
    """Business logic for sessions."""

    def __init__(self, session_repo: SessionRepository):
        self.session_repo = session_repo

    def get_detail(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> SessionDetail:
        """Get session detail with access check."""
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))

        # Only owner or admin can access
        is_owner = session.user_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
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
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user.

        If user_id is None, returns all sessions (admin view).
        """
        offset = (page - 1) * limit
        return self.session_repo.list_for_user(user_id, limit, offset, status)

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
