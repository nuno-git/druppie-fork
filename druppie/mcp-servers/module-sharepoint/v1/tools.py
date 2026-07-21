"""SharePoint v1 — MCP Tool Definitions.

Read-only access to SharePoint sites via Microsoft Graph API. The agent can
discover sites the user has access to, then browse and read files within them.

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
        "Read-only access to SharePoint sites the user has access to. "
        "Use list_sites first to discover available sites, then browse "
        "files with list_files, read_file, etc. "
        "All operations use delegated (OBO) authentication."
    ),
)

module = SharePointModule()


@mcp.tool()
async def list_sites(
    query: str = "",
    user_token: str | None = None,
) -> dict:
    """List SharePoint sites the user has access to.

    Args:
        query: Optional search query to filter sites by name.
               Leave empty to list all accessible sites.
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with sites (id, name, web_url, description) and count.
        Use the site id with other tools to browse that site's files.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.list_sites(user_token, query)


@mcp.tool()
async def resolve_site_url(
    url: str,
    user_token: str | None = None,
) -> dict:
    """Resolve a SharePoint site URL to its site ID.

    Use this when you have a SharePoint URL (e.g. from the user) and need
    the site ID for other tools. Works with Files.Read.All permission.

    Args:
        url: Full SharePoint site URL, e.g.
             "https://contoso.sharepoint.com/sites/TeamSite"
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with site id, name, web_url, and description.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.resolve_site_url(url, user_token)


@mcp.tool()
async def list_files(
    site_id: str,
    folder_path: str | None = None,
    user_token: str | None = None,
) -> dict:
    """List files and folders on a SharePoint site.

    Args:
        site_id: The SharePoint site ID (from list_sites results).
        folder_path: Optional folder path to list. Omit to list the drive root.
                     Example: "Documents/Reports/2026"
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with folder path, items (id, name, type, web_url, size,
        mime_type, last_modified, child_count), and count.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.list_files(site_id, user_token, folder_path)


@mcp.tool()
async def read_file(
    site_id: str,
    file_id: str,
    user_token: str | None = None,
) -> dict:
    """Read a file from SharePoint. Returns text content for text-based files,
    or metadata with a web_url link for binary/Office files.

    Args:
        site_id: The SharePoint site ID.
        file_id: The drive item ID of the file to read (from list_files).
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with file metadata and either content (for text files) or a
        message with web_url (for binary files).
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.read_file(site_id, file_id, user_token)


@mcp.tool()
async def get_file_metadata(
    site_id: str,
    file_id: str,
    user_token: str | None = None,
) -> dict:
    """Get metadata for a file or folder without downloading its content.

    Args:
        site_id: The SharePoint site ID.
        file_id: The drive item ID (from list_files results).
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with id, name, size, type, mime_type, web_url, dates,
        created_by, and modified_by.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.get_file_metadata(site_id, file_id, user_token)


@mcp.tool()
async def search_files(
    site_id: str,
    query: str,
    user_token: str | None = None,
) -> dict:
    """Search for files within a SharePoint site.

    Args:
        site_id: The SharePoint site ID.
        query: Search query string (e.g. "budget report", "meeting notes").
        user_token: Entra ID access token (injected automatically, do not
                    provide).

    Returns:
        Dict with query, items (id, name, type, web_url, size,
        last_modified, mime_type, path), and count.
    """
    if not user_token:
        return {"success": False, "error": "Entra ID authentication required"}
    return await module.search_files(site_id, query, user_token)
