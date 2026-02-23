"""Bestand Zoeker MCP Server.

Provides tools for local file search and web browsing.
Combines file search capabilities with web content retrieval.
Uses FastMCP framework for HTTP transport.
"""

import logging
import os

from fastmcp import FastMCP

from module import WebModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bestand-zoeker")

mcp = FastMCP("Bestand Zoeker MCP Server")

SEARCH_ROOT = os.getenv("SEARCH_ROOT", "/dataset")

module = WebModule(search_root=SEARCH_ROOT)


@mcp.tool()
async def fetch_url(url: str) -> dict:
    """Fetch and return content from a URL."""
    return await module.fetch_url(url=url)


@mcp.tool()
async def search_web(query: str, num_results: int = 5) -> dict:
    """Search web for information."""
    return await module.search_web(query=query, num_results=num_results)


@mcp.tool()
async def get_page_info(url: str) -> dict:
    """Get basic information about a web page."""
    return await module.get_page_info(url=url)


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


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "bestand-zoeker",
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9004"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
