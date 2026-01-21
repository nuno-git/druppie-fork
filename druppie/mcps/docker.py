"""Docker MCP Server.

Provides Docker container and compose operations.
"""

import os
import subprocess
from typing import Any

import structlog

from .registry import ApprovalType, MCPRegistry, MCPServer, MCPTool

logger = structlog.get_logger()


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

DOCKER_TOOLS = [
    MCPTool(
        id="docker:build",
        name="Build Image",
        description="Build a Docker image from Dockerfile",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Build context path"},
                "tag": {"type": "string", "description": "Image tag"},
                "dockerfile": {
                    "type": "string",
                    "description": "Dockerfile path",
                    "default": "Dockerfile",
                },
            },
            "required": ["path", "tag"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.NONE,
        danger_level="medium",
    ),
    MCPTool(
        id="docker:run",
        name="Run Container",
        description="Run a Docker container",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Image to run"},
                "name": {"type": "string", "description": "Container name"},
                "ports": {
                    "type": "object",
                    "description": "Port mappings (host: container)",
                },
                "env": {
                    "type": "object",
                    "description": "Environment variables",
                },
                "detach": {
                    "type": "boolean",
                    "description": "Run in background",
                    "default": True,
                },
            },
            "required": ["image"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="docker:stop",
        name="Stop Container",
        description="Stop a running container",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Container name or ID"},
            },
            "required": ["name"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="docker:logs",
        name="Container Logs",
        description="Get logs from a container",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Container name or ID"},
                "tail": {
                    "type": "integer",
                    "description": "Number of lines to show",
                    "default": 100,
                },
            },
            "required": ["name"],
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="docker:ps",
        name="List Containers",
        description="List running containers",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "all": {
                    "type": "boolean",
                    "description": "Show all containers",
                    "default": False,
                },
            },
        },
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="docker:rm",
        name="Remove Container",
        description="Remove a container",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Container name or ID"},
                "force": {
                    "type": "boolean",
                    "description": "Force remove running container",
                    "default": False,
                },
            },
            "required": ["name"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="docker:compose_up",
        name="Docker Compose Up",
        description="Start services defined in docker-compose.yml",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to docker-compose.yml"},
                "services": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Services to start (empty = all)",
                },
                "build": {
                    "type": "boolean",
                    "description": "Build images before starting",
                    "default": False,
                },
                "detach": {
                    "type": "boolean",
                    "description": "Run in background",
                    "default": True,
                },
            },
            "required": ["path"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.SELF,
        danger_level="medium",
    ),
    MCPTool(
        id="docker:compose_down",
        name="Docker Compose Down",
        description="Stop and remove docker-compose services",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to docker-compose.yml"},
                "volumes": {
                    "type": "boolean",
                    "description": "Remove volumes",
                    "default": False,
                },
            },
            "required": ["path"],
        },
        allowed_roles=["developer", "infra-engineer", "admin"],
        approval_type=ApprovalType.NONE,
    ),
    MCPTool(
        id="docker:compose_logs",
        name="Docker Compose Logs",
        description="Get logs from compose services",
        category="docker",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to docker-compose.yml"},
                "services": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Services to get logs for",
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of lines",
                    "default": 100,
                },
            },
            "required": ["path"],
        },
        approval_type=ApprovalType.NONE,
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _run_docker(args: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Run a docker command and return the result."""
    cmd = ["docker"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for builds
            cwd=cwd,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_compose(args: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Run a docker compose command and return the result."""
    cmd = ["docker", "compose"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=cwd,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================


async def build(
    path: str,
    tag: str,
    dockerfile: str = "Dockerfile",
) -> dict[str, Any]:
    """Build a Docker image."""
    args = ["build", "-t", tag, "-f", dockerfile, "."]
    result = _run_docker(args, cwd=path)
    if result["success"]:
        logger.info("docker_build_success", tag=tag, path=path)
    else:
        logger.error("docker_build_failed", tag=tag, error=result.get("stderr", "")[:200])
    return result


async def run(
    image: str,
    name: str | None = None,
    ports: dict[str, int] | None = None,
    env: dict[str, str] | None = None,
    detach: bool = True,
) -> dict[str, Any]:
    """Run a Docker container."""
    args = ["run"]

    if detach:
        args.append("-d")

    if name:
        args.extend(["--name", name])

    if ports:
        for host_port, container_port in ports.items():
            args.extend(["-p", f"{host_port}:{container_port}"])

    if env:
        for key, value in env.items():
            args.extend(["-e", f"{key}={value}"])

    args.append(image)

    result = _run_docker(args)
    if result["success"]:
        container_id = result["stdout"].strip()[:12]
        result["container_id"] = container_id
        logger.info("container_started", image=image, name=name, id=container_id)
    return result


async def stop(name: str) -> dict[str, Any]:
    """Stop a running container."""
    result = _run_docker(["stop", name])
    if result["success"]:
        logger.info("container_stopped", name=name)
    return result


async def logs(name: str, tail: int = 100) -> dict[str, Any]:
    """Get logs from a container."""
    return _run_docker(["logs", "--tail", str(tail), name])


async def ps(all: bool = False) -> dict[str, Any]:
    """List running containers."""
    args = ["ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"]
    if all:
        args.insert(1, "-a")
    return _run_docker(args)


async def rm(name: str, force: bool = False) -> dict[str, Any]:
    """Remove a container."""
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(name)

    result = _run_docker(args)
    if result["success"]:
        logger.info("container_removed", name=name)
    return result


async def compose_up(
    path: str,
    services: list[str] | None = None,
    build: bool = False,
    detach: bool = True,
) -> dict[str, Any]:
    """Start docker-compose services."""
    # Get directory containing compose file
    compose_dir = os.path.dirname(path) or "."
    compose_file = os.path.basename(path)

    args = ["-f", compose_file, "up"]

    if build:
        args.append("--build")

    if detach:
        args.append("-d")

    if services:
        args.extend(services)

    result = _run_compose(args, cwd=compose_dir)
    if result["success"]:
        logger.info("compose_up", path=path, services=services)
    return result


async def compose_down(
    path: str,
    volumes: bool = False,
) -> dict[str, Any]:
    """Stop docker-compose services."""
    compose_dir = os.path.dirname(path) or "."
    compose_file = os.path.basename(path)

    args = ["-f", compose_file, "down"]

    if volumes:
        args.append("-v")

    result = _run_compose(args, cwd=compose_dir)
    if result["success"]:
        logger.info("compose_down", path=path)
    return result


async def compose_logs(
    path: str,
    services: list[str] | None = None,
    tail: int = 100,
) -> dict[str, Any]:
    """Get logs from compose services."""
    compose_dir = os.path.dirname(path) or "."
    compose_file = os.path.basename(path)

    args = ["-f", compose_file, "logs", "--tail", str(tail)]

    if services:
        args.extend(services)

    return _run_compose(args, cwd=compose_dir)


# =============================================================================
# REGISTRATION
# =============================================================================


def register(registry: MCPRegistry) -> None:
    """Register the docker MCP server."""
    server = MCPServer(
        id="docker",
        name="Docker",
        description="Docker container and compose operations",
        tools=DOCKER_TOOLS,
    )

    # Register handlers
    server.register_handler("build", build)
    server.register_handler("run", run)
    server.register_handler("stop", stop)
    server.register_handler("logs", logs)
    server.register_handler("ps", ps)
    server.register_handler("rm", rm)
    server.register_handler("compose_up", compose_up)
    server.register_handler("compose_down", compose_down)
    server.register_handler("compose_logs", compose_logs)

    registry.register_server(server)
