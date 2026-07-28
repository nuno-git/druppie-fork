"""SharePoint module — read-only file access via Microsoft Graph.

Supports browsing any SharePoint site the user has access to. All operations
take a site_id parameter so the agent can discover sites and navigate them.
"""

import logging
import os

import httpx

from .client import SharePointClient

logger = logging.getLogger("sharepoint-mcp")

_MAX_VERIFIED_CACHE = 1000

TEXT_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/yaml",
)
TEXT_EXTENSIONS = {
    ".txt", ".csv", ".json", ".md", ".xml", ".yaml", ".yml",
    ".log", ".ini", ".cfg", ".toml", ".env",
    ".sh", ".py", ".js", ".ts", ".html", ".css", ".sql",
}


def _load_allowed_sites() -> set[str] | None:
    raw = os.environ.get("SHAREPOINT_ALLOWED_SITES", "").strip()
    if not raw:
        return set()
    if raw.lower() == "all":
        return None
    return {s.strip().rstrip("/").lower() for s in raw.split(";") if s.strip()}


class SharePointModule:
    """High-level file operations for SharePoint sites."""

    def __init__(self) -> None:
        self._client = SharePointClient()
        self._allowed_urls = _load_allowed_sites()
        self._verified_ids: dict[str, bool] = {}
        if self._allowed_urls is None:
            logger.info("SharePoint MCP initialized (all sites allowed)")
        elif self._allowed_urls:
            logger.info("SharePoint MCP initialized (allowed sites: %s)", self._allowed_urls)
        else:
            logger.info("SharePoint MCP initialized (no sites allowed)")

    def _is_site_allowed_by_url(self, web_url: str) -> bool:
        if self._allowed_urls is None:
            return True
        return web_url.rstrip("/").lower() in self._allowed_urls

    async def _is_site_allowed(self, site_id: str, user_token: str) -> bool:
        if self._allowed_urls is None:
            return True
        if not self._allowed_urls:
            return False
        if site_id in self._verified_ids:
            return self._verified_ids[site_id]
        try:
            site = await self._client.get_site(site_id, user_token)
            web_url = site.get("webUrl", "")
            allowed = self._is_site_allowed_by_url(web_url)
            if len(self._verified_ids) > _MAX_VERIFIED_CACHE:
                self._verified_ids.clear()
            self._verified_ids[site_id] = allowed
            return allowed
        except Exception:
            return False

    async def list_sites(self, user_token: str, query: str = "") -> dict:
        """List SharePoint sites the user has access to."""
        if self._allowed_urls is not None and not self._allowed_urls:
            return {"success": True, "sites": [], "count": 0}
        try:
            sites = await self._client.search_sites(query, user_token)
            result = []
            for site in sites:
                site_id = site["id"]
                web_url = site.get("webUrl", "")
                if not self._is_site_allowed_by_url(web_url):
                    continue
                if len(self._verified_ids) > _MAX_VERIFIED_CACHE:
                    self._verified_ids.clear()
                self._verified_ids[site_id] = True
                result.append({
                    "id": site_id,
                    "name": site.get("displayName", ""),
                    "web_url": web_url,
                    "description": site.get("description", ""),
                })
            return {
                "success": True,
                "sites": result,
                "count": len(result),
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                return {
                    "success": False,
                    "error": "Insufficient permissions to search sites (Sites.Read.All required). "
                             "Use the resolve_site_url tool with a SharePoint URL instead.",
                }
            logger.warning("list_sites failed: %s", exc)
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("list_sites failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def resolve_site_url(self, url: str, user_token: str) -> dict:
        """Resolve a SharePoint site URL to its site ID and metadata."""
        try:
            site = await self._client.get_site_by_url(url, user_token)
            site_id = site["id"]
            web_url = site.get("webUrl", "")
            if not self._is_site_allowed_by_url(web_url):
                return {"success": False, "error": "Access to this site is not allowed."}
            if len(self._verified_ids) > _MAX_VERIFIED_CACHE:
                self._verified_ids.clear()
            self._verified_ids[site_id] = True
            return {
                "success": True,
                "id": site_id,
                "name": site.get("displayName", ""),
                "web_url": web_url,
                "description": site.get("description", ""),
            }
        except Exception as exc:
            logger.warning("resolve_site_url(%s) failed: %s", url, exc)
            return {"success": False, "error": str(exc)}

    async def list_files(
        self,
        site_id: str,
        user_token: str,
        folder_path: str | None = None,
    ) -> dict:
        """List files and folders on a site (at root or a specific folder)."""
        if not await self._is_site_allowed(site_id, user_token):
            return {"success": False, "error": "Access to this site is not allowed."}
        try:
            items = await self._client.list_folder(
                site_id, user_token, folder_path
            )
            files = []
            for item in items:
                entry = {
                    "id": item["id"],
                    "name": item["name"],
                    "type": "folder" if "folder" in item else "file",
                    "web_url": item.get("webUrl", ""),
                }
                if "file" in item:
                    entry["size"] = item.get("size", 0)
                    entry["mime_type"] = item["file"].get("mimeType", "")
                    entry["last_modified"] = item.get(
                        "lastModifiedDateTime", ""
                    )
                if "folder" in item:
                    entry["child_count"] = item["folder"].get(
                        "childCount", 0
                    )
                files.append(entry)

            return {
                "success": True,
                "site_id": site_id,
                "folder": folder_path or "/",
                "items": files,
                "count": len(files),
            }
        except Exception as exc:
            logger.warning("list_files failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def read_file(
        self, site_id: str, file_id: str, user_token: str
    ) -> dict:
        """Read file: text content for text formats, metadata-only for binary."""
        if not await self._is_site_allowed(site_id, user_token):
            return {"success": False, "error": "Access to this site is not allowed."}
        try:
            metadata = await self._client.get_item(site_id, file_id, user_token)
            name = metadata.get("name", "")
            ext = os.path.splitext(name)[1].lower() if name else ""
            content_type = metadata.get("file", {}).get(
                "mimeType", "application/octet-stream"
            )

            result = {
                "success": True,
                "id": file_id,
                "name": name,
                "size": metadata.get("size", 0),
                "mime_type": content_type,
                "web_url": metadata.get("webUrl", ""),
                "last_modified": metadata.get("lastModifiedDateTime", ""),
            }

            is_text = (
                any(content_type.startswith(p) for p in TEXT_MIME_PREFIXES)
                or ext in TEXT_EXTENSIONS
            )

            if is_text:
                content_bytes = await self._client._get_bytes(
                    f"sites/{site_id}/drive/items/{file_id}/content",
                    user_token,
                )
                try:
                    result["content"] = content_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    result["content"] = content_bytes.decode(
                        "utf-8", errors="replace"
                    )
                result["content_included"] = True
            else:
                result["content_included"] = False
                result["message"] = (
                    f"Binary file ({content_type}). "
                    "Use the web_url to view in browser."
                )

            return result
        except Exception as exc:
            logger.warning("read_file(%s) failed: %s", file_id, exc)
            return {"success": False, "error": str(exc)}

    async def get_file_metadata(
        self, site_id: str, file_id: str, user_token: str
    ) -> dict:
        """Get metadata for a file or folder without downloading content."""
        if not await self._is_site_allowed(site_id, user_token):
            return {"success": False, "error": "Access to this site is not allowed."}
        try:
            metadata = await self._client.get_item(site_id, file_id, user_token)

            result = {
                "success": True,
                "id": file_id,
                "name": metadata.get("name", ""),
                "size": metadata.get("size", 0),
                "web_url": metadata.get("webUrl", ""),
                "last_modified": metadata.get("lastModifiedDateTime", ""),
                "created": metadata.get("createdDateTime", ""),
            }

            if "file" in metadata:
                result["type"] = "file"
                result["mime_type"] = metadata["file"].get("mimeType", "")
            elif "folder" in metadata:
                result["type"] = "folder"
                result["child_count"] = metadata["folder"].get(
                    "childCount", 0
                )

            if "createdBy" in metadata:
                result["created_by"] = (
                    metadata["createdBy"]
                    .get("user", {})
                    .get("displayName", "")
                )
            if "lastModifiedBy" in metadata:
                result["modified_by"] = (
                    metadata["lastModifiedBy"]
                    .get("user", {})
                    .get("displayName", "")
                )

            return result
        except Exception as exc:
            logger.warning("get_file_metadata(%s) failed: %s", file_id, exc)
            return {"success": False, "error": str(exc)}

    async def search_files(
        self, site_id: str, query: str, user_token: str
    ) -> dict:
        """Search files within a SharePoint site's drive."""
        if not await self._is_site_allowed(site_id, user_token):
            return {"success": False, "error": "Access to this site is not allowed."}
        try:
            items = await self._client.search(site_id, query, user_token)
            files = []
            for item in items:
                entry = {
                    "id": item["id"],
                    "name": item["name"],
                    "type": "folder" if "folder" in item else "file",
                    "web_url": item.get("webUrl", ""),
                    "size": item.get("size", 0),
                    "last_modified": item.get("lastModifiedDateTime", ""),
                }
                if "file" in item:
                    entry["mime_type"] = item["file"].get("mimeType", "")
                if "parentReference" in item:
                    entry["path"] = item["parentReference"].get("path", "")
                files.append(entry)

            return {
                "success": True,
                "site_id": site_id,
                "query": query,
                "items": files,
                "count": len(files),
            }
        except Exception as exc:
            logger.warning("search_files failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_all_files(self, site_id: str, user_token: str) -> dict:
        """Return a folder-level summary of a site's drive via delta query.

        Instead of listing every file (which can overflow agent context),
        aggregates into per-folder stats: file count, total size, and file
        type breakdown.  The agent uses this to orient, then drills into
        specific folders with list_files or search_files.
        """
        if not await self._is_site_allowed(site_id, user_token):
            return {"success": False, "error": "Access to this site is not allowed."}
        try:
            items = await self._client.delta(site_id, user_token)

            folders: dict[str, dict] = {}
            total_files = 0
            total_size = 0

            for item in items:
                if "deleted" in item:
                    continue

                parent = item.get("parentReference", {})
                parent_path = parent.get("path", "")
                drive_root = "/root:"
                idx = parent_path.find(drive_root)
                if idx >= 0:
                    folder = parent_path[idx + len(drive_root):].strip("/")
                else:
                    folder = ""

                if "folder" in item:
                    path = f"{folder}/{item.get('name', '')}" if folder else item.get("name", "")
                    if path not in folders:
                        folders[path] = {"file_count": 0, "total_size": 0, "types": {}}
                    continue

                if "file" not in item:
                    continue

                total_files += 1
                size = item.get("size", 0)
                total_size += size
                mime = item["file"].get("mimeType", "unknown")
                ext = mime.split("/")[-1] if "/" in mime else mime

                if folder not in folders:
                    folders[folder] = {"file_count": 0, "total_size": 0, "types": {}}
                folders[folder]["file_count"] += 1
                folders[folder]["total_size"] += size
                folders[folder]["types"][ext] = folders[folder]["types"].get(ext, 0) + 1

            tree = []
            for path in sorted(folders):
                info = folders[path]
                entry = {
                    "path": path or "/",
                    "file_count": info["file_count"],
                    "total_size": info["total_size"],
                }
                if info["types"]:
                    entry["file_types"] = info["types"]
                tree.append(entry)

            return {
                "success": True,
                "site_id": site_id,
                "total_files": total_files,
                "total_size": total_size,
                "folders": tree,
                "folder_count": len(tree),
            }
        except Exception as exc:
            logger.warning("list_all_files failed: %s", exc)
            return {"success": False, "error": str(exc)}
