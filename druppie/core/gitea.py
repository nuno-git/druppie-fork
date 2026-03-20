"""Gitea HTTP Client.

Provides HTTP client for Gitea API operations.
This is a core service, NOT an MCP server - it's used internally by WorkspaceService.
"""

import base64
import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

GITEA_URL = os.getenv("GITEA_URL", "http://gitea:3000")
GITEA_INTERNAL_URL = os.getenv("GITEA_INTERNAL_URL", GITEA_URL)
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "")
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")

# Security warning for missing credentials
if not GITEA_ADMIN_PASSWORD:
    logger.warning(
        "gitea_password_not_configured",
        message="GITEA_ADMIN_PASSWORD not set - Gitea operations will fail",
    )


class GiteaClient:
    """HTTP client for Gitea API."""

    def __init__(
        self,
        base_url: str | None = None,
        admin_user: str | None = None,
        admin_password: str | None = None,
        org: str | None = None,
    ):
        self.base_url = base_url or GITEA_INTERNAL_URL
        self.admin_user = admin_user or GITEA_ADMIN_USER
        self.admin_password = admin_password or GITEA_ADMIN_PASSWORD
        self.org = org or GITEA_ORG
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/v1",
                auth=(self.admin_user, self.admin_password),
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an API request to Gitea."""
        client = await self._get_client()

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                json=json_data,
                params=params,
            )

            result = {
                "success": response.status_code in (200, 201, 204),
                "status_code": response.status_code,
            }

            if response.text:
                try:
                    result["data"] = response.json()
                except ValueError:
                    result["data"] = response.text

            if not result["success"]:
                logger.warning(
                    "gitea_api_error",
                    method=method,
                    endpoint=endpoint,
                    status=response.status_code,
                    response=result.get("data"),
                )

            return result

        except httpx.RequestError as e:
            logger.error("gitea_request_error", method=method, endpoint=endpoint, error=str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # User Operations
    # =========================================================================

    async def create_user(
        self,
        username: str,
        email: str,
    ) -> dict[str, Any]:
        """Create a new Gitea user account.

        The user will be able to login via Keycloak OAuth due to Gitea's
        ACCOUNT_LINKING=auto setting, which auto-links by email.

        Args:
            username: Username for the new account
            email: Email address (must match Keycloak email for auto-linking)

        Returns:
            Dict with success, user data
        """
        import secrets

        # Create user with random password - user will login via OAuth
        # Gitea's ACCOUNT_LINKING=auto will auto-link by email
        user_data = {
            "username": username,
            "email": email,
            "login_name": username,
            "must_change_password": False,
            "password": secrets.token_urlsafe(32),  # Unused - login via OAuth
        }

        result = await self._request(
            "POST",
            "/admin/users",
            json_data=user_data,
        )

        if result["success"]:
            logger.info(
                "gitea_user_created",
                username=username,
                email=email,
            )

        return result

    async def user_exists(self, username: str) -> bool:
        """Check if a Gitea user exists."""
        result = await self._request("GET", f"/users/{username}")
        return result.get("success", False)

    async def find_user_by_email(self, email: str) -> str | None:
        """Find a Gitea username by email address."""
        result = await self._request("GET", f"/admin/users")
        if result.get("success") and isinstance(result.get("data"), list):
            for user in result["data"]:
                if user.get("email") == email:
                    return user.get("login") or user.get("username")
        return None

    async def ensure_user_exists(
        self,
        username: str,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Ensure a Gitea user exists, creating if necessary.

        Users will be able to login via Keycloak OAuth - Gitea auto-links
        accounts by email when ACCOUNT_LINKING=auto is configured.

        Handles reserved Gitea usernames (e.g., "admin") by prefixing
        with "druppie_".

        Args:
            username: Username to check/create
            email: Email for new user (must match Keycloak email for auto-linking)

        Returns:
            Dict with success, created (bool), username (actual Gitea username)
        """
        # Check if user already exists
        if await self.user_exists(username):
            return {"success": True, "created": False, "username": username}

        # Create the user - Gitea will auto-link to OAuth by email
        if not email:
            email = f"{username}@druppie.local"

        result = await self.create_user(
            username=username,
            email=email,
        )

        if result.get("success"):
            return {"success": True, "created": True, "username": username}

        # Handle reserved usernames — retry with "druppie_" prefix
        error_str = str(result.get("error") or result.get("data") or "")
        if "reserved" in error_str.lower():
            alt_username = f"druppie_{username}"
            logger.info(
                "gitea_username_reserved_using_alt",
                original=username,
                alt=alt_username,
            )

            if await self.user_exists(alt_username):
                return {"success": True, "created": False, "username": alt_username}

            alt_result = await self.create_user(
                username=alt_username,
                email=email,
            )
            if alt_result.get("success"):
                return {"success": True, "created": True, "username": alt_username}

        # Last resort: find existing user by email (e.g., gitea_admin shares email)
        if email:
            existing = await self.find_user_by_email(email)
            if existing:
                logger.info(
                    "gitea_user_found_by_email",
                    email=email,
                    gitea_username=existing,
                )
                return {"success": True, "created": False, "username": existing}

        return {
            "success": False,
            "error": result.get("error") or result.get("data"),
            "username": username,
        }

    # =========================================================================
    # Repository Operations
    # =========================================================================

    async def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = True,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Create a new repository.

        Args:
            name: Repository name
            description: Repository description
            private: Whether repo is private
            auto_init: Initialize with README
            owner: Username to create repo under (uses admin API).
                   If None, creates in the organization.

        Returns:
            Dict with success, repo_url, clone_url, repo_name, owner
        """
        if owner:
            # Create repo under user's account using admin API
            endpoint = f"/admin/users/{owner}/repos"
        else:
            # Create repo in organization
            endpoint = f"/orgs/{self.org}/repos"

        result = await self._request(
            "POST",
            endpoint,
            json_data={
                "name": name,
                "description": description,
                "private": private,
                "auto_init": auto_init,
            },
        )

        if result["success"] and "data" in result:
            repo_data = result["data"]
            result["repo_url"] = repo_data.get("html_url")
            result["clone_url"] = repo_data.get("clone_url")
            result["ssh_url"] = repo_data.get("ssh_url")
            result["repo_name"] = repo_data.get("name")
            result["owner"] = repo_data.get("owner", {}).get("login", owner or self.org)
            logger.info(
                "gitea_repo_created",
                name=name,
                owner=result.get("owner"),
                url=result.get("repo_url"),
            )

        return result

    async def delete_repo(self, name: str, owner: str | None = None) -> dict[str, Any]:
        """Delete a repository."""
        repo_owner = owner or self.org
        result = await self._request("DELETE", f"/repos/{repo_owner}/{name}")
        if result["success"]:
            logger.info("gitea_repo_deleted", name=name, owner=repo_owner)
        return result

    async def list_repos(self) -> dict[str, Any]:
        """List all repositories in the organization."""
        result = await self._request("GET", f"/orgs/{self.org}/repos")

        if result["success"] and "data" in result:
            repos = result["data"]
            result["repos"] = [
                {
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "description": r.get("description"),
                    "html_url": r.get("html_url"),
                    "clone_url": r.get("clone_url"),
                }
                for r in repos
            ]
            result["count"] = len(repos)

        return result

    async def get_repo(self, name: str) -> dict[str, Any]:
        """Get repository details."""
        result = await self._request("GET", f"/repos/{self.org}/{name}")

        if result["success"] and "data" in result:
            repo_data = result["data"]
            result["repo_url"] = repo_data.get("html_url")
            result["clone_url"] = repo_data.get("clone_url")
            result["default_branch"] = repo_data.get("default_branch", "main")

        return result

    async def repo_exists(self, name: str) -> bool:
        """Check if a repository exists."""
        result = await self.get_repo(name)
        return result.get("success", False)

    # =========================================================================
    # File Operations
    # =========================================================================

    async def create_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str = "Add file",
        branch: str = "main",
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Create a file in a repository."""
        repo_owner = owner or self.org
        encoded_content = base64.b64encode(content.encode()).decode()

        return await self._request(
            "POST",
            f"/repos/{repo_owner}/{repo}/contents/{path}",
            json_data={
                "content": encoded_content,
                "message": message,
                "branch": branch,
            },
        )

    async def update_file(
        self,
        repo: str,
        path: str,
        content: str,
        sha: str,
        message: str = "Update file",
        branch: str = "main",
    ) -> dict[str, Any]:
        """Update a file in a repository."""
        encoded_content = base64.b64encode(content.encode()).decode()

        return await self._request(
            "PUT",
            f"/repos/{self.org}/{repo}/contents/{path}",
            json_data={
                "content": encoded_content,
                "sha": sha,
                "message": message,
                "branch": branch,
            },
        )

    async def get_file(
        self,
        repo: str,
        path: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Get file contents and SHA from a repository."""
        result = await self._request(
            "GET",
            f"/repos/{self.org}/{repo}/contents/{path}",
            params={"ref": branch},
        )

        if result["success"] and "data" in result:
            file_data = result["data"]
            result["sha"] = file_data.get("sha")
            result["name"] = file_data.get("name")
            result["path"] = file_data.get("path")
            result["size"] = file_data.get("size")

            # Decode content from base64
            if file_data.get("content"):
                try:
                    content = base64.b64decode(file_data["content"]).decode("utf-8")
                    result["content"] = content
                except (UnicodeDecodeError, ValueError):
                    # Binary file or invalid encoding - mark as binary
                    result["content"] = None
                    result["binary"] = True

        return result

    async def list_files(
        self,
        repo: str,
        path: str = "",
        branch: str = "main",
    ) -> dict[str, Any]:
        """List files in a directory of a repository."""
        endpoint = f"/repos/{self.org}/{repo}/contents"
        if path:
            endpoint = f"{endpoint}/{path}"

        result = await self._request(
            "GET",
            endpoint,
            params={"ref": branch},
        )

        if result["success"] and "data" in result:
            items = result["data"]
            # Handle both single file and directory listing
            if isinstance(items, dict):
                items = [items]

            result["files"] = [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "type": item.get("type"),  # "file" or "dir"
                    "size": item.get("size", 0),
                    "sha": item.get("sha"),
                }
                for item in items
            ]
            result["count"] = len(items)

        return result

    async def delete_file(
        self,
        repo: str,
        path: str,
        sha: str,
        message: str = "Delete file",
        branch: str = "main",
    ) -> dict[str, Any]:
        """Delete a file from a repository."""
        return await self._request(
            "DELETE",
            f"/repos/{self.org}/{repo}/contents/{path}",
            json_data={
                "sha": sha,
                "message": message,
                "branch": branch,
            },
        )

    async def push_template(
        self,
        repo: str,
        template_dir: str,
        owner: str | None = None,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Push all files from a template directory into a repository.

        Clones the repo via git, copies template files, commits, and pushes
        in a single commit. Falls back to per-file API calls if git fails.
        Skips __pycache__ and .pyc files.

        Args:
            repo: Repository name
            template_dir: Absolute path to the template directory
            owner: Repository owner (defaults to org)
            branch: Target branch

        Returns:
            Dict with success, files_pushed count, and any errors
        """
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        template_path = Path(template_dir)
        if not template_path.is_dir():
            return {"success": False, "error": f"Template dir not found: {template_dir}"}

        # Collect template files
        files: list[tuple[str, str]] = []  # (relative_path, content)
        for file_path in sorted(template_path.rglob("*")):
            if not file_path.is_file():
                continue
            if "__pycache__" in str(file_path) or file_path.suffix == ".pyc":
                continue
            try:
                content = file_path.read_text()
            except UnicodeDecodeError:
                continue  # skip binary files
            files.append((str(file_path.relative_to(template_path)), content))

        if not files:
            return {"success": True, "files_pushed": 0, "errors": None}

        # Try git clone + commit + push for a single commit
        clone_url = self.get_clone_url(repo, owner)
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="druppie-template-")
            clone_result = subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1", clone_url, tmp_dir],
                capture_output=True, text=True, timeout=60,
            )
            if clone_result.returncode != 0:
                raise RuntimeError(f"Clone failed: {clone_result.stderr}")

            # Copy template files into the clone
            for relative, content in files:
                dest = Path(tmp_dir) / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)

            # Configure git identity for the commit
            subprocess.run(
                ["git", "config", "user.email", "druppie@druppie.local"],
                cwd=tmp_dir, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "config", "user.name", "Druppie"],
                cwd=tmp_dir, capture_output=True, timeout=10,
            )

            # Stage, commit, push
            subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True, timeout=30)
            commit_result = subprocess.run(
                ["git", "commit", "-m", "feat: scaffold project template"],
                cwd=tmp_dir, capture_output=True, text=True, timeout=30,
            )
            if commit_result.returncode != 0:
                raise RuntimeError(f"Commit failed: {commit_result.stderr}")

            push_result = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=tmp_dir, capture_output=True, text=True, timeout=120,
            )
            if push_result.returncode != 0:
                raise RuntimeError(f"Push failed: {push_result.stderr}")

            logger.info(
                "gitea_template_pushed",
                repo=repo,
                owner=owner or self.org,
                files_pushed=len(files),
                method="git",
            )
            return {"success": True, "files_pushed": len(files), "errors": None}

        except Exception as e:
            logger.warning("gitea_template_git_push_failed", error=str(e), fallback="api")
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # Fallback: per-file API calls (creates N commits)
        errors = []
        pushed = 0
        for relative, content in files:
            result = await self.create_file(
                repo=repo,
                path=relative,
                content=content,
                message=f"feat: scaffold project template ({relative})",
                branch=branch,
                owner=owner,
            )
            if result.get("success"):
                pushed += 1
            else:
                errors.append(f"{relative}: {result.get('error') or result.get('data')}")

        logger.info(
            "gitea_template_pushed",
            repo=repo,
            owner=owner or self.org,
            files_pushed=pushed,
            errors=len(errors),
            method="api_fallback",
        )

        return {
            "success": len(errors) == 0,
            "files_pushed": pushed,
            "errors": errors if errors else None,
        }

    # =========================================================================
    # Branch Operations
    # =========================================================================

    async def list_branches(self, repo: str) -> dict[str, Any]:
        """List all branches in a repository."""
        result = await self._request("GET", f"/repos/{self.org}/{repo}/branches")

        if result["success"] and "data" in result:
            branches = result["data"]
            result["branches"] = [
                {
                    "name": b.get("name"),
                    "commit_sha": b.get("commit", {}).get("id"),
                    "commit_message": b.get("commit", {}).get("message"),
                }
                for b in branches
            ]
            result["count"] = len(branches)

        return result

    async def create_branch(
        self,
        repo: str,
        branch: str,
        from_branch: str = "main",
    ) -> dict[str, Any]:
        """Create a new branch in a repository."""
        result = await self._request(
            "POST",
            f"/repos/{self.org}/{repo}/branches",
            json_data={
                "new_branch_name": branch,
                "old_branch_name": from_branch,
            },
        )

        if result["success"]:
            logger.info("gitea_branch_created", repo=repo, branch=branch, from_branch=from_branch)

        return result

    async def delete_branch(self, repo: str, branch: str) -> dict[str, Any]:
        """Delete a branch from a repository."""
        result = await self._request(
            "DELETE",
            f"/repos/{self.org}/{repo}/branches/{branch}",
        )

        if result["success"]:
            logger.info("gitea_branch_deleted", repo=repo, branch=branch)

        return result

    async def get_branch(self, repo: str, branch: str) -> dict[str, Any]:
        """Get branch details."""
        return await self._request(
            "GET",
            f"/repos/{self.org}/{repo}/branches/{branch}",
        )

    async def branch_exists(self, repo: str, branch: str) -> bool:
        """Check if a branch exists."""
        result = await self.get_branch(repo, branch)
        return result.get("success", False)

    # =========================================================================
    # Merge Operations
    # =========================================================================

    async def merge_branch(
        self,
        repo: str,
        head: str,
        base: str = "main",
        message: str | None = None,
    ) -> dict[str, Any]:
        """Merge a branch into another branch via PR."""
        if message is None:
            message = f"Merge branch '{head}' into {base}"

        # Create a PR
        pr_result = await self._request(
            "POST",
            f"/repos/{self.org}/{repo}/pulls",
            json_data={
                "title": message,
                "head": head,
                "base": base,
                "body": f"Automated merge of {head} into {base}",
            },
        )

        if not pr_result.get("success"):
            return pr_result

        pr_number = pr_result["data"].get("number")
        if not pr_number:
            return {"success": False, "error": "Failed to get PR number"}

        # Merge the PR
        merge_result = await self._request(
            "POST",
            f"/repos/{self.org}/{repo}/pulls/{pr_number}/merge",
            json_data={
                "Do": "merge",
                "MergeMessageField": message,
            },
        )

        if merge_result["success"]:
            logger.info("gitea_branch_merged", repo=repo, head=head, base=base, pr=pr_number)

        return merge_result

    async def get_branch_diff(
        self,
        repo: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        """Get the diff between two branches."""
        result = await self._request(
            "GET",
            f"/repos/{self.org}/{repo}/compare/{base}...{head}",
        )

        if result["success"] and "data" in result:
            diff_data = result["data"]
            result["total_commits"] = diff_data.get("total_commits", 0)
            result["commits"] = [
                {
                    "sha": c.get("sha"),
                    "message": c.get("commit", {}).get("message"),
                    "author": c.get("commit", {}).get("author", {}).get("name"),
                }
                for c in diff_data.get("commits", [])
            ]
            result["files_changed"] = len(diff_data.get("files", []))
            result["files"] = [
                {
                    "filename": f.get("filename"),
                    "status": f.get("status"),
                    "additions": f.get("additions"),
                    "deletions": f.get("deletions"),
                }
                for f in diff_data.get("files", [])
            ]

        return result

    # =========================================================================
    # Clone URL Helper
    # =========================================================================

    def get_clone_url(self, repo_name: str, owner: str | None = None) -> str:
        """Get the clone URL for a repository (with embedded credentials).

        Args:
            repo_name: Repository name
            owner: Owner username. If None, uses the organization.
        """
        # Use internal URL for cloning within Docker network
        # URL format: http://user:pass@host:port/owner/repo.git
        base = GITEA_INTERNAL_URL.replace("http://", "").replace("https://", "")
        repo_owner = owner or self.org
        return f"http://{self.admin_user}:{self.admin_password}@{base}/{repo_owner}/{repo_name}.git"

    def get_public_url(self, repo_name: str, owner: str | None = None) -> str:
        """Get the public repo URL (without credentials).

        Args:
            repo_name: Repository name
            owner: Owner username. If None, uses the organization.
        """
        # Use external URL for display
        repo_owner = owner or self.org
        return f"{GITEA_URL}/{repo_owner}/{repo_name}"


# Singleton instance
_gitea_client: GiteaClient | None = None


def get_gitea_client() -> GiteaClient:
    """Get the global GiteaClient instance."""
    global _gitea_client
    if _gitea_client is None:
        _gitea_client = GiteaClient()
    return _gitea_client
