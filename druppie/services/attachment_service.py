"""Attachment service - file storage, validation, and text extraction."""

import mimetypes
import os
import re
from pathlib import Path

import structlog

logger = structlog.get_logger()

UPLOAD_DIR = Path(os.getenv("WORKSPACE_PATH", "/app/workspace")) / "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_EXTRACTED_TEXT = 50_000  # characters

ALLOWED_CONTENT_TYPES = {
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
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200] if name else "unnamed"


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


def extract_text(file_path: Path, content_type: str) -> str | None:
    if content_type in TEXT_CONTENT_TYPES:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_EXTRACTED_TEXT]
        except Exception:
            logger.warning("text_extraction_failed", path=str(file_path))
            return None

    if content_type == "application/pdf":
        return _extract_pdf_text(file_path)

    return None


def _extract_pdf_text(file_path: Path) -> str | None:
    text = _extract_pdf_text_native(file_path)
    if text:
        return text
    return _extract_pdf_text_ocr(file_path)


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


def _extract_pdf_text_ocr(file_path: Path) -> str | None:
    try:
        from pdf2image import convert_from_path
        import pytesseract

        images = convert_from_path(str(file_path), dpi=200)
        text_parts = []
        for image in images:
            page_text = pytesseract.image_to_string(image)
            if page_text and page_text.strip():
                text_parts.append(page_text.strip())
        full_text = "\n".join(text_parts)
        if full_text.strip():
            logger.info("pdf_ocr_success", path=str(file_path), chars=len(full_text))
            return full_text[:MAX_EXTRACTED_TEXT]
        return None
    except ImportError:
        logger.info("ocr_not_available", hint="Install pytesseract and pdf2image for OCR")
        return None
    except Exception:
        logger.warning("pdf_ocr_failed", path=str(file_path))
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
