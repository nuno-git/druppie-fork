"""Vision MCP Server - OCR-only text extraction.

Everything goes through the vision API. Per-page processing with automatic
DPI reduction on repeated failures. No silent failures — keeps retrying.
"""

import asyncio
import logging
import os

logger = logging.getLogger("vision-mcp")

DEEPINFRA_DEFAULT_VISION_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_DPI = 150
MIN_DPI = 75
DPI_STEP = 25
PAGE_TIMEOUT_SECONDS = 120
MAX_RETRIES_PER_PAGE = 10


class VisionModule:

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

    def _pdf_to_images(self, pdf_path: str, dpi: int = DEFAULT_DPI, pages: list[int] | None = None) -> tuple[list[str], str]:
        """Convert PDF pages to PNG images. Returns (image_paths, tmpdir)."""
        import tempfile
        from pdf2image import convert_from_path
        tmpdir = tempfile.mkdtemp()
        kwargs = dict(dpi=dpi, output_folder=tmpdir, fmt="png")
        if pages:
            kwargs["first_page"] = min(pages)
            kwargs["last_page"] = max(pages)
        images = convert_from_path(pdf_path, **kwargs)
        paths = []
        for i, img in enumerate(images):
            p = os.path.join(tmpdir, f"page_{i + 1}.png")
            img.save(p, "PNG", optimize=True)
            paths.append(p)
        logger.info("PDF → %d page(s) at %d DPI", len(paths), dpi)
        return paths, tmpdir

    async def _ocr_page_zai(self, session, image_path: str, page_num: int, prompt: str) -> str:
        """OCR a single page. Retries up to MAX_RETRIES_PER_PAGE times.
        After every 5 failures, re-renders the page at lower DPI."""
        current_path = image_path
        current_dpi = DEFAULT_DPI

        for attempt in range(1, MAX_RETRIES_PER_PAGE + 1):
            try:
                result = await asyncio.wait_for(
                    session.call_tool("extract_text_from_screenshot", {
                        "image_source": current_path,
                        "prompt": prompt or "Extract all text from this document",
                    }),
                    timeout=PAGE_TIMEOUT_SECONDS,
                )
                text = result.content[0].text if result.content else ""
                if text.strip():
                    return text
                logger.warning("Page %d: empty OCR result (attempt %d/%d)", page_num, attempt, MAX_RETRIES_PER_PAGE)
            except asyncio.TimeoutError:
                logger.warning("Page %d: timed out (attempt %d/%d)", page_num, attempt, MAX_RETRIES_PER_PAGE)
            except Exception as e:
                logger.warning("Page %d: %s (attempt %d/%d)", page_num, e, attempt, MAX_RETRIES_PER_PAGE)

            if attempt % 5 == 0:
                current_dpi = max(current_dpi - DPI_STEP, MIN_DPI)
                logger.info("Page %d: lowering DPI to %d for retry", page_num, current_dpi)
                current_path = self._rerender_at_dpi(current_path, page_num, current_dpi)

        logger.error("Page %d: failed after %d attempts", page_num, MAX_RETRIES_PER_PAGE)
        return ""

    def _rerender_at_dpi(self, current_image: str, page_num: int, dpi: int) -> str:
        """Re-render the current page image at a lower DPI by re-scaling."""
        from PIL import Image
        import tempfile

        img = Image.open(current_image)
        scale = dpi / DEFAULT_DPI
        new_w = max(int(img.width * scale), 100)
        new_h = max(int(img.height * scale), 100)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        new_path = os.path.join(os.path.dirname(current_image), f"page_{page_num}_dpi{dpi}.png")
        resized.save(new_path, "PNG", optimize=True)
        img.close()
        return new_path

    async def _ocr_all_pages_zai(self, image_paths: list[str], prompt: str) -> list[str]:
        """OCR all pages sequentially with per-page retry."""
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

        results: list[str] = []
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for idx, path in enumerate(image_paths):
                    text = await self._ocr_page_zai(session, path, idx + 1, prompt)
                    results.append(text)
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

    def _resolve_to_file(self, image_source: str) -> tuple[str, bool]:
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

    async def ocr(self, image_source: str, prompt: str = "") -> str:
        """Extract text via OCR. Processes ALL pages with retry."""
        if not self._zai_key and not self._deepinfra_key:
            raise RuntimeError("No vision provider configured — set ZAI_API_KEY or DEEPINFRA_API_KEY")

        file_path, is_temp = self._resolve_to_file(image_source)
        try:
            if self._is_pdf(file_path):
                import shutil
                image_paths, tmpdir = self._pdf_to_images(file_path)
                try:
                    if self._provider == "zai":
                        results = await self._ocr_all_pages_zai(image_paths, prompt)
                    else:
                        results = [self._call_deepinfra(p, prompt or "Extract all text") for p in image_paths]
                    parts = [f"--- Pagina {i + 1} ---\n{text}" for i, text in enumerate(results)]
                    return "\n\n".join(parts)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if self._provider == "zai":
                results = await self._ocr_all_pages_zai([file_path], prompt)
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
                import tempfile, shutil
                from pdf2image import convert_from_path
                tmpdir = tempfile.mkdtemp()
                try:
                    images = convert_from_path(
                        file_path, dpi=DEFAULT_DPI, output_folder=tmpdir, fmt="png",
                        first_page=1, last_page=1,
                    )
                    page_path = os.path.join(tmpdir, "page_1.png")
                    images[0].save(page_path, "PNG", optimize=True)
                    if self._provider == "zai":
                        return await self._analyze_with_zai(page_path, prompt)
                    else:
                        return self._call_deepinfra(page_path, prompt)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if self._provider == "zai":
                return await self._analyze_with_zai(file_path, prompt)
            else:
                return self._call_deepinfra(image_source, prompt)
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
                # For analysis, only need first page
                tmpdir = tempfile.mkdtemp()
                images = []
                from pdf2image import convert_from_path
                try:
                    images = convert_from_path(
                        file_path, dpi=OCR_DPI, output_folder=tmpdir, fmt="png",
                        first_page=1, last_page=1,
                    )
                    page_path = os.path.join(tmpdir, "page_1.png")
                    images[0].save(page_path, "PNG", optimize=True)

                    if self._provider == "zai":
                        return await self._analyze_with_zai(page_path, prompt)
                    else:
                        return self._call_deepinfra(page_path, prompt)
                finally:
                    import shutil
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if self._provider == "zai":
                return await self._analyze_with_zai(file_path, prompt)
            else:
                return self._call_deepinfra(image_source, prompt)
        finally:
            if is_temp:
                os.unlink(file_path)
