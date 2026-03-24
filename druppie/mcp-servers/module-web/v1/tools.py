"""Web v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
from fastmcp import FastMCP
from .module import WebModule

MODULE_ID = "web"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "Web v1",
    version=MODULE_VERSION,
    instructions="Local file search and web browsing. Use for fetching web content, searching the web, and searching local datasets.",
)

SEARCH_ROOT = os.getenv("SEARCH_ROOT", "/dataset")
module = WebModule(search_root=SEARCH_ROOT)


@mcp.tool(
    name="search_files",
    description="Search for files containing text content matching query.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search_files(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict:
    return module.search_files(
        query=query,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        case_sensitive=case_sensitive,
    )


@mcp.tool(
    name="list_directory",
    description="List files and directories in search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def list_directory(
    path: str = ".",
    recursive: bool = False,
    show_hidden: bool = False,
) -> dict:
    return module.list_directory(
        path=path,
        recursive=recursive,
        show_hidden=show_hidden,
    )


@mcp.tool(
    name="read_file",
    description="Read file content from search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def read_file(path: str) -> dict:
    return module.read_file(path=path)


@mcp.tool(
    name="fetch_url",
    description="Fetch and return content from a URL.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def fetch_url(url: str) -> dict:
    return await module.fetch_url(url=url)


@mcp.tool(
    name="search_web",
    description="Search web for information.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search_web(query: str, num_results: int = 5) -> dict:
    return await module.search_web(query=query, num_results=num_results)


@mcp.tool(
    name="get_page_info",
    description="Get basic information about a web page.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_page_info(url: str) -> dict:
    return await module.get_page_info(url=url)
