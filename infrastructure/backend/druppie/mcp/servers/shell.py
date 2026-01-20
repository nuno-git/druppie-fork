"""Shell MCP Server.

Provides shell command execution via MCP protocol.
"""

import subprocess
import os
from typing import Any

from .base import MCPServerBase


class ShellMCPServer(MCPServerBase):
    """MCP Server for shell operations."""

    def __init__(self):
        super().__init__("shell", "Shell")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all shell tools."""
        self.register_tool("run", self.run_command)
        self.register_tool("run_script", self.run_script)
        self.register_tool("which", self.which)
        self.register_tool("env", self.get_env)

    def run_command(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        """Run a shell command."""
        try:
            # Merge environment variables
            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=full_env,
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
                "error": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def run_script(
        self,
        script: str,
        interpreter: str = "/bin/bash",
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run a multi-line script."""
        try:
            # Merge environment variables
            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            result = subprocess.run(
                [interpreter],
                input=script,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=full_env,
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
                "error": f"Script timed out after {timeout} seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


    def which(self, program: str) -> dict[str, Any]:
        """Find the path to a program."""
        try:
            result = subprocess.run(
                ["which", program],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {
                "success": result.returncode == 0,
                "path": result.stdout.strip() if result.returncode == 0 else None,
                "found": result.returncode == 0,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_env(self, var: str | None = None) -> dict[str, Any]:
        """Get environment variables."""
        try:
            if var:
                value = os.environ.get(var)
                return {
                    "success": True,
                    "var": var,
                    "value": value,
                    "found": value is not None,
                }
            else:
                return {
                    "success": True,
                    "env": dict(os.environ),
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


def main():
    """Entry point for the Shell MCP server."""
    server = ShellMCPServer()
    server.run()


if __name__ == "__main__":
    main()
