"""Git MCP Server.

Provides git version control operations via MCP.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

from druppie.mcp.servers.base import MCPServerBase


class GitMCPServer(MCPServerBase):
    """MCP server for git operations."""

    def __init__(self, working_dir: str | None = None):
        self.working_dir = working_dir or os.getcwd()
        super().__init__()

    def _register_tools(self) -> None:
        """Register git tools."""
        self.tools = {
            "clone": self.clone,
            "init": self.init,
            "checkout": self.checkout,
            "commit": self.commit,
            "push": self.push,
            "pull": self.pull,
            "status": self.status,
            "add": self.add,
            "branch": self.branch,
            "log": self.log,
        }

    def _run_git(self, args: list[str], cwd: str | None = None) -> dict[str, Any]:
        """Run a git command and return the result."""
        cwd = cwd or self.working_dir
        cmd = ["git"] + args

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,
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

    def clone(
        self,
        repo_url: str,
        path: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Clone a git repository.

        Args:
            repo_url: Repository URL to clone
            path: Local path to clone to
            branch: Branch to checkout (optional)
        """
        args = ["clone"]
        if branch:
            args.extend(["-b", branch])
        args.extend([repo_url, path])

        result = self._run_git(args)
        if result["success"]:
            result["path"] = path
        return result

    def init(self, path: str) -> dict[str, Any]:
        """Initialize a new git repository.

        Args:
            path: Path to initialize repository in
        """
        # Create directory if it doesn't exist
        Path(path).mkdir(parents=True, exist_ok=True)

        result = self._run_git(["init"], cwd=path)
        if result["success"]:
            result["path"] = path
        return result

    def checkout(
        self,
        branch: str,
        create: bool = False,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Checkout or create a branch.

        Args:
            branch: Branch name
            create: Create the branch if it doesn't exist
            path: Repository path (optional)
        """
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
        """Commit staged changes.

        Args:
            message: Commit message
            path: Repository path (optional)
        """
        return self._run_git(["commit", "-m", message], cwd=path)

    def push(
        self,
        remote: str = "origin",
        branch: str | None = None,
        message: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Push commits to remote.

        Args:
            remote: Remote name (default: origin)
            branch: Branch to push
            message: Optional commit message (will commit first)
            path: Repository path (optional)
        """
        cwd = path or self.working_dir

        # If message provided, add and commit first
        if message:
            self._run_git(["add", "-A"], cwd=cwd)
            self._run_git(["commit", "-m", message], cwd=cwd)

        args = ["push", remote]
        if branch:
            args.append(branch)

        return self._run_git(args, cwd=cwd)

    def pull(
        self,
        remote: str = "origin",
        branch: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Pull from remote.

        Args:
            remote: Remote name (default: origin)
            branch: Branch to pull
            path: Repository path (optional)
        """
        args = ["pull", remote]
        if branch:
            args.append(branch)

        return self._run_git(args, cwd=path)

    def status(self, path: str | None = None) -> dict[str, Any]:
        """Get repository status.

        Args:
            path: Repository path (optional)
        """
        result = self._run_git(["status", "--porcelain"], cwd=path)
        if result["success"]:
            # Parse status output
            files = []
            for line in result["stdout"].split("\n"):
                if line:
                    status = line[:2].strip()
                    filename = line[3:]
                    files.append({"status": status, "file": filename})
            result["files"] = files
        return result

    def add(
        self,
        files: str | list[str] = ".",
        path: str | None = None,
    ) -> dict[str, Any]:
        """Add files to staging.

        Args:
            files: Files to add (default: all)
            path: Repository path (optional)
        """
        if isinstance(files, str):
            files = [files]

        return self._run_git(["add"] + files, cwd=path)

    def branch(
        self,
        name: str | None = None,
        delete: bool = False,
        path: str | None = None,
    ) -> dict[str, Any]:
        """List or manage branches.

        Args:
            name: Branch name (for create/delete)
            delete: Delete the branch
            path: Repository path (optional)
        """
        args = ["branch"]
        if name:
            if delete:
                args.extend(["-d", name])
            else:
                args.append(name)

        result = self._run_git(args, cwd=path)
        if result["success"] and not name:
            # Parse branch list
            branches = []
            current = None
            for line in result["stdout"].split("\n"):
                if line:
                    if line.startswith("*"):
                        current = line[2:].strip()
                        branches.append(current)
                    else:
                        branches.append(line.strip())
            result["branches"] = branches
            result["current"] = current
        return result

    def log(
        self,
        count: int = 10,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Get commit log.

        Args:
            count: Number of commits to show
            path: Repository path (optional)
        """
        result = self._run_git(
            ["log", f"-{count}", "--pretty=format:%H|%s|%an|%ad"],
            cwd=path,
        )
        if result["success"]:
            commits = []
            for line in result["stdout"].split("\n"):
                if line:
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1],
                            "author": parts[2],
                            "date": parts[3],
                        })
            result["commits"] = commits
        return result


def main():
    """Run the git MCP server."""
    server = GitMCPServer()
    server.run()


if __name__ == "__main__":
    main()
