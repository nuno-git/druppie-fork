"""Gitea MCP Server.

Provides Gitea API operations for repository management via MCP protocol.
"""

import os
import requests
from typing import Any

from .base import MCPServerBase


class GiteaMCPServer(MCPServerBase):
    """MCP Server for Gitea operations."""

    def __init__(self):
        super().__init__("gitea", "Gitea")
        self.base_url = os.getenv("GITEA_URL", "http://gitea:3000")
        self.admin_user = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
        self.admin_password = os.getenv("GITEA_ADMIN_PASSWORD", "GiteaAdmin123")
        self.org = os.getenv("GITEA_ORG", "druppie")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all Gitea tools."""
        self.register_tool("create_repo", self.create_repo)
        self.register_tool("delete_repo", self.delete_repo)
        self.register_tool("list_repos", self.list_repos)
        self.register_tool("get_repo", self.get_repo)
        self.register_tool("create_file", self.create_file)
        self.register_tool("update_file", self.update_file)
        self.register_tool("get_file", self.get_file)
        self.register_tool("list_branches", self.list_branches)
        self.register_tool("create_branch", self.create_branch)
        self.register_tool("merge_branch", self.merge_branch)
        self.register_tool("get_branch_diff", self.get_branch_diff)
        self.register_tool("delete_branch", self.delete_branch)

    def _api_request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        """Make an API request to Gitea."""
        url = f"{self.base_url}/api/v1{endpoint}"
        auth = (self.admin_user, self.admin_password)

        try:
            response = requests.request(
                method=method,
                url=url,
                json=json_data,
                auth=auth,
                timeout=30,
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

            return result

        except requests.RequestException as e:
            return {
                "success": False,
                "error": str(e),
            }

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = True,
    ) -> dict[str, Any]:
        """Create a new repository in the Druppie organization."""
        result = self._api_request(
            "POST",
            f"/orgs/{self.org}/repos",
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

        return result

    def delete_repo(self, name: str) -> dict[str, Any]:
        """Delete a repository from the Druppie organization."""
        return self._api_request("DELETE", f"/repos/{self.org}/{name}")

    def list_repos(self) -> dict[str, Any]:
        """List all repositories in the Druppie organization."""
        result = self._api_request("GET", f"/orgs/{self.org}/repos")

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

    def get_repo(self, name: str) -> dict[str, Any]:
        """Get repository details."""
        return self._api_request("GET", f"/repos/{self.org}/{name}")

    def create_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str = "Add file",
        branch: str = "main",
    ) -> dict[str, Any]:
        """Create a file in a repository."""
        import base64

        encoded_content = base64.b64encode(content.encode()).decode()

        return self._api_request(
            "POST",
            f"/repos/{self.org}/{repo}/contents/{path}",
            json_data={
                "content": encoded_content,
                "message": message,
                "branch": branch,
            },
        )

    def update_file(
        self,
        repo: str,
        path: str,
        content: str,
        sha: str,
        message: str = "Update file",
        branch: str = "main",
    ) -> dict[str, Any]:
        """Update a file in a repository."""
        import base64

        encoded_content = base64.b64encode(content.encode()).decode()

        return self._api_request(
            "PUT",
            f"/repos/{self.org}/{repo}/contents/{path}",
            json_data={
                "content": encoded_content,
                "sha": sha,
                "message": message,
                "branch": branch,
            },
        )

    def get_file(
        self,
        repo: str,
        path: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Get file contents and SHA from a repository."""
        import base64

        result = self._api_request(
            "GET",
            f"/repos/{self.org}/{repo}/contents/{path}?ref={branch}",
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
                except Exception:
                    result["content"] = None
                    result["binary"] = True

        return result

    def list_branches(self, repo: str) -> dict[str, Any]:
        """List all branches in a repository."""
        result = self._api_request("GET", f"/repos/{self.org}/{repo}/branches")

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

    def create_branch(
        self,
        repo: str,
        branch: str,
        from_branch: str = "main",
    ) -> dict[str, Any]:
        """Create a new branch in a repository."""
        return self._api_request(
            "POST",
            f"/repos/{self.org}/{repo}/branches",
            json_data={
                "new_branch_name": branch,
                "old_branch_name": from_branch,
            },
        )

    def merge_branch(
        self,
        repo: str,
        head: str,
        base: str = "main",
        message: str = None,
    ) -> dict[str, Any]:
        """Merge a branch into another branch."""
        if message is None:
            message = f"Merge branch '{head}' into {base}"

        # Gitea uses a different endpoint for merges via API
        # We'll use the merge API endpoint
        result = self._api_request(
            "POST",
            f"/repos/{self.org}/{repo}/merge-upstream",
            json_data={
                "base": base,
                "head": f"{self.org}:{head}",
            },
        )

        # If merge-upstream doesn't work, try manual merge via git operations
        # by creating a temporary PR and merging it
        if not result.get("success"):
            # Alternative: Create a PR and merge it
            pr_result = self._api_request(
                "POST",
                f"/repos/{self.org}/{repo}/pulls",
                json_data={
                    "title": message,
                    "head": head,
                    "base": base,
                    "body": f"Automated merge of {head} into {base}",
                },
            )

            if pr_result.get("success") and "data" in pr_result:
                pr_number = pr_result["data"].get("number")
                # Merge the PR
                merge_result = self._api_request(
                    "POST",
                    f"/repos/{self.org}/{repo}/pulls/{pr_number}/merge",
                    json_data={
                        "Do": "merge",
                        "MergeMessageField": message,
                    },
                )
                return merge_result

        return result

    def get_branch_diff(
        self,
        repo: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        """Get the diff between two branches."""
        result = self._api_request(
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

    def delete_branch(self, repo: str, branch: str) -> dict[str, Any]:
        """Delete a branch from a repository."""
        return self._api_request(
            "DELETE",
            f"/repos/{self.org}/{repo}/branches/{branch}",
        )


def main():
    """Entry point for the Gitea MCP server."""
    server = GiteaMCPServer()
    server.run()


if __name__ == "__main__":
    main()
