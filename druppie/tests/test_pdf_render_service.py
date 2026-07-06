"""Tests for PdfRenderService cache behaviour."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cache_miss_compiles_and_stores(tmp_path, monkeypatch):
    """First call resolves from Gitea, compiles Typst, and inserts cache row."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    from druppie.services.pdf_render_service import PdfRenderService

    pid = uuid.uuid4()
    db = MagicMock()
    service = PdfRenderService(db=db)

    gitea = AsyncMock()
    gitea.get_file = AsyncMock(return_value={
        "success": True,
        "content": "#import \"/druppie/templates/documents/rijnland.typ\": rijnland_doc\n#show: rijnland_doc.with(title=\"T\")\n= Hello\n",
        "data": {"sha": "abc123def456"},
    })
    gitea.list_files = AsyncMock(return_value={"success": False})

    with patch("druppie.services.pdf_render_service.get_gitea_client", return_value=gitea):
        with patch.object(
            service.typst,
            "compile_typ",
            return_value=b"FAKE_PDF_BYTES",
        ):
            with patch("druppie.services.pdf_render_service.PdfRenderRepository") as MockRepo:
                mock_repo = MagicMock()
                mock_repo.get_by_cache_key.return_value = None
                MockRepo.return_value = mock_repo

                pdf_bytes, storage_path, error = await service.get_or_create_pdf(
                    project_id=pid,
                    repo_name="test-repo",
                    repo_owner="test-owner",
                    typ_path="docs/report.typ",
                )

    assert error == ""
    assert pdf_bytes == b"FAKE_PDF_BYTES"
    assert "pdf-cache" in storage_path
    mock_repo.create.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_bytes(tmp_path, monkeypatch):
    """Second call with identical sha returns pre-cached PDF instantly."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    from druppie.services.pdf_render_service import PdfRenderService

    pid = uuid.uuid4()
    db = MagicMock()
    service = PdfRenderService(db=db)

    cache_dir = tmp_path / "uploads" / "pdf-cache" / str(pid) / "abc123de"
    cache_dir.mkdir(parents=True)
    (cache_dir / "report.pdf").write_bytes(b"CACHED_PDF")

    gitea = AsyncMock()
    gitea.get_file = AsyncMock(return_value={
        "success": True,
        "content": "typst code",
        "data": {"sha": "abc123def4567890"},
    })

    class FakeRender:
        pdf_storage_path = f"uploads/pdf-cache/{pid}/abc123de/report.pdf"

    with patch("druppie.services.pdf_render_service.get_gitea_client", return_value=gitea):
        with patch("druppie.services.pdf_render_service.PdfRenderRepository") as MockRepo:
            with patch.object(service.typst, "compile_typ") as mock_compile:
                mock_repo = MagicMock()
                mock_repo.get_by_cache_key.return_value = FakeRender()
                MockRepo.return_value = mock_repo

                pdf_bytes, storage_path, error = await service.get_or_create_pdf(
                    project_id=pid,
                    repo_name="test-repo",
                    repo_owner="test-owner",
                    typ_path="docs/report.typ",
                )

    assert error == ""
    assert pdf_bytes == b"CACHED_PDF"
    mock_repo.create.assert_not_called()
    mock_compile.assert_not_called()


@pytest.mark.asyncio
async def test_branch_fallback_on_miss(tmp_path, monkeypatch):
    """Tries first branch, falls back to second when first returns no content."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    from druppie.services.pdf_render_service import PdfRenderService

    pid = uuid.uuid4()
    service = PdfRenderService(db=MagicMock())

    gitea = AsyncMock()
    gitea.get_file = AsyncMock(side_effect=[
        {"success": False},
        {"success": True, "content": "= Hi\n", "data": {"sha": "shaaa"}},
    ])
    gitea.list_files = AsyncMock(return_value={"success": False})

    with patch("druppie.services.pdf_render_service.get_gitea_client", return_value=gitea):
        with patch.object(service.typst, "compile_typ", return_value=b"PDF"):
            with patch("druppie.services.pdf_render_service.PdfRenderRepository") as MockRepo:
                mock_repo = MagicMock()
                mock_repo.get_by_cache_key.return_value = None
                MockRepo.return_value = mock_repo

                pdf_bytes, _, error = await service.get_or_create_pdf(
                    project_id=pid,
                    repo_name="test-repo",
                    repo_owner="test-owner",
                    typ_path="docs/report.typ",
                    branches=["nonexistent", "main"],
                )

    assert error == ""
    assert pdf_bytes == b"PDF"
    assert gitea.get_file.call_count == 2


@pytest.mark.asyncio
async def test_gitea_file_not_found_returns_error(tmp_path, monkeypatch):
    """No branch resolves the file → error message, no compilation."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    from druppie.services.pdf_render_service import PdfRenderService

    pid = uuid.uuid4()
    service = PdfRenderService(db=MagicMock())

    gitea = AsyncMock()
    gitea.get_file = AsyncMock(return_value={"success": False})

    with patch("druppie.services.pdf_render_service.get_gitea_client", return_value=gitea):
        with patch("druppie.services.pdf_render_service.PdfRenderRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_cache_key.return_value = None
            MockRepo.return_value = mock_repo

            pdf_bytes, _, error = await service.get_or_create_pdf(
                project_id=pid,
                repo_name="test-repo",
                repo_owner="test-owner",
                typ_path="docs/nope.typ",
            )

    assert pdf_bytes is None
    assert "not found" in error.lower()
    mock_repo.create.assert_not_called()
