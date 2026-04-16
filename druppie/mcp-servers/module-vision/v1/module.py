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

    def _resolve_to_file(self, image_source: str) -> tuple[str, bool]:
        """Resolve image_source to a local file path.

        Returns (file_path, is_temp) — caller must clean up if is_temp=True.
        """
        if image_source.startswith("data:"):
            import base64, tempfile
            header, b64data = image_source.split(",", 1)
            ext = "png"
            if "jpeg" in header or "jpg" in header:
                ext = "jpg"
            elif "pdf" in header:
                ext = "pdf"
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                f.write(base64.b64decode(b64data))
                return f.name, True
        return image_source, False

    def _is_pdf(self, path: str) -> bool:
        return path.lower().endswith(".pdf")

    async def _ocr_pdf(self, pdf_path: str, prompt: str) -> str:
        """Convert PDF pages to images and OCR each one."""
        import tempfile, shutil
        from pdf2image import convert_from_path

        tmpdir = tempfile.mkdtemp()
        try:
            images = convert_from_path(pdf_path, dpi=200, output_folder=tmpdir, fmt="png")
            logger.info("PDF converted to %d page(s)", len(images))

            all_text = []
            for i, img in enumerate(images):
                page_path = os.path.join(tmpdir, f"page_{i+1}.png")
                img.save(page_path, "PNG")
                page_prompt = prompt or f"Extract all text from page {i+1} of this document"
                text = await self._call_zai_mcp("extract_text_from_screenshot", {
                    "image_source": page_path,
                    "prompt": page_prompt,
                })
                all_text.append(f"--- Page {i+1} ---\n{text}")

            return "\n\n".join(all_text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def ocr(self, image_source: str, prompt: str = "") -> str:
        """Extract text from an image or PDF (OCR).

        Args:
            image_source: Local file path, URL, or base64 data URI.
                Supports images (JPG, PNG) and PDFs (converted page-by-page).
            prompt: Optional prompt to guide extraction.
        """
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        if self._provider == "zai":
            file_path, is_temp = self._resolve_to_file(image_source)
            try:
                if self._is_pdf(file_path):
                    return await self._ocr_pdf(file_path, prompt)
                return await self._call_zai_mcp("extract_text_from_screenshot", {
                    "image_source": file_path,
                    "prompt": prompt or "Extract all text from this document",
                })
            finally:
                if is_temp:
                    os.unlink(file_path)
        else:
            return self._call_deepinfra(image_source, prompt or "Extract all text from this image.")

    async def analyze(self, image_source: str, prompt: str = "Describe this image.") -> str:
        """Analyze and describe an image or PDF.

        Args:
            image_source: Local file path, URL, or base64 data URI.
            prompt: What to analyze about the image.
        """
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        if self._provider == "zai":
            file_path, is_temp = self._resolve_to_file(image_source)
            try:
                if self._is_pdf(file_path):
                    # For PDFs, analyze first page only
                    import tempfile, shutil
                    from pdf2image import convert_from_path
                    tmpdir = tempfile.mkdtemp()
                    try:
                        images = convert_from_path(file_path, dpi=200, output_folder=tmpdir, fmt="png", first_page=1, last_page=1)
                        page_path = os.path.join(tmpdir, "page_1.png")
                        images[0].save(page_path, "PNG")
                        return await self._call_zai_mcp("analyze_image", {
                            "image_source": page_path,
                            "prompt": prompt,
                        })
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                return await self._call_zai_mcp("analyze_image", {
                    "image_source": file_path,
                    "prompt": prompt,
                })
            finally:
                if is_temp:
                    os.unlink(file_path)
        else:
            return self._call_deepinfra(image_source, prompt)
