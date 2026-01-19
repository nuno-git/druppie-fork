"""Docker MCP Server.

Provides Docker container operations via MCP.
"""

import json
import subprocess
from typing import Any

from druppie.mcp.servers.base import MCPServerBase


class DockerMCPServer(MCPServerBase):
    """MCP server for Docker operations."""

    def _register_tools(self) -> None:
        """Register Docker tools."""
        self.tools = {
            "build": self.build,
            "run": self.run,
            "stop": self.stop,
            "logs": self.logs,
            "ps": self.ps,
            "images": self.images,
            "rm": self.rm,
            "rmi": self.rmi,
            "exec": self.exec,
            "pull": self.pull,
        }

    def _run_docker(self, args: list[str], timeout: int = 600) -> dict[str, Any]:
        """Run a docker command and return the result."""
        cmd = ["docker"] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "returncode": -1,
            }

    def build(
        self,
        path: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        build_args: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build a Docker image.

        Args:
            path: Path to build context
            tag: Image tag
            dockerfile: Dockerfile name
            build_args: Build arguments
        """
        args = ["build", "-t", tag, "-f", f"{path}/{dockerfile}"]

        if build_args:
            for key, value in build_args.items():
                args.extend(["--build-arg", f"{key}={value}"])

        args.append(path)

        result = self._run_docker(args, timeout=1800)  # 30 min for builds
        if result["success"]:
            result["image"] = tag
        return result

    def run(
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
        """Run a container.

        Args:
            image: Image to run
            name: Container name
            command: Command to run
            detach: Run in background
            port: Port mapping (e.g., "8080:8080")
            volumes: Volume mounts
            env: Environment variables
            workdir: Working directory
            rm: Remove container after exit
        """
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

        result = self._run_docker(args)
        if result["success"] and detach:
            result["container_id"] = result["stdout"]
        return result

    def stop(self, container: str, timeout: int = 10) -> dict[str, Any]:
        """Stop a running container.

        Args:
            container: Container ID or name
            timeout: Seconds to wait before killing
        """
        return self._run_docker(["stop", "-t", str(timeout), container])

    def logs(
        self,
        container: str,
        tail: int = 100,
        follow: bool = False,
    ) -> dict[str, Any]:
        """Get container logs.

        Args:
            container: Container ID or name
            tail: Number of lines to show
            follow: Follow log output
        """
        args = ["logs", "--tail", str(tail)]
        if follow:
            args.append("-f")
        args.append(container)

        return self._run_docker(args)

    def ps(self, all: bool = False) -> dict[str, Any]:
        """List containers.

        Args:
            all: Show all containers (including stopped)
        """
        args = ["ps", "--format", "{{json .}}"]
        if all:
            args.insert(1, "-a")

        result = self._run_docker(args)
        if result["success"]:
            containers = []
            for line in result["stdout"].split("\n"):
                if line:
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            result["containers"] = containers
        return result

    def images(self) -> dict[str, Any]:
        """List images."""
        result = self._run_docker(["images", "--format", "{{json .}}"])
        if result["success"]:
            images = []
            for line in result["stdout"].split("\n"):
                if line:
                    try:
                        images.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            result["images"] = images
        return result

    def rm(self, container: str, force: bool = False) -> dict[str, Any]:
        """Remove a container.

        Args:
            container: Container ID or name
            force: Force removal
        """
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container)

        return self._run_docker(args)

    def rmi(self, image: str, force: bool = False) -> dict[str, Any]:
        """Remove an image.

        Args:
            image: Image ID or tag
            force: Force removal
        """
        args = ["rmi"]
        if force:
            args.append("-f")
        args.append(image)

        return self._run_docker(args)

    def exec(
        self,
        container: str,
        command: str,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command in a running container.

        Args:
            container: Container ID or name
            command: Command to execute
            workdir: Working directory
        """
        args = ["exec"]
        if workdir:
            args.extend(["-w", workdir])
        args.append(container)
        args.extend(command.split())

        return self._run_docker(args)

    def pull(self, image: str) -> dict[str, Any]:
        """Pull an image.

        Args:
            image: Image to pull
        """
        return self._run_docker(["pull", image], timeout=1800)


def main():
    """Run the Docker MCP server."""
    server = DockerMCPServer()
    server.run()


if __name__ == "__main__":
    main()
