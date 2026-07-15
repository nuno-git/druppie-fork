"""Attachment service - file storage, validation, and text extraction."""

import asyncio
import base64
import mimetypes
import os
import re
from pathlib import Path
from uuid import UUID

import httpx
import structlog

logger = structlog.get_logger()

UPLOAD_DIR = Path(os.getenv("WORKSPACE_ROOT", "/app/workspace")) / "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_EXTRACTED_TEXT = 50_000  # characters

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_OCR_MODEL = "google/gemma-4-31B-it"
OCR_PAGE_TIMEOUT = 120
OCR_MAX_PAGES = 50
OCR_CONCURRENCY = 4
OCR_MAX_RETRIES = 2
OCR_RETRY_BACKOFF = 2.0

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


def _render_pdf_pages_to_png(file_path: Path, max_pages: int) -> list[bytes]:
    """Open PDF once, render up to max_pages pages to PNG bytes."""
    import pymupdf

    with pymupdf.open(str(file_path)) as doc:
        page_count = len(doc)
        pages_to_render = min(page_count, max_pages)
        if page_count > max_pages:
            logger.info("pdf_ocr_page_limit", path=str(file_path), total=page_count, processing=pages_to_render)

        results = []
        for i in range(pages_to_render):
            try:
                pix = doc[i].get_pixmap(dpi=150)
                results.append(pix.tobytes("png"))
            except Exception:
                logger.warning("pdf_page_render_failed", path=str(file_path), page=i, exc_info=True)
        return results


async def _extract_pdf_text_ocr(file_path: Path) -> str | None:
    """OCR fallback: render PDF pages to PNG, send to vision model.

    Pages are OCR'd concurrently (up to OCR_CONCURRENCY at a time) and each
    page is retried up to OCR_MAX_RETRIES times for transient failures.
    """
    api_key = os.getenv("DEEPINFRA_API_KEY", "")
    if not api_key:
        logger.info("deepinfra_ocr_skipped", reason="DEEPINFRA_API_KEY not set")
        return None

    try:
        png_pages = await asyncio.to_thread(_render_pdf_pages_to_png, file_path, OCR_MAX_PAGES)
    except ImportError:
        logger.warning("pymupdf_not_available", hint="Install pymupdf for PDF OCR support")
        return None
    except Exception:
        logger.warning("pdf_ocr_render_failed", path=str(file_path), exc_info=True)
        return None

    if not png_pages:
        logger.warning("pdf_ocr_no_pages", path=str(file_path))
        return None

    semaphore = asyncio.Semaphore(OCR_CONCURRENCY)

    async def _ocr_one_page(
        client: httpx.AsyncClient, page_index: int, png_bytes: bytes
    ) -> str | None:
        b64 = base64.b64encode(png_bytes).decode()
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        }
        body = {
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
        }
        last_exc: Exception | None = None
        async with semaphore:
            for attempt in range(OCR_MAX_RETRIES + 1):
                try:
                    resp = await client.post(
                        f"{DEEPINFRA_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=OCR_PAGE_TIMEOUT,
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    page_text = data["choices"][0]["message"]["content"]
                    if page_text and page_text.strip():
                        return page_text.strip()
                    return None
                except (
                    httpx.TimeoutException,
                    httpx.HTTPStatusError,
                    httpx.NetworkError,
                    KeyError,
                    ValueError,
                ) as e:
                    last_exc = e
                    if attempt < OCR_MAX_RETRIES:
                        await asyncio.sleep(OCR_RETRY_BACKOFF)
                        continue
                    break
        logger.warning(
            "pdf_ocr_page_failed",
            path=str(file_path),
            page=page_index,
            error_type=type(last_exc).__name__ if last_exc else "Unknown",
            error=str(last_exc) if last_exc else "",
        )
        return None

    async with httpx.AsyncClient() as client:
        page_results = await asyncio.gather(
            *[_ocr_one_page(client, i, b) for i, b in enumerate(png_pages)]
        )

    text_parts = [t for t in page_results if t]
    full_text = "\n".join(text_parts)
    if full_text.strip():
        logger.info("pdf_ocr_success", path=str(file_path), chars=len(full_text), pages=len(text_parts))
        return full_text[:MAX_EXTRACTED_TEXT]

    logger.warning("pdf_ocr_empty", path=str(file_path), pages_processed=len(png_pages))
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
    except (OSError, ValueError) as e:
        logger.warning("file_delete_failed", path=storage_path, error=str(e))


# In-process background extraction registry. Safe because the backend runs a
# single uvicorn worker (dev --reload, prod single-worker enforced by commit),
# so upload requests and the orchestrator background task share one event loop.
_pending_extractions: dict[UUID, asyncio.Task] = {}


async def await_extractions(att_ids: list[UUID]) -> None:
    """Wait for any in-flight background extraction tasks to finish.

    Called by the orchestrator before building attachment context, so a chat
    message sent right after upload still sees the full OCR output. Never
    raises — a failed extraction leaves extracted_text as None. Tolerates
    unknown ids, empty lists, and already-done tasks.
    """
    if not att_ids:
        return
    pending: list[asyncio.Task] = []
    for aid in att_ids:
        task = _pending_extractions.get(aid)
        if task is not None and not task.done():
            pending.append(task)
    if not pending:
        return
    for result in await asyncio.gather(*pending, return_exceptions=True):
        if isinstance(result, Exception):
            logger.warning("extraction_await_failed", error=str(result)[:200])


def schedule_extraction(att_id: UUID, file_path: Path, content_type: str) -> None:
    """Schedule background text extraction for an attachment. Never raises.

    The upload route calls this after committing the attachment row, so the
    HTTP response returns immediately while extraction (potentially minutes
    for scanned PDFs) continues in the background. The task updates the
    attachment row's extracted_text in a fresh DB session and removes itself
    from _pending_extractions on completion.
    """
    if att_id in _pending_extractions:
        # Already scheduled — avoid orphaning a running task.
        return

    async def _run_extraction() -> None:
        try:
            text = await extract_text(file_path, content_type)
            from druppie.db.database import SessionLocal
            from druppie.repositories.attachment_repository import AttachmentRepository

            db = SessionLocal()
            try:
                repo = AttachmentRepository(db)
                attachment = repo.get_by_id(att_id)
                if attachment is not None:
                    attachment.extracted_text = text
                    db.commit()
            finally:
                db.close()
            logger.info(
                "extraction_completed",
                attachment_id=str(att_id),
                chars=len(text) if text else 0,
            )
        except Exception:
            logger.error(
                "extraction_background_failed",
                attachment_id=str(att_id),
                exc_info=True,
            )
        finally:
            _pending_extractions.pop(att_id, None)

    task = asyncio.create_task(_run_extraction())
    _pending_extractions[att_id] = task
    logger.info("extraction_scheduled", attachment_id=str(att_id))
