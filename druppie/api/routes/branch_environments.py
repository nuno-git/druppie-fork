"""Branch environments API routes.

Manages the lifecycle of per-branch Druppie environments: a developer clicks
"Deploy" on a git branch and the backend stands up a full isolated Druppie
stack in its own namespace, tracks its status, supports teardown, and accepts a
CI webhook that upgrades the environment when new branch images are pushed.

Architecture:
    Route (this file)
      │
      └──▶ BranchEnvironmentService ──▶ BranchEnvironmentRepository ──▶ Database
                                       └──▶ kubectl / helm (subprocess)
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from druppie.api.deps import (
    get_branch_environment_service,
    get_current_user,
    get_user_roles,
    require_any_role,
    verify_internal_api_key,
)
from druppie.domain import (
    BranchEnvironmentCreate,
    BranchEnvironmentDetail,
    BranchEnvironmentListResponse,
)
from druppie.services import BranchEnvironmentService

logger = structlog.get_logger()

router = APIRouter()


class CIWebhookRequest(BaseModel):
    """CI image-push webhook body (internal-key authenticated)."""

    branch: str
    image_tag: str


class CIWebhookResponse(BaseModel):
    """CI webhook result."""

    environment_updated: bool


@router.get("/branch-environments", response_model=BranchEnvironmentListResponse)
async def list_branch_environments(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentListResponse:
    """List all branch environments."""
    items, total = service.list_all(page=page, limit=limit)
    return BranchEnvironmentListResponse(items=items, total=total)


@router.post("/branch-environments", response_model=BranchEnvironmentDetail, status_code=202)
async def create_branch_environment(
    body: BranchEnvironmentCreate,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Deploy a full isolated Druppie stack for a git branch.

    Creates the DB record (status=deploying) and returns immediately; the helm
    install runs as a background task.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return await service.create(
        owner_id=user_id,
        branch=body.branch,
        image_tag=body.image_tag,
        user_roles=user_roles,
    )


@router.get("/branch-environments/{env_id}", response_model=BranchEnvironmentDetail)
async def get_branch_environment(
    env_id: UUID,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Get a single branch environment detail."""
    return service.get(env_id)


@router.post(
    "/branch-environments/{env_id}/redeploy",
    response_model=BranchEnvironmentDetail,
    status_code=202,
)
async def redeploy_branch_environment(
    env_id: UUID,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Re-run the helm upgrade for an existing environment. Owner or admin only."""
    return await service.redeploy(
        env_id=env_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )


@router.delete("/branch-environments/{env_id}", response_model=BranchEnvironmentDetail, status_code=202)
async def delete_branch_environment(
    env_id: UUID,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Tear down a branch environment. Owner or admin only."""
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return await service.teardown(
        env_id=env_id,
        user_id=user_id,
        user_roles=user_roles,
    )


@router.post("/branch-environments/ci-webhook", response_model=CIWebhookResponse)
async def ci_webhook(
    body: CIWebhookRequest,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    _auth: bool = Depends(verify_internal_api_key),
) -> CIWebhookResponse:
    """Upgrade an existing environment when CI pushes a new branch image.

    Authenticated only by the internal API key (server-to-server); no user auth.
    """
    updated = await service.handle_ci_image_push(branch=body.branch, image_tag=body.image_tag)
    return CIWebhookResponse(environment_updated=updated)
