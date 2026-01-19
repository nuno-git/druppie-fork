"""Shell MCP Server.

Provides shell command execution via MCP.
"""

import os
import subprocess
from typing import Any

from druppie.mcp.servers.base import MCPServerBase


class ShellMCPServer(MCPServerBase):
    """MCP server for shell command execution."""

    def __init__(self, working_dir: str | None = None):
        self.working_dir = working_dir or os.getcwd()
        super().__init__()

    def _register_tools(self) -> None:
        """Register shell tools."""
        self.tools = {
            "run": self.run,
            "which": self.which,
            "env": self.get_env,
        }

    def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300,
        shell: bool = True,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a shell command.

        Args:
            command: Command to execute
            cwd: Working directory
            timeout: Timeout in seconds
            shell: Run through shell
            env: Environment variables to set
        """
        cwd = cwd or self.working_dir

        # Merge with current environment
        run_env = dict(os.environ)
        if env:
            run_env.update(env)

        try:
            result = subprocess.run(
                command,
                shell=shell,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
                "command": command,
                "cwd": cwd,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "command": command,
                "cwd": cwd,
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "cwd": cwd,
                "returncode": -1,
            }

    def which(self, program: str) -> dict[str, Any]:
        """Find the path to a program.

        Args:
            program: Program name to find
        """
        result = self.run(f"which {program}")
        if result["success"]:
            result["path"] = result["stdout"]
        return result

    def get_env(self, var: str | None = None) -> dict[str, Any]:
        """Get environment variables.

        Args:
            var: Specific variable to get (optional, returns all if not specified)
        """
        if var:
            value = os.environ.get(var)
            return {
                "success": value is not None,
                "variable": var,
                "value": value,
            }
        else:
            return {
                "success": True,
                "environment": dict(os.environ),
            }


def main():
    """Run the Shell MCP server."""
    server = ShellMCPServer()
    server.run()


if __name__ == "__main__":
    main()
