"""Web MCP Server.

Provides tools for web browsing and content retrieval.
Example server to demonstrate MCP integration.
"""

import httpx
import logging
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("web-mcp")

# Initialize FastMCP server
mcp = FastMCP("Web MCP Server")

# Request timeout in seconds
REQUEST_TIMEOUT = 30.0


@mcp.tool()
async def fetch_url(url: str) -> dict:
    """Fetch and return content from a URL.

    Args:
        url: The URL to fetch

    Returns:
        Dict with success, content, status_code
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url)

            return {
                "success": True,
                "url": url,
                "status_code": response.status_code,
                "content": response.text[:10000],  # Limit to 10k chars
            }
    except Exception as e:
        logger.error(f"Error fetching URL {url}: {e}")
        return {
            "success": False,
            "error": str(e),
            "url": url,
        }


@mcp.tool()
async def search_web(query: str, num_results: int = 5) -> dict:
    """Search the web for information.

    Args:
        query: Search query
        num_results: Number of results to return (default: 5)

    Returns:
        Dict with success, results array
    """
    # Note: This is a placeholder. In production, you'd use a real search API
    logger.info(f"Searching for: {query}")
    return {
        "success": True,
        "query": query,
        "results": [
            {
                "title": f"Result {i + 1} for '{query}'",
                "url": f"https://example.com/result{i + 1}",
                "snippet": f"This is a placeholder search result for {query}",
            }
            for i in range(min(num_results, 5))
        ],
    }


@mcp.tool()
async def get_page_info(url: str) -> dict:
    """Get basic information about a web page.

    Args:
        url: The URL to analyze

    Returns:
        Dict with title, description, links count
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url)

            # Simple HTML parsing to extract title
            content = response.text
            title = "No title found"
            if "<title>" in content:
                start = content.find("<title>") + 7
                end = content.find("</title>", start)
                title = content[start:end].strip()

            # Count links
            links_count = content.count("<a")

            return {
                "success": True,
                "url": url,
                "title": title,
                "links_count": links_count,
                "status_code": response.status_code,
            }
    except Exception as e:
        logger.error(f"Error getting page info for {url}: {e}")
        return {
            "success": False,
            "error": str(e),
            "url": url,
        }


if __name__ == "__main__":
    import uvicorn
    import os
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({
            "status": "healthy",
            "service": "web-mcp",
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9004"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
