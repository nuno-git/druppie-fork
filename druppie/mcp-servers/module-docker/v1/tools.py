"""Docker v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import yaml as pyyaml
from fastmcp import FastMCP

from .module import DockerModule

MODULE_ID = "docker"
MODULE_VERSION = "1.0.0"

logger = logging.getLogger("docker-mcp")

mcp = FastMCP(
    "Docker v1",
    version=MODULE_VERSION,
    instructions="""Docker container operations. Build images from git repos, run containers with auto-port assignment.

Use when:
- Building Docker images from a git repository or Gitea repo
- Running containers with automatic host port assignment
- Stopping or removing containers
- Getting container logs
- Listing or inspecting containers
- Executing commands inside running containers
- Deploying apps via docker compose (compose_up/compose_down)

Don't use when:
- You need file system operations (use coding module)
- You need web search (use web module)
""",
)

# Validation for Docker resource names (container names, compose project names)
_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')


def _validate_name(name: str, label: str) -> str | None:
    """Returns an error message if name is invalid, None if ok."""
    if not name or not _SAFE_NAME_RE.match(name) or len(name) > 128:
        return f"Invalid {label}: must start with alphanumeric, contain only alphanumeric/hyphens/dots/underscores, max 128 chars"
    return None


# Configuration
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "druppie-new-network")
PORT_RANGE_START = int(os.getenv("PORT_RANGE_START", "9100"))
PORT_RANGE_END = int(os.getenv("PORT_RANGE_END", "9199"))
BUILD_DIR = Path(os.getenv("BUILD_DIR", "/tmp/docker-builds"))

# Gitea config for cloning
GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")
GITEA_PASSWORD = os.getenv("GITEA_PASSWORD", "")

# Track used ports (guarded by _port_lock for async concurrency safety)
used_ports: set[int] = set()
_port_lock = asyncio.Lock()


# Track compose project -> port mapping for clean teardown.
# In-memory only: after MCP server restart this dict is empty, but compose_down
# has a fallback that discovers ports from running containers via docker ps.
compose_port_registry: dict[str, int] = {}


def get_used_host_ports() -> set[int]:
    """Get set of host ports currently in use by Docker containers."""
    try:
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
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            for mapping in line.split(", "):
                if "->" in mapping:
                    host_part = mapping.split("->")[0]
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


def _is_port_free_on_host(port: int) -> bool:
    """Check if a host port is free by asking the Docker daemon to bind it.

    Starts a throwaway container with the candidate port mapping. The port
    bind happens at start time (not create time), so we must actually start
    the container to detect conflicts. This correctly catches orphaned
    docker-proxy processes from any Docker daemon on the host — including
    the system daemon when we run under rootless Docker.
    """
    probe_name = f"port-probe-{port}"
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "-d", "--name", probe_name,
             "-p", f"{port}:80", "alpine", "sleep", "5"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        # Port bound successfully — clean up and report free
        subprocess.run(
            ["docker", "rm", "-f", probe_name],
            capture_output=True, text=True, timeout=5,
        )
        return True
    except Exception as e:
        logger.warning("Port probe failed for %d: %s", port, e)
        return False
    finally:
        subprocess.run(
            ["docker", "rm", "-f", probe_name],
            capture_output=True, text=True, timeout=5,
        )


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding on the Docker host."""
    docker_ports = get_used_host_ports()
    if port in docker_ports:
        return False
    if port in used_ports:
        return False
    return True


async def get_next_port() -> int:
    """Get next available port from the configured range.

    Checks Docker containers, internal tracking, AND actual host port
    availability via the Docker daemon (catches orphaned docker-proxy processes).
    Uses _port_lock to prevent TOCTOU races on concurrent compose_up calls.
    """
    async with _port_lock:
        docker_ports = get_used_host_ports()
        for port in range(PORT_RANGE_START, PORT_RANGE_END):
            if port in docker_ports or port in used_ports:
                continue
            if not _is_port_free_on_host(port):
                logger.info("Port %d is bound on host (orphaned proxy?), skipping", port)
                continue
            used_ports.add(port)
            logger.info("Auto-selected available port %d", port)
            return port
        raise RuntimeError(f"No available ports in range {PORT_RANGE_START}-{PORT_RANGE_END}")


async def release_port(port: int) -> None:
    """Release a port back to pool."""
    async with _port_lock:
        used_ports.discard(port)


def get_gitea_clone_url(repo_name: str, repo_owner: str | None = None) -> str:
    """Get Gitea clone URL with embedded credentials if available."""
    owner = repo_owner or "druppie"
    if GITEA_USER and GITEA_PASSWORD:
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
    """Clone from git and build Docker image."""
    build_id = str(uuid.uuid4())[:8]
    build_path = BUILD_DIR / build_id
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    try:
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
            timeout=600,
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
        if build_path.exists():
            shutil.rmtree(build_path, ignore_errors=True)
            logger.info("Cleaned up build directory: %s", build_path)


def check_and_remove_existing_container(container_name: str) -> dict | None:
    """Check if container exists and remove it if it does."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.ID}} {{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        output = result.stdout.strip().split("\n")[0]
        parts = output.split(" ", 1)
        container_id = parts[0]
        status = parts[1] if len(parts) > 1 else ""

        logger.info("Found existing container %s (ID: %s, Status: %s) - removing it",
                   container_name, container_id, status)

        if "Up" in status:
            stop_result = subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if stop_result.returncode != 0:
                logger.warning("Failed to stop container: %s", stop_result.stderr)

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


def parse_container_line(line: str) -> dict | None:
    """Parse a single `docker ps` tab-delimited line into a container dict.

    Factored out for unit-testing without a live Docker daemon.
    Returns None when the line is empty or malformed.
    """
    if not line:
        return None
    parts = line.split("\t")
    if len(parts) < 4:
        return None

    labels_str = parts[5] if len(parts) > 5 else ""
    labels: dict[str, str] = {}
    if labels_str:
        for label in labels_str.split(","):
            if "=" in label:
                k, v = label.split("=", 1)
                if k.startswith("druppie."):
                    labels[k] = v

    status_str = parts[3]
    if "(healthy)" in status_str:
        health = "healthy"
    elif "(unhealthy)" in status_str:
        health = "unhealthy"
    elif "(health: starting)" in status_str:
        health = "starting"
    else:
        health = "none"

    if status_str.startswith("Up"):
        state = "running"
    elif status_str.startswith("Restarting"):
        state = "restarting"
    elif status_str.startswith("Paused"):
        state = "paused"
    elif status_str.startswith("Created"):
        state = "created"
    else:
        state = "exited"

    return {
        "id": parts[0],
        "name": parts[1],
        "image": parts[2],
        "status": status_str,
        "state": state,
        "health": health,
        "ports": parts[4] if len(parts) > 4 else "",
        "labels": labels,
    }


def _discover_container_port(compose_file: Path) -> int:
    """Parse the app service's container port from docker-compose.yaml.

    Falls back to 8000 if the port cannot be determined.
    """
    try:
        data = pyyaml.safe_load(compose_file.read_text())
        ports = data.get("services", {}).get("app", {}).get("ports", [])
        for mapping in ports:
            mapping_str = str(mapping)
            # Handle "HOST:CONTAINER" or "${VAR:-HOST}:CONTAINER"
            if ":" in mapping_str:
                container_port_str = mapping_str.rsplit(":", 1)[1]
                # Strip protocol suffix like "/tcp"
                container_port_str = container_port_str.split("/")[0]
                return int(container_port_str)
        logger.warning("compose_up: no port mapping found for 'app' service, defaulting to 8000")
    except Exception as e:
        logger.warning("compose_up: could not parse container port from compose file: %s — defaulting to 8000", e)
    return 8000


@mcp.tool(
    name="build",
    description="Build Docker image from a git repository. Clones from git URL, builds, then cleans up the temp directory.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def build(
    image_name: str,
    git_url: str | None = None,
    repo_name: str | None = None,
    repo_owner: str | None = None,
    branch: str = "main",
    project_id: str | None = None,
    session_id: str | None = None,
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
) -> dict:
    """Build Docker image from a git repository.

    Args:
        image_name: Name for the built image (e.g., "myapp:latest")
        git_url: Full git URL to clone
        repo_name: Gitea repo name (will construct URL using Gitea config)
        repo_owner: Gitea repo owner/username (defaults to "druppie" org)
        branch: Git branch (default: main)
        project_id: Project ID for tracking (added to result)
        session_id: Session ID for tracking (added to result)
        dockerfile: Dockerfile name (default: "Dockerfile")
        build_args: Optional Docker build arguments

    Returns:
        Dict with success, image_name, build_log, project_id, session_id
    """
    try:
        if not git_url and not repo_name:
            return {
                "success": False,
                "error": "Must provide either git_url or repo_name",
            }

        url = git_url or get_gitea_clone_url(repo_name, repo_owner)
        logger.info(
            "Building Docker image: %s -> %s (branch: %s, project: %s, session: %s)",
            url, image_name, branch, project_id, session_id
        )

        result = clone_and_build(
            git_url=url,
            image_name=image_name,
            branch=branch,
            dockerfile=dockerfile,
            build_args=build_args,
        )

        if result.get("success"):
            result["project_id"] = project_id
            result["session_id"] = session_id

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="run",
    description="Run Docker container with ownership tracking via labels. Auto-assigns host port from free port range.",
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
    """Run Docker container with ownership tracking via labels.

    Args:
        image_name: Docker image to run
        container_name: Name for the container
        container_port: Container port (from Dockerfile EXPOSE) - REQUIRED
        project_id: Project ID (added as label for tracking)
        session_id: Session ID (added as label for tracking)
        user_id: User ID (added as label for tracking)
        git_url: Git URL used for build (added as label)
        branch: Git branch used for build (added as label)
        port: Host port to expose (auto-assigned from 9100-9199 if not provided)
        port_mapping: Full port mapping string (e.g., "8080:3000") - overrides port/container_port
        env_vars: Environment variables
        volumes: Volume mounts (format: "host:container")
        command: Override command

    Returns:
        Dict with success, container_name, port, container_port, url, labels
    """
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        # Check for and remove existing container with same name
        existing = check_and_remove_existing_container(container_name)
        if existing:
            logger.info("Removed existing container: %s", existing)

        requested_port = None
        actual_container_port = container_port
        if port_mapping:
            parts = port_mapping.split(":")
            requested_port = int(parts[0])
            actual_container_port = int(parts[1]) if len(parts) > 1 else container_port
        else:
            requested_port = port

        if requested_port:
            if is_port_available(requested_port):
                host_port = requested_port
            else:
                logger.warning(
                    "Requested port %d is not available, auto-selecting alternative",
                    requested_port
                )
                host_port = await get_next_port()
        else:
            host_port = await get_next_port()

        logger.info(
            "Running container %s from image %s (port %d:%d, project=%s, session=%s)",
            container_name, image_name, host_port, actual_container_port, project_id, session_id
        )

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
            "-p", f"{host_port}:{actual_container_port}",
        ]

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

        if env_vars:
            for key, value in env_vars.items():
                cmd.extend(["-e", f"{key}={value}"])

        if volumes:
            for volume in volumes:
                cmd.extend(["-v", volume])

        cmd.append(image_name)
        if command:
            cmd.extend(command.split())

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            await release_port(host_port)
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

        if requested_port and host_port != requested_port:
            response["note"] = f"Port {requested_port} was busy, using {host_port} instead"

        return response

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="compose_up",
    description="Deploy application with docker compose (app + database). Clones from git, builds, runs health check.",
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
    """Deploy application with docker compose (app + database).

    Clones from git, writes a label override, runs `docker compose up -d --build`,
    waits for health check, then returns the URL.

    Args:
        repo_name: Gitea repo name (constructs URL using Gitea config)
        repo_owner: Gitea repo owner (defaults to "druppie" org)
        git_url: Full git URL (alternative to repo_name/repo_owner)
        branch: Git branch (default: main)
        compose_project_name: Docker Compose project name (auto-derived if omitted)
        project_id: Project ID for labels (injected)
        session_id: Session ID for labels (injected)
        user_id: User ID for labels (injected)
        health_path: Health check endpoint path (default: /health, not agent-facing)
        health_timeout: Seconds to wait for health check (default: 300, not agent-facing)

    Returns:
        Dict with success, url, port, compose_project_name, containers, health_check
    """
    try:
        if not git_url and not repo_name:
            return {"success": False, "error": "Must provide either git_url or repo_name"}

        # Prefer repo_name (uses internal Gitea URL) over git_url (may be external/localhost)
        if repo_name:
            url = get_gitea_clone_url(repo_name, repo_owner)
        else:
            url = git_url

        # Step 1: Clone repository
        build_id = str(uuid.uuid4())[:8]
        clone_path = BUILD_DIR / build_id
        BUILD_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("compose_up: cloning %s (branch: %s)", url, branch)
        clone_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", "--branch", branch, "--depth", "1", url, str(clone_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if clone_result.returncode != 0:
            return {"success": False, "error": f"Git clone failed: {clone_result.stderr}"}

        # Step 2: Verify docker-compose.yaml exists
        compose_file = clone_path / "docker-compose.yaml"
        if not compose_file.exists():
            compose_file = clone_path / "docker-compose.yml"
        if not compose_file.exists():
            shutil.rmtree(clone_path, ignore_errors=True)
            return {"success": False, "error": "No docker-compose.yaml found in repository"}

        # Step 2b: Inject Druppie SDK (if mounted)
        sdk_source = Path("/druppie-sdk")
        if sdk_source.is_dir():
            sdk_dest = clone_path / "druppie-sdk"
            shutil.copytree(sdk_source, sdk_dest)
            logger.info("compose_up: injected druppie-sdk into build context")

        # All remaining steps wrapped in try/finally to guarantee clone_path cleanup
        host_port = None
        project_name = None
        try:
            # Step 3: Allocate host port
            host_port = await get_next_port()

            # Step 4: Determine compose project name
            # Use project_id when available so re-deploys replace instead of duplicate.
            # Fallback to repo_name + session suffix for one-off builds.
            project_name = compose_project_name
            if not project_name and project_id:
                project_name = project_id
            if not project_name:
                sid_suffix = (session_id or build_id)[:8]
                project_name = f"{repo_name or 'app'}-{sid_suffix}"
            # Sanitize: compose project names must be lowercase alphanumeric + hyphens
            project_name = re.sub(r'[^a-z0-9-]', '', project_name.lower().replace("_", "-"))
            if not project_name:
                project_name = f"app-{build_id}"

            # Step 4b: Tear down any existing deployment for this project.
            # Ensures clean replacement — removes old containers, volumes, networks.
            existing_port = compose_port_registry.get(project_name)
            try:
                down_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "compose", "-p", project_name, "down", "-v"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if down_result.returncode == 0 and existing_port:
                    await release_port(existing_port)
                    compose_port_registry.pop(project_name, None)
                    logger.info("compose_up: cleaned up previous deployment for %s", project_name)
            except Exception as e:
                logger.warning("compose_up: pre-cleanup failed for %s: %s", project_name, e)

            # Step 5: Write override file with druppie labels and network config
            labels = {}
            if project_id:
                labels["druppie.project_id"] = project_id
            if session_id:
                labels["druppie.session_id"] = session_id
            if user_id:
                labels["druppie.user_id"] = user_id
            if branch:
                labels["druppie.branch"] = branch
            labels["druppie.compose_project"] = project_name

            override_data: dict[str, Any] = {
                "services": {
                    "app": {
                        "labels": labels,
                    }
                }
            }

            # Join the Druppie Docker network so containers are discoverable
            if DOCKER_NETWORK:
                override_data["services"]["app"]["networks"] = [
                    "default",
                    DOCKER_NETWORK,
                ]
                override_data["networks"] = {
                    DOCKER_NETWORK: {
                        "external": True,
                        "name": DOCKER_NETWORK,
                    }
                }

            override_content = pyyaml.dump(
                override_data, default_flow_style=False, sort_keys=False
            )
            override_path = clone_path / "docker-compose.override.yaml"
            override_path.write_text(override_content)

            # Step 6: Run docker compose up
            logger.info("compose_up: starting project %s on port %d", project_name, host_port)
            env = {
                **os.environ,
                "APP_PORT": str(host_port),
                "DRUPPIE_URL": os.environ.get("DRUPPIE_URL", "http://druppie-backend:8000"),
                # Shared secret for the /api/modules/{id}/call proxy. Apps
                # forward this back via the X-Druppie-Token header through
                # the Druppie SDK. Empty string = dev mode / no auth.
                "DRUPPIE_MODULE_API_TOKEN": os.environ.get("DRUPPIE_MODULE_API_TOKEN", ""),
            }
            compose_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "compose", "-p", project_name, "up", "-d", "--build"],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(clone_path),
                env=env,
            )

            if compose_result.returncode != 0:
                await release_port(host_port)
                host_port = None
                return {
                    "success": False,
                    "error": "Docker compose up failed",
                    "build_log": compose_result.stdout + compose_result.stderr,
                }

            # Step 7: Track port mapping
            compose_port_registry[project_name] = host_port

            # Step 8: Health check via Docker network (not localhost)
            # Discover the container port from the compose file instead of hardcoding
            container_port = _discover_container_port(compose_file)
            app_container = f"{project_name}-app-1"
            health_url = f"http://{app_container}:{container_port}{health_path}"
            health_passed = False

            for elapsed in range(health_timeout):
                try:
                    req = urllib.request.Request(health_url)
                    resp = await asyncio.to_thread(
                        urllib.request.urlopen, req, timeout=2
                    )
                    if resp.status == 200:
                        health_passed = True
                        resp.close()
                        break
                    resp.close()
                except Exception:
                    pass
                if elapsed % 30 == 29:
                    logger.info(
                        "compose_up: health check pending (%ds/%ds)", elapsed + 1, health_timeout
                    )
                await asyncio.sleep(1)

            if not health_passed:
                # Get logs for debugging
                log_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "compose", "-p", project_name, "logs", "app"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                # Tear down failed deployment to avoid port/container leak
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "compose", "-p", project_name, "down", "-v"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                failed_port = host_port
                await release_port(host_port)
                host_port = None
                compose_port_registry.pop(project_name, None)
                return {
                    "success": False,
                    "error": f"Health check failed after {health_timeout}s",
                    "url": f"http://localhost:{failed_port}",
                    "port": failed_port,
                    "compose_project_name": project_name,
                    "logs": log_result.stdout + log_result.stderr,
                }

            # Step 9: Get container list
            ps_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "compose", "-p", project_name, "ps", "--format", "{{.Name}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            containers = [
                c.strip() for c in ps_result.stdout.strip().split("\n") if c.strip()
            ]

            logger.info("compose_up: project %s running on port %d", project_name, host_port)

            return {
                "success": True,
                "url": f"http://localhost:{host_port}",
                "port": host_port,
                "compose_project_name": project_name,
                "containers": containers,
                "health_check": "passed",
                "labels": labels,
            }

        finally:
            # Always clean up cloned temp directory
            shutil.rmtree(clone_path, ignore_errors=True)
            # Release port if we allocated one but didn't register success
            if host_port is not None and (
                project_name is None or project_name not in compose_port_registry
            ):
                await release_port(host_port)

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="compose_down",
    description="Stop and remove a docker compose deployment.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def compose_down(
    compose_project_name: str,
    remove_volumes: bool = True,
) -> dict:
    """Stop and remove a docker compose deployment.

    Args:
        compose_project_name: Compose project name to stop
        remove_volumes: Remove associated volumes (default: True)

    Returns:
        Dict with success, stopped project name
    """
    try:
        # Sanitize project name the same way compose_up does
        compose_project_name = re.sub(
            r'[^a-z0-9-]', '', compose_project_name.lower().replace("_", "-")
        )
        if not compose_project_name:
            return {"success": False, "error": "Invalid compose_project_name: empty after sanitization"}

        # Look up port from in-memory registry (may be empty after MCP server restart)
        port = compose_port_registry.get(compose_project_name)

        # Fallback: discover port from running containers if not in registry
        if port is None:
            try:
                ps_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "compose", "-p", compose_project_name, "ps",
                     "--format", "{{.Ports}}"],
                    capture_output=True, text=True, timeout=10,
                )
                # Parse "0.0.0.0:9101->8000/tcp" to extract host port
                for mapping in ps_result.stdout.split(","):
                    if "->" in mapping:
                        host_part = mapping.strip().split("->")[0]
                        port_str = host_part.rsplit(":", 1)[-1]
                        port = int(port_str)
                        break
            except Exception:
                pass

        # Run docker compose down
        cmd = ["docker", "compose", "-p", compose_project_name, "down"]
        if remove_volumes:
            cmd.append("-v")

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Docker compose down failed: {result.stderr}",
            }

        # Release port
        if port:
            await release_port(port)
            compose_port_registry.pop(compose_project_name, None)

        logger.info("compose_down: stopped project %s", compose_project_name)

        return {
            "success": True,
            "stopped": compose_project_name,
            "removed_volumes": remove_volumes,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="stop",
    description="Stop a running Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def stop(container_name: str, remove: bool = True) -> dict:
    """Stop a running container.

    Args:
        container_name: Name of container to stop
        remove: Whether to remove container after stopping

    Returns:
        Dict with success
    """
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

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

        if remove:
            subprocess.run(
                ["docker", "rm", container_name],
                capture_output=True,
                timeout=10,
            )

        return {"success": True, "stopped": container_name, "removed": remove}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="logs",
    description="Get logs from a Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

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


@mcp.tool(
    name="remove",
    description="Remove a Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def remove(container_name: str, force: bool = False) -> dict:
    """Remove a container.

    Args:
        container_name: Name of container to remove
        force: Force remove running container

    Returns:
        Dict with success
    """
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

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


@mcp.tool(
    name="list_containers",
    description="List Docker containers with optional filtering by ownership labels.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_containers(
    all: bool = False,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """List Docker containers with optional filtering by labels.

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
            parsed = parse_container_line(line)
            if parsed is not None:
                containers.append(parsed)

        return {"success": True, "containers": containers, "count": len(containers)}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="inspect",
    description="Inspect a Docker container and return its details.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def inspect(container_name: str) -> dict:
    """Inspect a container.

    Args:
        container_name: Name of container

    Returns:
        Dict with container details
    """
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

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


@mcp.tool(
    name="exec_command",
    description="Execute a command inside a running Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
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
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

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


@mcp.tool(
    name="start",
    description="Start a stopped Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def start(container_name: str) -> dict:
    """Start a stopped container."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        result = subprocess.run(
            ["docker", "start", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"success": False, "error": f"Failed to start: {result.stderr}"}

        return {"success": True, "started": container_name}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="restart",
    description="Restart a Docker container.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def restart(container_name: str, timeout: int = 10) -> dict:
    """Restart a container."""
    try:
        err = _validate_name(container_name, "container_name")
        if err:
            return {"success": False, "error": err}

        # Clamp so a caller can't pin the MCP worker on a runaway timeout.
        timeout = max(1, min(timeout, 300))

        result = subprocess.run(
            ["docker", "restart", "-t", str(timeout), container_name],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )

        if result.returncode != 0:
            return {"success": False, "error": f"Failed to restart: {result.stderr}"}

        return {"success": True, "restarted": container_name}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="list_volumes",
    description="List Docker volumes, optionally filtered by druppie labels or compose project.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_volumes(
    project_id: str | None = None,
    compose_project: str | None = None,
    druppie_only: bool = True,
) -> dict:
    """List Docker volumes with optional filtering.

    Args:
        project_id: Filter by druppie.project_id label
        compose_project: Filter by compose project label (com.docker.compose.project)
        druppie_only: If True, only return volumes tied to druppie.* labels or compose projects
            that also carry a druppie label on any container

    Returns:
        Dict with volumes list (name, driver, labels, size if available)
    """
    try:
        cmd = ["docker", "volume", "ls", "--format",
               "{{.Name}}\t{{.Driver}}\t{{.Labels}}"]
        if project_id:
            cmd.extend(["--filter", f"label=druppie.project_id={project_id}"])
        if compose_project:
            cmd.extend(["--filter", f"label=com.docker.compose.project={compose_project}"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        volumes = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name, driver = parts[0], parts[1]
            labels_str = parts[2] if len(parts) > 2 else ""
            labels: dict[str, str] = {}
            if labels_str and labels_str != "<no value>":
                for label in labels_str.split(","):
                    if "=" in label:
                        k, v = label.split("=", 1)
                        labels[k] = v

            # Keep only druppie-linked volumes when requested. A volume is
            # druppie-linked if it carries a druppie.* label directly OR belongs
            # to a compose project whose name starts with a druppie-managed prefix.
            if druppie_only:
                has_druppie_label = any(k.startswith("druppie.") for k in labels)
                if not has_druppie_label:
                    continue

            volumes.append({
                "name": name,
                "driver": driver,
                "labels": labels,
                "project_id": labels.get("druppie.project_id"),
                "session_id": labels.get("druppie.session_id"),
                "compose_project": labels.get("com.docker.compose.project"),
            })

        return {"success": True, "volumes": volumes, "count": len(volumes)}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="remove_volume",
    description="Remove a Docker volume.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def remove_volume(volume_name: str, force: bool = False) -> dict:
    """Remove a volume. Fails if the volume is in use unless force=True."""
    try:
        err = _validate_name(volume_name, "volume_name")
        if err:
            return {"success": False, "error": err}

        cmd = ["docker", "volume", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(volume_name)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()}

        return {"success": True, "removed": volume_name}

    except Exception as e:
        return {"success": False, "error": str(e)}
