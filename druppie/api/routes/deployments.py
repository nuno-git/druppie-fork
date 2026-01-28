"""Deployments API routes.

Bridge to Docker MCP - lets frontend manage containers that agents have deployed.

Architecture:
    Route (this file)
      │
      ├──▶ Database (SQLAlchemy)
      │         (deployment/build records)
      │
      └──▶ Docker MCP (via BuilderService)
              (stop, run, logs)

How it works:
    Frontend → POST /deployments/{id}/stop → Backend → docker MCP: stop → Container stopped
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
import structlog

from druppie.api.deps import get_current_user, get_db, check_resource_ownership, get_user_roles
from druppie.api.errors import NotFoundError, ExternalServiceError
from druppie.db.models import Build, Project
from druppie.core.builder import get_builder_service
from druppie.domain import DeploymentSummary

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# RESPONSE MODELS (action responses only - list uses domain model)
# =============================================================================


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
# ROUTES
# =============================================================================


@router.get("/deployments", response_model=DeploymentListResponse)
async def list_deployments(
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DeploymentListResponse:
    """List running deployments.

    Returns all running containers from builds. Admin users see all,
    others only see their own projects' deployments.

    Returns:
        List of running deployments with container info
    """
    user_id = user.get("sub")
    user_roles = get_user_roles(user)
    is_admin = "admin" in user_roles

    # Query running builds with project info
    query = (
        db.query(Build, Project)
        .join(Project, Build.project_id == Project.id)
        .filter(Build.status == "running")
    )

    # Non-admin users only see their own
    if not is_admin:
        query = query.filter(Project.owner_id == user_id)

    results = query.all()

    items = [
        DeploymentSummary(
            id=build.id,
            project_id=project.id,
            project_name=project.name,
            container_name=build.container_name,
            host_port=build.port,
            app_url=build.app_url,
            status=build.status,
            started_at=build.created_at,
        )
        for build, project in results
    ]

    return DeploymentListResponse(items=items)


@router.post("/deployments/{deployment_id}/stop", response_model=StopResponse)
async def stop_deployment(
    deployment_id: UUID,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> StopResponse:
    """Stop a running deployment.

    Calls docker:stop via the MCP to stop the container.

    Args:
        deployment_id: Build/deployment UUID

    Returns:
        Success status

    Raises:
        NotFoundError: Deployment doesn't exist
        AuthorizationError: User doesn't own the project
        ExternalServiceError: Docker operation failed
    """
    build = db.query(Build).filter(Build.id == deployment_id).first()

    if not build:
        raise NotFoundError("deployment", str(deployment_id))

    # Check ownership via project
    project = db.query(Project).filter(Project.id == build.project_id).first()
    if project:
        check_resource_ownership(user, project.owner_id)

    try:
        builder = get_builder_service(db)
        success = await builder.stop_project(build.id)

        logger.info("deployment_stopped", deployment_id=str(deployment_id))

        return StopResponse(
            success=success,
            status="stopped" if success else "failed",
        )

    except Exception as e:
        logger.error("stop_failed", deployment_id=str(deployment_id), error=str(e))
        raise ExternalServiceError("docker", f"Stop failed: {str(e)}", str(e))


@router.post("/deployments/{deployment_id}/restart", response_model=RestartResponse)
async def restart_deployment(
    deployment_id: UUID,
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> RestartResponse:
    """Restart a deployment.

    Calls docker:stop then docker:run via the MCP.

    Args:
        deployment_id: Build/deployment UUID

    Returns:
        Success status and new app URL

    Raises:
        NotFoundError: Deployment doesn't exist
        AuthorizationError: User doesn't own the project
        ExternalServiceError: Docker operation failed
    """
    build = db.query(Build).filter(Build.id == deployment_id).first()

    if not build:
        raise NotFoundError("deployment", str(deployment_id))

    # Check ownership via project
    project = db.query(Project).filter(Project.id == build.project_id).first()
    if project:
        check_resource_ownership(user, project.owner_id)

    try:
        builder = get_builder_service(db)

        # Stop then run
        await builder.stop_project(build.id)
        updated_build = await builder.run_project(build.id)

        logger.info("deployment_restarted", deployment_id=str(deployment_id))

        return RestartResponse(
            success=True,
            status="running",
            app_url=updated_build.app_url,
        )

    except Exception as e:
        logger.error("restart_failed", deployment_id=str(deployment_id), error=str(e))
        raise ExternalServiceError("docker", f"Restart failed: {str(e)}", str(e))


@router.get("/deployments/{deployment_id}/logs", response_model=LogsResponse)
async def get_deployment_logs(
    deployment_id: UUID,
    tail: int = Query(100, ge=1, le=1000, description="Number of lines"),
    user: dict = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> LogsResponse:
    """Get container logs.

    Calls docker:logs via the MCP.

    Args:
        deployment_id: Build/deployment UUID
        tail: Number of log lines to return (1-1000)

    Returns:
        Container logs

    Raises:
        NotFoundError: Deployment doesn't exist
        AuthorizationError: User doesn't own the project
        ExternalServiceError: Docker operation failed
    """
    build = db.query(Build).filter(Build.id == deployment_id).first()

    if not build:
        raise NotFoundError("deployment", str(deployment_id))

    # Check ownership via project
    project = db.query(Project).filter(Project.id == build.project_id).first()
    if project:
        check_resource_ownership(user, project.owner_id)

    if not build.container_name:
        raise NotFoundError("container", str(deployment_id), "No container for this deployment")

    try:
        builder = get_builder_service(db)
        logs = await builder.get_logs(build.container_name, tail=tail)

        return LogsResponse(
            container_name=build.container_name,
            logs=logs,
        )

    except Exception as e:
        logger.error("logs_failed", deployment_id=str(deployment_id), error=str(e))
        raise ExternalServiceError("docker", f"Failed to get logs: {str(e)}", str(e))
