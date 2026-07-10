"""Escalation service for the FD-escalation HITL state machine.

This service is the authorization + audit gate for human HITL decisions: every
human decision is authorized here and recorded as an EscalationEvent.

It does NOT execute or resume the session. The orchestrator performs the actual
session state transitions (a separate phase). The API layer calls this service
to authorize + record a decision, then calls the orchestrator to resume.

Architecture:
    Route
      |
      +-> EscalationService (this) --> EscalationRepository --> Database
      |         (authorize + audit)     SessionRepository
      |
      +-> Orchestrator --> session state transitions (separate phase)
"""

from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, NotFoundError
from ..db.models import Session
from ..domain import EscalationEventDetail, EscalationEventList
from ..domain.common import EscalationEventType
from ..repositories import EscalationRepository, SessionRepository

logger = structlog.get_logger()


class EscalationService:
    """Authorize human HITL decisions and record them as audit events.

    Responsibilities:
    - Authorize the acting user against the session for a given auth level.
    - Record the decision as an EscalationEvent (the audit trail).
    - List a session's escalation event history.

    It does NOT perform session state transitions or resume execution.
    """

    def __init__(
        self,
        escalation_repo: EscalationRepository,
        session_repo: SessionRepository,
    ):
        self.escalation_repo = escalation_repo
        self.session_repo = session_repo

    def record_ba_hitl_decision(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        decision: str,
        feedback: str | None = None,
    ) -> EscalationEventDetail:
        """Record a BA human-in-the-loop decision (auth level: ba_hitl).

        decision must be one of: iterate, ready, escalate, terminate.
        """
        session = self._get_session_or_404(session_id)
        self._check_authorization(session, user_id, user_roles, level="ba_hitl")

        event_type = self._ba_decision_event_type(decision)
        return self._record(
            session=session,
            actor_user_id=user_id,
            decision=decision,
            event_type=event_type,
            feedback=feedback,
        )

    def record_architect_hitl_decision(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        decision: str,
        next_on_reject: str | None = None,
    ) -> EscalationEventDetail:
        """Record an architect human-in-the-loop decision (auth level: architect_hitl).

        decision must be one of: approve, reject. When decision is "reject",
        next_on_reject must be "ba_hitl" or "terminate".
        """
        session = self._get_session_or_404(session_id)
        self._check_authorization(session, user_id, user_roles, level="architect_hitl")

        event_type = self._architect_decision_event_type(decision, next_on_reject)
        return self._record(
            session=session,
            actor_user_id=user_id,
            decision=decision,
            event_type=event_type,
        )

    def terminate(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        reason: str | None = None,
    ) -> EscalationEventDetail:
        """Terminate the session (auth level: terminate)."""
        session = self._get_session_or_404(session_id)
        self._check_authorization(session, user_id, user_roles, level="terminate")

        return self._record(
            session=session,
            actor_user_id=user_id,
            decision="terminate",
            event_type=EscalationEventType.SESSION_TERMINATED,
            feedback=reason,
        )

    def list_history(self, session_id: UUID) -> EscalationEventList:
        """Return a session's escalation events, oldest first."""
        return EscalationEventList(items=self.escalation_repo.get_for_session(session_id))

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _check_authorization(
        self,
        session: Session,
        user_id: UUID,
        user_roles: list[str],
        level: str,
    ) -> None:
        """Raise AuthorizationError unless the user may act at the given level.

        Admins are always authorized. Otherwise:
            ba_hitl:        business_analyst role OR session owner
            architect_hitl: architect role
            terminate:      session owner
        """
        if "admin" in user_roles:
            return

        match level:
            case "ba_hitl":
                if "business_analyst" in user_roles or session.user_id == user_id:
                    return
                raise AuthorizationError(
                    "Only the session owner or a business analyst can act on the BA HITL",
                )
            case "architect_hitl":
                if "architect" in user_roles:
                    return
                raise AuthorizationError(
                    "Requires architect role for the architect HITL",
                    required_roles=["architect"],
                )
            case "terminate":
                if session.user_id == user_id:
                    return
                raise AuthorizationError("Only the session owner can terminate this session")
            case _:
                raise AuthorizationError(f"Unknown authorization level: {level}")

    # ------------------------------------------------------------------
    # Decision -> event-type mapping (exhaustive; unknown inputs raise)
    # ------------------------------------------------------------------

    @staticmethod
    def _ba_decision_event_type(decision: str) -> EscalationEventType:
        match decision:
            case "iterate":
                return EscalationEventType.BA_HITL_ITERATE
            case "ready":
                return EscalationEventType.BA_HITL_READY
            case "escalate":
                return EscalationEventType.BA_HITL_ESCALATE
            case "terminate":
                return EscalationEventType.SESSION_TERMINATED
            case _:
                raise ValueError(f"Invalid BA HITL decision: {decision!r}")

    @staticmethod
    def _architect_decision_event_type(
        decision: str,
        next_on_reject: str | None,
    ) -> EscalationEventType:
        match decision:
            case "approve":
                return EscalationEventType.ARCHITECT_HITL_APPROVE
            case "reject":
                match next_on_reject:
                    case "ba_hitl":
                        return EscalationEventType.ARCHITECT_HITL_REJECT_TO_BA
                    case "terminate":
                        return EscalationEventType.ARCHITECT_HITL_REJECT_TERMINATE
                    case _:
                        raise ValueError(
                            "next_on_reject must be 'ba_hitl' or 'terminate' "
                            f"when decision is 'reject' (got {next_on_reject!r})",
                        )
            case _:
                raise ValueError(f"Invalid architect HITL decision: {decision!r}")

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def _get_session_or_404(self, session_id: UUID) -> Session:
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", str(session_id))
        return session

    def _record(
        self,
        session: Session,
        actor_user_id: UUID,
        decision: str,
        event_type: EscalationEventType,
        feedback: str | None = None,
    ) -> EscalationEventDetail:
        """Persist an EscalationEvent and commit. Shared by all record methods."""
        event = self.escalation_repo.create(
            session_id=session.id,
            event_type=event_type.value,
            actor_user_id=actor_user_id,
            decision=decision,
            feedback=feedback,
            rejection_count_at_event=session.fd_rejection_count or 0,
        )
        self.escalation_repo.commit()
        logger.info(
            "escalation_event_recorded",
            session_id=str(session.id),
            event_type=event_type.value,
            by_user=str(actor_user_id),
            decision=decision,
        )
        return event
