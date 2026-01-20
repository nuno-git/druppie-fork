"""Git MCP Server.

Provides Git version control operations via MCP protocol.
"""

import os
import subprocess
from typing import Any

from .base import MCPServerBase


class GitMCPServer(MCPServerBase):
    """MCP Server for Git operations."""

    def __init__(self):
        super().__init__("git", "Git")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all Git tools."""
        self.register_tool("clone", self.clone)
        self.register_tool("init", self.init)
        self.register_tool("checkout", self.checkout)
        self.register_tool("commit", self.commit)
        self.register_tool("push", self.push)
        self.register_tool("pull", self.pull_repo)
        self.register_tool("status", self.status)
        self.register_tool("add", self.add)
        self.register_tool("branch", self.branch)
        self.register_tool("log", self.log)

    def _run_git(self, args: list[str], cwd: str | None = None) -> dict[str, Any]:
        """Run a git command and return the result."""
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                cwd=cwd,
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

    def clone(
        self,
        repo_url: str,
        path: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Clone a git repository."""
        args = ["clone"]
        if branch:
            args.extend(["-b", branch])
        args.extend([repo_url, path])
        return self._run_git(args)

    def init(self, path: str) -> dict[str, Any]:
        """Initialize a new git repository."""
        os.makedirs(path, exist_ok=True)
        return self._run_git(["init"], cwd=path)

    def checkout(
        self,
        branch: str,
        create: bool = False,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Checkout or create a branch."""
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        return self._run_git(args, cwd=path)

    def commit(
        self,
        message: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Commit staged changes."""
        return self._run_git(["commit", "-m", message], cwd=path)

    def push(
        self,
        branch: str,
        remote: str = "origin",
        message: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Push commits to remote.

        If message is provided, will commit first.
        """
        results = []

        # Optionally commit first
        if message:
            add_result = self._run_git(["add", "."], cwd=path)
            results.append({"add": add_result})

            commit_result = self._run_git(["commit", "-m", message], cwd=path)
            results.append({"commit": commit_result})

        # Push
        push_result = self._run_git(["push", "-u", remote, branch], cwd=path)
        results.append({"push": push_result})

        return {
            "success": push_result["success"],
            "operations": results,
        }

    def pull_repo(
        self,
        remote: str = "origin",
        branch: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Pull from remote."""
        args = ["pull", remote]
        if branch:
            args.append(branch)
        return self._run_git(args, cwd=path)

    def status(self, path: str | None = None) -> dict[str, Any]:
        """Get repository status."""
        result = self._run_git(["status", "--porcelain"], cwd=path)
        if result["success"]:
            # Parse status output
            files = []
            for line in result["stdout"].strip().split("\n"):
                if line:
                    status = line[:2].strip()
                    filename = line[3:]
                    files.append({"status": status, "file": filename})
            result["files"] = files
        return result

    def add(
        self,
        files: str = ".",
        path: str | None = None,
    ) -> dict[str, Any]:
        """Add files to staging."""
        return self._run_git(["add", files], cwd=path)

    def branch(
        self,
        name: str | None = None,
        delete: bool = False,
        path: str | None = None,
    ) -> dict[str, Any]:
        """List or manage branches."""
        args = ["branch"]
        if delete and name:
            args.extend(["-d", name])
        elif name:
            args.append(name)
        return self._run_git(args, cwd=path)

    def log(
        self,
        count: int = 10,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Get commit log."""
        result = self._run_git(
            ["log", f"-{count}", "--oneline", "--format=%H|%s|%an|%ai"],
            cwd=path,
        )
        if result["success"]:
            commits = []
            for line in result["stdout"].strip().split("\n"):
                if line:
                    parts = line.split("|")
                    if len(parts) >= 4:
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1],
                            "author": parts[2],
                            "date": parts[3],
                        })
            result["commits"] = commits
        return result


def main():
    """Entry point for the Git MCP server."""
    server = GitMCPServer()
    server.run()


if __name__ == "__main__":
    main()
