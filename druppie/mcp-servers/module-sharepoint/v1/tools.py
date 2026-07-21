"""SharePoint v1 — MCP Tool Definitions.

Read-only access to files in a configured SharePoint folder via Microsoft
Graph API. The site and folder are fixed by server configuration
(SHAREPOINT_SITE_ID, SHAREPOINT_FOLDER_PATH) and are never tool arguments,
so an agent cannot access any other site or folder.

All operations use delegated (OBO) authentication — the agent reads as the
logged-in user. There are no write tools.
"""

import logging

from fastmcp import FastMCP

from .module import SharePointModule

logger = logging.getLogger("sharepoint-mcp")

MODULE_ID = "sharepoint"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "SharePoint v1",
    version=MODULE_VERSION,
    instructions=(
        "Read-only access to files in a configured SharePoint folder. "
        "All operations use delegated (OBO) authentication — "
        "the agent reads as the logged-in user."
    ),
)

module = SharePointModule()


@mcp.tool()
async def list_files(
    subfolder: str | None = None,
    user_token: str | None = None,
) -> dict:
    """List files and folders in the configured SharePoint folder.

    Returns a list of items (files and folders) with their metadata.
    Use the returned file IDs with read_file() or get_file_metadata()
    for more details.

    Args:
        subfolder: Optional subfolder path relative to the configured root
                   folder. Example: "reports/2026" to list files in that
                   subfolder.
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with folder path, items (id, name, type, web_url, size,
        mime_type, last_modified, child_count), and count.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.list_files(user_token, subfolder)


@mcp.tool()
async def read_file(
    file_id: str,
    user_token: str | None = None,
) -> dict:
    """Read a file from SharePoint. Returns text content for text-based files,
    or metadata with a web_url link for binary/Office files.

    Use list_files() first to find the file_id.

    Args:
        file_id: The drive item ID of the file to read (from list_files
                 results).
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with file metadata and either content (for text files) or a
        message with web_url (for binary files). The content_included field
        indicates whether the file content is in the response.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.read_file(file_id, user_token)


@mcp.tool()
async def get_file_metadata(
    file_id: str,
    user_token: str | None = None,
) -> dict:
    """Get metadata for a file or folder without downloading its content.

    Returns: name, size, type, dates, author, web_url.

    Args:
        file_id: The drive item ID (from list_files results).
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with id, name, size, type, mime_type, web_url, dates,
        created_by, and modified_by.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.get_file_metadata(file_id, user_token)


@mcp.tool()
async def search_files(
    query: str,
    user_token: str | None = None,
) -> dict:
    """Search for files within the configured SharePoint site.

    Searches file names and content. Returns matching files with metadata.

    Args:
        query: Search query string (e.g. "budget report", "meeting notes").
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with query, items (id, name, type, web_url, size,
        last_modified, mime_type, path), and count.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.search_files(query, user_token)
