"""File Search MCP Server.

Local file search with configurable search path (default: /dataset).
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP

from module import FileSearchModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("filesearch-mcp")

mcp = FastMCP("File Search MCP Server")

SEARCH_ROOT = os.getenv("SEARCH_ROOT", "/dataset")

module = FileSearchModule(search_root=SEARCH_ROOT)


@mcp.tool()
async def search_files(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict:
    """Search for files containing text content matching query."""
    return module.search_files(
        query=query,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        case_sensitive=case_sensitive,
    )


@mcp.tool()
async def list_directory(
    path: str = ".",
    recursive: bool = False,
    show_hidden: bool = False,
) -> dict:
    """List files and directories in search path."""
    return module.list_directory(
        path=path,
        recursive=recursive,
        show_hidden=show_hidden,
    )


@mcp.tool()
async def read_file(path: str) -> dict:
    """Read file content from search path."""
    return module.read_file(path=path)


@mcp.tool()
async def get_search_stats(path: str = ".") -> dict:
    """Get statistics about files in search path."""
    return module.get_search_stats(path=path)


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "filesearch-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9004"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
