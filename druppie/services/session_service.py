"""Session service for business logic."""

from uuid import UUID
import structlog

from ..repositories import SessionRepository
from ..domain import SessionDetail, SessionSummary
from ..api.errors import NotFoundError, AuthorizationError

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
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user."""
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
