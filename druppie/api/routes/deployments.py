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
    state: str = "unknown"
    health: str = "none"
    ports: str = ""
    project_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    compose_project: str | None = None
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


class ActionResponse(BaseModel):
    """Generic response for start/restart actions."""
    success: bool
    container_name: str
    error: str | None = None


class VolumeSummary(BaseModel):
    name: str
    driver: str = "local"
    project_id: str | None = None
    session_id: str | None = None
    compose_project: str | None = None
    labels: dict[str, str] = {}


class VolumeListResponse(BaseModel):
    items: list[VolumeSummary]
    count: int


class WipeResponse(BaseModel):
    success: bool
    project_id: str
    containers_removed: list[str] = []
    volumes_removed: list[str] = []
    errors: list[str] = []


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
        state=container.get("state", "unknown"),
        health=container.get("health", "none"),
        ports=ports_str,
        project_id=labels.get("druppie.project_id"),
        session_id=labels.get("druppie.session_id"),
        user_id=labels.get("druppie.user_id"),
        compose_project=labels.get("druppie.compose_project"),
        app_url=app_url,
    )


async def _verify_owner_or_admin(
    mcp_http: MCPHttp,
    container_name: str,
    user: dict,
    action: str,
) -> None:
    """Raise 403/404 if user is not admin and doesn't own the container."""
    if "admin" in user.get("roles", []):
        return
    try:
        inspect_result = await mcp_http.call(
            server="docker",
            tool="inspect",
            args={"container_name": container_name},
            timeout_seconds=10.0,
        )
        if not inspect_result.get("success"):
            raise NotFoundError("deployment", container_name)
        owner_id = inspect_result.get("labels", {}).get("druppie.user_id")
        if owner_id and owner_id != user.get("sub"):
            raise HTTPException(
                status_code=403,
                detail=f"Not authorized to {action} this deployment",
            )
    except MCPHttpError:
        raise NotFoundError("deployment", container_name)


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


# =============================================================================
# LIFECYCLE ACTIONS
# =============================================================================


@router.post("/deployments/{container_name}/start", response_model=ActionResponse)
async def start_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> ActionResponse:
    """Start a stopped deployment."""
    mcp_http = get_mcp_http()
    await _verify_owner_or_admin(mcp_http, container_name, user, "start")

    try:
        result = await mcp_http.call(
            server="docker",
            tool="start",
            args={"container_name": container_name},
            timeout_seconds=30.0,
        )
        return ActionResponse(
            success=result.get("success", False),
            container_name=container_name,
            error=result.get("error"),
        )
    except MCPHttpError as e:
        logger.error("deployment_start_error", container=container_name, error=str(e))
        return ActionResponse(success=False, container_name=container_name, error=str(e))


@router.post("/deployments/{container_name}/restart", response_model=ActionResponse)
async def restart_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> ActionResponse:
    """Restart a deployment."""
    mcp_http = get_mcp_http()
    await _verify_owner_or_admin(mcp_http, container_name, user, "restart")

    try:
        result = await mcp_http.call(
            server="docker",
            tool="restart",
            args={"container_name": container_name},
            timeout_seconds=60.0,
        )
        return ActionResponse(
            success=result.get("success", False),
            container_name=container_name,
            error=result.get("error"),
        )
    except MCPHttpError as e:
        logger.error("deployment_restart_error", container=container_name, error=str(e))
        return ActionResponse(success=False, container_name=container_name, error=str(e))


# =============================================================================
# VOLUMES
# =============================================================================


@router.get("/deployments/volumes/list", response_model=VolumeListResponse)
async def list_volumes(
    project_id: str | None = Query(None, description="Filter by druppie.project_id"),
    user: dict = Depends(get_current_user),
) -> VolumeListResponse:
    """List druppie-labeled Docker volumes.

    Non-admins only see volumes for projects they own (checked via any container
    in that project carrying their druppie.user_id).
    """
    mcp_http = get_mcp_http()
    args: dict[str, Any] = {"druppie_only": True}
    if project_id:
        args["project_id"] = project_id

    try:
        result = await mcp_http.call(
            server="docker",
            tool="list_volumes",
            args=args,
            timeout_seconds=15.0,
        )
        if not result.get("success"):
            return VolumeListResponse(items=[], count=0)

        raw = result.get("volumes", [])
        # Non-admins: filter to volumes whose project_id is owned by the user.
        # We piggyback on druppie.project_id label set by compose overrides.
        user_roles = user.get("roles", [])
        if "admin" not in user_roles:
            owned = await _owned_project_ids(mcp_http, user.get("sub", ""))
            raw = [v for v in raw if v.get("project_id") in owned]

        items = [VolumeSummary(**v) for v in raw]
        return VolumeListResponse(items=items, count=len(items))

    except MCPHttpError as e:
        logger.error("volumes_list_error", error=str(e))
        return VolumeListResponse(items=[], count=0)


async def _owned_project_ids(mcp_http: MCPHttp, user_id: str) -> set[str]:
    """Return set of druppie.project_id values the user owns any container in."""
    try:
        result = await mcp_http.call(
            server="docker",
            tool="list_containers",
            args={"all": True, "user_id": user_id},
            timeout_seconds=15.0,
        )
        if not result.get("success"):
            return set()
        return {
            c["labels"].get("druppie.project_id")
            for c in result.get("containers", [])
            if c.get("labels", {}).get("druppie.project_id")
        }
    except MCPHttpError:
        return set()


# =============================================================================
# PROJECT WIPE (containers + volumes)
# =============================================================================


@router.post("/deployments/project/{project_id}/wipe", response_model=WipeResponse)
async def wipe_project(
    project_id: str,
    user: dict = Depends(get_current_user),
) -> WipeResponse:
    """Stop and remove every container + labeled volume for a project.

    Destructive. Only admins or the owning user may call this. Containers are
    force-removed (docker rm -f) then labeled volumes are removed.
    """
    mcp_http = get_mcp_http()
    containers_removed: list[str] = []
    volumes_removed: list[str] = []
    errors: list[str] = []

    # Enumerate containers for the project (all states)
    try:
        list_result = await mcp_http.call(
            server="docker",
            tool="list_containers",
            args={"all": True, "project_id": project_id},
            timeout_seconds=15.0,
        )
    except MCPHttpError as e:
        raise HTTPException(status_code=502, detail=f"Docker MCP unreachable: {e}")

    containers = list_result.get("containers", []) if list_result.get("success") else []

    # Ownership check: non-admin must own every container
    user_roles = user.get("roles", [])
    if "admin" not in user_roles:
        user_id = user.get("sub")
        if not containers:
            raise NotFoundError("project", project_id)
        foreign = [
            c for c in containers
            if c.get("labels", {}).get("druppie.user_id")
            and c["labels"]["druppie.user_id"] != user_id
        ]
        if foreign:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to wipe this project",
            )

    # Remove containers
    for c in containers:
        name = c.get("name")
        if not name:
            continue
        try:
            r = await mcp_http.call(
                server="docker",
                tool="remove",
                args={"container_name": name, "force": True},
                timeout_seconds=30.0,
            )
            if r.get("success"):
                containers_removed.append(name)
            else:
                errors.append(f"rm {name}: {r.get('error', 'unknown')}")
        except MCPHttpError as e:
            errors.append(f"rm {name}: {e}")

    # Remove volumes labeled with this project_id
    try:
        vols = await mcp_http.call(
            server="docker",
            tool="list_volumes",
            args={"project_id": project_id, "druppie_only": True},
            timeout_seconds=15.0,
        )
        for v in vols.get("volumes", []) if vols.get("success") else []:
            vname = v.get("name")
            if not vname:
                continue
            try:
                r = await mcp_http.call(
                    server="docker",
                    tool="remove_volume",
                    args={"volume_name": vname, "force": False},
                    timeout_seconds=15.0,
                )
                if r.get("success"):
                    volumes_removed.append(vname)
                else:
                    errors.append(f"rm volume {vname}: {r.get('error', 'unknown')}")
            except MCPHttpError as e:
                errors.append(f"rm volume {vname}: {e}")
    except MCPHttpError as e:
        errors.append(f"list_volumes: {e}")

    return WipeResponse(
        success=len(errors) == 0,
        project_id=project_id,
        containers_removed=containers_removed,
        volumes_removed=volumes_removed,
        errors=errors,
    )
