"""Minimal async Gitea Contents-API client for the ArchiMate write flow.

The archimate MCP used to read/write ``docs/architecture.archimate`` on a
shared-volume workspace that the coding MCP cloned per session. When coding
became a sandbox orchestrator that shared-volume workspace disappeared, so the
archimate module now reads and writes the model — and its exported SVGs —
directly against Gitea, which is the durable source of truth the coding
sandboxes push to and the frontend renderer reads from.

Auth mirrors ``druppie.core.gitea`` (admin basic-auth) but is kept
self-contained because the module container does not ship ``druppie.core``.
"""

import base64
import logging
import os

import httpx

logger = logging.getLogger("archimate-gitea-io")

GITEA_INTERNAL_URL = os.getenv(
    "GITEA_INTERNAL_URL", os.getenv("GITEA_URL", "http://gitea:3000")
)
GITEA_ORG = os.getenv("GITEA_ORG", "druppie")
GITEA_USER = os.getenv("GITEA_ADMIN_USER", os.getenv("GITEA_USER", "gitea_admin"))
GITEA_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", os.getenv("GITEA_PASSWORD", ""))


class GiteaError(Exception):
    """Raised when a Gitea Contents-API call fails (non-404)."""


class GiteaFileStore:
    """Read/write single files in a Gitea repository via the Contents API."""

    def __init__(self, *, base_url=None, user=None, password=None, org=None):
        self.base_url = (base_url or GITEA_INTERNAL_URL).rstrip("/")
        self.user = user or GITEA_USER
        self.password = password or GITEA_PASSWORD
        self.org = org or GITEA_ORG

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            auth=(self.user, self.password),
            timeout=30.0,
        )

    async def get_file(self, *, owner, repo, path, ref="main"):
        """Return ``(content_str, sha)``; ``(None, None)`` if the file is absent.

        Raises :class:`GiteaError` for any non-200/404 response so the caller
        never silently treats a real failure as "file missing".
        """
        async with self._client() as client:
            resp = await client.get(
                f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
            )
        if resp.status_code == 404:
            return None, None
        if resp.status_code != 200:
            raise GiteaError(
                f"get_file {owner}/{repo}:{path}@{ref} -> {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        sha = data.get("sha")
        encoded = data.get("content") or ""
        try:
            content = base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GiteaError(f"cannot decode {path}: {exc}") from exc
        return content, sha

    async def put_file(self, *, owner, repo, path, content, message, branch="main", sha=None):
        """Create (no ``sha``) or update (with ``sha``) a text file. Returns the API payload."""
        payload = {
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "message": message,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        async with self._client() as client:
            resp = await client.request(
                "PUT" if sha else "POST",
                f"/repos/{owner}/{repo}/contents/{path}",
                json=payload,
            )
        if resp.status_code not in (200, 201):
            raise GiteaError(
                f"put_file {owner}/{repo}:{path}@{branch} -> {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()
