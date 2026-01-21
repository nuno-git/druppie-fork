"""Builder Service - Builds and runs Docker applications.

Manages the lifecycle of user-created applications:
- Detects app type and generates Dockerfile
- Builds Docker images
- Runs containers with port allocation
- Manages preview vs production builds
"""

import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
import redis
import yaml
from sqlalchemy.orm import Session as DBSession

from druppie.db.models import Build, Project

logger = structlog.get_logger()

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace"))
PROJECTS_NETWORK = os.getenv("PROJECTS_NETWORK", "druppie-projects")
HOST_PORT_START = int(os.getenv("HOST_PORT_START", "9001"))
HOST_PORT_END = int(os.getenv("HOST_PORT_END", "9100"))
PREVIEW_PORT_START = int(os.getenv("PREVIEW_PORT_START", "9101"))
PREVIEW_PORT_END = int(os.getenv("PREVIEW_PORT_END", "9200"))
EXTERNAL_HOST = os.getenv("EXTERNAL_HOST", "localhost")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Internal ports for different app types (container port)
APP_INTERNAL_PORTS = {
    "flask": 5000,
    "python": 5000,
    "express": 3000,
    "node": 3000,
    "vite": 80,  # nginx serves built files
    "react": 80,  # nginx serves built files
    "static": 80,  # nginx serves static files
    "html": 80,  # nginx serves static files
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

    def allocate_port(self, key: str, is_preview: bool = False) -> int:
        """Allocate a port, reusing existing if already allocated.

        Args:
            key: Unique key for the allocation (e.g., project_id or build_id)
            is_preview: Use preview port range if True

        Returns:
            Allocated port number
        """
        # Check if already allocated
        if self.redis:
            existing = self.redis.hget(self._port_key, key)
            if existing:
                return int(existing)

        # Determine port range
        start = PREVIEW_PORT_START if is_preview else HOST_PORT_START
        end = PREVIEW_PORT_END if is_preview else HOST_PORT_END

        # Find available port
        for port in range(start, end):
            if self._is_port_available(port, key):
                self._reserve_port(port, key)
                return port

        raise RuntimeError(f"No available ports in range {start}-{end}")

    def _is_port_available(self, port: int, key: str) -> bool:
        """Check if a port is available."""
        # Check Redis registry
        if self.redis:
            owner = self.redis.hget(self._port_key, f"port:{port}")
            if owner and owner != key:
                return False

        # Check actual Docker containers
        result = subprocess.run(
            ["docker", "ps", "--filter", f"publish={port}", "-q"],
            capture_output=True,
            text=True,
        )
        return not result.stdout.strip()

    def _reserve_port(self, port: int, key: str):
        """Reserve a port."""
        if self.redis:
            self.redis.hset(self._port_key, key, port)
            self.redis.hset(self._port_key, f"port:{port}", key)
            logger.info("port_allocated", key=key, port=port)

    def release_port(self, key: str):
        """Release a port allocation."""
        if self.redis:
            port = self.redis.hget(self._port_key, key)
            if port:
                self.redis.hdel(self._port_key, key)
                self.redis.hdel(self._port_key, f"port:{port}")
                logger.info("port_released", key=key, port=port)

    def get_port(self, key: str) -> int | None:
        """Get the allocated port for a key."""
        if self.redis:
            port = self.redis.hget(self._port_key, key)
            if port:
                return int(port)
        return None


class BuilderService:
    """Service for building and running Docker applications."""

    def __init__(self, db: DBSession):
        self.db = db
        self._port_registry = PortRegistry()
        self._ensure_network()

    def _ensure_network(self):
        """Ensure the projects network exists."""
        try:
            subprocess.run(
                ["docker", "network", "create", PROJECTS_NETWORK],
                capture_output=True,
            )
        except Exception:
            pass  # Network might already exist

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

    def generate_dockerfile(self, project_path: Path, app_type: str) -> str:
        """Generate appropriate Dockerfile for the app type."""
        dockerfiles = {
            "react": """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            "vite": """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            "flask": """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
""",
            "python": """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
""",
            "node": """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
""",
            "express": """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
""",
            "static": """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
            "html": """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
        }

        return dockerfiles.get(app_type, dockerfiles["static"])

    def generate_docker_compose(
        self,
        project_id: str,
        app_type: str,
        host_port: int,
        is_preview: bool = False,
    ) -> str:
        """Generate docker-compose.yml for the project."""
        suffix = "-preview" if is_preview else ""
        container_name = f"druppie-app-{project_id[:8]}{suffix}"
        internal_port = APP_INTERNAL_PORTS.get(app_type, 80)

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

    async def build_project(
        self,
        project_id: str,
        branch: str = "main",
        is_preview: bool = False,
    ) -> Build:
        """Build Docker image for project branch.

        Args:
            project_id: Project ID
            branch: Branch to build
            is_preview: Whether this is a preview build

        Returns:
            Build instance
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        # Determine project path - look for workspace or use project name
        project_path = None
        for session_dir in WORKSPACE_ROOT.iterdir():
            if session_dir.is_dir():
                # Check if this workspace has the project
                git_config = session_dir / ".git" / "config"
                if git_config.exists():
                    config_text = git_config.read_text()
                    if project.repo_name in config_text:
                        project_path = session_dir
                        break

        if not project_path:
            # Try direct project path
            project_path = WORKSPACE_ROOT / project.repo_name
            if not project_path.exists():
                raise ValueError(f"Project workspace not found for: {project.name}")

        # Create build record
        build_id = str(uuid.uuid4())
        build = Build(
            id=build_id,
            project_id=project_id,
            branch=branch,
            status="building",
            is_preview=is_preview,
        )
        self.db.add(build)
        self.db.commit()

        try:
            # Detect app type
            app_type = self.detect_app_type(project_path)
            logger.info("detected_app_type", project_id=project_id, app_type=app_type)

            # Generate Dockerfile if not exists
            dockerfile_path = project_path / "Dockerfile"
            if not dockerfile_path.exists():
                dockerfile = self.generate_dockerfile(project_path, app_type)
                dockerfile_path.write_text(dockerfile)
                logger.info("generated_dockerfile", project_id=project_id)

            # Allocate port
            port = self._port_registry.allocate_port(build_id, is_preview=is_preview)
            build.port = port

            # Generate docker-compose.yml
            compose_file = "docker-compose.preview.yml" if is_preview else "docker-compose.yml"
            compose = self.generate_docker_compose(
                project_id,
                app_type,
                port,
                is_preview=is_preview,
            )
            (project_path / compose_file).write_text(compose)
            logger.info("generated_compose", project_id=project_id, file=compose_file, port=port)

            # Build the image
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker-compose", "-f", compose_file, "build"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                build.status = "failed"
                build.build_logs = result.stderr
                self.db.commit()
                logger.error("build_failed", project_id=project_id, stderr=result.stderr[:500])
                return build

            build.status = "built"
            build.container_name = f"druppie-app-{project_id[:8]}{'-preview' if is_preview else ''}"
            self.db.commit()

            logger.info("build_successful", build_id=build_id, project_id=project_id)
            return build

        except subprocess.TimeoutExpired:
            build.status = "failed"
            build.build_logs = "Build timed out"
            self.db.commit()
            raise
        except Exception as e:
            build.status = "failed"
            build.build_logs = str(e)
            self.db.commit()
            raise

    async def run_project(self, build_id: str) -> Build:
        """Run Docker container from build.

        Args:
            build_id: Build ID to run

        Returns:
            Updated Build instance
        """
        build = self.db.query(Build).filter(Build.id == build_id).first()
        if not build:
            raise ValueError(f"Build not found: {build_id}")

        project = self.db.query(Project).filter(Project.id == build.project_id).first()
        if not project:
            raise ValueError(f"Project not found: {build.project_id}")

        # Find project path
        project_path = None
        for session_dir in WORKSPACE_ROOT.iterdir():
            if session_dir.is_dir():
                git_config = session_dir / ".git" / "config"
                if git_config.exists():
                    config_text = git_config.read_text()
                    if project.repo_name in config_text:
                        project_path = session_dir
                        break

        if not project_path:
            project_path = WORKSPACE_ROOT / project.repo_name
            if not project_path.exists():
                raise ValueError(f"Project workspace not found: {project.name}")

        compose_file = "docker-compose.preview.yml" if build.is_preview else "docker-compose.yml"

        # Start the container
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker-compose", "-f", compose_file, "up", "-d"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                build.status = "failed"
                build.build_logs = result.stderr
                self.db.commit()
                logger.error("run_failed", build_id=build_id, stderr=result.stderr[:500])
                return build

            # Verify container is running
            await asyncio.sleep(2)
            verify_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "ps", "--filter", f"name={build.container_name}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
            )

            if "Up" not in verify_result.stdout:
                build.status = "failed"
                # Get container logs
                logs_result = subprocess.run(
                    ["docker", "logs", build.container_name, "--tail", "50"],
                    capture_output=True,
                    text=True,
                )
                build.build_logs = logs_result.stderr or logs_result.stdout
                self.db.commit()
                logger.error("container_not_running", build_id=build_id)
                return build

            build.status = "running"
            build.app_url = f"http://{EXTERNAL_HOST}:{build.port}"
            self.db.commit()

            logger.info("project_running", build_id=build_id, url=build.app_url)
            return build

        except subprocess.TimeoutExpired:
            build.status = "failed"
            build.build_logs = "Startup timed out"
            self.db.commit()
            raise

    async def stop_project(self, build_id: str) -> bool:
        """Stop a running container.

        Args:
            build_id: Build ID to stop

        Returns:
            True if successful
        """
        build = self.db.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.warning("build_not_found", build_id=build_id)
            return False

        project = self.db.query(Project).filter(Project.id == build.project_id).first()
        if not project:
            return False

        # Find project path
        project_path = None
        for session_dir in WORKSPACE_ROOT.iterdir():
            if session_dir.is_dir():
                git_config = session_dir / ".git" / "config"
                if git_config.exists():
                    config_text = git_config.read_text()
                    if project.repo_name in config_text:
                        project_path = session_dir
                        break

        if not project_path:
            project_path = WORKSPACE_ROOT / project.repo_name

        compose_file = "docker-compose.preview.yml" if build.is_preview else "docker-compose.yml"

        try:
            if project_path.exists() and (project_path / compose_file).exists():
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker-compose", "-f", compose_file, "down"],
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            else:
                # Fallback: stop container directly
                if build.container_name:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "stop", build.container_name],
                        capture_output=True,
                        timeout=30,
                    )

            # Release port
            self._port_registry.release_port(build_id)

            build.status = "stopped"
            self.db.commit()

            logger.info("project_stopped", build_id=build_id)
            return True

        except Exception as e:
            logger.error("stop_failed", build_id=build_id, error=str(e))
            return False

    def get_build(self, build_id: str) -> Build | None:
        """Get build by ID."""
        return self.db.query(Build).filter(Build.id == build_id).first()

    def get_builds_for_project(self, project_id: str) -> list[Build]:
        """Get all builds for a project."""
        return (
            self.db.query(Build)
            .filter(Build.project_id == project_id)
            .order_by(Build.created_at.desc())
            .all()
        )

    def get_main_build(self, project_id: str) -> Build | None:
        """Get the main (non-preview) running build for a project."""
        return (
            self.db.query(Build)
            .filter(
                Build.project_id == project_id,
                Build.is_preview == False,
                Build.status == "running",
            )
            .first()
        )

    def get_preview_builds(self, project_id: str) -> list[Build]:
        """Get all preview builds for a project."""
        return (
            self.db.query(Build)
            .filter(
                Build.project_id == project_id,
                Build.is_preview == True,
            )
            .order_by(Build.created_at.desc())
            .all()
        )


def get_builder_service(db: DBSession) -> BuilderService:
    """Get a BuilderService instance for the given DB session."""
    return BuilderService(db)
