"""File Search v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

import os
from fastmcp import FastMCP
from .module import FileSearchModule

MODULE_ID = "filesearch"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "File Search v1",
    version=MODULE_VERSION,
    instructions="""Local file search within a dataset directory.

Use when:
- Searching for text content in local files
- Listing files in a dataset directory
- Reading file content from the dataset

Don't use when:
- You need web search (use web module)
- You need workspace file operations (use coding module)
""",
)

SEARCH_ROOT = os.getenv("SEARCH_ROOT", "/dataset")
module = FileSearchModule(search_root=SEARCH_ROOT)


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
    name="get_search_stats",
    description="Get statistics about files in search path.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def get_search_stats(path: str = ".") -> dict:
    return module.get_search_stats(path=path)
