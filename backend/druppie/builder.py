"""Builder Service - Builds and runs Docker applications.

Manages the lifecycle of user-created applications:
- Generates docker-compose.yml for projects
- Builds Docker images
- Runs containers
- Exposes URLs for running apps
"""

import os
import subprocess
import uuid
import json
import time
from pathlib import Path
from typing import Any
from datetime import datetime

import structlog
import redis
import yaml

logger = structlog.get_logger()

WORKSPACE_PATH = Path(os.getenv("WORKSPACE_PATH", "/app/workspace"))
PROJECTS_NETWORK = os.getenv("PROJECTS_NETWORK", "druppie-projects")
HOST_PORT_START = int(os.getenv("HOST_PORT_START", "9001"))
HOST_PORT_END = int(os.getenv("HOST_PORT_END", "9100"))
EXTERNAL_HOST = os.getenv("EXTERNAL_HOST", "localhost")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Internal ports for different app types (container port)
APP_INTERNAL_PORTS = {
    "flask": 5000,
    "python": 5000,
    "express": 3000,
    "node": 3000,
    "vite": 80,      # nginx serves built files
    "react": 80,     # nginx serves built files
    "static": 80,    # nginx serves static files
    "html": 80,      # nginx serves static files
}


class PortRegistry:
    """Redis-based port registry to track allocated ports across restarts."""

    def __init__(self):
        self._redis = None
        self._port_key = "druppie:ports"

    @property
    def redis(self):
        if self._redis is None:
            try:
                self._redis = redis.from_url(REDIS_URL, decode_responses=True)
                self._redis.ping()
            except Exception as e:
                logger.warning("Redis not available for port registry", error=str(e))
                self._redis = None
        return self._redis

    def allocate_port(self, project_id: str) -> int:
        """Allocate a port for a project, reusing existing if already allocated."""
        # Check if project already has a port
        if self.redis:
            existing = self.redis.hget(self._port_key, project_id)
            if existing:
                return int(existing)

        # Find available port
        for port in range(HOST_PORT_START, HOST_PORT_END):
            if self._is_port_available(port, project_id):
                self._reserve_port(port, project_id)
                return port

        raise RuntimeError("No available ports for new application")

    def _is_port_available(self, port: int, project_id: str) -> bool:
        """Check if a port is available."""
        # Check Redis registry
        if self.redis:
            owner = self.redis.hget(self._port_key, f"port:{port}")
            if owner and owner != project_id:
                return False

        # Check actual Docker containers
        result = subprocess.run(
            ["docker", "ps", "--filter", f"publish={port}", "-q"],
            capture_output=True,
            text=True,
        )
        return not result.stdout.strip()

    def _reserve_port(self, port: int, project_id: str):
        """Reserve a port for a project."""
        if self.redis:
            self.redis.hset(self._port_key, project_id, port)
            self.redis.hset(self._port_key, f"port:{port}", project_id)
            logger.info("Port allocated", project_id=project_id, port=port)

    def release_port(self, project_id: str):
        """Release a project's port."""
        if self.redis:
            port = self.redis.hget(self._port_key, project_id)
            if port:
                self.redis.hdel(self._port_key, project_id)
                self.redis.hdel(self._port_key, f"port:{port}")
                logger.info("Port released", project_id=project_id, port=port)

    def get_project_port(self, project_id: str) -> int | None:
        """Get the allocated port for a project."""
        if self.redis:
            port = self.redis.hget(self._port_key, project_id)
            if port:
                return int(port)
        return None


class RunningApp:
    """Represents a running application."""

    def __init__(
        self,
        project_id: str,
        container_name: str,
        port: int,
        status: str = "running",
    ):
        self.project_id = project_id
        self.container_name = container_name
        self.port = port
        self.status = status
        self.started_at = datetime.utcnow()

    @property
    def url(self) -> str:
        return f"http://{EXTERNAL_HOST}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "container_name": self.container_name,
            "port": self.port,
            "status": self.status,
            "url": self.url,
            "started_at": self.started_at.isoformat(),
        }


class BuilderService:
    """Service for building and running Docker applications."""

    def __init__(self):
        self._running_apps: dict[str, RunningApp] = {}
        self._port_registry = PortRegistry()
        self._ensure_network()

    def _ensure_network(self):
        """Ensure the projects network exists."""
        try:
            subprocess.run(
                ["docker", "network", "create", PROJECTS_NETWORK],
                capture_output=True,
            )
            logger.info("Ensured network exists", network=PROJECTS_NETWORK)
        except Exception:
            pass  # Network might already exist

    def generate_dockerfile(self, project_path: Path, app_type: str) -> str:
        """Generate appropriate Dockerfile for the app type."""
        if app_type == "react" or app_type == "vite":
            return """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        elif app_type == "flask" or app_type == "python":
            return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
"""
        elif app_type == "static" or app_type == "html":
            return """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        elif app_type == "node" or app_type == "express":
            return """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
"""
        else:
            # Default: static files with nginx
            return """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""

    def generate_docker_compose(
        self,
        project_id: str,
        project_path: Path,
        app_type: str,
        host_port: int,
        container_suffix: str = "",
    ) -> str:
        """Generate docker-compose.yml for the project.

        Args:
            project_id: The project ID
            project_path: Path to project files
            app_type: Type of application
            host_port: Host port to expose
            container_suffix: Optional suffix for container name (e.g., "preview")

        Returns:
            Docker Compose YAML content
        """
        suffix = f"-{container_suffix}" if container_suffix else ""
        container_name = f"druppie-app-{project_id[:8]}{suffix}"
        internal_port = APP_INTERNAL_PORTS.get(app_type, 80)
        is_preview = "preview" in container_suffix.lower() if container_suffix else False

        compose = f"""version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {container_name}
    ports:
      - "{host_port}:{internal_port}"
    networks:
      - {PROJECTS_NETWORK}
    restart: unless-stopped
    labels:
      - "druppie.project_id={project_id}"
      - "druppie.app_type={app_type}"
      - "druppie.internal_port={internal_port}"
      - "druppie.is_preview={str(is_preview).lower()}"

networks:
  {PROJECTS_NETWORK}:
    external: true
"""
        return compose

    def detect_app_type(self, project_path: Path) -> str:
        """Detect the type of application based on files."""
        # Check for package.json (Node.js)
        if (project_path / "package.json").exists():
            try:
                with open(project_path / "package.json") as f:
                    pkg = json.load(f)
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                    if "vite" in deps:
                        return "vite"
                    if "react" in deps:
                        return "react"
                    if "express" in deps:
                        return "express"
                    return "node"
            except Exception:
                return "node"

        # Check for Python
        if (project_path / "requirements.txt").exists():
            return "python"
        if (project_path / "app.py").exists():
            return "flask"
        if (project_path / "main.py").exists():
            return "python"

        # Check for static HTML
        if (project_path / "index.html").exists():
            return "static"

        return "static"

    def build_project(
        self,
        project_id: str,
        tag_suffix: str = "",
        port_range: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """Build a project's Docker image.

        Args:
            project_id: The project ID
            tag_suffix: Optional suffix for the image tag (e.g., "-preview")
            port_range: Optional custom port range (start, end)

        Returns:
            Dict with success status and build details
        """
        project_path = WORKSPACE_PATH / project_id

        if not project_path.exists():
            return {"success": False, "error": "Project not found"}

        # Detect app type
        app_type = self.detect_app_type(project_path)
        logger.info("Detected app type", project_id=project_id, app_type=app_type, tag_suffix=tag_suffix)

        # Generate Dockerfile if not exists
        dockerfile_path = project_path / "Dockerfile"
        if not dockerfile_path.exists():
            dockerfile = self.generate_dockerfile(project_path, app_type)
            dockerfile_path.write_text(dockerfile)
            logger.info("Generated Dockerfile", project_id=project_id)

        # Determine port allocation key (separate for preview builds)
        port_key = f"{project_id}{tag_suffix}" if tag_suffix else project_id

        # Allocate port via registry (use custom range for preview builds)
        if port_range:
            port = self._allocate_port_in_range(port_key, port_range[0], port_range[1])
        else:
            port = self._port_registry.allocate_port(port_key)

        # Generate docker-compose.yml (with suffix for preview)
        compose_file = f"docker-compose{tag_suffix}.yml" if tag_suffix else "docker-compose.yml"
        compose = self.generate_docker_compose(
            project_id,
            project_path,
            app_type,
            port,
            container_suffix=tag_suffix.replace("-", "") if tag_suffix else "",
        )
        compose_path = project_path / compose_file
        compose_path.write_text(compose)
        logger.info("Generated compose file", project_id=project_id, file=compose_file, port=port, app_type=app_type)

        # Build the image
        try:
            result = subprocess.run(
                ["docker-compose", "-f", compose_file, "build"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                logger.error("Build failed", stderr=result.stderr)
                return {
                    "success": False,
                    "error": f"Build failed: {result.stderr}",
                }

            logger.info("Build successful", project_id=project_id, tag_suffix=tag_suffix)
            return {
                "success": True,
                "app_type": app_type,
                "port": port,
                "compose_file": compose_file,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Build timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _allocate_port_in_range(self, key: str, start: int, end: int) -> int:
        """Allocate a port within a specific range."""
        # Check if already allocated
        if self._port_registry.redis:
            existing = self._port_registry.redis.hget(self._port_registry._port_key, key)
            if existing:
                return int(existing)

        # Find available port in range
        for port in range(start, end):
            if self._port_registry._is_port_available(port, key):
                self._port_registry._reserve_port(port, key)
                return port

        raise RuntimeError(f"No available ports in range {start}-{end}")

    def run_project(
        self,
        project_id: str,
        container_suffix: str = "",
        port_range: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """Run a project's Docker container.

        Args:
            project_id: The project ID
            container_suffix: Optional suffix for container name (e.g., "-preview")
            port_range: Optional custom port range (start, end)

        Returns:
            Dict with success status and run details including URL
        """
        project_path = WORKSPACE_PATH / project_id

        if not project_path.exists():
            return {"success": False, "error": "Project not found"}

        # Determine compose file to use
        tag_suffix = f"-{container_suffix}" if container_suffix else ""
        compose_file = f"docker-compose{tag_suffix}.yml" if container_suffix else "docker-compose.yml"

        # Build first if needed
        if not (project_path / compose_file).exists():
            build_result = self.build_project(
                project_id,
                tag_suffix=tag_suffix,
                port_range=port_range,
            )
            if not build_result.get("success"):
                return build_result

        suffix = f"-{container_suffix}" if container_suffix else ""
        container_name = f"druppie-app-{project_id[:8]}{suffix}"

        # Start the container
        try:
            result = subprocess.run(
                ["docker-compose", "-f", compose_file, "up", "-d", "--build"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=120,  # Longer timeout for build + start
            )

            if result.returncode != 0:
                logger.error("Failed to start container", stderr=result.stderr, stdout=result.stdout)
                return {
                    "success": False,
                    "error": f"Failed to start: {result.stderr or result.stdout}",
                }

            # Verify container is actually running
            time.sleep(2)  # Give container time to start
            verify_result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
            )

            if "Up" not in verify_result.stdout:
                # Container failed to start - get logs
                logs_result = subprocess.run(
                    ["docker", "logs", container_name, "--tail", "50"],
                    capture_output=True,
                    text=True,
                )
                logger.error("Container not running",
                            container=container_name,
                            status=verify_result.stdout,
                            logs=logs_result.stderr or logs_result.stdout)
                return {
                    "success": False,
                    "error": f"Container failed to start. Logs: {logs_result.stderr or logs_result.stdout}",
                }

            # Parse port from compose file using YAML parser
            compose_path = project_path / compose_file
            compose_content = compose_path.read_text()
            port = HOST_PORT_START  # Default

            try:
                compose_data = yaml.safe_load(compose_content)
                ports_list = compose_data.get("services", {}).get("app", {}).get("ports", [])
                if ports_list:
                    port_mapping = str(ports_list[0])
                    # Handle both "9000:80" and "9000:5000" formats
                    port = int(port_mapping.split(":")[0].strip('"'))
            except Exception as e:
                logger.warning("Failed to parse port from compose", error=str(e))
                # Fallback: get from port registry
                port_key = f"{project_id}{tag_suffix}" if tag_suffix else project_id
                registry_port = self._port_registry.get_project_port(port_key)
                if registry_port:
                    port = registry_port

            # Register running app with appropriate key
            app_key = f"{project_id}{suffix}" if suffix else project_id
            app = RunningApp(
                project_id=project_id,
                container_name=container_name,
                port=port,
            )
            self._running_apps[app_key] = app

            logger.info("Container started and verified", project_id=project_id, url=app.url, container_suffix=container_suffix)

            return {
                "success": True,
                "url": app.url,
                "container_name": container_name,
                "port": port,
                "is_preview": bool(container_suffix),
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Startup timed out (120s)"}
        except Exception as e:
            logger.error("Run project failed", project_id=project_id, error=str(e))
            return {"success": False, "error": str(e)}

    def stop_project(self, project_id: str) -> dict[str, Any]:
        """Stop a project's container."""
        project_path = WORKSPACE_PATH / project_id

        if not project_path.exists():
            return {"success": False, "error": "Project not found"}

        try:
            result = subprocess.run(
                ["docker-compose", "down"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Clean up tracking
            if project_id in self._running_apps:
                del self._running_apps[project_id]

            # Release port from registry
            self._port_registry.release_port(project_id)

            logger.info("Container stopped", project_id=project_id)

            return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_running_app(self, project_id: str) -> RunningApp | None:
        """Get info about a running app."""
        return self._running_apps.get(project_id)

    def list_running_apps(self) -> list[RunningApp]:
        """List all running apps."""
        # Sync with actual Docker containers
        try:
            result = subprocess.run(
                [
                    "docker", "ps",
                    "--filter", "label=druppie.project_id",
                    "--format", "{{.Names}}\t{{.Label \"druppie.project_id\"}}\t{{.Ports}}",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        container_name, project_id, ports = parts[0], parts[1], parts[2]

                        # Parse port from "0.0.0.0:9000->80/tcp" or "0.0.0.0:9000->5000/tcp"
                        port = HOST_PORT_START
                        if ":" in ports and "->" in ports:
                            port_str = ports.split(":")[1].split("->")[0]
                            try:
                                port = int(port_str)
                            except ValueError:
                                pass

                        if project_id not in self._running_apps:
                            self._running_apps[project_id] = RunningApp(
                                project_id=project_id,
                                container_name=container_name,
                                port=port,
                            )

        except Exception as e:
            logger.error("Failed to list containers", error=str(e))

        return list(self._running_apps.values())

    def get_project_status(self, project_id: str) -> dict[str, Any]:
        """Get the status of a project (built, running, etc.)."""
        project_path = WORKSPACE_PATH / project_id

        if not project_path.exists():
            return {"status": "not_found"}

        has_dockerfile = (project_path / "Dockerfile").exists()
        has_compose = (project_path / "docker-compose.yml").exists()
        is_running = project_id in self._running_apps

        if is_running:
            app = self._running_apps[project_id]
            return {
                "status": "running",
                "url": app.url,
                "port": app.port,
            }
        elif has_compose:
            return {"status": "built"}
        elif has_dockerfile:
            return {"status": "ready_to_build"}
        else:
            return {"status": "created"}


# Singleton instance
builder_service = BuilderService()
