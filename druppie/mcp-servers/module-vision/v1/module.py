"""Vision MCP Server - Business Logic Module.

Strategy for text extraction:
1. PDFs: try pdfplumber first (fast, no AI). If text found, use it.
   Only fall back to OCR for scanned/image PDFs with no extractable text.
2. Images: always use Z.AI MCP server for OCR.
3. OCR uses a single MCP session for all pages (no per-page npx spawn).
"""

import asyncio
import logging
import os

logger = logging.getLogger("vision-mcp")

DEEPINFRA_DEFAULT_VISION_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
MAX_OCR_PAGES = 3  # limit OCR to first N pages (each takes ~20s)


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
            logger.warning("No vision API key set — vision calls will fail")

    @property
    def provider(self) -> str:
        return self._provider

    # -----------------------------------------------------------------
    # PDF text extraction (no AI needed)
    # -----------------------------------------------------------------

    def _extract_pdf_text(self, pdf_path: str) -> str | None:
        """Try extracting text directly from PDF (works for text-based PDFs).

        Returns extracted text if found, None if the PDF is scanned/image-only.
        """
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed — skipping direct text extraction")
            return None

        try:
            all_text = []
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text and text.strip():
                        all_text.append(f"--- Pagina {i + 1} ---\n{text.strip()}")

            if all_text:
                combined = "\n\n".join(all_text)
                logger.info("Extracted text from %d PDF pages (no OCR needed)", len(all_text))
                return combined

            logger.info("No extractable text in PDF — falling back to OCR")
            return None

        except Exception as e:
            logger.warning("PDF text extraction failed: %s — falling back to OCR", e)
            return None

    # -----------------------------------------------------------------
    # Z.AI MCP vision (single session for multiple calls)
    # -----------------------------------------------------------------

    async def _ocr_with_zai(self, image_paths: list[str], prompt: str) -> list[str]:
        """OCR multiple images in a single MCP session (one npx spawn)."""
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

        results = []
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for path in image_paths:
                    try:
                        result = await session.call_tool("extract_text_from_screenshot", {
                            "image_source": path,
                            "prompt": prompt or "Extract all text from this document",
                        })
                        text = result.content[0].text if result.content else ""
                        results.append(text)
                    except Exception as e:
                        logger.error("OCR failed for %s: %s", path, e)
                        results.append(f"[OCR fout: {e}]")
        return results

    async def _analyze_with_zai(self, image_path: str, prompt: str) -> str:
        """Analyze a single image via Z.AI MCP."""
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
                result = await session.call_tool("analyze_image", {
                    "image_source": image_path,
                    "prompt": prompt,
                })
                return result.content[0].text if result.content else ""

    # -----------------------------------------------------------------
    # DeepInfra fallback
    # -----------------------------------------------------------------

    def _call_deepinfra(self, image_url: str, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self._deepinfra_key, base_url=DEEPINFRA_BASE_URL)
        content = [{"type": "image_url", "image_url": {"url": image_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        response = client.chat.completions.create(
            model=DEEPINFRA_DEFAULT_VISION_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content

    # -----------------------------------------------------------------
    # File handling helpers
    # -----------------------------------------------------------------

    def _resolve_to_file(self, image_source: str) -> tuple[str, bool]:
        """Resolve to local file. Returns (path, is_temp)."""
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

    def _pdf_to_images(self, pdf_path: str, max_pages: int = MAX_OCR_PAGES) -> tuple[list[str], str]:
        """Convert PDF pages to PNG images. Returns (image_paths, tmpdir)."""
        import tempfile
        from pdf2image import convert_from_path
        tmpdir = tempfile.mkdtemp()
        images = convert_from_path(
            pdf_path, dpi=200, output_folder=tmpdir, fmt="png",
            first_page=1, last_page=max_pages,
        )
        paths = []
        for i, img in enumerate(images):
            p = os.path.join(tmpdir, f"page_{i + 1}.png")
            img.save(p, "PNG")
            paths.append(p)
        logger.info("PDF → %d page image(s) (max %d)", len(paths), max_pages)
        return paths, tmpdir

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    async def ocr(self, image_source: str, prompt: str = "") -> str:
        """Extract text from an image or PDF.

        For PDFs: tries direct text extraction first (fast). Falls back
        to OCR only for scanned/image PDFs. OCR limited to first 3 pages.
        """
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        file_path, is_temp = self._resolve_to_file(image_source)
        try:
            # PDF: try direct text extraction first
            if self._is_pdf(file_path):
                direct_text = self._extract_pdf_text(file_path)
                if direct_text:
                    return direct_text

                # Scanned PDF — convert to images and OCR
                if self._provider == "zai":
                    import shutil
                    image_paths, tmpdir = self._pdf_to_images(file_path)
                    try:
                        results = await self._ocr_with_zai(image_paths, prompt)
                        parts = [f"--- Pagina {i + 1} ---\n{text}" for i, text in enumerate(results)]
                        return "\n\n".join(parts)
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                else:
                    return self._call_deepinfra(image_source, prompt or "Extract all text")

            # Image: OCR directly
            if self._provider == "zai":
                results = await self._ocr_with_zai([file_path], prompt)
                return results[0] if results else ""
            else:
                return self._call_deepinfra(image_source, prompt or "Extract all text")

        finally:
            if is_temp:
                os.unlink(file_path)

    async def analyze(self, image_source: str, prompt: str = "Describe this image.") -> str:
        """Analyze and describe an image or first page of a PDF."""
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        file_path, is_temp = self._resolve_to_file(image_source)
        try:
            if self._is_pdf(file_path):
                import shutil
                image_paths, tmpdir = self._pdf_to_images(file_path, max_pages=1)
                try:
                    if self._provider == "zai":
                        return await self._analyze_with_zai(image_paths[0], prompt)
                    else:
                        return self._call_deepinfra(image_paths[0], prompt)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if self._provider == "zai":
                return await self._analyze_with_zai(file_path, prompt)
            else:
                return self._call_deepinfra(image_source, prompt)
        finally:
            if is_temp:
                os.unlink(file_path)
