"""Vision MCP Server - OCR via PaddleOCR-VL (DeepInfra).

Direct HTTP calls to DeepInfra's PaddleOCR-VL-0.9B — a dedicated OCR model.
Pages are processed in parallel via async HTTP. Falls back to ZAI MCP server
if DEEPINFRA_API_KEY is not set.
"""

import asyncio
import base64
import logging
import os

import httpx

logger = logging.getLogger("vision-mcp")

PADDLEOCR_MODEL = "PaddlePaddle/PaddleOCR-VL-0.9B"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_DPI = 150
OCR_TIMEOUT = 30
MAX_CONCURRENT_PAGES = 8


class VisionModule:

    def __init__(self):
        self._deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")
        self._zai_key = os.environ.get("ZAI_API_KEY", "")

        if self._deepinfra_key:
            self._provider = "deepinfra"
            logger.info("Vision provider: DeepInfra PaddleOCR-VL (parallel HTTP)")
        elif self._zai_key:
            self._provider = "zai"
            logger.info("Vision provider: Z.AI MCP server (sequential)")
        else:
            self._provider = "none"
            logger.warning("No vision API key set — vision calls will fail")

    @property
    def provider(self) -> str:
        return self._provider

    # -----------------------------------------------------------------
    # PDF → images
    # -----------------------------------------------------------------

    def _pdf_to_images(self, pdf_path: str) -> tuple[list[str], str]:
        import tempfile
        from pdf2image import convert_from_path
        tmpdir = tempfile.mkdtemp()
        images = convert_from_path(pdf_path, dpi=DEFAULT_DPI, output_folder=tmpdir, fmt="png")
        paths = []
        for i, img in enumerate(images):
            p = os.path.join(tmpdir, f"page_{i + 1}.png")
            img.save(p, "PNG", optimize=True)
            paths.append(p)
        logger.info("PDF → %d page(s) at %d DPI", len(paths), DEFAULT_DPI)
        return paths, tmpdir

    # -----------------------------------------------------------------
    # DeepInfra PaddleOCR (parallel async HTTP)
    # -----------------------------------------------------------------

    async def _ocr_page_deepinfra(self, client: httpx.AsyncClient, image_path: str, page_num: int) -> str:
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        resp = await client.post(
            f"{DEEPINFRA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {self._deepinfra_key}"},
            json={
                "model": PADDLEOCR_MODEL,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        logger.info("Page %d: %d chars via PaddleOCR", page_num, len(text))
        return text

    async def _ocr_pages_parallel(self, image_paths: list[str]) -> list[str]:
        sem = asyncio.Semaphore(MAX_CONCURRENT_PAGES)
        async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
            async def limited(page_num, path):
                async with sem:
                    return await self._ocr_page_deepinfra(client, path, page_num)
            return await asyncio.gather(*[limited(i + 1, p) for i, p in enumerate(image_paths)])

    # -----------------------------------------------------------------
    # ZAI MCP fallback (sequential)
    # -----------------------------------------------------------------

    async def _ocr_all_pages_zai(self, image_paths: list[str], prompt: str) -> list[str]:
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
                    result = await session.call_tool("extract_text_from_screenshot", {
                        "image_source": path,
                        "prompt": prompt or "Extract all text from this document",
                    })
                    results.append(result.content[0].text if result.content else "")
        return results

    async def _analyze_single_zai(self, image_path: str, prompt: str) -> str:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = StdioServerParameters(
            command="npx", args=["-y", "@z_ai/mcp-server"],
            env={"Z_AI_API_KEY": self._zai_key, "Z_AI_MODE": "ZAI",
                 "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/root")},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("analyze_image", {"image_source": image_path, "prompt": prompt})
                return result.content[0].text if result.content else ""

    # -----------------------------------------------------------------
    # File helpers
    # -----------------------------------------------------------------

    def _resolve_to_file(self, image_source: str) -> tuple[str, bool]:
        if image_source.startswith("data:"):
            import tempfile
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

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    async def ocr(self, image_source: str, prompt: str = "") -> str:
        """Extract text via OCR. All pages, parallel if DeepInfra."""
        if self._provider == "none":
            raise RuntimeError("No vision provider configured — set DEEPINFRA_API_KEY or ZAI_API_KEY")

        file_path, is_temp = self._resolve_to_file(image_source)
        try:
            if self._is_pdf(file_path):
                import shutil
                image_paths, tmpdir = self._pdf_to_images(file_path)
                try:
                    if self._provider == "deepinfra":
                        results = await self._ocr_pages_parallel(image_paths)
                    else:
                        results = await self._ocr_all_pages_zai(image_paths, prompt)
                    parts = [f"--- Pagina {i + 1} ---\n{text}" for i, text in enumerate(results)]
                    return "\n\n".join(parts)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            # Single image
            if self._provider == "deepinfra":
                results = await self._ocr_pages_parallel([file_path])
                return results[0] if results else ""
            else:
                results = await self._ocr_all_pages_zai([file_path], prompt)
                return results[0] if results else ""

        finally:
            if is_temp:
                os.unlink(file_path)

    async def analyze(self, image_source: str, prompt: str = "Describe this image.") -> str:
        """Analyze and describe an image or first page of a PDF."""
        if self._provider == "none":
            raise RuntimeError("No vision provider configured — set DEEPINFRA_API_KEY or ZAI_API_KEY")

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

                    if self._provider == "deepinfra":
                        b64 = base64.b64encode(open(page_path, "rb").read()).decode()
                        async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
                            resp = await client.post(
                                f"{DEEPINFRA_BASE_URL}/chat/completions",
                                headers={"Authorization": f"Bearer {self._deepinfra_key}"},
                                json={"model": PADDLEOCR_MODEL, "max_tokens": 4096,
                                      "messages": [{"role": "user", "content": [
                                          {"type": "image_url", "image_url": {
                                              "url": f"data:image/png;base64,{b64}"}}]}]},
                            )
                            return resp.json()["choices"][0]["message"]["content"]
                    else:
                        return await self._analyze_single_zai(page_path, prompt)
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if self._provider == "deepinfra":
                b64 = base64.b64encode(open(file_path, "rb").read()).decode()
                async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
                    resp = await client.post(
                        f"{DEEPINFRA_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {self._deepinfra_key}"},
                        json={"model": PADDLEOCR_MODEL, "max_tokens": 4096,
                              "messages": [{"role": "user", "content": [
                                  {"type": "image_url", "image_url": {
                                      "url": f"data:image/png;base64,{b64}"}}]}]},
                    )
                    return resp.json()["choices"][0]["message"]["content"]
            else:
                return await self._analyze_single_zai(file_path, prompt)
        finally:
            if is_temp:
                os.unlink(file_path)
