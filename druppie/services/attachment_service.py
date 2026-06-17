"""Attachment service - file storage, validation, and text extraction."""

import base64
import mimetypes
import os
import re
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()

UPLOAD_DIR = Path(os.getenv("WORKSPACE_PATH", "/app/workspace")) / "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_EXTRACTED_TEXT = 50_000  # characters

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_OCR_MODEL = "google/gemma-4-31B-it"
OCR_PAGE_TIMEOUT = 120
OCR_MAX_PAGES = 50

_DEFAULT_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/x-python",
    "text/javascript",
    "text/html",
    "text/css",
    "text/xml",
    "application/json",
    "application/x-yaml",
    "text/yaml",
    "application/pdf",
}


def _load_allowed_content_types() -> set[str]:
    env_val = os.getenv("UPLOAD_ALLOWED_TYPES")
    if env_val:
        return {t.strip() for t in env_val.split(",") if t.strip()}
    return _DEFAULT_ALLOWED_CONTENT_TYPES.copy()


ALLOWED_CONTENT_TYPES = _load_allowed_content_types()

TEXT_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/x-python",
    "text/javascript",
    "text/html",
    "text/css",
    "text/xml",
    "application/json",
    "application/x-yaml",
    "text/yaml",
}

EXTENSION_TO_CONTENT_TYPE = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/javascript",
    ".jsx": "text/javascript",
    ".tsx": "text/javascript",
    ".html": "text/html",
    ".css": "text/css",
    ".xml": "text/xml",
    ".json": "application/json",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".pdf": "application/pdf",
}


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename)
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w\-]", "_", stem)
    ext = re.sub(r"[^\w.]", "_", ext)
    sanitized = f"{stem}{ext}" if ext else stem
    return sanitized[:200] if sanitized else "unnamed"


def resolve_content_type(filename: str, declared_type: str | None) -> str:
    ext = Path(filename).suffix.lower()
    if ext in EXTENSION_TO_CONTENT_TYPE:
        return EXTENSION_TO_CONTENT_TYPE[ext]
    if declared_type and declared_type != "application/octet-stream":
        return declared_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def validate_file(filename: str, content_type: str, size: int) -> None:
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {size} bytes (max {MAX_FILE_SIZE // 1024 // 1024} MB)")
    if size == 0:
        raise ValueError("File is empty")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"File type not allowed: {content_type}")


async def extract_text(file_path: Path, content_type: str) -> str | None:
    if content_type in TEXT_CONTENT_TYPES:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_EXTRACTED_TEXT]
        except Exception:
            logger.warning("text_extraction_failed", path=str(file_path))
            return None

    if content_type == "application/pdf":
        return await _extract_pdf_text(file_path)

    return None


async def _extract_pdf_text(file_path: Path) -> str | None:
    text = _extract_pdf_text_native(file_path)
    if text:
        return text
    return await _extract_pdf_text_ocr(file_path)


def _extract_pdf_text_native(file_path: Path) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        full_text = "\n".join(text_parts)
        return full_text[:MAX_EXTRACTED_TEXT] if full_text.strip() else None
    except ImportError:
        logger.info("pypdf_not_available", hint="Install pypdf for PDF text extraction")
        return None
    except Exception:
        logger.warning("pdf_native_extraction_failed", path=str(file_path))
        return None


def _render_pdf_page_to_png(file_path: Path, page_index: int) -> bytes | None:
    """Render a single PDF page to PNG bytes using pymupdf."""
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        if page_index >= len(doc):
            doc.close()
            return None
        page = doc[page_index]
        # 150 DPI for good OCR quality without excessive size
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
    except Exception:
        logger.warning("pdf_page_render_failed", path=str(file_path), page=page_index, exc_info=True)
        return None


def _get_pdf_page_count(file_path: Path) -> int:
    """Get the number of pages in a PDF."""
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


async def _extract_pdf_text_ocr(file_path: Path) -> str | None:
    """OCR fallback: render PDF pages to PNG, send to vision model."""
    api_key = os.getenv("DEEPINFRA_API_KEY", "")
    if not api_key:
        logger.info("deepinfra_ocr_skipped", reason="DEEPINFRA_API_KEY not set")
        return None

    page_count = _get_pdf_page_count(file_path)
    if page_count == 0:
        logger.warning("pdf_ocr_no_pages", path=str(file_path))
        return None

    pages_to_process = min(page_count, OCR_MAX_PAGES)
    if page_count > OCR_MAX_PAGES:
        logger.info("pdf_ocr_page_limit", path=str(file_path), total=page_count, processing=pages_to_process)

    text_parts = []
    try:
        async with httpx.AsyncClient() as client:
            for i in range(pages_to_process):
                png_bytes = _render_pdf_page_to_png(file_path, i)
                if png_bytes is None:
                    continue

                b64 = base64.b64encode(png_bytes).decode()
                image_content = {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }

                try:
                    resp = await client.post(
                        f"{DEEPINFRA_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=OCR_PAGE_TIMEOUT,
                        json={
                            "model": DEEPINFRA_OCR_MODEL,
                            "max_tokens": 8192,
                            "temperature": 0.0,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        image_content,
                                        {"type": "text", "text": "Extract all text from this document page. Return only the extracted text, preserving the original structure and formatting. Do not add commentary."},
                                    ],
                                }
                            ],
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    page_text = data["choices"][0]["message"]["content"]
                    if page_text and page_text.strip():
                        text_parts.append(page_text.strip())
                except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                    logger.warning("pdf_ocr_page_failed", path=str(file_path), page=i, error=str(e)[:200])
                    continue

        full_text = "\n".join(text_parts)
        if full_text.strip():
            logger.info("pdf_ocr_success", path=str(file_path), chars=len(full_text), pages=len(text_parts))
            return full_text[:MAX_EXTRACTED_TEXT]

        logger.warning("pdf_ocr_empty", path=str(file_path), pages_processed=pages_to_process)
        return None

    except ImportError:
        logger.warning("pymupdf_not_available", hint="Install pymupdf for PDF OCR support")
        return None
    except Exception:
        logger.warning("pdf_ocr_failed", path=str(file_path), exc_info=True)
        return None


def get_file_path(storage_path: str) -> Path:
    full_path = (UPLOAD_DIR.parent / storage_path).resolve()
    if not full_path.is_relative_to(UPLOAD_DIR.resolve()):
        raise ValueError("Invalid storage path")
    return full_path


def delete_file(storage_path: str) -> None:
    try:
        path = get_file_path(storage_path)
        if path.exists():
            path.unlink()
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
    except Exception:
        logger.warning("file_delete_failed", path=storage_path)
