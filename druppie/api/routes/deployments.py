"""Deployments API routes.

Bridge to Docker MCP - lets frontend manage containers that agents have deployed.

TODO: This file needs to be rewritten to use Docker MCP directly instead of
the deleted Build database model. Deployments should be tracked via container
labels (druppie.project_id, druppie.session_id) not database records.

Architecture (target):
    Route (this file)
      │
      └──▶ Docker MCP (list_containers, stop, run, logs)
              (filter by druppie.* labels)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user, get_user_roles
from druppie.api.errors import NotFoundError

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class DeploymentSummary(BaseModel):
    """Deployment info from Docker MCP."""
    container_name: str
    project_id: UUID | None = None
    status: str
    app_url: str | None = None
    host_port: int | None = None


class DeploymentListResponse(BaseModel):
    """List of deployments response."""
    items: list[DeploymentSummary]


class StopResponse(BaseModel):
    """Response from stop operation."""
    success: bool
    status: str


class RestartResponse(BaseModel):
    """Response from restart operation."""
    success: bool
    status: str
    app_url: str | None = None


class LogsResponse(BaseModel):
    """Container logs response."""
    container_name: str
    logs: str


# =============================================================================
# ROUTES - TODO: Implement using Docker MCP
# =============================================================================


@router.get("/deployments", response_model=DeploymentListResponse)
async def list_deployments(
    user: dict = Depends(get_current_user),
) -> DeploymentListResponse:
    """List running deployments.

    TODO: Query Docker MCP list_containers with filter:
    - druppie.owner_id={user_id} (or all if admin)
    - status=running

    Returns:
        List of running deployments with container info
    """
    # TODO: Call Docker MCP to list containers with druppie.* labels
    logger.warning("deployments_api_not_implemented", action="list")
    return DeploymentListResponse(items=[])


@router.post("/deployments/{container_name}/stop", response_model=StopResponse)
async def stop_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> StopResponse:
    """Stop a running deployment.

    TODO: Verify ownership via container labels, then call Docker MCP stop.
    """
    logger.warning("deployments_api_not_implemented", action="stop", container=container_name)
    raise NotImplementedError("Deployment stop via Docker MCP not yet implemented")


@router.post("/deployments/{container_name}/restart", response_model=RestartResponse)
async def restart_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> RestartResponse:
    """Restart a deployment.

    TODO: Verify ownership via container labels, then call Docker MCP stop + run.
    """
    logger.warning("deployments_api_not_implemented", action="restart", container=container_name)
    raise NotImplementedError("Deployment restart via Docker MCP not yet implemented")


@router.get("/deployments/{container_name}/logs", response_model=LogsResponse)
async def get_deployment_logs(
    container_name: str,
    tail: int = Query(100, ge=1, le=1000, description="Number of lines"),
    user: dict = Depends(get_current_user),
) -> LogsResponse:
    """Get container logs.

    TODO: Verify ownership via container labels, then call Docker MCP logs.
    """
    logger.warning("deployments_api_not_implemented", action="logs", container=container_name)
    raise NotImplementedError("Deployment logs via Docker MCP not yet implemented")
