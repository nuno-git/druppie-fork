"""Tests for attachment_service background extraction pipeline.

Covers the new functionality added by the pdf-upload-hardening PR:
- schedule_extraction: spawns a background task, registers in _pending_extractions
- await_extractions: waits for in-flight background tasks to complete
- extract_text: text/PDF happy paths with mocked I/O
- _extract_pdf_text_ocr: concurrent OCR with retry logic
- Error handling: extraction failure cleans up _pending_extractions
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

# Stub out fastmcp before druppie.services.__init__ pulls in the full
# execution chain.  The attachment_service module itself never uses fastmcp;
# the error comes from transitive imports via WorkflowService -> Orchestrator.
for _mod in ("fastmcp", "fastmcp.client", "fastmcp.client.transports", "fastmcp.settings"):
    sys.modules.setdefault(_mod, MagicMock())

from druppie.services import attachment_service
from druppie.services.attachment_service import (
    MAX_EXTRACTED_TEXT,
    OCR_MAX_RETRIES,
    _pending_extractions,
    await_extractions,
    extract_text,
    schedule_extraction,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    """Ensure _pending_extractions is empty before and after every test."""
    _pending_extractions.clear()
    yield
    # Cancel any lingering tasks so they don't leak into the next test.
    for task in _pending_extractions.values():
        task.cancel()
    _pending_extractions.clear()


# ---------------------------------------------------------------------------
# schedule_extraction
# ---------------------------------------------------------------------------


class TestScheduleExtraction:
    @pytest.mark.asyncio
    async def test_registers_task_in_pending(self):
        """schedule_extraction adds the attachment id to _pending_extractions."""
        att_id = uuid4()
        fake_path = Path("/tmp/fake.txt")

        with patch.object(attachment_service, "extract_text", new_callable=AsyncMock, return_value="hello"):
            with patch("druppie.db.database.SessionLocal") as MockSL:
                mock_db = MagicMock()
                MockSL.return_value = mock_db
                with patch("druppie.repositories.attachment_repository.AttachmentRepository") as MockRepo:
                    mock_repo = MagicMock()
                    mock_repo.get_by_id.return_value = MagicMock()
                    MockRepo.return_value = mock_repo

                    schedule_extraction(att_id, fake_path, "text/plain")

                    assert att_id in _pending_extractions
                    assert isinstance(_pending_extractions[att_id], asyncio.Task)

                    # Let the task finish.
                    await _pending_extractions[att_id]

    @pytest.mark.asyncio
    async def test_task_updates_db_and_cleans_up(self):
        """Background task writes extracted_text to DB and removes itself from registry."""
        att_id = uuid4()
        fake_path = Path("/tmp/fake.txt")
        mock_attachment = MagicMock()

        with patch.object(attachment_service, "extract_text", new_callable=AsyncMock, return_value="extracted"):
            with patch("druppie.db.database.SessionLocal") as MockSL:
                mock_db = MagicMock()
                MockSL.return_value = mock_db
                with patch("druppie.repositories.attachment_repository.AttachmentRepository") as MockRepo:
                    mock_repo = MagicMock()
                    mock_repo.get_by_id.return_value = mock_attachment
                    MockRepo.return_value = mock_repo

                    schedule_extraction(att_id, fake_path, "text/plain")
                    await _pending_extractions[att_id]

        # Verify DB was updated and closed.
        assert mock_attachment.extracted_text == "extracted"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

        # Task should have removed itself from the registry.
        assert att_id not in _pending_extractions

    @pytest.mark.asyncio
    async def test_duplicate_schedule_is_noop(self):
        """Calling schedule_extraction twice for the same id does not replace the task."""
        att_id = uuid4()
        fake_path = Path("/tmp/fake.txt")

        with patch.object(attachment_service, "extract_text", new_callable=AsyncMock, return_value="t"):
            with patch("druppie.db.database.SessionLocal") as MockSL:
                MockSL.return_value = MagicMock()
                with patch("druppie.repositories.attachment_repository.AttachmentRepository") as MockRepo:
                    MockRepo.return_value = MagicMock(get_by_id=MagicMock(return_value=MagicMock()))

                    schedule_extraction(att_id, fake_path, "text/plain")
                    first_task = _pending_extractions[att_id]

                    schedule_extraction(att_id, fake_path, "text/plain")
                    assert _pending_extractions[att_id] is first_task

                    await first_task

    @pytest.mark.asyncio
    async def test_extraction_failure_cleans_up_pending(self):
        """If extract_text raises, the task still removes itself from _pending_extractions."""
        att_id = uuid4()
        fake_path = Path("/tmp/fake.pdf")

        with patch.object(
            attachment_service, "extract_text", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            schedule_extraction(att_id, fake_path, "application/pdf")
            task = _pending_extractions[att_id]
            await task

        # Must be cleaned up even after failure.
        assert att_id not in _pending_extractions

    @pytest.mark.asyncio
    async def test_attachment_not_found_still_succeeds(self):
        """If the attachment row is gone by the time extraction finishes, no crash."""
        att_id = uuid4()
        fake_path = Path("/tmp/fake.txt")

        with patch.object(attachment_service, "extract_text", new_callable=AsyncMock, return_value="text"):
            with patch("druppie.db.database.SessionLocal") as MockSL:
                mock_db = MagicMock()
                MockSL.return_value = mock_db
                with patch("druppie.repositories.attachment_repository.AttachmentRepository") as MockRepo:
                    mock_repo = MagicMock()
                    mock_repo.get_by_id.return_value = None  # deleted
                    MockRepo.return_value = mock_repo

                    schedule_extraction(att_id, fake_path, "text/plain")
                    await _pending_extractions[att_id]

        # Should not crash and should clean up.
        assert att_id not in _pending_extractions
        mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# await_extractions
# ---------------------------------------------------------------------------


class TestAwaitExtractions:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        """await_extractions returns immediately for an empty list."""
        await await_extractions([])  # Should not raise.

    @pytest.mark.asyncio
    async def test_unknown_ids_tolerated(self):
        """Unknown attachment ids are silently ignored."""
        await await_extractions([uuid4(), uuid4()])

    @pytest.mark.asyncio
    async def test_waits_for_pending_task(self):
        """await_extractions blocks until the pending task completes."""
        att_id = uuid4()
        completed = False

        async def slow_task():
            nonlocal completed
            await asyncio.sleep(0.05)
            completed = True

        task = asyncio.create_task(slow_task())
        _pending_extractions[att_id] = task

        await await_extractions([att_id])
        assert completed

    @pytest.mark.asyncio
    async def test_already_done_task_skipped(self):
        """A task that is already done does not block."""
        att_id = uuid4()

        async def instant():
            return

        task = asyncio.create_task(instant())
        await task  # Ensure it finishes.
        _pending_extractions[att_id] = task

        # Should return instantly — no pending tasks to gather.
        await await_extractions([att_id])

    @pytest.mark.asyncio
    async def test_failed_task_does_not_raise(self):
        """If a pending extraction task raised, await_extractions swallows the error."""
        att_id = uuid4()

        async def failing_task():
            raise RuntimeError("extraction failed")

        task = asyncio.create_task(failing_task())
        _pending_extractions[att_id] = task
        # Give the task time to fail.
        await asyncio.sleep(0.01)

        # Must not raise.
        await await_extractions([att_id])

    @pytest.mark.asyncio
    async def test_mixed_known_and_unknown(self):
        """Mix of known pending, known done, and unknown ids all handled."""
        pending_id = uuid4()
        done_id = uuid4()
        unknown_id = uuid4()
        value = []

        async def track():
            value.append("done")

        pending_task = asyncio.create_task(track())
        _pending_extractions[pending_id] = pending_task

        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        _pending_extractions[done_id] = done_task

        await await_extractions([pending_id, done_id, unknown_id])
        assert value == ["done"]


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    @pytest.mark.asyncio
    async def test_text_file_reads_content(self, tmp_path):
        """Plain text files are read directly and truncated to MAX_EXTRACTED_TEXT."""
        f = tmp_path / "notes.txt"
        f.write_text("Hello, world!", encoding="utf-8")

        result = await extract_text(f, "text/plain")
        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_text_file_truncated(self, tmp_path):
        """Text longer than MAX_EXTRACTED_TEXT is truncated."""
        f = tmp_path / "big.txt"
        f.write_text("x" * (MAX_EXTRACTED_TEXT + 100), encoding="utf-8")

        result = await extract_text(f, "text/plain")
        assert result is not None
        assert len(result) == MAX_EXTRACTED_TEXT

    @pytest.mark.asyncio
    async def test_text_file_read_failure(self, tmp_path):
        """Unreadable text file returns None instead of crashing."""
        f = tmp_path / "bad.txt"
        f.write_bytes(b"\x80\x81")  # not valid utf-8 in strict mode

        # The service uses errors="replace", so it actually succeeds.
        # Simulate a real failure by making the path a directory.
        d = tmp_path / "dir_not_file"
        d.mkdir()
        result = await extract_text(d, "text/plain")
        assert result is None

    @pytest.mark.asyncio
    async def test_markdown_treated_as_text(self, tmp_path):
        """Markdown content type is handled by the text branch."""
        f = tmp_path / "doc.md"
        f.write_text("# Title\n\nBody", encoding="utf-8")

        result = await extract_text(f, "text/markdown")
        assert result == "# Title\n\nBody"

    @pytest.mark.asyncio
    async def test_pdf_delegates_to_pdf_extractor(self, tmp_path):
        """application/pdf delegates to _extract_pdf_text."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"fake-pdf")

        with patch(
            "druppie.services.attachment_service._extract_pdf_text",
            new_callable=AsyncMock,
            return_value="PDF content here",
        ) as mock_pdf:
            result = await extract_text(f, "application/pdf")

        assert result == "PDF content here"
        mock_pdf.assert_awaited_once_with(f)

    @pytest.mark.asyncio
    async def test_unknown_content_type_returns_none(self, tmp_path):
        """Unsupported content types return None."""
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")

        result = await extract_text(f, "image/png")
        assert result is None


# ---------------------------------------------------------------------------
# _extract_pdf_text_ocr — retry & concurrency
# ---------------------------------------------------------------------------


class TestOcrRetryAndConcurrency:
    @pytest.mark.asyncio
    async def test_ocr_skipped_without_api_key(self, monkeypatch):
        """OCR is skipped when DEEPINFRA_API_KEY is not set."""
        monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)

        result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))
        assert result is None

    @pytest.mark.asyncio
    async def test_ocr_retries_on_timeout(self, monkeypatch):
        """OCR retries up to OCR_MAX_RETRIES times on timeout, then returns None."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timed out")

        with patch.object(
            attachment_service, "_render_pdf_pages_to_png", return_value=[b"fake-png"]
        ):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = mock_post
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                with patch.object(attachment_service, "OCR_RETRY_BACKOFF", 0.01):
                    result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is None
        assert call_count == OCR_MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_ocr_succeeds_on_retry(self, monkeypatch):
        """OCR succeeds after a transient failure on the first attempt."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timed out")
            # Succeed on second attempt.
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "choices": [{"message": {"content": "Extracted page text"}}]
            }
            return resp

        with patch.object(
            attachment_service, "_render_pdf_pages_to_png", return_value=[b"fake-png"]
        ):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = mock_post
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                with patch.object(attachment_service, "OCR_RETRY_BACKOFF", 0.01):
                    result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result == "Extracted page text"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_ocr_concurrent_pages(self, monkeypatch):
        """Multiple pages are OCR'd concurrently and results are joined."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        page_texts = ["Page 1 content", "Page 2 content", "Page 3 content"]
        call_pages = []

        async def mock_post(*args, **kwargs):
            body = kwargs.get("json", {})
            # Track that we got called
            call_pages.append(True)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            idx = len(call_pages) - 1
            text = page_texts[idx] if idx < len(page_texts) else ""
            resp.json.return_value = {
                "choices": [{"message": {"content": text}}]
            }
            return resp

        png_pages = [b"png1", b"png2", b"png3"]
        with patch.object(
            attachment_service, "_render_pdf_pages_to_png", return_value=png_pages
        ):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = mock_post
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is not None
        assert "Page 1 content" in result
        assert "Page 2 content" in result
        assert "Page 3 content" in result
        assert len(call_pages) == 3

    @pytest.mark.asyncio
    async def test_ocr_empty_response_returns_none(self, monkeypatch):
        """If OCR returns only whitespace, the result is None."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "choices": [{"message": {"content": "   "}}]
            }
            return resp

        with patch.object(
            attachment_service, "_render_pdf_pages_to_png", return_value=[b"png"]
        ):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.post = mock_post
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is None

    @pytest.mark.asyncio
    async def test_ocr_pymupdf_import_error(self, monkeypatch):
        """If pymupdf is not installed, OCR returns None gracefully."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        with patch(
            "druppie.services.attachment_service.asyncio.to_thread",
            side_effect=ImportError("No module named 'pymupdf'"),
        ):
            result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is None

    @pytest.mark.asyncio
    async def test_ocr_render_failure(self, monkeypatch):
        """If PDF rendering fails, OCR returns None gracefully."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        with patch(
            "druppie.services.attachment_service.asyncio.to_thread",
            side_effect=RuntimeError("render exploded"),
        ):
            result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is None

    @pytest.mark.asyncio
    async def test_ocr_no_pages_rendered(self, monkeypatch):
        """If PDF renders zero pages, OCR returns None."""
        monkeypatch.setenv("DEEPINFRA_API_KEY", "test-key")

        with patch.object(
            attachment_service, "_render_pdf_pages_to_png", return_value=[]
        ):
            with patch(
                "druppie.services.attachment_service.asyncio.to_thread",
                return_value=[],
            ):
                result = await attachment_service._extract_pdf_text_ocr(Path("/tmp/fake.pdf"))

        assert result is None


# ---------------------------------------------------------------------------
# _extract_pdf_text — native + OCR fallback
# ---------------------------------------------------------------------------


class TestExtractPdfText:
    @pytest.mark.asyncio
    async def test_native_extraction_succeeds(self):
        """If native pypdf extraction returns text, OCR is not called."""
        with patch(
            "druppie.services.attachment_service._extract_pdf_text_native",
            return_value="Native text",
        ) as mock_native:
            with patch(
                "druppie.services.attachment_service._extract_pdf_text_ocr",
                new_callable=AsyncMock,
            ) as mock_ocr:
                result = await attachment_service._extract_pdf_text(Path("/tmp/doc.pdf"))

        assert result == "Native text"
        mock_native.assert_called_once()
        mock_ocr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_native_fails_falls_back_to_ocr(self):
        """If native extraction returns None, falls back to OCR."""
        with patch(
            "druppie.services.attachment_service._extract_pdf_text_native",
            return_value=None,
        ):
            with patch(
                "druppie.services.attachment_service._extract_pdf_text_ocr",
                new_callable=AsyncMock,
                return_value="OCR text",
            ) as mock_ocr:
                result = await attachment_service._extract_pdf_text(Path("/tmp/doc.pdf"))

        assert result == "OCR text"
        mock_ocr.assert_awaited_once()


# ---------------------------------------------------------------------------
# _extract_pdf_text_native
# ---------------------------------------------------------------------------


class TestExtractPdfTextNative:
    def test_pypdf_not_installed(self):
        """Returns None when pypdf is not available."""
        import builtins

        real_import = builtins.__import__

        def _no_pypdf(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("No module named 'pypdf'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_pypdf):
            result = attachment_service._extract_pdf_text_native(Path("/tmp/doc.pdf"))
        assert result is None

    def test_extraction_exception_returns_none(self):
        """If pypdf raises during extraction, return None."""
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock(extract_text=MagicMock(side_effect=Exception("corrupt")))]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = attachment_service._extract_pdf_text_native(Path("/tmp/doc.pdf"))
        assert result is None

    def test_empty_text_returns_none(self):
        """If all pages produce empty text, return None."""
        page1 = MagicMock(extract_text=MagicMock(return_value=""))
        page2 = MagicMock(extract_text=MagicMock(return_value="   "))
        mock_reader = MagicMock()
        mock_reader.pages = [page1, page2]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = attachment_service._extract_pdf_text_native(Path("/tmp/doc.pdf"))
        assert result is None

    def test_successful_extraction(self):
        """Happy path: pages yield text joined by newlines."""
        page1 = MagicMock(extract_text=MagicMock(return_value="Page one"))
        page2 = MagicMock(extract_text=MagicMock(return_value="Page two"))
        mock_reader = MagicMock()
        mock_reader.pages = [page1, page2]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = attachment_service._extract_pdf_text_native(Path("/tmp/doc.pdf"))
        assert result == "Page one\nPage two"

    def test_result_truncated_to_max(self):
        """Extracted text is capped at MAX_EXTRACTED_TEXT characters."""
        long_text = "x" * (MAX_EXTRACTED_TEXT + 500)
        page = MagicMock(extract_text=MagicMock(return_value=long_text))
        mock_reader = MagicMock()
        mock_reader.pages = [page]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = attachment_service._extract_pdf_text_native(Path("/tmp/doc.pdf"))
        assert result is not None
        assert len(result) == MAX_EXTRACTED_TEXT
