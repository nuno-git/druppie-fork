"""Vision MCP Server - Business Logic Module.

Wraps Z.AI's MCP vision server (@z_ai/mcp-server) for image analysis and OCR.
Falls back to DeepInfra PaddleOCR if ZAI_API_KEY is not set.

The Z.AI coding plan includes vision via their MCP server (stdio), not via
the OpenAI-compatible chat API. This module spawns the Z.AI MCP server as
a subprocess and proxies calls to it.
"""

import asyncio
import logging
import os

logger = logging.getLogger("vision-mcp")

# DeepInfra fallback
DEEPINFRA_DEFAULT_VISION_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class VisionModule:
    """Business logic for vision/OCR operations."""

    def __init__(self):
        self._zai_key = os.environ.get("ZAI_API_KEY", "")
        self._deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")

        if self._zai_key:
            self._provider = "zai"
            logger.info("Vision provider: Z.AI MCP server (@z_ai/mcp-server)")
        elif self._deepinfra_key:
            self._provider = "deepinfra"
            logger.info("Vision provider: DeepInfra (model=%s)", DEEPINFRA_DEFAULT_VISION_MODEL)
        else:
            self._provider = "none"
            logger.warning("No vision API key set (ZAI_API_KEY or DEEPINFRA_API_KEY) — vision calls will fail")

    @property
    def provider(self) -> str:
        return self._provider

    async def _call_zai_mcp(self, tool_name: str, arguments: dict) -> str:
        """Call the Z.AI MCP server via stdio."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = StdioServerParameters(
            command="npx",
            args=["-y", "@z_ai/mcp-server"],
            env={
                "Z_AI_API_KEY": self._zai_key,
                "Z_AI_MODE": "ZAI",
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", "/root"),
            },
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.content:
                    return result.content[0].text
                return ""

    def _call_deepinfra(self, image_url: str, prompt: str) -> str:
        """Fall back to DeepInfra OpenAI-compatible vision."""
        from openai import OpenAI

        client = OpenAI(
            api_key=self._deepinfra_key,
            base_url=DEEPINFRA_BASE_URL,
        )
        content = [{"type": "image_url", "image_url": {"url": image_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})

        response = client.chat.completions.create(
            model=DEEPINFRA_DEFAULT_VISION_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content

    async def ocr(self, image_source: str, prompt: str = "") -> str:
        """Extract text from an image (OCR).

        Args:
            image_source: Local file path, URL, or base64 data URI.
            prompt: Optional prompt to guide extraction.
        """
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        if self._provider == "zai":
            # Z.AI MCP server handles local files, URLs, and base64
            # For base64 data URIs, write to a temp file first
            if image_source.startswith("data:"):
                import base64, tempfile
                # Parse data URI: data:mime;base64,XXXX
                header, b64data = image_source.split(",", 1)
                ext = "png"  # default
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "pdf" in header:
                    ext = "pdf"
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                    f.write(base64.b64decode(b64data))
                    temp_path = f.name
                try:
                    return await self._call_zai_mcp("extract_text_from_screenshot", {
                        "image_source": temp_path,
                        "prompt": prompt or "Extract all text from this document",
                    })
                finally:
                    os.unlink(temp_path)
            else:
                return await self._call_zai_mcp("extract_text_from_screenshot", {
                    "image_source": image_source,
                    "prompt": prompt or "Extract all text from this document",
                })
        else:
            return self._call_deepinfra(image_source, prompt or "Extract all text from this image.")

    async def analyze(self, image_source: str, prompt: str = "Describe this image.") -> str:
        """Analyze and describe an image.

        Args:
            image_source: Local file path, URL, or base64 data URI.
            prompt: What to analyze about the image.
        """
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        if self._provider == "zai":
            if image_source.startswith("data:"):
                import base64, tempfile
                header, b64data = image_source.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                    f.write(base64.b64decode(b64data))
                    temp_path = f.name
                try:
                    return await self._call_zai_mcp("analyze_image", {
                        "image_source": temp_path,
                        "prompt": prompt,
                    })
                finally:
                    os.unlink(temp_path)
            else:
                return await self._call_zai_mcp("analyze_image", {
                    "image_source": image_source,
                    "prompt": prompt,
                })
        else:
            return self._call_deepinfra(image_source, prompt)
