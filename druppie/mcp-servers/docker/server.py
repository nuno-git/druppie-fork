"""Docker MCP Server.

Docker container operations - build, run, stop, logs.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP

from module import DockerModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("docker-mcp")

mcp = FastMCP("Docker MCP Server")

WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", "/workspaces")
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "druppie-new-network")
PORT_RANGE_START = int(os.getenv("PORT_RANGE_START", "9100"))
PORT_RANGE_END = int(os.getenv("PORT_RANGE_END", "9199"))

module = DockerModule(
    workspace_root=WORKSPACE_ROOT,
    docker_network=DOCKER_NETWORK,
    port_range_start=PORT_RANGE_START,
    port_range_end=PORT_RANGE_END,
)


@mcp.tool()
async def register_workspace(
    workspace_id: str,
    workspace_path: str,
    project_id: str | None = None,
    branch: str | None = None,
) -> dict:
    """Register a workspace for Docker operations."""
    return module.register_workspace(
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        project_id=project_id,
        branch=branch,
    )


@mcp.tool()
async def build(
    image_name: str,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Build Docker image from workspace."""
    return module.build(
        image_name=image_name,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        dockerfile=dockerfile,
        build_args=build_args,
    )


@mcp.tool()
async def run(
    image_name: str,
    container_name: str,
    port: int | None = None,
    container_port: int = 3000,
    port_mapping: str | None = None,
    env_vars: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    command: str | None = None,
) -> dict:
    """Run Docker container."""
    return module.run(
        image_name=image_name,
        container_name=container_name,
        port=port,
        container_port=container_port,
        port_mapping=port_mapping,
        env_vars=env_vars,
        volumes=volumes,
        command=command,
    )


@mcp.tool()
async def stop(container_name: str, remove: bool = True) -> dict:
    """Stop a running container."""
    return module.stop(container_name=container_name, remove=remove)


@mcp.tool()
async def logs(
    container_name: str,
    tail: int = 100,
    follow: bool = False,
) -> dict:
    """Get container logs."""
    return module.logs(
        container_name=container_name,
        tail=tail,
        follow=follow,
    )


@mcp.tool()
async def remove(container_name: str, force: bool = False) -> dict:
    """Remove a container."""
    return module.remove(container_name=container_name, force=force)


@mcp.tool()
async def list_containers(all: bool = False) -> dict:
    """List Docker containers."""
    return module.list_containers(all=all)


@mcp.tool()
async def inspect(container_name: str) -> dict:
    """Inspect a container."""
    return module.inspect(container_name=container_name)


@mcp.tool()
async def exec_command(
    container_name: str,
    command: str,
    workdir: str | None = None,
) -> dict:
    """Execute command in running container."""
    return module.exec_command(
        container_name=container_name,
        command=command,
        workdir=workdir,
    )


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "docker-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9002"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
