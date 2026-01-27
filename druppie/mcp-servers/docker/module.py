"""Docker MCP Server - Business Logic Module.

Contains all business logic for Docker container operations.
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("docker-mcp")


class DockerModule:
    """Business logic module for Docker operations."""

    def __init__(self, workspace_root, docker_network, port_range_start, port_range_end):
        self.workspace_root = Path(workspace_root)
        self.docker_network = docker_network
        self.port_range_start = int(port_range_start)
        self.port_range_end = int(port_range_end)
        self.used_ports = set()
        self.workspaces = {}

    def get_used_host_ports(self) -> set[int]:
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

    def is_port_available(self, port: int) -> bool:
        """Check if a port is available for binding on the Docker host."""
        docker_ports = self.get_used_host_ports()
        if port in docker_ports:
            return False
        if port in self.used_ports:
            return False
        return True

    def get_next_port(self) -> int:
        """Get next available port from the configured range."""
        for port in range(self.port_range_start, self.port_range_end):
            if self.is_port_available(port):
                self.used_ports.add(port)
                logger.info("Auto-selected available port %d", port)
                return port
        raise RuntimeError(f"No available ports in range {self.port_range_start}-{self.port_range_end}")

    def release_port(self, port: int) -> None:
        """Release a port back to pool."""
        self.used_ports.discard(port)

    def resolve_workspace_path(self, workspace_id: str | None, workspace_path: str | None) -> Path | None:
        """Resolve workspace path from workspace_id or direct path."""
        if workspace_path:
            p = Path(workspace_path)
            if p.exists():
                return p
            p = self.workspace_root / workspace_path
            if p.exists():
                return p

        if workspace_id:
            if workspace_id in self.workspaces:
                return Path(self.workspaces[workspace_id]["path"])
            for user_dir in self.workspace_root.iterdir():
                if user_dir.is_dir():
                    for project_dir in user_dir.iterdir():
                        if project_dir.is_dir():
                            for session_dir in project_dir.iterdir():
                                if session_dir.is_dir():
                                    if workspace_id in str(session_dir):
                                        return session_dir

        return None

    def register_workspace(
        self,
        workspace_id: str,
        workspace_path: str,
        project_id: str | None = None,
        branch: str | None = None,
    ) -> dict:
        """Register a workspace for Docker operations."""
        self.workspaces[workspace_id] = {
            "path": workspace_path,
            "project_id": project_id,
            "branch": branch,
        }
        logger.info("Registered workspace %s at %s", workspace_id, workspace_path)
        return {"success": True, "workspace_id": workspace_id}

    def build(
        self,
        image_name: str,
        workspace_id: str | None = None,
        workspace_path: str | None = None,
        dockerfile: str = "Dockerfile",
        build_args: dict[str, str] | None = None,
    ) -> dict:
        """Build Docker image from workspace."""
        try:
            workspace = self.resolve_workspace_path(workspace_id, workspace_path)
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

            cmd = ["docker", "build", "-t", image_name, "-f", str(dockerfile_path)]

            if build_args:
                for key, value in build_args.items():
                    cmd.extend(["--build-arg", f"{key}={value}"])

            cmd.append(str(workspace))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
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

    def check_and_remove_existing_container(self, container_name: str) -> dict | None:
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

    def run(
        self,
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
        try:
            existing = self.check_and_remove_existing_container(container_name)
            if existing:
                logger.info("Removed existing container: %s", existing)

            requested_port = None
            if port_mapping:
                parts = port_mapping.split(":")
                requested_port = int(parts[0])
                container_port = int(parts[1]) if len(parts) > 1 else 3000
            else:
                requested_port = port

            if requested_port:
                if self.is_port_available(requested_port):
                    host_port = requested_port
                else:
                    logger.warning(
                        "Requested port %d is not available, auto-selecting alternative",
                        requested_port
                    )
                    host_port = self.get_next_port()
            else:
                host_port = self.get_next_port()

            logger.info(
                "Running container %s from image %s (port %d:%d)",
                container_name, image_name, host_port, container_port
            )

            cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--network", self.docker_network,
                "-p", f"{host_port}:{container_port}",
            ]

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
                self.release_port(host_port)
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

            if requested_port and host_port != requested_port:
                response["note"] = f"Port {requested_port} was busy, using {host_port} instead"

            return response

        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop(self, container_name: str, remove: bool = True) -> dict:
        """Stop a running container."""
        try:
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

    def logs(
        self,
        container_name: str,
        tail: int = 100,
        follow: bool = False,
    ) -> dict:
        """Get container logs."""
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

    def remove(self, container_name: str, force: bool = False) -> dict:
        """Remove a container."""
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

    def list_containers(self, all: bool = False) -> dict:
        """List Docker containers."""
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

    def inspect(self, container_name: str) -> dict:
        """Inspect a container."""
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr}

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

    def exec_command(
        self,
        container_name: str,
        command: str,
        workdir: str | None = None,
    ) -> dict:
        """Execute command in running container."""
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
