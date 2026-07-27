"""Tests for builtin tool helpers."""
from __future__ import annotations

import base64
import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_resolve_typ_file_downloads_images_from_gitea(tmp_path):
    """Gitea fallback fetches #image() references and ArchiMate SVG exports."""
    from druppie.agents.builtin_tools import _resolve_typ_file

    sid = uuid.uuid4()

    class FakeSession:
        id = sid
        project_id = uuid.uuid4()
        user_id = uuid.uuid4()

    class FakeExecutor:
        class db:
            pass

    session = FakeSession()
    executor = FakeExecutor()

    workspace = tmp_path / "ws"
    workspace.mkdir()

    gitea = MagicMock()

    typ_content = '#image("diagrams/view.svg")\n= Hello\n'
    typ_b64 = base64.b64encode(typ_content.encode()).decode()
    svg_data = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    svg_b64 = base64.b64encode(svg_data).decode()

    gitea.get_file = AsyncMock(side_effect=[
        {"success": True, "content": typ_content, "data": {"content": typ_b64}},
        {"success": True, "data": {"content": svg_b64}},
        {"success": True, "data": {"content": svg_b64}},
    ])
    gitea.list_files = AsyncMock(return_value={
        "success": True,
        "files": [{"path": "docs/diagrams/other.svg"}],
    })

    with patch("druppie.core.workspace.workspace_path_for_session", return_value=workspace):
        with patch("druppie.core.gitea.get_gitea_client", return_value=gitea):
            with patch("druppie.repositories.ProjectRepository") as MockRepo:
                mock_repo_instance = MagicMock()
                mock_project = MagicMock()
                mock_project.repo_name = "test-repo"
                mock_project.repo_owner = "test-owner"
                mock_repo_instance.get_by_id.return_value = mock_project
                MockRepo.return_value = mock_repo_instance

                typ_file, error = await _resolve_typ_file(
                    "docs/report.typ", session, executor
                )

    assert error is None
    assert typ_file is not None
    assert typ_file.name == "report.typ"

    img1 = typ_file.parent / "diagrams/view.svg"
    img2 = typ_file.parent / "docs/diagrams/other.svg"
    assert img1.exists()
    assert img2.exists()
    assert img1.read_bytes() == svg_data
    assert img2.read_bytes() == svg_data

    if typ_file.parent.exists():
        shutil.rmtree(typ_file.parent)


@pytest.mark.asyncio
async def test_resolve_typ_file_skips_urls_and_absolute_paths(tmp_path):
    """#image() references with http://, https://, or / are skipped."""
    from druppie.agents.builtin_tools import _resolve_typ_file

    sid = uuid.uuid4()

    class FakeSession:
        id = sid
        project_id = uuid.uuid4()
        user_id = uuid.uuid4()

    class FakeExecutor:
        class db:
            pass

    session = FakeSession()
    executor = FakeExecutor()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    gitea = MagicMock()

    typ_content = (
        '#image("http://example.com/img.svg")\n'
        '#image("/druppie/templates/logo.png")\n'
        '#image("diagrams/local.svg")\n'
    )
    typ_b64 = base64.b64encode(typ_content.encode()).decode()
    svg_data = b'<svg/>'
    svg_b64 = base64.b64encode(svg_data).decode()

    gitea.get_file = AsyncMock(side_effect=[
        {"success": True, "content": typ_content, "data": {"content": typ_b64}},
        {"success": True, "data": {"content": svg_b64}},
    ])
    gitea.list_files = AsyncMock(return_value={"success": False})

    with patch("druppie.core.workspace.workspace_path_for_session", return_value=workspace):
        with patch("druppie.core.gitea.get_gitea_client", return_value=gitea):
            with patch("druppie.repositories.ProjectRepository") as MockRepo:
                mock_repo_instance = MagicMock()
                mock_project = MagicMock()
                mock_project.repo_name = "test-repo"
                mock_project.repo_owner = "test-owner"
                mock_repo_instance.get_by_id.return_value = mock_project
                MockRepo.return_value = mock_repo_instance

                typ_file, error = await _resolve_typ_file(
                    "report.typ", session, executor
                )

    assert error is None

    img_local = typ_file.parent / "diagrams/local.svg"
    img_http = typ_file.parent / "img.svg"
    img_abs = typ_file.parent / "logo.png"

    assert img_local.exists()
    assert not img_http.exists()
    assert not img_abs.exists()

    if typ_file.parent.exists():
        shutil.rmtree(typ_file.parent)
