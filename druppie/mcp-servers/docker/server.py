"""Docker MCP Server.

Docker container operations - build, run, stop, logs.
Uses FastMCP framework for HTTP transport.

This is a STANDALONE service:
- build: Clones from git URL (no workspace dependency)
- run: Adds labels for ownership tracking (druppie.project_id, druppie.session_id)
- list_containers: Can filter by project_id/session_id via labels
"""

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
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
BUILD_DIR = Path(os.getenv("BUILD_DIR", "/tmp/docker-builds"))

# Gitea config for cloning
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")

# Track used ports
used_ports: set[int] = set()

# In-memory workspace registry (for backward compatibility)
workspaces: dict[str, dict] = {}


def get_used_host_ports() -> set[int]:
    """Get set of host ports currently in use by Docker containers.

    This queries Docker to find which host ports are bound by running containers.
    Works correctly when called from inside a Docker container.
    """
    try:
        # Use docker ps to get port mappings of all running containers
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Failed to query Docker ports: %s", result.stderr)
            return set()

        ports = set()
        # Parse port mappings like "0.0.0.0:8080->80/tcp, 0.0.0.0:443->443/tcp"
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Each line may have multiple port mappings separated by comma
            for mapping in line.split(", "):
                # Format: "0.0.0.0:HOST_PORT->CONTAINER_PORT/proto" or "HOST_PORT->CONTAINER_PORT/proto"
                if "->" in mapping:
                    host_part = mapping.split("->")[0]
                    # Extract port number (after last colon if IP present)
                    if ":" in host_part:
                        port_str = host_part.rsplit(":", 1)[1]
                    else:
                        port_str = host_part
                    try:
                        ports.add(int(port_str))
                    except ValueError:
                        pass
        return ports
    except Exception as e:
        logger.warning("Error getting used ports: %s", e)
        return set()


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding on the Docker host.

    This checks both:
    1. Docker containers using the port (via docker ps)
    2. Our internal tracking of ports we've allocated
    """
    # Check if Docker is already using this port on the host
    docker_ports = get_used_host_ports()
    if port in docker_ports:
        return False

    # Also check our internal tracking
    if port in used_ports:
        return False

    return True


def get_next_port() -> int:
    """Get next available port from the configured range.

    Checks both Docker's currently bound ports and our internal tracking.
    """
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if is_port_available(port):
            used_ports.add(port)
            logger.info("Auto-selected available port %d", port)
            return port
    raise RuntimeError(f"No available ports in range {PORT_RANGE_START}-{PORT_RANGE_END}")


def release_port(port: int) -> None:
    """Release a port back to pool."""
    used_ports.discard(port)


def resolve_workspace_path(workspace_id: str | None, workspace_path: str | None) -> Path | None:
    """Resolve workspace path from workspace_id or direct path.

    NOTE: This is legacy/fallback. Prefer git-based builds using git_url or repo_name.

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


def get_gitea_clone_url(repo_name: str, repo_owner: str | None = None) -> str:
    """Get Gitea clone URL with embedded credentials if available.

    Args:
        repo_name: Repository name
        repo_owner: Owner username (defaults to GITEA_ORG if not provided)
    """
    owner = repo_owner or "druppie"
    if GITEA_USER and GITEA_PASSWORD:
        # Authenticated URL: http://user:pass@host:port/owner/repo.git
        host_part = GITEA_URL.replace("http://", "").replace("https://", "")
        return f"http://{GITEA_USER}:{GITEA_PASSWORD}@{host_part}/{owner}/{repo_name}.git"
    return f"{GITEA_URL}/{owner}/{repo_name}.git"


def clone_and_build(
    git_url: str,
    image_name: str,
    branch: str = "main",
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Clone from git and build Docker image.

    This is the standalone approach - clones to temp dir, builds, cleans up.
    No dependency on workspace or coding MCP.

    Args:
        git_url: Git URL to clone
        image_name: Docker image name
        branch: Git branch (default: main)
        dockerfile: Dockerfile path (default: Dockerfile)
        build_args: Docker build args

    Returns:
        Dict with success, image_name, build_log
    """
    build_id = str(uuid.uuid4())[:8]
    build_path = BUILD_DIR / build_id
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # Clone repository
        logger.info("Cloning %s (branch: %s) to %s", git_url, branch, build_path)
        clone_result = subprocess.run(
            ["git", "clone", "--branch", branch, "--depth", "1", git_url, str(build_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if clone_result.returncode != 0:
            return {
                "success": False,
                "error": f"Git clone failed: {clone_result.stderr}",
            }

        # Build Docker image
        dockerfile_path = build_path / dockerfile
        if not dockerfile_path.exists():
            return {
                "success": False,
                "error": f"Dockerfile not found: {dockerfile}",
            }

        cmd = ["docker", "build", "-t", image_name]

        if build_args:
            for key, value in build_args.items():
                cmd.extend(["--build-arg", f"{key}={value}"])

        cmd.extend(["-f", str(dockerfile_path), str(build_path)])

        logger.info("Building Docker image: %s", " ".join(cmd))

        build_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout for builds
        )

        if build_result.returncode != 0:
            return {
                "success": False,
                "error": f"Docker build failed: {build_result.stderr}",
                "build_log": build_result.stdout + build_result.stderr,
            }

        logger.info("Successfully built image: %s", image_name)

        return {
            "success": True,
            "image_name": image_name,
            "build_log": build_result.stdout,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Build timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        # Always cleanup temp build directory
        if build_path.exists():
            shutil.rmtree(build_path, ignore_errors=True)
            logger.info("Cleaned up build directory: %s", build_path)


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
    git_url: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    branch: str = "main",
    project_id: str | None = None,
    session_id: str | None = None,
    workspace_id: str | None = None,
    workspace_path: str | None = None,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Build Docker image.

    Two modes:
    1. GIT-BASED (preferred): Clone from git URL, build, cleanup
       - Use git_url for any git repo
       - Use repo_name + repo_owner for Gitea repos (will construct URL)

    2. WORKSPACE-BASED (legacy): Build from existing workspace path

    Args:
        image_name: Name for the built image (e.g., "myapp:latest")
        git_url: Full git URL to clone (preferred)
        repo_name: Gitea repo name (will construct URL)
        repo_owner: Gitea repo owner/username (defaults to "druppie" org)
        branch: Git branch (default: main)
        project_id: Project ID for tracking
        session_id: Session ID for tracking
        workspace_id: Legacy workspace ID (will resolve to path)
        workspace_path: Legacy direct path to workspace with Dockerfile
        dockerfile: Dockerfile name (default: "Dockerfile")
        build_args: Optional build arguments

    Returns:
        Dict with success, image_name, logs
    """
    try:
        # Mode 1: Git-based build (preferred)
        if git_url or repo_name:
            url = git_url or get_gitea_clone_url(repo_name, repo_owner)
            logger.info(
                "Git-based build: %s -> %s (branch: %s, project: %s, session: %s)",
                url, image_name, branch, project_id, session_id
            )
            result = clone_and_build(
                git_url=url,
                image_name=image_name,
                branch=branch,
                dockerfile=dockerfile,
                build_args=build_args,
            )
            # Add tracking info to result
            if result.get("success"):
                result["project_id"] = project_id
                result["session_id"] = session_id
                result["build_mode"] = "git"
            return result

        # Mode 2: Workspace-based build (legacy)
        workspace = resolve_workspace_path(workspace_id, workspace_path)
        if workspace is None:
            return {
                "success": False,
                "error": "Must provide git_url, repo_name, workspace_id, or workspace_path",
            }

        logger.info("Workspace-based build: %s -> %s", workspace, image_name)

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
            "build_mode": "workspace",
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Build timed out after 10 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_and_remove_existing_container(container_name: str) -> dict | None:
    """Check if container exists and remove it if it does.

    Args:
        container_name: Name of container to check

    Returns:
        Dict with info about what was done, or None if no existing container
    """
    try:
        # Check if container exists (running or stopped)
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.ID}} {{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None  # No existing container

        # Container exists - get its ID and status
        output = result.stdout.strip().split("\n")[0]
        parts = output.split(" ", 1)
        container_id = parts[0]
        status = parts[1] if len(parts) > 1 else ""

        logger.info("Found existing container %s (ID: %s, Status: %s) - removing it",
                   container_name, container_id, status)

        # Stop container if it's running
        if "Up" in status:
            stop_result = subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if stop_result.returncode != 0:
                logger.warning("Failed to stop container: %s", stop_result.stderr)

        # Remove the container
        rm_result = subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if rm_result.returncode != 0:
            logger.warning("Failed to remove container: %s", rm_result.stderr)
            return {"removed": False, "error": rm_result.stderr}

        return {"removed": True, "previous_status": status}

    except Exception as e:
        logger.warning("Error checking/removing existing container: %s", e)
        return {"removed": False, "error": str(e)}


@mcp.tool()
async def run(
    image_name: str,
    container_name: str,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    git_url: str | None = None,
    branch: str | None = None,
    port: int | None = None,
    container_port: int = 3000,
    port_mapping: str | None = None,
    env_vars: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    command: str | None = None,
) -> dict:
    """Run Docker container with ownership tracking via labels.

    Labels added to container for ownership tracking:
    - druppie.project_id: Project this container belongs to
    - druppie.session_id: Session that created this container
    - druppie.user_id: User who owns this container
    - druppie.git_url: Source git URL (if applicable)
    - druppie.branch: Git branch used for build

    Args:
        image_name: Docker image to run
        container_name: Name for the container
        project_id: Project ID (added as label for tracking)
        session_id: Session ID (added as label for tracking)
        user_id: User ID (added as label for tracking)
        git_url: Git URL used for build (added as label)
        branch: Git branch used for build (added as label)
        port: Host port to expose (auto-assigned if not provided)
        container_port: Container port to map to (default: 3000)
        port_mapping: Full port mapping string (e.g., "8080:3000") - overrides port/container_port
        env_vars: Environment variables
        volumes: Volume mounts (format: "host:container")
        command: Override command

    Returns:
        Dict with success, container_name, port, url, labels
    """
    try:
        # Check for and remove existing container with same name
        existing = check_and_remove_existing_container(container_name)
        if existing:
            logger.info("Removed existing container: %s", existing)

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
            "Running container %s from image %s (port %d:%d, project=%s, session=%s)",
            container_name, image_name, host_port, container_port, project_id, session_id
        )

        # Build run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
            "-p", f"{host_port}:{container_port}",
        ]

        # Add ownership labels for tracking
        labels = {}
        if project_id:
            cmd.extend(["--label", f"druppie.project_id={project_id}"])
            labels["druppie.project_id"] = project_id
        if session_id:
            cmd.extend(["--label", f"druppie.session_id={session_id}"])
            labels["druppie.session_id"] = session_id
        if user_id:
            cmd.extend(["--label", f"druppie.user_id={user_id}"])
            labels["druppie.user_id"] = user_id
        if git_url:
            cmd.extend(["--label", f"druppie.git_url={git_url}"])
            labels["druppie.git_url"] = git_url
        if branch:
            cmd.extend(["--label", f"druppie.branch={branch}"])
            labels["druppie.branch"] = branch

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
            "labels": labels,
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
async def list_containers(
    all: bool = False,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """List Docker containers with optional filtering by labels.

    Can filter containers by ownership labels:
    - project_id: Only containers with druppie.project_id label
    - session_id: Only containers with druppie.session_id label
    - user_id: Only containers with druppie.user_id label

    Args:
        all: Include stopped containers
        project_id: Filter by project_id label
        session_id: Filter by session_id label
        user_id: Filter by user_id label

    Returns:
        Dict with containers list (including labels)
    """
    try:
        cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Labels}}"]
        if all:
            cmd.append("-a")

        # Add label filters
        if project_id:
            cmd.extend(["--filter", f"label=druppie.project_id={project_id}"])
        if session_id:
            cmd.extend(["--filter", f"label=druppie.session_id={session_id}"])
        if user_id:
            cmd.extend(["--filter", f"label=druppie.user_id={user_id}"])

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
                    # Parse labels into dict
                    labels_str = parts[5] if len(parts) > 5 else ""
                    labels = {}
                    if labels_str:
                        for label in labels_str.split(","):
                            if "=" in label:
                                k, v = label.split("=", 1)
                                # Only include druppie.* labels
                                if k.startswith("druppie."):
                                    labels[k] = v

                    containers.append({
                        "id": parts[0],
                        "name": parts[1],
                        "image": parts[2],
                        "status": parts[3],
                        "ports": parts[4] if len(parts) > 4 else "",
                        "labels": labels,
                    })

        return {"success": True, "containers": containers, "count": len(containers)}

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
            # Extract druppie.* labels
            all_labels = container.get("Config", {}).get("Labels", {}) or {}
            druppie_labels = {k: v for k, v in all_labels.items() if k.startswith("druppie.")}

            return {
                "success": True,
                "id": container.get("Id", "")[:12],
                "name": container.get("Name", "").lstrip("/"),
                "image": container.get("Config", {}).get("Image", ""),
                "status": container.get("State", {}).get("Status", ""),
                "created": container.get("Created", ""),
                "ports": container.get("NetworkSettings", {}).get("Ports", {}),
                "labels": druppie_labels,
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
