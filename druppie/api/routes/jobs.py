"""Jobs API routes for scheduled cron jobs."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
import structlog

from druppie.api.deps import get_job_service, require_admin, get_current_user, get_user_roles
from druppie.api.errors import NotFoundError
from druppie.services import JobService
from druppie.domain import JobDefinitionList, JobRunList, JobRunDetail
from druppie.domain.common import JobRunStatus

logger = structlog.get_logger()

router = APIRouter()


class RejectJobRequest(BaseModel):
    """Request body for rejecting a job run."""
    reason: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Reason for rejection (1-10000 characters)",
    )


@router.get("")
async def list_jobs(
    service: JobService = Depends(get_job_service),
    user: dict = Depends(require_admin),
) -> JobDefinitionList:
    return service.list_definitions()


@router.post("/{job_definition_id}/trigger")
async def trigger_job(
    job_definition_id: UUID,
    service: JobService = Depends(get_job_service),
    user: dict = Depends(require_admin),
) -> JobRunDetail:
    user_id = UUID(user["sub"])

    definition = service.get_definition(job_definition_id)
    if not definition:
        raise NotFoundError("job_definition", str(job_definition_id))

    run = service.trigger_job(job_definition_id, user_id=user_id)
    if run.session_id and run.status != JobRunStatus.WAITING_APPROVAL:
        service.execute_job_in_background(run.id, run.session_id)
    return run


@router.get("/runs")
async def list_all_job_runs(
    status: JobRunStatus | None = None,
    page: int = 1,
    limit: int = 20,
    service: JobService = Depends(get_job_service),
    user: dict = Depends(require_admin),
) -> JobRunList:
    return service.list_job_runs(status=status, page=page, limit=limit)


@router.get("/pending-approvals")
async def list_pending_job_approvals(
    service: JobService = Depends(get_job_service),
    user: dict = Depends(get_current_user),
) -> JobRunList:
    user_roles = get_user_roles(user)
    runs = service.get_pending_approval_runs(user_roles)
    return JobRunList(items=runs, total=len(runs), page=1, limit=len(runs) or 20)


@router.post("/{job_run_id}/approve")
async def approve_job_run(
    job_run_id: UUID,
    service: JobService = Depends(get_job_service),
    user: dict = Depends(get_current_user),
) -> JobRunDetail:
    from uuid import UUID as UuidType
    user_id = UuidType(user["sub"])
    user_roles = get_user_roles(user)
    return service.approve_job_run(job_run_id, user_id, user_roles)


@router.post("/{job_run_id}/reject")
async def reject_job_run(
    job_run_id: UUID,
    request: RejectJobRequest,
    service: JobService = Depends(get_job_service),
    user: dict = Depends(get_current_user),
) -> JobRunDetail:
    from uuid import UUID as UuidType
    user_id = UuidType(user["sub"])
    user_roles = get_user_roles(user)
    return service.reject_job_run(job_run_id, user_id, user_roles, request.reason)


@router.get("/{job_definition_id}/runs")
async def list_job_runs(
    job_definition_id: UUID,
    page: int = 1,
    limit: int = 20,
    service: JobService = Depends(get_job_service),
    user: dict = Depends(require_admin),
) -> JobRunList:
    definition = service.get_definition(job_definition_id)
    if not definition:
        raise NotFoundError("job_definition", str(job_definition_id))

    return service.list_job_runs(
        job_definition_id=job_definition_id,
        page=page,
        limit=limit,
    )
