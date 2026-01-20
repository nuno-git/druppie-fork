"""Docker MCP Server.

Provides Docker container operations via MCP protocol.
"""

import subprocess
import json
from typing import Any

from .base import MCPServerBase


class DockerMCPServer(MCPServerBase):
    """MCP Server for Docker operations."""

    def __init__(self):
        super().__init__("docker", "Docker")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all Docker tools."""
        self.register_tool("build", self.build)
        self.register_tool("run", self.run_container)
        self.register_tool("stop", self.stop)
        self.register_tool("logs", self.logs)
        self.register_tool("ps", self.ps)
        self.register_tool("images", self.images)
        self.register_tool("rm", self.rm)
        self.register_tool("rmi", self.rmi)
        self.register_tool("exec", self.exec_cmd)
        self.register_tool("pull", self.pull)

    def _run_docker(self, args: list[str]) -> dict[str, Any]:
        """Run a docker command and return the result."""
        cmd = ["docker"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def build(
        self,
        path: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        build_args: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build a Docker image."""
        args = ["build", "-t", tag, "-f", dockerfile]
        if build_args:
            for key, value in build_args.items():
                args.extend(["--build-arg", f"{key}={value}"])
        args.append(path)
        return self._run_docker(args)

    def run_container(
        self,
        image: str,
        name: str | None = None,
        command: str | None = None,
        detach: bool = False,
        port: str | None = None,
        volumes: list[str] | None = None,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
        rm: bool = False,
    ) -> dict[str, Any]:
        """Run a Docker container."""
        args = ["run"]
        if detach:
            args.append("-d")
        if name:
            args.extend(["--name", name])
        if port:
            args.extend(["-p", port])
        if volumes:
            for vol in volumes:
                args.extend(["-v", vol])
        if env:
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])
        if workdir:
            args.extend(["-w", workdir])
        if rm:
            args.append("--rm")
        args.append(image)
        if command:
            args.extend(command.split())
        return self._run_docker(args)

    def stop(self, container: str, timeout: int = 10) -> dict[str, Any]:
        """Stop a running container."""
        return self._run_docker(["stop", "-t", str(timeout), container])

    def logs(
        self,
        container: str,
        tail: int = 100,
        follow: bool = False,
    ) -> dict[str, Any]:
        """Get container logs."""
        args = ["logs", "--tail", str(tail)]
        if follow:
            args.append("-f")
        args.append(container)
        return self._run_docker(args)

    def ps(self, all: bool = False) -> dict[str, Any]:
        """List containers."""
        args = ["ps", "--format", "json"]
        if all:
            args.append("-a")
        result = self._run_docker(args)
        if result["success"] and result.get("stdout"):
            # Parse JSON output
            try:
                containers = []
                for line in result["stdout"].strip().split("\n"):
                    if line:
                        containers.append(json.loads(line))
                result["containers"] = containers
            except json.JSONDecodeError:
                pass
        return result

    def images(self) -> dict[str, Any]:
        """List Docker images."""
        result = self._run_docker(["images", "--format", "json"])
        if result["success"] and result.get("stdout"):
            try:
                images = []
                for line in result["stdout"].strip().split("\n"):
                    if line:
                        images.append(json.loads(line))
                result["images"] = images
            except json.JSONDecodeError:
                pass
        return result

    def rm(self, container: str, force: bool = False) -> dict[str, Any]:
        """Remove a container."""
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container)
        return self._run_docker(args)

    def rmi(self, image: str, force: bool = False) -> dict[str, Any]:
        """Remove an image."""
        args = ["rmi"]
        if force:
            args.append("-f")
        args.append(image)
        return self._run_docker(args)

    def exec_cmd(
        self,
        container: str,
        command: str,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command in a running container."""
        args = ["exec"]
        if workdir:
            args.extend(["-w", workdir])
        args.append(container)
        args.extend(command.split())
        return self._run_docker(args)

    def pull(self, image: str) -> dict[str, Any]:
        """Pull a Docker image."""
        return self._run_docker(["pull", image])


def main():
    """Entry point for the Docker MCP server."""
    server = DockerMCPServer()
    server.run()


if __name__ == "__main__":
    main()
