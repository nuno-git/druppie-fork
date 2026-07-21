"""SearXNG v1 — MCP Tool Definitions.

Single source of truth for tool contract:
- Tool name, description, input schema via @mcp.tool()
- Version and module_id via @mcp.tool(meta={...})
- Agent guidance via FastMCP(instructions=...)
"""

from fastmcp import FastMCP

from .module import SearXNGModule

MODULE_ID = "searxng"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "SearXNG v1",
    version=MODULE_VERSION,
    instructions=(
        "Privacy-friendly web search via a self-hosted SearXNG instance. "
        "Use `search` to find pages on the web, then `fetch` to read a "
        "specific URL's content."
    ),
)

module = SearXNGModule()


@mcp.tool(
    name="search",
    description="Search the web via SearXNG (meta-search). Returns titles, URLs, and snippets.",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def search(
    query: str,
    categories: str = "general",
    language: str = "",
    max_results: int = 10,
) -> dict:
    return await module.search(
        query=query,
        categories=categories or None,
        language=language or None,
        max_results=max_results,
    )


@mcp.tool(
    name="fetch",
    description="Fetch and return the raw content of a URL (use on a result from search).",
    meta={"module_id": MODULE_ID, "version": MODULE_VERSION},
)
async def fetch(url: str) -> dict:
    return await module.fetch(url=url)
