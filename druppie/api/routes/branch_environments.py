"""Branch environments API routes.

Manages the lifecycle of per-branch Druppie environments: a developer clicks
"Deploy" on a git branch and the backend commits the environment's manifests
to the GitOps repo (ai/k8s); FluxCD stands up the isolated Druppie stack in
its own namespace. Teardown removes the manifests and Flux prunes. Status is
read live from the cluster's HelmRelease conditions.

Architecture:
    Route (this file)
      │
      └──▶ BranchEnvironmentService ──▶ Gitea API (GitOps repo, source of truth)
                                      └──▶ Kubernetes API (read-only status)

CI image upgrades need no webhook here: the build pipeline updates the
imageTag in the env's committed HelmRelease directly.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends

from druppie.api.deps import (
    get_branch_environment_service,
    get_current_user,
    get_user_roles,
    require_any_role,
)
from druppie.domain import (
    BranchEnvironmentCreate,
    BranchEnvironmentDetail,
    BranchEnvironmentListResponse,
    BranchEnvironmentPipeline,
)
from druppie.services import BranchEnvironmentService

logger = structlog.get_logger()

router = APIRouter()


@router.get("/branch-environments", response_model=BranchEnvironmentListResponse)
async def list_branch_environments(
    page: int = 1,
    limit: int = 100,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentListResponse:
    """List all branch environments."""
    items, total = await service.list_all(page=page, limit=limit)
    return BranchEnvironmentListResponse(items=items, total=total)


@router.post("/branch-environments", response_model=BranchEnvironmentDetail, status_code=202)
async def create_branch_environment(
    body: BranchEnvironmentCreate,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Deploy a full isolated Druppie stack for a git branch.

    Commits the environment manifests to the GitOps repo and returns
    immediately (status=deploying); FluxCD performs the actual deploy.
    """
    user_id = UUID(user["sub"])
    user_roles = get_user_roles(user)
    return await service.create(
        owner_id=user_id,
        branch=body.branch,
        image_tag=body.image_tag,
        user_roles=user_roles,
        secrets_source=body.secrets_source,
        # The deployer's own identity — "developer" secrets always resolve to
        # THEIR Vault map; there is deliberately no way to pick someone else's.
        owner_username=user.get("preferred_username"),
    )


@router.get("/branch-environments/{env_id}", response_model=BranchEnvironmentDetail)
async def get_branch_environment(
    env_id: str,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Get a single branch environment detail (id = slug)."""
    return await service.get(env_id)


@router.get(
    "/branch-environments/{env_id}/pipeline", response_model=BranchEnvironmentPipeline
)
async def get_branch_environment_pipeline(
    env_id: str,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentPipeline:
    """Live deploy pipeline for one environment (id = slug).

    One stage per hop in the GitOps chain — commit (aigit) → Flux sync → chart
    source / secrets → helm install → pods & images — so the UI can show where
    a deploy is busy and where it went wrong.
    """
    return await service.pipeline(env_id)


@router.post(
    "/branch-environments/{env_id}/redeploy",
    response_model=BranchEnvironmentDetail,
    status_code=202,
)
async def redeploy_branch_environment(
    env_id: str,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Commit a forced-reconcile (and optional new tag). Owner or admin only."""
    return await service.redeploy(
        env_id=env_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )


@router.post(
    "/branch-environments/{env_id}/workspace",
    response_model=BranchEnvironmentDetail,
    status_code=202,
)
async def enable_branch_environment_workspace(
    env_id: str,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Enable the dev workspace for a branch environment. Owner or admin only.

    Commits ``workspace.yaml`` to the env's GitOps directory; Flux stands up a
    code-server pod (branch checked out, hot reload) fronted by a Keycloak
    oauth2-proxy sidecar.
    """
    return await service.enable_workspace(
        env_id=env_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )


@router.delete(
    "/branch-environments/{env_id}/workspace",
    response_model=BranchEnvironmentDetail,
    status_code=202,
)
async def disable_branch_environment_workspace(
    env_id: str,
    service: BranchEnvironmentService = Depends(get_branch_environment_service),
    user: dict = Depends(get_current_user),
    _: bool = Depends(require_any_role(["developer", "admin"])),
) -> BranchEnvironmentDetail:
    """Disable the dev workspace for a branch environment. Owner or admin only."""
    return await service.disable_workspace(
        env_id=env_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )


@router.delete(
    "/branch-environments/{env_id}", response_model=BranchEnvironmentDetail, status_code=202
)
async def delete_branch_environment(
    env_id: str,
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
