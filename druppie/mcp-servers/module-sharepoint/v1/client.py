"""Async Microsoft Graph API client for SharePoint file access.

Authenticates with a delegated (OBO) user token passed per-request and talks
to the Microsoft Graph REST API. Every call is hard-scoped to ONE SharePoint
site that is read from configuration — there is no method that accepts a
caller-chosen site, so the client cannot be steered at a different site.

Tokens are passed per-request from the orchestration layer and are NEVER
stored or written to disk.
"""

import logging

import httpx

logger = logging.getLogger("sharepoint-mcp")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointClient:
    """REST client bound to a single SharePoint site and root folder."""

    def __init__(self, site_id: str, folder_path: str) -> None:
        self._site_id = site_id
        self._folder_path = folder_path.strip("/")

    def _auth_header(self, user_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {user_token}"}

    async def _get(self, path: str, user_token: str, **kwargs) -> dict:
        """GET request to Graph API. Returns parsed JSON."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{path}",
                headers=self._auth_header(user_token),
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()

    async def _get_bytes(self, path: str, user_token: str) -> bytes:
        """GET request returning raw bytes (for file downloads).

        Uses follow_redirects=True because Graph's /content endpoint returns
        a 302 redirect to the actual download URL.
        """
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{path}",
                headers=self._auth_header(user_token),
            )
            resp.raise_for_status()
            return resp.content

    async def list_folder(
        self, user_token: str, subfolder: str | None = None
    ) -> list[dict]:
        """List children of the configured folder (or a subfolder within it)."""
        folder = self._folder_path
        if subfolder:
            subfolder_clean = subfolder.strip("/")
            folder = f"{folder}/{subfolder_clean}"
        path = f"sites/{self._site_id}/drive/root:/{folder}:/children"
        # Request specific fields to keep response lean
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder"
        }
        result = await self._get(path, user_token, params=params)
        return result.get("value", [])

    async def get_item(self, item_id: str, user_token: str) -> dict:
        """Get metadata for a specific drive item."""
        path = f"sites/{self._site_id}/drive/items/{item_id}"
        return await self._get(path, user_token)

    async def download_file(
        self, item_id: str, user_token: str
    ) -> tuple[bytes, str, dict]:
        """Download file content. Returns (bytes, content_type, metadata)."""
        # First get metadata to know the content type
        metadata = await self.get_item(item_id, user_token)
        content_type = metadata.get("file", {}).get(
            "mimeType", "application/octet-stream"
        )
        path = f"sites/{self._site_id}/drive/items/{item_id}/content"
        content = await self._get_bytes(path, user_token)
        return content, content_type, metadata

    async def search(self, query: str, user_token: str) -> list[dict]:
        """Search files within the site's drive."""
        safe_query = query.replace("'", "''")
        path = f"sites/{self._site_id}/drive/root/search(q='{safe_query}')"
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder,parentReference"
        }
        result = await self._get(path, user_token, params=params)
        return result.get("value", [])
