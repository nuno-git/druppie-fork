"""Async Microsoft Graph API client for SharePoint file access.

Authenticates with a delegated (OBO) user token passed per-request and talks
to the Microsoft Graph REST API. Every method takes a site_id parameter so
the caller can target any site the user has access to.

Tokens are passed per-request from the orchestration layer and are NEVER
stored or written to disk.
"""

import logging

import httpx

logger = logging.getLogger("sharepoint-mcp")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointClient:
    """Stateless REST client for SharePoint via Microsoft Graph."""

    def _auth_header(self, user_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {user_token}"}

    async def _get(self, path: str, user_token: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{path}",
                headers=self._auth_header(user_token),
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()

    async def _get_bytes(self, path: str, user_token: str) -> bytes:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/{path}",
                headers=self._auth_header(user_token),
            )
            resp.raise_for_status()
            return resp.content

    async def search_sites(self, query: str, user_token: str) -> list[dict]:
        """Search for SharePoint sites the user has access to."""
        params = {"$select": "id,displayName,webUrl,description"}
        if query:
            params["search"] = query
        result = await self._get("sites", user_token, params=params)
        return result.get("value", [])

    async def list_folder(
        self,
        site_id: str,
        user_token: str,
        folder_path: str | None = None,
    ) -> list[dict]:
        """List children of a folder (or drive root) on a site."""
        if folder_path:
            folder_clean = folder_path.strip("/")
            path = f"sites/{site_id}/drive/root:/{folder_clean}:/children"
        else:
            path = f"sites/{site_id}/drive/root/children"
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder"
        }
        result = await self._get(path, user_token, params=params)
        return result.get("value", [])

    async def get_item(
        self, site_id: str, item_id: str, user_token: str
    ) -> dict:
        path = f"sites/{site_id}/drive/items/{item_id}"
        return await self._get(path, user_token)

    async def download_file(
        self, site_id: str, item_id: str, user_token: str
    ) -> tuple[bytes, str, dict]:
        metadata = await self.get_item(site_id, item_id, user_token)
        content_type = metadata.get("file", {}).get(
            "mimeType", "application/octet-stream"
        )
        path = f"sites/{site_id}/drive/items/{item_id}/content"
        content = await self._get_bytes(path, user_token)
        return content, content_type, metadata

    async def search(
        self, site_id: str, query: str, user_token: str
    ) -> list[dict]:
        safe_query = query.replace("'", "''")
        path = f"sites/{site_id}/drive/root/search(q='{safe_query}')"
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder,parentReference"
        }
        result = await self._get(path, user_token, params=params)
        return result.get("value", [])
