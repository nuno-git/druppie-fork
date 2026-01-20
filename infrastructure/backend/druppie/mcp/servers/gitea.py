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


def main():
    """Entry point for the Gitea MCP server."""
    server = GiteaMCPServer()
    server.run()


if __name__ == "__main__":
    main()
