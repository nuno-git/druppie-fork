"""Unit tests for SharePoint module pure logic.

Covers: allowlist loading, URL matching, text/binary classification,
verified-ID cache eviction, and delta aggregation.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

# Ensure the v1 package is importable from its parent directory.
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from v1.module import (
    SharePointModule,
    TEXT_EXTENSIONS,
    TEXT_MIME_PREFIXES,
    _load_allowed_sites,
    _MAX_VERIFIED_CACHE,
)


# -- _load_allowed_sites -----------------------------------------------------

class TestLoadAllowedSites:
    def test_empty_env_returns_empty_set(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": ""}):
            assert _load_allowed_sites() == set()

    def test_unset_env_returns_empty_set(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _load_allowed_sites() == set()

    def test_all_returns_none(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            assert _load_allowed_sites() is None

    def test_all_case_insensitive(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "ALL"}):
            assert _load_allowed_sites() is None

    def test_semicolon_separated(self):
        urls = "https://a.sharepoint.com/sites/X;https://b.sharepoint.com/sites/Y"
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": urls}):
            result = _load_allowed_sites()
            assert result == {
                "https://a.sharepoint.com/sites/x",
                "https://b.sharepoint.com/sites/y",
            }

    def test_whitespace_trimmed(self):
        urls = "  https://a.sharepoint.com/sites/X ; ; https://b.sharepoint.com "
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": urls}):
            result = _load_allowed_sites()
            assert result == {
                "https://a.sharepoint.com/sites/x",
                "https://b.sharepoint.com",
            }

    def test_trailing_slashes_stripped(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "https://a.com/sites/X/"}):
            result = _load_allowed_sites()
            assert "https://a.com/sites/x" in result


# -- _is_site_allowed_by_url -------------------------------------------------

class TestIsSiteAllowedByUrl:
    def _make_module(self, allowed_urls):
        """Create module with pre-set allowlist (skip env loading)."""
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": ""}):
            mod = SharePointModule()
        mod._allowed_urls = allowed_urls
        return mod

    def test_none_allows_everything(self):
        mod = self._make_module(None)
        assert mod._is_site_allowed_by_url("https://anything.com") is True

    def test_url_in_list_allowed(self):
        mod = self._make_module({"https://a.sharepoint.com/sites/team"})
        assert mod._is_site_allowed_by_url("https://a.sharepoint.com/sites/team") is True

    def test_url_not_in_list_blocked(self):
        mod = self._make_module({"https://a.sharepoint.com/sites/team"})
        assert mod._is_site_allowed_by_url("https://other.sharepoint.com") is False

    def test_case_insensitive(self):
        mod = self._make_module({"https://a.sharepoint.com/sites/team"})
        assert mod._is_site_allowed_by_url("https://A.SharePoint.COM/sites/Team") is True

    def test_trailing_slash_normalized(self):
        mod = self._make_module({"https://a.sharepoint.com/sites/team"})
        assert mod._is_site_allowed_by_url("https://a.sharepoint.com/sites/team/") is True

    def test_empty_set_blocks_all(self):
        mod = self._make_module(set())
        assert mod._is_site_allowed_by_url("https://any.com") is False


# -- Text / binary classification --------------------------------------------

class TestTextBinaryClassification:
    """Verify the is_text branching logic in read_file."""

    def test_text_mime_prefixes_match(self):
        text_types = ["text/plain", "text/html", "application/json", "application/xml"]
        for ct in text_types:
            assert any(ct.startswith(p) for p in TEXT_MIME_PREFIXES), f"{ct} should match"

    def test_binary_mime_not_matched(self):
        binary_types = ["application/pdf", "image/png", "application/octet-stream"]
        for ct in binary_types:
            assert not any(ct.startswith(p) for p in TEXT_MIME_PREFIXES), f"{ct} should not match"

    def test_text_extensions_recognized(self):
        for ext in [".py", ".json", ".md", ".csv", ".sql", ".html"]:
            assert ext in TEXT_EXTENSIONS

    def test_binary_extensions_not_in_set(self):
        for ext in [".pdf", ".png", ".docx", ".xlsx", ".zip"]:
            assert ext not in TEXT_EXTENSIONS

    @pytest.mark.asyncio
    async def test_read_file_text_includes_content(self):
        """Text file: metadata fetched, content downloaded and included."""
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.get_item.return_value = {
            "name": "readme.md",
            "size": 42,
            "file": {"mimeType": "text/plain"},
            "webUrl": "https://sp.com/readme.md",
            "lastModifiedDateTime": "2026-01-01",
        }
        mod._client._get_bytes.return_value = b"# Hello"

        result = await mod.read_file("site1", "file1", "token")
        assert result["success"] is True
        assert result["content_included"] is True
        assert result["content"] == "# Hello"
        mod._client._get_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_file_binary_metadata_only(self):
        """Binary file: no download, content_included=False."""
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.get_item.return_value = {
            "name": "diagram.pdf",
            "size": 999,
            "file": {"mimeType": "application/pdf"},
            "webUrl": "https://sp.com/diagram.pdf",
            "lastModifiedDateTime": "2026-01-01",
        }

        result = await mod.read_file("site1", "file1", "token")
        assert result["success"] is True
        assert result["content_included"] is False
        assert "Binary file" in result["message"]
        mod._client._get_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_file_text_by_extension_fallback(self):
        """Extension in TEXT_EXTENSIONS overrides opaque mime type."""
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.get_item.return_value = {
            "name": "config.toml",
            "size": 10,
            "file": {"mimeType": "application/octet-stream"},
            "webUrl": "https://sp.com/config.toml",
            "lastModifiedDateTime": "2026-01-01",
        }
        mod._client._get_bytes.return_value = b"key = 'val'"

        result = await mod.read_file("site1", "file1", "token")
        assert result["content_included"] is True
        assert result["content"] == "key = 'val'"


# -- Verified-ID cache eviction ----------------------------------------------

class TestVerifiedCacheEviction:
    @pytest.mark.asyncio
    async def test_cache_clears_when_exceeding_max(self):
        """When cache exceeds _MAX_VERIFIED_CACHE, it is cleared before adding."""
        # Need a real allowlist (not None) so _is_site_allowed doesn't short-circuit
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "https://a.com"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.get_site.return_value = {"webUrl": "https://a.com"}

        # Pre-fill cache to just above the limit
        mod._verified_ids = {f"site-{i}": True for i in range(_MAX_VERIFIED_CACHE + 1)}
        assert len(mod._verified_ids) > _MAX_VERIFIED_CACHE

        # Calling _is_site_allowed with an uncached site triggers eviction
        await mod._is_site_allowed("new-site", "token")

        # Cache was cleared then the new entry added
        assert len(mod._verified_ids) == 1
        assert "new-site" in mod._verified_ids

    @pytest.mark.asyncio
    async def test_cache_persists_under_limit(self):
        """Cache entries stay when under the limit."""
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "https://a.com"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.get_site.return_value = {"webUrl": "https://a.com"}

        mod._verified_ids = {"existing": True}
        await mod._is_site_allowed("new-site", "token")

        assert len(mod._verified_ids) == 2
        assert "existing" in mod._verified_ids
        assert "new-site" in mod._verified_ids


# -- list_all_files delta aggregation -----------------------------------------

class TestDeltaAggregation:
    @pytest.mark.asyncio
    async def test_folder_summary_aggregation(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            mod = SharePointModule()
        mod._client = AsyncMock()

        # Simulate delta response: 1 folder + 2 files in it, 1 file at root
        mod._client.delta.return_value = [
            {
                "id": "f1", "name": "Reports",
                "folder": {"childCount": 2},
                "parentReference": {"path": "/drives/d1/root:"},
            },
            {
                "id": "i1", "name": "q1.csv", "size": 100,
                "file": {"mimeType": "text/csv"},
                "parentReference": {"path": "/drives/d1/root:/Reports"},
            },
            {
                "id": "i2", "name": "q2.csv", "size": 200,
                "file": {"mimeType": "text/csv"},
                "parentReference": {"path": "/drives/d1/root:/Reports"},
            },
            {
                "id": "i3", "name": "readme.md", "size": 50,
                "file": {"mimeType": "text/markdown"},
                "parentReference": {"path": "/drives/d1/root:"},
            },
        ]

        result = await mod.list_all_files("site1", "token")
        assert result["success"] is True
        assert result["total_files"] == 3
        assert result["total_size"] == 350

        by_path = {f["path"]: f for f in result["folders"]}
        assert by_path["Reports"]["file_count"] == 2
        assert by_path["Reports"]["total_size"] == 300
        assert by_path["Reports"]["file_types"] == {"csv": 2}
        # Root-level file
        assert by_path["/"]["file_count"] == 1

    @pytest.mark.asyncio
    async def test_deleted_items_excluded(self):
        with patch.dict(os.environ, {"SHAREPOINT_ALLOWED_SITES": "all"}):
            mod = SharePointModule()
        mod._client = AsyncMock()
        mod._client.delta.return_value = [
            {"id": "d1", "name": "old.txt", "deleted": {"state": "deleted"},
             "file": {"mimeType": "text/plain"}, "size": 10,
             "parentReference": {"path": "/drives/d1/root:"}},
            {"id": "i1", "name": "keep.txt", "size": 20,
             "file": {"mimeType": "text/plain"},
             "parentReference": {"path": "/drives/d1/root:"}},
        ]

        result = await mod.list_all_files("site1", "token")
        assert result["total_files"] == 1
        assert result["total_size"] == 20
