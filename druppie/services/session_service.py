"""Session service for business logic."""

from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..db.models import MessageAttachment, Session as SessionModel
from ..domain import SessionDetail, SessionSummary
from ..repositories.session_repository import DetailOptions
from ..domain.common import SessionStatus
from ..repositories import SessionRepository, QuestionRepository
from ..services import attachment_service

logger = structlog.get_logger()


class SessionService:
    """Business logic for sessions."""

    def __init__(
        self,
        session_repo: SessionRepository,
        question_repo: QuestionRepository | None = None,
    ):
        self.session_repo = session_repo
        self.question_repo = question_repo

    def _user_is_session_expert(
        self,
        session_id: UUID,
        user_roles: list[str],
    ) -> bool:
        if not user_roles or self.question_repo is None:
            return False
        expert_session_ids = self.question_repo.list_session_ids_with_expert_role(user_roles)
        return session_id in expert_session_ids

    def check_access(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> bool:
        """Check whether a user is allowed to access a session.

        Access rules:
          - Owner: full access
          - Admin: full access
          - Expert (a user holding a role this session has asked an expert
            question for): read-only access
        """
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))

        is_owner = session.user_id is not None and session.user_id == user_id
        is_admin = "admin" in user_roles
        is_expert = (
            not is_owner
            and not is_admin
            and self._user_is_session_expert(session_id, user_roles)
        )

        return is_owner or is_admin or is_expert

    def get_detail(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        since_sequence: int | None = None,
        exclude: set[str] | None = None,
    ) -> SessionDetail:
        """Get session detail with access check.

        Access rules:
          - Owner: full access
          - Admin: full access
          - Expert (a user holding a role this session has asked an expert
            question for): read-only access
        """
        if not self.check_access(session_id, user_id, user_roles):
            raise AuthorizationError("Cannot access this session")

        options = DetailOptions(since_sequence=since_sequence, exclude=exclude or set())
        detail = self.session_repo.get_with_chat(session_id, options=options)
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
        user is involved as an expert.
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

        is_owner = session.user_id is not None and session.user_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        attachments = (
            self.session_repo.db.query(MessageAttachment)
            .filter(MessageAttachment.session_id == session_id)
            .all()
        )
        for att in attachments:
            attachment_service.delete_file(att.storage_path)

        self.session_repo.delete(session_id)
        self.session_repo.commit()
        logger.info("session_deleted", session_id=str(session_id), by_user=str(user_id))

    def delete_many(
        self,
        session_ids: list[UUID],
        user_id: UUID,
        user_roles: list[str],
    ) -> int:
        """Delete specific sessions by IDs (owner or admin only)."""
        is_admin = "admin" in user_roles

        if not is_admin:
            sessions = (
                self.session_repo.db.query(SessionModel)
                .filter(SessionModel.id.in_(session_ids), SessionModel.user_id == user_id)
                .all()
            )
            allowed_ids = [s.id for s in sessions]
        else:
            allowed_ids = session_ids

        if not allowed_ids:
            return 0

        attachments = (
            self.session_repo.db.query(MessageAttachment)
            .filter(MessageAttachment.session_id.in_(allowed_ids))
            .all()
        )
        for att in attachments:
            attachment_service.delete_file(att.storage_path)

        count = self.session_repo.delete_many(allowed_ids)
        self.session_repo.commit()
        logger.info("sessions_batch_deleted", count=count, by_user=str(user_id))
        return count

    def delete_all_for_user(self, user_id: UUID | None) -> int:
        """Delete all sessions for a user (None = all sessions), including attachment files."""
        sessions, _ = self.session_repo.list_for_user(user_id, limit=10000, offset=0)
        if not sessions:
            return 0

        session_ids = [s.id for s in sessions]

        attachments = (
            self.session_repo.db.query(MessageAttachment)
            .filter(MessageAttachment.session_id.in_(session_ids))
            .all()
        )
        for att in attachments:
            attachment_service.delete_file(att.storage_path)

        self.session_repo.delete_all_for_user(user_id)
        self.session_repo.commit()
        logger.info("all_sessions_deleted", user_id=str(user_id), count=len(session_ids))
        return len(session_ids)

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

        Allows paused, paused_hitl, paused_crashed, and failed sessions
        (failed sessions may have orphaned running agent runs after
        infrastructure crashes; paused_hitl sessions can be resumed when
        no HITL question is pending).

        Raises:
            NotFoundError: Session not found
            ValueError: Session is not paused or failed (cannot resume)
        """
        session = self.session_repo.get_by_id_for_update(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        resumable = {
            SessionStatus.PAUSED.value,
            SessionStatus.PAUSED_HITL.value,
            SessionStatus.PAUSED_CRASHED.value,
            SessionStatus.PAUSED_APPROVAL.value,
            SessionStatus.PAUSED_ENTRA_AUTH.value,
            SessionStatus.PAUSED_SANDBOX.value,
            SessionStatus.FAILED.value,
        }
        if session.status not in resumable:
            raise ValueError(f"Cannot resume session with status '{session.status}'")

        session.status = SessionStatus.ACTIVE.value
        self.session_repo.commit()  # Lock released here

    def lock_for_continuation(self, session_id: UUID) -> None:
        session = self.session_repo.get_by_id_for_update(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        if session.status != SessionStatus.COMPLETED.value:
            raise ValueError(f"Cannot continue session with status '{session.status}'")
        session.status = SessionStatus.ACTIVE.value
        self.session_repo.commit()

    def lock_for_hitl_resume(self, session_id: UUID) -> str:
        """Atomically lock and transition session to ACTIVE for HITL resume.

        Returns the previous session status so callers can revert on failure.
        """
        session = self.session_repo.get_by_id_for_update(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        resumable = {
            SessionStatus.PAUSED_HITL.value,
            SessionStatus.PAUSED_APPROVAL.value,
            SessionStatus.PAUSED_SANDBOX.value,
        }
        if session.status not in resumable:
            raise ValueError(f"Cannot resume HITL for session with status '{session.status}'")
        previous_status = session.status
        session.status = SessionStatus.ACTIVE.value
        self.session_repo.commit()
        return previous_status

    def revert_to_hitl_paused(self, session_id: UUID, previous_status: str | None = None) -> None:
        """Revert session status after a failed HITL resume attempt.

        If previous_status is provided, restores to that exact status.
        Otherwise defaults to paused_hitl.
        """
        target = previous_status or SessionStatus.PAUSED_HITL.value
        try:
            target_enum = SessionStatus(target)
        except ValueError:
            target_enum = SessionStatus.PAUSED_HITL
        self.session_repo.update_status(session_id, target_enum)
        self.session_repo.commit()
