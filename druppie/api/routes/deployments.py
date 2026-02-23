"""Deployments API routes.

Bridge to Docker MCP - lets frontend manage containers that agents have deployed.

Architecture:
    Route (this file)
      │
      └──▶ MCP Bridge (Docker MCP list_containers, stop, logs)
            (filter by druppie.* labels)

Deployments are tracked via container labels:
- druppie.project_id: Project this container belongs to
- druppie.session_id: Session that created this container
- druppie.user_id: User who owns this container
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
import structlog

from druppie.api.deps import get_current_user
from druppie.api.errors import NotFoundError
from druppie.core.mcp_config import MCPConfig
from druppie.execution.mcp_http import MCPHttp, MCPHttpError

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

_mcp_config: MCPConfig | None = None
_mcp_http: MCPHttp | None = None


def get_mcp_config() -> MCPConfig:
    """Get or create MCP config singleton."""
    global _mcp_config
    if _mcp_config is None:
        _mcp_config = MCPConfig()
    return _mcp_config


def get_mcp_http() -> MCPHttp:
    """Get or create MCP HTTP client singleton."""
    global _mcp_http
    if _mcp_http is None:
        _mcp_http = MCPHttp(get_mcp_config())
    return _mcp_http


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class DeploymentSummary(BaseModel):
    """Deployment info from Docker MCP."""
    container_id: str
    container_name: str
    image: str
    status: str
    ports: str = ""
    project_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    app_url: str | None = None


class DeploymentListResponse(BaseModel):
    """List of deployments response."""
    items: list[DeploymentSummary]
    count: int


class StopResponse(BaseModel):
    """Response from stop operation."""
    success: bool
    container_name: str
    stopped: bool = False
    removed: bool = False


class LogsResponse(BaseModel):
    """Container logs response."""
    success: bool
    container_name: str
    logs: str


class InspectResponse(BaseModel):
    """Container inspect response."""
    success: bool
    container_name: str
    details: dict[str, Any]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def parse_container_to_deployment(container: dict) -> DeploymentSummary:
    """Parse Docker container info to DeploymentSummary."""
    labels = container.get("labels", {})

    # Extract port from ports string like "0.0.0.0:9100->3000/tcp"
    ports_str = container.get("ports", "")
    app_url = None
    if ports_str and "->" in ports_str:
        # Extract host port
        try:
            host_part = ports_str.split("->")[0]
            port = host_part.rsplit(":", 1)[1] if ":" in host_part else host_part
            app_url = f"http://localhost:{port}"
        except (IndexError, ValueError):
            pass

    return DeploymentSummary(
        container_id=container.get("id", ""),
        container_name=container.get("name", ""),
        image=container.get("image", ""),
        status=container.get("status", "unknown"),
        ports=ports_str,
        project_id=labels.get("druppie.project_id"),
        session_id=labels.get("druppie.session_id"),
        user_id=labels.get("druppie.user_id"),
        app_url=app_url,
    )


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/deployments", response_model=DeploymentListResponse)
async def list_deployments(
    project_id: str | None = Query(None, description="Filter by project ID"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    all_containers: bool = Query(False, description="Include stopped containers"),
    user: dict = Depends(get_current_user),
) -> DeploymentListResponse:
    """List running deployments via Docker MCP.

    Filters by druppie.* labels to show only Druppie-managed containers.
    Non-admin users only see their own deployments.
    """
    mcp_http = get_mcp_http()

    # Build filter args
    args: dict[str, Any] = {"all": all_containers}

    # Add label filters
    if project_id:
        args["project_id"] = project_id
    if session_id:
        args["session_id"] = session_id

    # Non-admin users can only see their own containers
    user_roles = user.get("roles", [])
    if "admin" not in user_roles:
        args["user_id"] = user.get("sub")

    try:
        result = await mcp_http.call(
            server="docker",
            tool="list_containers",
            args=args,
            timeout_seconds=30.0,
        )

        if not result.get("success", False):
            logger.warning(
                "deployments_list_failed",
                error=result.get("error"),
            )
            return DeploymentListResponse(items=[], count=0)

        containers = result.get("containers", [])

        # Filter to only druppie-managed containers (have at least one druppie.* label)
        druppie_containers = [
            c for c in containers
            if any(k.startswith("druppie.") for k in c.get("labels", {}).keys())
        ]

        items = [parse_container_to_deployment(c) for c in druppie_containers]

        return DeploymentListResponse(
            items=items,
            count=len(items),
        )

    except MCPHttpError as e:
        logger.error("deployments_list_error", error=str(e))
        return DeploymentListResponse(items=[], count=0)


@router.post("/deployments/{container_name}/stop", response_model=StopResponse)
async def stop_deployment(
    container_name: str,
    remove: bool = Query(True, description="Remove container after stopping"),
    user: dict = Depends(get_current_user),
) -> StopResponse:
    """Stop a running deployment via Docker MCP.

    Verifies ownership via container labels before stopping.
    """
    mcp_http = get_mcp_http()

    # First, verify ownership by inspecting the container
    user_roles = user.get("roles", [])
    if "admin" not in user_roles:
        try:
            inspect_result = await mcp_http.call(
                server="docker",
                tool="inspect",
                args={"container_name": container_name},
                timeout_seconds=10.0,
            )

            if not inspect_result.get("success"):
                raise NotFoundError("deployment", container_name)

            labels = inspect_result.get("labels", {})
            owner_id = labels.get("druppie.user_id")

            if owner_id and owner_id != user.get("sub"):
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to stop this deployment",
                )

        except MCPHttpError:
            raise NotFoundError("deployment", container_name)

    # Stop the container
    try:
        result = await mcp_http.call(
            server="docker",
            tool="stop",
            args={
                "container_name": container_name,
                "remove": remove,
            },
            timeout_seconds=60.0,
        )

        return StopResponse(
            success=result.get("success", False),
            container_name=container_name,
            stopped=True,
            removed=result.get("removed", False),
        )

    except MCPHttpError as e:
        logger.error("deployment_stop_error", container=container_name, error=str(e))
        return StopResponse(
            success=False,
            container_name=container_name,
        )


@router.get("/deployments/{container_name}/logs", response_model=LogsResponse)
async def get_deployment_logs(
    container_name: str,
    tail: int = Query(100, ge=1, le=1000, description="Number of lines"),
    user: dict = Depends(get_current_user),
) -> LogsResponse:
    """Get container logs via Docker MCP.

    Verifies ownership via container labels before fetching logs.
    """
    mcp_http = get_mcp_http()

    # Verify ownership for non-admins
    user_roles = user.get("roles", [])
    if "admin" not in user_roles:
        try:
            inspect_result = await mcp_http.call(
                server="docker",
                tool="inspect",
                args={"container_name": container_name},
                timeout_seconds=10.0,
            )

            if not inspect_result.get("success"):
                raise NotFoundError("deployment", container_name)

            labels = inspect_result.get("labels", {})
            owner_id = labels.get("druppie.user_id")

            if owner_id and owner_id != user.get("sub"):
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to view logs for this deployment",
                )

        except MCPHttpError:
            raise NotFoundError("deployment", container_name)

    # Get logs
    try:
        result = await mcp_http.call(
            server="docker",
            tool="logs",
            args={
                "container_name": container_name,
                "tail": tail,
            },
            timeout_seconds=30.0,
        )

        return LogsResponse(
            success=result.get("success", False),
            container_name=container_name,
            logs=result.get("logs", ""),
        )

    except MCPHttpError as e:
        logger.error("deployment_logs_error", container=container_name, error=str(e))
        return LogsResponse(
            success=False,
            container_name=container_name,
            logs=f"Error fetching logs: {e}",
        )


@router.get("/deployments/{container_name}", response_model=InspectResponse)
async def inspect_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> InspectResponse:
    """Inspect a deployment container via Docker MCP.

    Returns detailed container information including labels and ports.
    """
    mcp_http = get_mcp_http()

    try:
        result = await mcp_http.call(
            server="docker",
            tool="inspect",
            args={"container_name": container_name},
            timeout_seconds=10.0,
        )

        if not result.get("success"):
            raise NotFoundError("deployment", container_name)

        # Verify ownership for non-admins
        user_roles = user.get("roles", [])
        if "admin" not in user_roles:
            labels = result.get("labels", {})
            owner_id = labels.get("druppie.user_id")

            if owner_id and owner_id != user.get("sub"):
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to inspect this deployment",
                )

        return InspectResponse(
            success=True,
            container_name=container_name,
            details=result,
        )

    except MCPHttpError as e:
        logger.error("deployment_inspect_error", container=container_name, error=str(e))
        raise NotFoundError("deployment", container_name)
