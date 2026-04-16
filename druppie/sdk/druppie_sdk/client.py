"""DruppieClient — call Druppie platform modules via the backend proxy."""

import os

import httpx


class DruppieClient:
    """Client for calling Druppie platform modules.

    All calls are proxied through the backend, which handles the MCP
    protocol. Apps only need DRUPPIE_URL (the backend address).

    Usage:
        from druppie_sdk import DruppieClient

        druppie = DruppieClient()
        result = druppie.call("llm", "chat", {"prompt": "Hello"})
        result = druppie.call("vision", "ocr", {"image_source": "data:image/jpeg;base64,..."})
        modules = druppie.list_modules()
    """

    def __init__(self, base_url: str | None = None, timeout: float = 60.0):
        self._base_url = (base_url or os.environ.get("DRUPPIE_URL", "http://druppie-backend:8000")).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def call(self, module: str, tool: str, arguments: dict | None = None, *, version: str | None = None) -> dict:
        """Call a tool on a Druppie module via the backend proxy.

        Args:
            module: Module ID (e.g. "llm", "vision", "audio").
            tool: Tool name (e.g. "chat", "ocr", "transcribe").
            arguments: Tool arguments dict.
            version: Optional version pin (reserved for future use).

        Returns:
            The result dict from the module.

        Raises:
            httpx.HTTPStatusError: If the call fails.
            RuntimeError: If the module returns an error.
        """
        resp = self._client.post(
            f"{self._base_url}/api/modules/{module}/call",
            json={"tool": tool, "arguments": arguments or {}},
        )
        resp.raise_for_status()
        body = resp.json()

        if isinstance(body, dict) and "error" in body:
            raise RuntimeError(f"Module error from {module}/{tool}: {body['error']}")

        return body

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
