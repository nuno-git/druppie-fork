"""SearXNG MCP Server - Business Logic Module.

Thin async client over a SearXNG (/search) meta-search instance.
All network calls go through httpx; no MCP/FastMCP imports here.
"""

import logging
import os
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("searxng-mcp")

REQUEST_TIMEOUT = 30.0
DEFAULT_MAX_RESULTS = 10


class SearXNGModule:
    """Business logic module for SearXNG web search."""

    def __init__(self, base_url: str | None = None, timeout: float = REQUEST_TIMEOUT):
        self.base_url = (base_url or os.getenv("SEARXNG_URL", "http://localhost:8080")).rstrip("/")
        self.timeout = timeout

    async def search(
        self,
        query: str,
        categories: str | None = None,
        language: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> dict:
        """Run a SearXNG meta-search and return normalized results."""
        params: dict[str, object] = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }
        if categories:
            params["categories"] = categories
        if language:
            params["language"] = language

        url = f"{self.base_url}/search?{urlencode(params)}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception as e:
            logger.error("SearXNG search failed for %r: %s", query, e)
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "searxng_url": self.base_url,
            }

        results = []
        for r in payload.get("results", [])[:max_results]:
            results.append(
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": r.get("content"),
                    "engine": r.get("engine"),
                    "score": r.get("score"),
                    "category": r.get("category"),
                }
            )

        logger.info(
            "SearXNG search ok: query=%r results=%d (of %s)",
            query,
            len(results),
            payload.get("number_of_results"),
        )

        return {
            "success": True,
            "query": query,
            "categories": categories,
            "result_count": len(results),
            "number_of_results": payload.get("number_of_results"),
            "results": results,
        }

    async def fetch(self, url: str) -> dict:
        """Fetch raw content for a URL (typically a hit from search())."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                return {
                    "success": True,
                    "url": url,
                    "status_code": response.status_code,
                    "content": response.text[:10000],
                    "content_type": response.headers.get("content-type"),
                }
        except Exception as e:
            logger.error("Fetch failed for %s: %s", url, e)
            return {
                "success": False,
                "error": str(e),
                "url": url,
            }
