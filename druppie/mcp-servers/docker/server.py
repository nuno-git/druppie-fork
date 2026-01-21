"""Docker MCP Server.

Docker container operations - build, run, stop, logs.
Uses FastMCP framework for HTTP transport.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Docker MCP Server")

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "druppie-new-network")
PORT_RANGE_START = int(os.getenv("PORT_RANGE_START", "9100"))
PORT_RANGE_END = int(os.getenv("PORT_RANGE_END", "9199"))

# Track used ports
used_ports: set[int] = set()


def get_next_port() -> int:
    """Get next available port."""
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if port not in used_ports:
            used_ports.add(port)
            return port
    raise RuntimeError("No available ports")


def release_port(port: int) -> None:
    """Release a port back to pool."""
    used_ports.discard(port)


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def build(
    workspace_path: str,
    image_name: str,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Build Docker image from workspace.

    Args:
        workspace_path: Path to workspace with Dockerfile
        image_name: Name for the built image
        dockerfile: Dockerfile name (default: "Dockerfile")
        build_args: Optional build arguments

    Returns:
        Dict with success, image_name, logs
    """
    try:
        workspace = Path(workspace_path)
        if not workspace.exists():
            return {"success": False, "error": f"Workspace not found: {workspace_path}"}

        dockerfile_path = workspace / dockerfile
        if not dockerfile_path.exists():
            return {"success": False, "error": f"Dockerfile not found: {dockerfile}"}

        # Build command
        cmd = ["docker", "build", "-t", image_name, "-f", str(dockerfile_path)]

        # Add build args
        if build_args:
            for key, value in build_args.items():
                cmd.extend(["--build-arg", f"{key}={value}"])

        cmd.append(str(workspace))

        # Run build
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes for builds
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": "Build failed",
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        return {
            "success": True,
            "image_name": image_name,
            "logs": result.stdout,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Build timed out after 10 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def run(
    image_name: str,
    container_name: str,
    port: int | None = None,
    env_vars: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    command: str | None = None,
) -> dict:
    """Run Docker container.

    Args:
        image_name: Docker image to run
        container_name: Name for the container
        port: Host port to expose (auto-assigned if not provided)
        env_vars: Environment variables
        volumes: Volume mounts (format: "host:container")
        command: Override command

    Returns:
        Dict with success, container_name, port, url
    """
    try:
        # Get port
        host_port = port or get_next_port()

        # Build run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
            "-p", f"{host_port}:8000",  # Default container port 8000
        ]

        # Add environment variables
        if env_vars:
            for key, value in env_vars.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Add volumes
        if volumes:
            for volume in volumes:
                cmd.extend(["-v", volume])

        # Add image and optional command
        cmd.append(image_name)
        if command:
            cmd.extend(command.split())

        # Run container
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            release_port(host_port)
            return {
                "success": False,
                "error": "Failed to start container",
                "stderr": result.stderr,
            }

        container_id = result.stdout.strip()

        return {
            "success": True,
            "container_name": container_name,
            "container_id": container_id[:12],
            "port": host_port,
            "url": f"http://localhost:{host_port}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def stop(container_name: str, remove: bool = True) -> dict:
    """Stop a running container.

    Args:
        container_name: Name of container to stop
        remove: Whether to remove container after stopping

    Returns:
        Dict with success
    """
    try:
        # Stop container
        result = subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to stop container: {result.stderr}",
            }

        # Remove if requested
        if remove:
            subprocess.run(
                ["docker", "rm", container_name],
                capture_output=True,
                timeout=10,
            )

        return {"success": True, "stopped": container_name, "removed": remove}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def logs(
    container_name: str,
    tail: int = 100,
    follow: bool = False,
) -> dict:
    """Get container logs.

    Args:
        container_name: Name of container
        tail: Number of lines to show (default: 100)
        follow: Not supported in MCP (always False)

    Returns:
        Dict with success, logs
    """
    try:
        cmd = ["docker", "logs", "--tail", str(tail), container_name]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to get logs: {result.stderr}",
            }

        return {
            "success": True,
            "container_name": container_name,
            "logs": result.stdout + result.stderr,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def remove(container_name: str, force: bool = False) -> dict:
    """Remove a container.

    Args:
        container_name: Name of container to remove
        force: Force remove running container

    Returns:
        Dict with success
    """
    try:
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(container_name)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to remove container: {result.stderr}",
            }

        return {"success": True, "removed": container_name}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_containers(all: bool = False) -> dict:
    """List Docker containers.

    Args:
        all: Include stopped containers

    Returns:
        Dict with containers list
    """
    try:
        cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
        if all:
            cmd.append("-a")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "id": parts[0],
                        "name": parts[1],
                        "image": parts[2],
                        "status": parts[3],
                        "ports": parts[4] if len(parts) > 4 else "",
                    })

        return {"success": True, "containers": containers}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def inspect(container_name: str) -> dict:
    """Inspect a container.

    Args:
        container_name: Name of container

    Returns:
        Dict with container details
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        import json
        data = json.loads(result.stdout)

        if data:
            container = data[0]
            return {
                "success": True,
                "id": container.get("Id", "")[:12],
                "name": container.get("Name", "").lstrip("/"),
                "image": container.get("Config", {}).get("Image", ""),
                "status": container.get("State", {}).get("Status", ""),
                "created": container.get("Created", ""),
                "ports": container.get("NetworkSettings", {}).get("Ports", {}),
            }

        return {"success": False, "error": "Container not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def exec_command(
    container_name: str,
    command: str,
    workdir: str | None = None,
) -> dict:
    """Execute command in running container.

    Args:
        container_name: Name of container
        command: Command to execute
        workdir: Working directory inside container

    Returns:
        Dict with stdout, stderr, return_code
    """
    try:
        cmd = ["docker", "exec"]

        if workdir:
            cmd.extend(["-w", workdir])

        cmd.extend([container_name, "sh", "-c", command])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
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
