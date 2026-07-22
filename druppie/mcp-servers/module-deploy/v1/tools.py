"""GitOps deployer — MCP Tool Definitions.

Deploys user apps via GitOps: commits Flux GitRepository+HelmRelease to ai/k8s,
triggers CI build, waits for Flux rollout + health gate.
"""

import logging
import re
from typing import Any

from fastmcp import FastMCP

MODULE_ID = "deploy"
MODULE_VERSION = "1.0.0"

logger = logging.getLogger("deploy-mcp")

mcp = FastMCP(
    "GitOps Deployer",
    version=MODULE_VERSION,
    instructions="""Deploy user applications via GitOps (Flux HelmRelease).

Use when:
- Deploying apps from a Gitea repo (compose_up)
- Tearing down deployed apps (compose_down)
- Listing deployed apps (list_containers)
- Reading app logs (logs)
- Stopping/removing apps (stop, remove)

Don't use when:
- You need file system operations (use coding module)
- You need web search (use web module)
""",
)

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')


def _validate_name(name: str, label: str) -> str | None:
    """Returns an error message if name is invalid, None if ok."""
    if not name or not _SAFE_NAME_RE.match(name) or len(name) > 128:
        return f"Invalid {label}: must start with alphanumeric, contain only alphanumeric/hyphens/dots/underscores, max 128 chars"
    return None


@mcp.tool(
    name="build",
    description="Dispatch the app's CI workflow and wait for it to finish.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def build(
    image_name: str = "",
    git_url: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    branch: str = "main",
    project_id: str | None = None,
    session_id: str | None = None,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Dispatch the app's CI workflow and wait for it to finish."""
    try:
        if not repo_name:
            return {"success": False, "error": "repo_name is required (dispatches the app's own CI)."}

        from .k8s_deploy import k8s_build
        result = await k8s_build(
            repo_name=repo_name,
            repo_owner=repo_owner,
            branch=branch,
            session_id=session_id,
        )
        if result.get("success"):
            result["project_id"] = project_id
            result["session_id"] = session_id
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="run",
    description="Run a container as a Kubernetes Deployment.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def run(
    image_name: str,
    container_name: str,
    container_port: int,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    git_url: str | None = None,
    branch: str | None = None,
    port: int | None = None,
    port_mapping: str | None = None,
    env_vars: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    command: str | None = None,
) -> dict:
    """Run a container as a Kubernetes Deployment."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        from .k8s_deploy import k8s_run
        return await k8s_run(
            image_name=image_name,
            container_name=container_name,
            container_port=container_port,
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            env_vars=env_vars,
            command=command,
        )

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="compose_up",
    description="Deploy application via GitOps: commit Flux manifests, trigger CI, wait for rollout.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def compose_up(
    repo_name: str | None = None,
    repo_owner: str | None = None,
    git_url: str | None = None,
    branch: str = "main",
    compose_project_name: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    health_path: str = "/health",
    health_timeout: int = 300,
) -> dict:
    """Deploy application via GitOps.

    Commits a Flux GitRepository + HelmRelease to ai/k8s, triggers the app's CI
    build, waits for Flux to roll it out, then health-gates the public URL.
    """
    try:
        if not repo_name:
            return {"success": False, "error": "repo_name is required (deploys via GitOps)."}

        from .k8s_deploy import k8s_compose_up
        project_name_final = compose_project_name or project_id or repo_name
        return await k8s_compose_up(
            repo_name=repo_name,
            repo_owner=repo_owner,
            branch=branch,
            compose_project_name=project_name_final,
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            health_path=health_path,
            health_timeout=health_timeout,
        )

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="compose_down",
    description="Teardown: delete the app's ai/k8s manifests. Flux prunes the namespace.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def compose_down(
    compose_project_name: str,
    remove_volumes: bool = True,
) -> dict:
    """Teardown: delete the app's ai/k8s manifests. Flux prunes the namespace."""
    try:
        compose_project_name = re.sub(
            r'[^a-z0-9-]', '', compose_project_name.lower().replace("_", "-")
        )
        if not compose_project_name:
            return {"success": False, "error": "Invalid compose_project_name: empty after sanitization"}

        from .k8s_deploy import k8s_compose_down
        return await k8s_compose_down(compose_project_name)

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="stop",
    description="Scale the app Deployment to 0.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def stop(container_name: str, remove: bool = True) -> dict:
    """Scale the app Deployment to 0, or teardown entirely."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        from .k8s_deploy import k8s_stop, k8s_remove
        if remove:
            return await k8s_remove(container_name)
        return await k8s_stop(container_name)

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="logs",
    description="Read logs from the app's first pod.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def logs(
    container_name: str,
    tail: int = 100,
    follow: bool = False,
) -> dict:
    """Read logs from the app's first pod."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        from .k8s_deploy import k8s_logs
        return await k8s_logs(container_name, tail=tail)

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="remove",
    description="Teardown: delete the app's ai/k8s manifests.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def remove(container_name: str, force: bool = False) -> dict:
    """Teardown: delete the app's ai/k8s manifests."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        from .k8s_deploy import k8s_remove
        return await k8s_remove(container_name)

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="list_containers",
    description="List deployed user-apps.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_containers(
    all: bool = False,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """List deployed user-apps by scanning ai/k8s clusters/user-apps/*."""
    try:
        from .k8s_deploy import k8s_list_containers
        containers = await k8s_list_containers(session_id=session_id, project_id=project_id)
        return {"success": True, "containers": containers}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="inspect",
    description="Inspect a deployed app. Not supported in GitOps mode.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def inspect(container_name: str) -> dict:
    """Inspect is not supported in GitOps mode. Use 'logs' or 'list_containers'."""
    try:
        from .k8s_deploy import k8s_inspect
        return await k8s_inspect(container_name)
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="exec_command",
    description="Execute a command inside a running container. Not supported in GitOps mode.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def exec_command(
    container_name: str,
    command: str,
    workdir: str | None = None,
) -> dict:
    """Exec is not supported in GitOps mode (apps are deployed, not interactive)."""
    try:
        from .k8s_deploy import k8s_exec_command
        return await k8s_exec_command(container_name, command)
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="start",
    description="Start a stopped container. Not supported in GitOps mode.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def start(container_name: str) -> dict:
    """Start is not supported in GitOps mode. Use compose_up to redeploy."""
    return {
        "success": False,
        "error": "'start' is not supported in GitOps mode. Use 'compose_up' to redeploy.",
    }


@mcp.tool(
    name="restart",
    description="Restart a container. Not supported in GitOps mode.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def restart(container_name: str, timeout: int = 10) -> dict:
    """Restart is not supported in GitOps mode. Use compose_up to redeploy."""
    return {
        "success": False,
        "error": "'restart' is not supported in GitOps mode. Use 'compose_up' to redeploy.",
    }


@mcp.tool(
    name="list_volumes",
    description="List volumes. Not supported in GitOps mode.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_volumes(
    project_id: str | None = None,
    compose_project: str | None = None,
    druppie_only: bool = True,
) -> dict:
    """List volumes is not supported in GitOps mode. PVCs are managed by the app Helm chart."""
    try:
        from .k8s_deploy import k8s_list_volumes
        return await k8s_list_volumes()
    except Exception as e:
        return {"success": False, "error": str(e)}
