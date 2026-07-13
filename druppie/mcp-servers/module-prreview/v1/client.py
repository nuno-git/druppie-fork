"""Thin async Gitea REST client for PR review.

Talks to ONE Gitea instance whose base URL and token come from server
configuration. There is no method that accepts a caller-chosen base URL or
token, so the client cannot be steered at a different Gitea instance.

TLS: verification is always on. For instances with a private CA, point
PRREVIEW_SSL_CA_BUNDLE at the CA file — there is no insecure off-switch.
"""

import logging

import httpx

logger = logging.getLogger("prreview-mcp")

REQUEST_TIMEOUT = 30.0


class GiteaPRClient:
    """REST client bound to a single Gitea instance."""

    def __init__(self, base_url: str, token: str, ca_bundle: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        # httpx `verify`: True (system CAs) or a path to a private CA bundle.
        self._verify = ca_bundle if ca_bundle else True

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self._token}"}

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        body = resp.text[:2000]
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {resp.reason_phrase} for url '{resp.url}'\n{body}",
            request=resp.request,
            response=resp,
        )

    async def _get(self, path: str, params: dict | None = None, *, raw: bool = False):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/{path}",
                params=params,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.text if raw else resp.json()

    async def _post(self, path: str, json_body: dict) -> dict:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/{path}",
                json=json_body,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json()

    async def _patch(self, path: str, json_body: dict) -> dict:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.patch(
                f"{self._base_url}/api/v1/{path}",
                json=json_body,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json()

    async def list_open_pulls(self, owner: str, repo: str, limit: int = 50) -> list[dict]:
        """List open pull requests for a repository."""
        return await self._get(
            f"repos/{owner}/{repo}/pulls",
            {"state": "open", "limit": limit},
        )

    async def get_pull_diff(self, owner: str, repo: str, index: int) -> str:
        """Fetch the unified diff of a pull request (base...head)."""
        return await self._get(f"repos/{owner}/{repo}/pulls/{index}.diff", raw=True)

    async def list_issue_comments(self, owner: str, repo: str, index: int) -> list[dict]:
        """List comments on a PR (Gitea PR comments live on the issue API)."""
        return await self._get(f"repos/{owner}/{repo}/issues/{index}/comments")

    async def create_issue_comment(self, owner: str, repo: str, index: int, body: str) -> dict:
        """Create a comment on a PR."""
        return await self._post(
            f"repos/{owner}/{repo}/issues/{index}/comments", {"body": body}
        )

    async def edit_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        """Edit an existing PR comment by its comment id."""
        return await self._patch(
            f"repos/{owner}/{repo}/issues/comments/{comment_id}", {"body": body}
        )
