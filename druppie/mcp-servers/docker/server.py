"""Docker MCP Server.

Docker container operations - build, run, stop, logs.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("docker-mcp")

# Initialize FastMCP server
mcp = FastMCP("Docker MCP Server")

# Configuration
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/workspaces"))
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "druppie-new-network")
PORT_RANGE_START = int(os.getenv("PORT_RANGE_START", "9100"))
PORT_RANGE_END = int(os.getenv("PORT_RANGE_END", "9199"))

# Track used ports
used_ports: set[int] = set()

# In-memory workspace registry (shared with coding MCP or populated on build)
workspaces: dict[str, dict] = {}


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("", port))
            return True
        except OSError:
            return False


def get_next_port() -> int:
    """Get next available port."""
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if port not in used_ports and is_port_available(port):
            used_ports.add(port)
            return port
    raise RuntimeError("No available ports")


def release_port(port: int) -> None:
    """Release a port back to pool."""
    used_ports.discard(port)


def resolve_workspace_path(workspace_id: str | None, workspace_path: str | None) -> Path | None:
    """Resolve workspace path from workspace_id or direct path.

    Args:
        workspace_id: Workspace ID to look up
        workspace_path: Direct path (takes precedence if provided)

    Returns:
        Resolved Path or None if not found
    """
    # Direct path takes precedence
    if workspace_path:
        p = Path(workspace_path)
        if p.exists():
            return p
        # Try under workspace root
        p = WORKSPACE_ROOT / workspace_path
        if p.exists():
            return p

    # Look up workspace_id
    if workspace_id:
        if workspace_id in workspaces:
            return Path(workspaces[workspace_id]["path"])
        # Try to find by scanning workspace root
        # Pattern: /workspaces/user_id/project_id/session_id
        for user_dir in WORKSPACE_ROOT.iterdir():
            if user_dir.is_dir():
                for project_dir in user_dir.iterdir():
                    if project_dir.is_dir():
                        for session_dir in project_dir.iterdir():
                            if session_dir.is_dir():
                                # Check if this matches workspace_id pattern
                                if workspace_id in str(session_dir):
                                    return session_dir

    return None


@mcp.tool()
async def register_workspace(
    workspace_id: str,
    workspace_path: str,
    project_id: str | None = None,
    branch: str | None = None,
) -> dict:
    """Register a workspace for Docker operations.

    Args:
        workspace_id: Workspace ID
        workspace_path: Path to workspace
        project_id: Optional project ID
        branch: Optional git branch

    Returns:
        Dict with success status
    """
    workspaces[workspace_id] = {
        "path": workspace_path,
        "project_id": project_id,
        "branch": branch,
    }
    logger.info("Registered workspace %s at %s", workspace_id, workspace_path)
    return {"success": True, "workspace_id": workspace_id}


# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def build(
    image_name: str,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Build Docker image from workspace.

    Args:
        image_name: Name for the built image (e.g., "myapp:latest")
        workspace_id: Workspace ID (will resolve to path)
        workspace_path: Direct path to workspace with Dockerfile (takes precedence)
        dockerfile: Dockerfile name (default: "Dockerfile")
        build_args: Optional build arguments

    Returns:
        Dict with success, image_name, logs
    """
    try:
        # Resolve workspace path
        workspace = resolve_workspace_path(workspace_id, workspace_path)
        if workspace is None:
            return {
                "success": False,
                "error": f"Workspace not found: workspace_id={workspace_id}, workspace_path={workspace_path}",
            }

        logger.info("Building Docker image %s from %s", image_name, workspace)

        if not workspace.exists():
            return {"success": False, "error": f"Workspace not found: {workspace}"}

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
    container_port: int = 3000,
    port_mapping: str | None = None,
    env_vars: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    command: str | None = None,
) -> dict:
    """Run Docker container.

    Args:
        image_name: Docker image to run
        container_name: Name for the container
        port: Host port to expose (auto-assigned if not provided)
        container_port: Container port to map to (default: 3000)
        port_mapping: Full port mapping string (e.g., "8080:3000") - overrides port/container_port
        env_vars: Environment variables
        volumes: Volume mounts (format: "host:container")
        command: Override command

    Returns:
        Dict with success, container_name, port, url
    """
    try:
        # Handle port mapping
        requested_port = None
        if port_mapping:
            # Parse "host:container" format
            parts = port_mapping.split(":")
            requested_port = int(parts[0])
            container_port = int(parts[1]) if len(parts) > 1 else 3000
        else:
            requested_port = port

        # Check if requested port is available, auto-select if not
        if requested_port:
            if is_port_available(requested_port):
                host_port = requested_port
            else:
                # Port is busy, auto-select an available one
                logger.warning(
                    "Requested port %d is not available, auto-selecting alternative",
                    requested_port
                )
                host_port = get_next_port()
        else:
            host_port = get_next_port()

        logger.info(
            "Running container %s from image %s (port %d:%d)",
            container_name, image_name, host_port, container_port
        )

        # Build run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
            "-p", f"{host_port}:{container_port}",
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

        response = {
            "success": True,
            "container_name": container_name,
            "container_id": container_id[:12],
            "port": host_port,
            "url": f"http://localhost:{host_port}",
        }

        # Add note if port was changed
        if requested_port and host_port != requested_port:
            response["note"] = f"Port {requested_port} was busy, using {host_port} instead"

        return response

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
