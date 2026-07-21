"""SharePoint module — read-only file access via Microsoft Graph.

Supports browsing any SharePoint site the user has access to. All operations
take a site_id parameter so the agent can discover sites and navigate them.
"""

import logging
import os

from .client import SharePointClient

logger = logging.getLogger("sharepoint-mcp")

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


class SharePointModule:
    """High-level file operations for SharePoint sites."""

    def __init__(self) -> None:
        self._client = SharePointClient()
        logger.info("SharePoint MCP initialized (multi-site mode)")

    async def list_sites(self, user_token: str, query: str = "") -> dict:
        """List SharePoint sites the user has access to."""
        try:
            sites = await self._client.search_sites(query, user_token)
            result = []
            for site in sites:
                result.append({
                    "id": site["id"],
                    "name": site.get("displayName", ""),
                    "web_url": site.get("webUrl", ""),
                    "description": site.get("description", ""),
                })
            return {
                "success": True,
                "sites": result,
                "count": len(result),
            }
        except Exception as exc:
            logger.warning("list_sites failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def list_files(
        self,
        site_id: str,
        user_token: str,
        folder_path: str | None = None,
    ) -> dict:
        """List files and folders on a site (at root or a specific folder)."""
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
        try:
            content_bytes, content_type, metadata = (
                await self._client.download_file(site_id, file_id, user_token)
            )
            name = metadata.get("name", "")
            ext = os.path.splitext(name)[1].lower() if name else ""

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
