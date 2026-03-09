"""Coding MCP Server - Business Logic Module.

Contains all business logic for file operations, git operations,
test execution, and workspace management.
"""

import json
import logging
import re
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("coding-mcp")

# =============================================================================
# SECURITY: COMMAND BLOCKLIST
# =============================================================================

BLOCKED_COMMAND_PATTERNS = [
    r"rm\s+(-[rf]+\s+)*\s*/\s*$",
    r"rm\s+(-[rf]+\s+)*\s*/\*",
    r"rm\s+(-[rf]+\s+)+\s*/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bsudo\b",
    r"\bsu\s+-",
    r"\bsu\s+root",
    r"\bchmod\s+777\b",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+.*\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[0-6]",
    r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|network)",
    r":\(\)\s*{\s*:\|\s*:&\s*}\s*;",
    r">\s*/dev/sd[a-z]",
    r">\s*/dev/null\s*2>&1\s*&",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
    r">\s*/etc/sudoers",
    r"\bnc\s+-[elp]",
    r"\bbash\s+-i\s+>&\s+/dev/tcp",
    r"\bcurl\s+.*\|\s*bash",
    r"\bwget\s+.*\|\s*bash",
    r"\bcurl\s+.*\|\s*sh",
    r"\bwget\s+.*\|\s*sh",
]

BLOCKED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_COMMAND_PATTERNS]


class CodingModule:
    """Business logic module for coding operations."""

    def __init__(self, workspace_root, gitea_url, gitea_org, gitea_token, gitea_user, gitea_password):
        self.workspace_root = Path(workspace_root)
        self.gitea_url = gitea_url
        self.gitea_org = gitea_org
        self.gitea_token = gitea_token
        self.gitea_user = gitea_user
        self.gitea_password = gitea_password
        self.workspaces = {}

    def is_command_blocked(self, command: str) -> tuple[bool, str | None]:
        """Check if a command matches any blocked patterns."""
        for i, pattern in enumerate(BLOCKED_PATTERNS_COMPILED):
            if pattern.search(command):
                return True, BLOCKED_COMMAND_PATTERNS[i]
        return False, None

    def get_gitea_clone_url(self, repo_name: str, repo_owner: str | None = None) -> str:
        """Get Gitea clone URL with embedded credentials."""
        owner = repo_owner or self.gitea_org
        if self.gitea_user and self.gitea_password:
            if "://" in self.gitea_url:
                from urllib.parse import quote
                protocol, rest = self.gitea_url.split("://", 1)
                return f"{protocol}://{quote(self.gitea_user)}:{quote(self.gitea_password)}@{rest}/{owner}/{repo_name}.git"
        return f"{self.gitea_url}/{owner}/{repo_name}.git"

    def is_gitea_configured(self) -> bool:
        """Check if Gitea is configured with credentials."""
        return bool(self.gitea_token or (self.gitea_user and self.gitea_password))

    async def create_gitea_repo(self, repo_name: str, description: str) -> dict:
        """Create repository in Gitea."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.gitea_url}/api/v1/orgs/{self.gitea_org}/repos",
                    json={
                        "name": repo_name,
                        "description": description,
                        "private": False,
                        "auto_init": True,
                    },
                    headers={"Authorization": f"token {self.gitea_token}"},
                    timeout=30,
                )
                if response.status_code in (200, 201):
                    return response.json()
                else:
                    return {"error": response.text, "status_code": response.status_code}
            except Exception as e:
                return {"error": str(e)}

    def register_workspace(
        self,
        workspace_id: str,
        workspace_path: str,
        project_id: str,
        branch: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Register an existing workspace."""
        path = Path(workspace_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"Workspace path does not exist: {workspace_path}",
            }

        self.workspaces[workspace_id] = {
            "path": str(path),
            "project_id": project_id,
            "branch": branch,
            "user_id": user_id,
            "session_id": session_id,
        }

        return {
            "success": True,
            "workspace_id": workspace_id,
            "workspace_path": str(path),
            "message": f"Workspace registered: {workspace_id}",
        }

    async def initialize_workspace(
        self,
        user_id: str,
        session_id: str,
        project_id: str | None = None,
        project_name: str | None = None,
    ) -> dict:
        """Initialize workspace for a conversation."""
        workspace_id = f"{user_id}-{session_id}"

        if project_id is None:
            project_id = str(uuid.uuid4())
            repo_name = f"project-{project_id[:8]}"
            if self.gitea_token:
                await self.create_gitea_repo(repo_name, project_name or "New Project")
            branch = "main"
        else:
            repo_name = f"project-{project_id[:8]}"
            branch = f"session-{session_id[:8]}"

        workspace_path = self.workspace_root / user_id / project_id / session_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        if self.is_gitea_configured():
            repo_url = self.get_gitea_clone_url(repo_name)
            try:
                subprocess.run(
                    ["git", "clone", repo_url, str(workspace_path)],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
            except subprocess.CalledProcessError:
                subprocess.run(["git", "init"], cwd=workspace_path, check=True)
                subprocess.run(
                    ["git", "remote", "add", "origin", repo_url],
                    cwd=workspace_path,
                    check=True,
                )

            if branch != "main":
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    cwd=workspace_path,
                    check=True,
                )
        else:
            subprocess.run(["git", "init"], cwd=workspace_path, check=True)

        self.workspaces[workspace_id] = {
            "path": str(workspace_path),
            "project_id": project_id,
            "branch": branch,
            "repo_name": repo_name,
            "user_id": user_id,
            "session_id": session_id,
        }

        return {
            "success": True,
            "workspace_id": workspace_id,
            "workspace_path": str(workspace_path),
            "project_id": project_id,
            "branch": branch,
        }

    def get_workspace(self, workspace_id: str) -> dict:
        """Get workspace by ID."""
        if workspace_id not in self.workspaces:
            raise ValueError(f"Workspace not found: {workspace_id}")
        return self.workspaces[workspace_id]

    def resolve_path(self, path: str, workspace_path: Path) -> Path:
        """Resolve a path relative to workspace root."""
        p = Path(path)

        if p.is_absolute():
            try:
                p.relative_to(workspace_path)
                return p
            except ValueError:
                return workspace_path / p.name

        resolved = (workspace_path / p).resolve()

        try:
            resolved.relative_to(workspace_path.resolve())
        except ValueError:
            raise ValueError(f"Path traversal not allowed: {path}")

        return resolved

    def read_file(self, workspace_id: str, path: str) -> dict:
        """Read file from workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            file_path = self.resolve_path(path, workspace_path)

            logger.info("Reading file in workspace %s: %s", workspace_id, path)

            if not file_path.exists():
                logger.debug("File not found in workspace %s: %s", workspace_id, path)
                return {"success": False, "error": f"File not found: {path}"}

            if not file_path.is_file():
                return {"success": False, "error": f"Not a file: {path}"}

            size = file_path.stat().st_size
            if size > 10 * 1024 * 1024:
                logger.warning(
                    "File too large in workspace %s: %s (%d bytes)",
                    workspace_id,
                    path,
                    size,
                )
                return {"success": False, "error": f"File too large: {size} bytes"}

            try:
                content = file_path.read_text(encoding="utf-8")
                logger.debug(
                    "Successfully read file in workspace %s: %s (%d bytes)",
                    workspace_id,
                    path,
                    size,
                )
                return {
                    "success": True,
                    "content": content,
                    "path": str(file_path.relative_to(workspace_path)),
                    "size": size,
                }
            except UnicodeDecodeError:
                logger.debug(
                    "Binary file detected in workspace %s: %s",
                    workspace_id,
                    path,
                )
                return {
                    "success": True,
                    "binary": True,
                    "path": str(file_path.relative_to(workspace_path)),
                    "size": size,
                    "message": "File is binary",
                }

        except ValueError as e:
            logger.warning(
                "Path resolution error in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(
                "Error reading file in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}

    async def write_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
        auto_commit: bool = True,
        commit_message: str | None = None,
    ) -> dict:
        """Write file to workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            file_path = self.resolve_path(path, workspace_path)

            logger.info(
                "Writing file in workspace %s: %s (%d bytes)",
                workspace_id,
                path,
                len(content),
            )

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            logger.debug(
                "Successfully wrote file in workspace %s: %s",
                workspace_id,
                path,
            )

            result = {
                "success": True,
                "path": str(file_path.relative_to(workspace_path)),
                "size": len(content),
            }

            if auto_commit:
                commit_result = await self._do_commit_and_push(
                    workspace_id,
                    commit_message or f"Update {path}",
                )
                result["committed"] = commit_result.get("success", False)
                if commit_result.get("success"):
                    result["commit_message"] = commit_message or f"Update {path}"

            return result

        except ValueError as e:
            logger.warning(
                "Path resolution error writing file in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(
                "Error writing file in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}

    def list_dir(
        self,
        workspace_id: str,
        path: str = ".",
        recursive: bool = False,
    ) -> dict:
        """List directory contents."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            dir_path = self.resolve_path(path, workspace_path)

            if not dir_path.exists():
                return {"success": False, "error": f"Directory not found: {path}"}

            if not dir_path.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            files = []
            directories = []

            if recursive:
                for item in dir_path.rglob("*"):
                    if item.name.startswith(".git"):
                        continue
                    if item.is_file():
                        files.append({
                            "name": item.name,
                            "path": str(item.relative_to(workspace_path)),
                            "type": "file",
                            "size": item.stat().st_size,
                        })
                    elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                        directories.append({
                            "name": item.name,
                            "path": str(item.relative_to(workspace_path)),
                            "type": "directory",
                        })
            else:
                for item in dir_path.iterdir():
                    if item.name.startswith(".git"):
                        continue
                    if item.is_file():
                        files.append({
                            "name": item.name,
                            "path": str(item.relative_to(workspace_path)),
                            "type": "file",
                            "size": item.stat().st_size,
                        })
                    elif item.is_dir() and item.name not in ["__pycache__", "node_modules"]:
                        directories.append({
                            "name": item.name,
                            "path": str(item.relative_to(workspace_path)),
                            "type": "directory",
                        })

            return {
                "success": True,
                "path": str(dir_path.relative_to(workspace_path)) if dir_path != workspace_path else ".",
                "files": files,
                "directories": directories,
                "count": len(files) + len(directories),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_file(
        self,
        workspace_id: str,
        path: str,
        auto_commit: bool = True,
    ) -> dict:
        """Delete file from workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = Path(ws["path"])
            file_path = self.resolve_path(path, workspace_path)

            logger.info("Deleting file in workspace %s: %s", workspace_id, path)

            if not file_path.exists():
                logger.debug("File not found for deletion in workspace %s: %s", workspace_id, path)
                return {"success": False, "error": f"File not found: {path}"}

            if file_path.is_dir():
                return {"success": False, "error": f"Path is a directory: {path}"}

            file_path.unlink()

            logger.info("Successfully deleted file in workspace %s: %s", workspace_id, path)

            result = {
                "success": True,
                "deleted": str(file_path.relative_to(workspace_path)),
            }

            if auto_commit:
                commit_result = await self._do_commit_and_push(workspace_id, f"Delete {path}")
                result["committed"] = commit_result.get("success", False)

            return result

        except ValueError as e:
            logger.warning(
                "Path resolution error deleting file in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(
                "Error deleting file in workspace %s: %s - %s",
                workspace_id,
                path,
                str(e),
            )
            return {"success": False, "error": str(e)}

    def run_command(
        self,
        workspace_id: str,
        command: str,
        timeout: int = 60,
    ) -> dict:
        """Execute shell command in workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = ws["path"]

            is_blocked, matched_pattern = self.is_command_blocked(command)
            if is_blocked:
                logger.warning(
                    "Blocked dangerous command in workspace %s: %s (matched pattern: %s)",
                    workspace_id,
                    command,
                    matched_pattern,
                )
                return {
                    "success": False,
                    "error": "Command blocked for security reasons",
                    "blocked": True,
                    "reason": "This command matches a dangerous pattern and cannot be executed",
                }

            logger.info(
                "Executing command in workspace %s: %s",
                workspace_id,
                command[:200] + "..." if len(command) > 200 else command,
            )

            result = subprocess.run(
                command,
                shell=True,
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            logger.info(
                "Command completed in workspace %s with return code %d",
                workspace_id,
                result.returncode,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "cwd": workspace_path,
            }

        except subprocess.TimeoutExpired:
            logger.warning(
                "Command timed out after %ds in workspace %s: %s",
                timeout,
                workspace_id,
                command[:100],
            )
            return {"success": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            logger.error(
                "Command execution failed in workspace %s: %s",
                workspace_id,
                str(e),
            )
            return {"success": False, "error": str(e)}

    async def _do_commit_and_push(self, workspace_id: str, message: str) -> dict:
        """Internal function to commit all changes and push to Gitea."""
        try:
            ws = self.get_workspace(workspace_id)
            cwd = ws["path"]
            branch = ws["branch"]

            subprocess.run(
                ["git", "config", "user.email", "agent@druppie.local"],
                cwd=cwd,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Druppie Agent"],
                cwd=cwd,
                check=False,
            )

            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)

            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )

            if not result.stdout.strip():
                return {"success": True, "message": "No changes to commit"}

            subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)

            if self.is_gitea_configured():
                try:
                    repo_name = ws.get("repo_name")
                    if repo_name:
                        auth_url = self.get_gitea_clone_url(repo_name)
                        subprocess.run(
                            ["git", "remote", "set-url", "origin", auth_url],
                            cwd=cwd,
                            check=True,
                            capture_output=True,
                        )

                    subprocess.run(
                        ["git", "push", "-u", "origin", branch],
                        cwd=cwd,
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                    return {"success": True, "message": f"Committed and pushed: {message}", "pushed": True}
                except subprocess.CalledProcessError as e:
                    return {"success": True, "message": f"Committed: {message}", "pushed": False, "push_error": str(e)}

            return {"success": True, "message": f"Committed: {message}", "pushed": False}

        except subprocess.CalledProcessError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def batch_write_files(
        self,
        workspace_id: str,
        files: dict[str, str],
        commit_message: str = "Create multiple files",
    ) -> dict:
        """Write multiple files to workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            workspace_path = Path(ws["path"])

            files_created = []
            errors = []

            for path, content in files.items():
                try:
                    file_path = self.resolve_path(path, workspace_path)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(content, encoding="utf-8")
                    files_created.append(str(file_path.relative_to(workspace_path)))
                except Exception as e:
                    errors.append({"path": path, "error": str(e)})

            if not files_created:
                return {
                    "success": False,
                    "error": "No files were created",
                    "errors": errors,
                }

            result = {
                "success": True,
                "files_created": files_created,
                "file_count": len(files_created),
            }

            if errors:
                result["errors"] = errors
                result["partial_success"] = True

            commit_result = await self._do_commit_and_push(workspace_id, commit_message)
            result["committed"] = commit_result.get("success", False)
            if commit_result.get("success"):
                result["commit_message"] = commit_message

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def commit_and_push(self, workspace_id: str, message: str) -> dict:
        """Commit all changes and push to Gitea."""
        return await self._do_commit_and_push(workspace_id, message)

    async def run_git(
        self,
        workspace_id: str,
        command: str,
        repo_name: str | None = None,
        repo_owner: str | None = None,
    ) -> dict:
        """Execute a whitelisted git command and return raw output."""
        ALLOWED_SUBCOMMANDS = {
            "add",
            "commit",
            "push",
            "status",
            "checkout",
            "log",
            "diff",
            "branch",
        }
        CREDENTIAL_SUBCOMMANDS = {"push"}

        try:
            parts = shlex.split(command)
        except ValueError as e:
            return {"success": False, "error": f"Invalid command syntax: {e}"}

        if not parts:
            return {"success": False, "error": "Empty command"}

        # Strip leading "git" if provided
        if parts[0] == "git":
            parts = parts[1:]

        if not parts:
            return {"success": False, "error": "No git subcommand provided"}

        subcommand = parts[0]

        if subcommand not in ALLOWED_SUBCOMMANDS:
            return {
                "success": False,
                "error": f"Git subcommand '{subcommand}' is not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_SUBCOMMANDS))}",
            }

        # Block destructive flags
        BLOCKED_FLAGS = {"--force", "--hard"}
        found = BLOCKED_FLAGS & set(parts)
        if found:
            return {
                "success": False,
                "error": f"Destructive flags are not allowed: {found}",
            }

        ws = self.get_workspace(workspace_id)
        work_dir = ws["path"]

        # Inject credentials for network commands
        if subcommand in CREDENTIAL_SUBCOMMANDS and repo_name and repo_owner:
            gitea_url = self.get_gitea_clone_url(repo_name, repo_owner)
            if gitea_url:
                try:
                    subprocess.run(
                        ["git", "remote", "set-url", "origin", gitea_url],
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception:
                    pass

        # Build and run the git command
        full_cmd = ["git"] + parts
        logger.info("run_git: command=%s work_dir=%s", full_cmd, work_dir)

        try:
            result = subprocess.run(
                full_cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out after 120 seconds"}
        except Exception as e:
            return {"success": False, "error": f"Failed to execute command: {e}"}

        output = result.stdout.strip()
        error_output = result.stderr.strip()
        combined = f"{output}\n{error_output}".strip() if error_output else output

        response = {
            "success": result.returncode == 0,
            "output": combined,
            "exit_code": result.returncode,
        }

        # Auto-capture commit SHA from git commit output
        if subcommand == "commit" and result.returncode == 0:
            sha_match = re.search(
                r"\[[\w/.-]+ ([a-f0-9]+)\]", output + " " + error_output
            )
            if sha_match:
                response["commit_sha"] = sha_match.group(1)

        # Update workspace branch tracking on checkout
        if subcommand == "checkout" and result.returncode == 0:
            try:
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if branch_result.returncode == 0:
                    ws["branch"] = branch_result.stdout.strip()
            except Exception:
                pass

        if not response["success"]:
            response["error"] = error_output or "Command failed"

        return response

    def create_branch(self, workspace_id: str, branch_name: str) -> dict:
        """Create and checkout a new git branch."""
        try:
            ws = self.get_workspace(workspace_id)
            cwd = ws["path"]

            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=cwd,
                check=True,
            )

            ws["branch"] = branch_name

            return {"success": True, "branch": branch_name}

        except subprocess.CalledProcessError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def merge_to_main(self, workspace_id: str) -> dict:
        """Merge current branch to main."""
        try:
            ws = self.get_workspace(workspace_id)
            cwd = ws["path"]
            current_branch = ws["branch"]

            if current_branch == "main":
                return {"success": False, "error": "Already on main branch"}

            subprocess.run(["git", "checkout", "main"], cwd=cwd, check=True)
            subprocess.run(["git", "merge", current_branch], cwd=cwd, check=True)

            if self.gitea_token:
                subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True)

            ws["branch"] = "main"

            return {"success": True, "merged": current_branch}

        except subprocess.CalledProcessError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_git_status(self, workspace_id: str) -> dict:
        """Get git status for workspace."""
        try:
            ws = self.get_workspace(workspace_id)
            cwd = ws["path"]

            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
            branch = branch_result.stdout.strip() or ws["branch"]

            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )

            files = []
            for line in status_result.stdout.strip().split("\n"):
                if line:
                    status = line[:2].strip()
                    filename = line[3:]
                    files.append({"status": status, "file": filename})

            return {
                "success": True,
                "branch": branch,
                "files": files,
                "has_changes": len(files) > 0,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
