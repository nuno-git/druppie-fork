"""Deployments API routes.

Bridge to module-deploy - lets frontend manage containers that agents have deployed.

Architecture:
    Route (this file)
      │
      └──▶ MCP Bridge (module-deploy list_apps, stop, logs)
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

from druppie.api.deps import get_current_user, get_user_roles
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
    """Deployment info from module-deploy."""
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
    """Parse container/app info to DeploymentSummary (Docker or K8s shape)."""
    # K8s (GitOps) shape from module-deploy k8s_list_apps:
    #   {name, namespace, url, ready, status_message}
    if "url" in container and "namespace" in container:
        ready = bool(container.get("ready"))
        return DeploymentSummary(
            container_id=container.get("namespace", ""),
            container_name=container.get("name", ""),
            image="",
            status=container.get("status_message") or ("ready" if ready else "deploying"),
            state="running" if ready else "pending",
            health="healthy" if ready else "none",
            ports="",
            project_id=None,
            session_id=None,
            user_id=None,
            compose_project=container.get("name"),
            app_url=container.get("url"),
        )

    # Docker shape (legacy / local-dev mode)
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
    if "admin" in get_user_roles(user):
        return
    try:
        inspect_result = await mcp_http.call(
            server="deploy",
            tool="inspect",
            args={"container_name": container_name},
            timeout_seconds=10.0,
        )
        if not inspect_result.get("success"):
            raise NotFoundError("deployment", container_name)
        owner_id = inspect_result.get("labels", {}).get("druppie.user_id")
        # Fail closed: a container without a druppie.user_id label is treated
        # as not-owned by any non-admin caller.
        if not owner_id or owner_id != user.get("sub"):
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
    """List running deployments via module-deploy.

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
    user_roles = get_user_roles(user)
    if "admin" not in user_roles:
        args["user_id"] = user.get("sub")

    try:
        result = await mcp_http.call(
            server="deploy",
            tool="list_apps",
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
    """Stop a running deployment via module-deploy.

    Verifies ownership via container labels before stopping.
    """
    mcp_http = get_mcp_http()
    await _verify_owner_or_admin(mcp_http, container_name, user, "stop")

    # Stop the container
    try:
        result = await mcp_http.call(
            server="deploy",
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
    """Get container logs via module-deploy.

    Verifies ownership via container labels before fetching logs.
    """
    mcp_http = get_mcp_http()
    await _verify_owner_or_admin(mcp_http, container_name, user, "view logs for")

    # Get logs
    try:
        result = await mcp_http.call(
            server="deploy",
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
    """Inspect a deployment container via module-deploy.

    Returns detailed container information including labels and ports.
    """
    mcp_http = get_mcp_http()

    try:
        result = await mcp_http.call(
            server="deploy",
            tool="inspect",
            args={"container_name": container_name},
            timeout_seconds=10.0,
        )

        if not result.get("success"):
            raise NotFoundError("deployment", container_name)

        # Fail closed on missing owner label — same semantics as the helper.
        if "admin" not in get_user_roles(user):
            owner_id = result.get("labels", {}).get("druppie.user_id")
            if not owner_id or owner_id != user.get("sub"):
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
    """Start is not supported in GitOps mode. Use deploy to redeploy."""
    return ActionResponse(
        success=False,
        container_name=container_name,
        error="'start' is not supported in GitOps mode. Use 'deploy' to redeploy.",
    )


@router.post("/deployments/{container_name}/restart", response_model=ActionResponse)
async def restart_deployment(
    container_name: str,
    user: dict = Depends(get_current_user),
) -> ActionResponse:
    """Restart is not supported in GitOps mode. Use deploy to redeploy."""
    return ActionResponse(
        success=False,
        container_name=container_name,
        error="'restart' is not supported in GitOps mode. Use 'deploy' to redeploy.",
    )


# =============================================================================
# VOLUMES
# =============================================================================


@router.get("/deployments/volumes/list", response_model=VolumeListResponse)
async def list_volumes(
    project_id: str | None = Query(None, description="Filter by druppie.project_id"),
    user: dict = Depends(get_current_user),
) -> VolumeListResponse:
    """Volumes are managed by the app's Helm chart (PVCs). Not listed here."""
    return VolumeListResponse(items=[], count=0)


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
            server="deploy",
            tool="list_apps",
            args={"all": True, "project_id": project_id},
            timeout_seconds=15.0,
        )
    except MCPHttpError as e:
        logger.error("wipe_project_mcp_unreachable", project_id=project_id, error=str(e))
        raise HTTPException(status_code=502, detail="module-deploy unreachable")

    containers = list_result.get("containers", []) if list_result.get("success") else []

    # Ownership check: fail closed — non-admin must own every container, and
    # any container missing druppie.user_id counts as not-owned.
    user_roles = get_user_roles(user)
    if "admin" not in user_roles:
        user_id = user.get("sub")
        if not containers:
            raise NotFoundError("project", project_id)
        foreign = [
            c for c in containers
            if c.get("labels", {}).get("druppie.user_id") != user_id
        ]
        if foreign:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to wipe this project",
            )

    # Collect compose project names from druppie-labeled containers so we can
    # tear down entire compose stacks (app + sidecars like postgres + volumes).
    compose_projects: set[str] = set()
    for c in containers:
        labels = c.get("labels", {})
        cp = labels.get("druppie.compose_project") or labels.get("com.docker.compose.project")
        if cp:
            compose_projects.add(cp)

    # Use teardown to remove all containers AND volumes per compose project.
    # This handles sidecar containers (db, redis, etc.) that don't carry
    # druppie.* labels but belong to the same compose stack.
    for cp in compose_projects:
        try:
            r = await mcp_http.call(
                server="deploy",
                tool="teardown",
                args={"compose_project_name": cp, "remove_volumes": True},
                timeout_seconds=60.0,
            )
            if r.get("success"):
                containers_removed.append(f"compose:{cp}")
                for v in r.get("volumes_removed", []):
                    volumes_removed.append(v)
            else:
                errors.append(f"teardown {cp}: {r.get('error', 'unknown')}")
        except MCPHttpError as e:
            errors.append(f"teardown {cp}: {e}")

    # Remove any druppie-labeled containers not part of a compose project
    # (e.g. standalone containers created outside deploy).
    standalone = [
        c for c in containers
        if not any(
            (c.get("labels", {}).get("druppie.compose_project") or
             c.get("labels", {}).get("com.docker.compose.project")) == cp
            for cp in compose_projects
        )
    ]
    for c in standalone:
        name = c.get("name")
        if not name:
            continue
        try:
            r = await mcp_http.call(
                server="deploy",
                tool="teardown",
                args={"container_name": name, "force": True},
                timeout_seconds=30.0,
            )
            if r.get("success"):
                containers_removed.append(name)
            else:
                errors.append(f"rm {name}: {r.get('error', 'unknown')}")
        except MCPHttpError as e:
            errors.append(f"rm {name}: {e}")

    return WipeResponse(
        success=len(errors) == 0,
        project_id=project_id,
        containers_removed=containers_removed,
        volumes_removed=volumes_removed,
        errors=errors,
    )
