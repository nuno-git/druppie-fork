"""DruppieClient — discover and call Druppie platform modules via MCP JSON-RPC."""

import os
import time

import httpx

_CACHE_TTL = 300  # seconds


class DruppieClient:
    """Client for calling Druppie platform modules.

    Usage:
        from druppie_sdk import DruppieClient

        druppie = DruppieClient()
        result = druppie.call("llm", "chat", {"prompt": "Hello"})
        result = druppie.call("llm", "chat", {"prompt": "Hi"}, version="1")
        modules = druppie.list_modules()
    """

    def __init__(self, base_url: str | None = None, timeout: float = 60.0):
        self._base_url = (base_url or os.environ.get("DRUPPIE_URL", "http://druppie-backend:8000")).rstrip("/")
        self._timeout = timeout
        self._endpoint_cache: dict[str, tuple[str, float]] = {}
        self._client = httpx.Client(timeout=self._timeout)
        self._call_id = 0

    def _discover(self, module_id: str) -> str:
        """Discover module URL via backend, cache result with TTL."""
        cached = self._endpoint_cache.get(module_id)
        if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
            return cached[0]

        resp = self._client.get(f"{self._base_url}/api/modules/{module_id}/endpoint")
        resp.raise_for_status()
        url = resp.json()["url"]
        self._endpoint_cache[module_id] = (url, time.monotonic())
        return url

    def call(self, module: str, tool: str, arguments: dict | None = None, *, version: str | None = None) -> dict:
        """Call a tool on a Druppie module via MCP JSON-RPC.

        Args:
            module: Module ID (e.g. "llm", "web").
            tool: Tool name (e.g. "chat", "search_web").
            arguments: Tool arguments dict.
            version: Optional version pin (e.g. "1" routes to /v1/mcp).

        Returns:
            The result dict from the MCP response.

        Raises:
            httpx.HTTPStatusError: If discovery or tool call fails.
            RuntimeError: If the MCP response contains an error.
        """
        base = self._discover(module)

        if version:
            mcp_url = f"{base}/v{version}/mcp"
        else:
            mcp_url = f"{base}/mcp"

        self._call_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._call_id,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": arguments or {},
            },
        }

        resp = self._client.post(mcp_url, json=payload)
        resp.raise_for_status()
        body = resp.json()

        if "error" in body:
            raise RuntimeError(f"MCP error from {module}/{tool}: {body['error']}")

        return body.get("result", body)

    def list_modules(self) -> list[dict]:
        """List available modules from the backend.

        Returns:
            List of module dicts with id, url, and type fields.
        """
        resp = self._client.get(f"{self._base_url}/api/modules")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
