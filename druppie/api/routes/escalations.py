"""Escalation API routes for the FD-escalation HITL state machine.

Human-facing surface for BA HITL and architect HITL decisions. Each call is
authorized + audited by EscalationService, then executed by the Orchestrator.

Architecture:
    POST /api/sessions/{id}/ba-hitl
      |
      +-> EscalationService.record_ba_hitl_decision()  (auth + audit)
      +-> Orchestrator.resume_after_ba_hitl()           (execute, background)

    POST /api/sessions/{id}/architect-hitl
      |
      +-> EscalationService.record_architect_hitl_decision()  (auth + audit)
      +-> Orchestrator.resume_after_architect_hitl()           (execute, background)

    POST /api/sessions/{id}/terminate
      |
      +-> EscalationService.terminate()           (auth + audit)
      +-> Orchestrator.terminate_session()        (execute)

    GET /api/sessions/{id}/escalation-history
      |
      +-> EscalationService.list_history()

The endpoint returns immediately. The client polls
GET /api/sessions/{id} to track progress.
"""

from __future__ import annotations

from typing import Literal, TYPE_CHECKING
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from druppie.api.deps import (
    get_current_user,
    get_escalation_service,
    get_orchestrator,
    get_user_roles,
)
from druppie.core.background_tasks import create_session_task, SessionTaskConflict, run_session_task
from druppie.domain import EscalationEventDetail, EscalationEventList
from druppie.services import EscalationService

if TYPE_CHECKING:
    from druppie.execution import Orchestrator

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class BaHitlRequest(BaseModel):
    """Request body for a BA HITL decision."""

    decision: Literal["iterate", "ready", "escalate", "terminate"]
    feedback: str | None = Field(default=None)


class ArchitectHitlRequest(BaseModel):
    """Request body for an architect HITL decision."""

    decision: Literal["approve", "reject"]
    next_on_reject: Literal["ba_hitl", "terminate"] | None = Field(default=None)

    @model_validator(mode="after")
    def _reject_requires_target(self) -> "ArchitectHitlRequest":
        if self.decision == "reject" and self.next_on_reject is None:
            raise ValueError("next_on_reject is required when decision is 'reject'")
        return self


class TerminateRequest(BaseModel):
    """Request body for session termination."""

    reason: str | None = Field(default=None)


class EscalationDecisionResponse(BaseModel):
    """Response after a HITL decision."""

    event: EscalationEventDetail
    message: str = "Processing started"


# =============================================================================
# BACKGROUND TASKS
# =============================================================================


async def _resume_ba_hitl(
    session_id: UUID,
    decision: str,
    feedback: str | None,
    user_id: UUID,
) -> None:
    """Resume BA HITL workflow in background using run_session_task for DB lifecycle."""

    async def task(ctx):
        await ctx.orchestrator.resume_after_ba_hitl(
            session_id=session_id,
            decision=decision,
            feedback=feedback,
            user_id=user_id,
        )

    await run_session_task(session_id, task, "resume_ba_hitl")


async def _resume_architect_hitl(
    session_id: UUID,
    decision: str,
    next_on_reject: str | None,
    user_id: UUID,
) -> None:
    """Resume architect HITL workflow in background using run_session_task for DB lifecycle."""

    async def task(ctx):
        await ctx.orchestrator.resume_after_architect_hitl(
            session_id=session_id,
            decision=decision,
            next_on_reject=next_on_reject,
            user_id=user_id,
        )

    await run_session_task(session_id, task, "resume_architect_hitl")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/{session_id}/ba-hitl", response_model=EscalationDecisionResponse)
async def ba_hitl(
    session_id: UUID,
    request: BaHitlRequest,
    escalation_service: EscalationService = Depends(get_escalation_service),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    user: dict = Depends(get_current_user),
) -> EscalationDecisionResponse:
    """Submit a BA human-in-the-loop decision.

    Record the decision (auth + audit), then resume the session via the
    orchestrator in a background task. Returns immediately.

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User lacks required role
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    logger.info(
        "ba_hitl_decision",
        session_id=str(session_id),
        decision=request.decision,
        user_id=str(user_id),
    )

    # Step 1: Authorize + record audit event
    if request.decision == "terminate":
        event = escalation_service.terminate(
            session_id=session_id,
            user_id=user_id,
            user_roles=user_roles,
            reason=request.feedback,
        )
    else:
        event = escalation_service.record_ba_hitl_decision(
            session_id=session_id,
            user_id=user_id,
            user_roles=user_roles,
            decision=request.decision,
            feedback=request.feedback,
        )

    # Step 2: Execute via orchestrator
    if request.decision == "terminate":
        try:
            orchestrator.terminate_session(session_id, reason=request.feedback, user_id=user_id)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to terminate session")
        message = "Session terminated"
    else:
        try:
            create_session_task(
                session_id,
                _resume_ba_hitl(
                    session_id=session_id,
                    decision=request.decision,
                    feedback=request.feedback,
                    user_id=user_id,
                ),
                name=f"resume-ba-hitl-{session_id}",
            )
        except SessionTaskConflict:
            raise HTTPException(
                status_code=409,
                detail="A task is already running for this session",
            )
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to start background task")
        message = f"{request.decision} - workflow resuming"

    logger.info("ba_hitl_recorded", session_id=str(session_id), decision=request.decision)

    return EscalationDecisionResponse(event=event, message=message)


@router.post("/{session_id}/architect-hitl", response_model=EscalationDecisionResponse)
async def architect_hitl(
    session_id: UUID,
    request: ArchitectHitlRequest,
    escalation_service: EscalationService = Depends(get_escalation_service),
    user: dict = Depends(get_current_user),
) -> EscalationDecisionResponse:
    """Submit an architect human-in-the-loop decision.

    Record the decision (auth + audit), then resume the session via the
    orchestrator in a background task. Returns immediately.

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User lacks required role
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    logger.info(
        "architect_hitl_decision",
        session_id=str(session_id),
        decision=request.decision,
        user_id=str(user_id),
    )

    # Step 1: Authorize + record audit event
    event = escalation_service.record_architect_hitl_decision(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
        decision=request.decision,
        next_on_reject=request.next_on_reject,
    )

    # Step 2: Spawn background task to resume
    try:
        create_session_task(
            session_id,
            _resume_architect_hitl(
                session_id=session_id,
                decision=request.decision,
                next_on_reject=request.next_on_reject,
                user_id=user_id,
            ),
            name=f"resume-architect-hitl-{session_id}",
        )
    except SessionTaskConflict:
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this session",
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to start background task")

    logger.info("architect_hitl_recorded", session_id=str(session_id), decision=request.decision)

    return EscalationDecisionResponse(
        event=event,
        message=f"{request.decision} - workflow resuming",
    )


@router.post("/{session_id}/terminate", response_model=EscalationDecisionResponse)
async def terminate(
    session_id: UUID,
    request: TerminateRequest,
    escalation_service: EscalationService = Depends(get_escalation_service),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    user: dict = Depends(get_current_user),
) -> EscalationDecisionResponse:
    """Terminate a session.

    Record the termination (auth + audit), then terminate via the orchestrator.

    Raises:
        NotFoundError: Session not found
        AuthorizationError: User lacks required role
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)

    logger.info("terminate_session", session_id=str(session_id), user_id=str(user_id))

    # Step 1: Authorize + record audit event
    event = escalation_service.terminate(
        session_id=session_id,
        user_id=user_id,
        user_roles=user_roles,
        reason=request.reason,
    )

    # Step 2: Execute termination
    try:
        orchestrator.terminate_session(session_id, reason=request.reason, user_id=user_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to terminate session")

    return EscalationDecisionResponse(event=event, message="Session terminated")


@router.get("/{session_id}/escalation-history", response_model=EscalationEventList)
async def escalation_history(
    session_id: UUID,
    escalation_service: EscalationService = Depends(get_escalation_service),
    user: dict = Depends(get_current_user),
) -> EscalationEventList:
    """Return a session's escalation event history.

    Raises:
        NotFoundError: Session not found
    """
    user_id = UUID(user["sub"])
    _ = get_user_roles(user)

    logger.info("escalation_history", session_id=str(session_id), user_id=str(user_id))

    return escalation_service.list_history(session_id)
