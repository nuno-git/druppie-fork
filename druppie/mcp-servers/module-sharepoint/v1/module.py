"""SharePoint module — read-only file access via Microsoft Graph.

Reads the SharePoint site ID and root folder path from the environment,
builds a SharePointClient, and exposes high-level read operations consumed
by the MCP tools. The site and folder are fixed here; no operation accepts
a caller-supplied site or folder root.
"""

import logging
import os

from .client import SharePointClient

logger = logging.getLogger("sharepoint-mcp")

# Text-based MIME types that we can return as string content
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
    """High-level file operations for the configured SharePoint site."""

    def __init__(self) -> None:
        self._site_id = os.getenv("SHAREPOINT_SITE_ID", "").strip()
        self._folder_path = os.getenv("SHAREPOINT_FOLDER_PATH", "").strip()

        if not self._site_id:
            raise ValueError(
                "SHAREPOINT_SITE_ID environment variable is required"
            )
        if not self._folder_path:
            raise ValueError(
                "SHAREPOINT_FOLDER_PATH environment variable is required"
            )

        self._client = SharePointClient(self._site_id, self._folder_path)
        logger.info(
            "SharePoint MCP bound to site '%s', folder '%s'",
            self._site_id,
            self._folder_path,
        )

    async def list_files(
        self, user_token: str, subfolder: str | None = None
    ) -> dict:
        """List files and folders in the configured root (or a subfolder)."""
        try:
            items = await self._client.list_folder(user_token, subfolder)
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

            folder_display = self._folder_path
            if subfolder:
                folder_display = (
                    f"{self._folder_path}/{subfolder.strip('/')}"
                )

            return {
                "success": True,
                "folder": folder_display,
                "items": files,
                "count": len(files),
            }
        except Exception as exc:
            logger.warning("list_files failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def read_file(self, file_id: str, user_token: str) -> dict:
        """Read file: text content for text formats, metadata-only for binary."""
        try:
            content_bytes, content_type, metadata = await self._client.download_file(
                file_id, user_token
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
        self, file_id: str, user_token: str
    ) -> dict:
        """Get metadata for a file or folder without downloading content."""
        try:
            metadata = await self._client.get_item(file_id, user_token)
            name = metadata.get("name", "")

            result = {
                "success": True,
                "id": file_id,
                "name": name,
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

    async def search_files(self, query: str, user_token: str) -> dict:
        """Search files within the configured SharePoint site's drive."""
        try:
            items = await self._client.search(query, user_token)
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
                "query": query,
                "items": files,
                "count": len(files),
            }
        except Exception as exc:
            logger.warning("search_files failed: %s", exc)
            return {"success": False, "error": str(exc)}
