"""Tests for the modules discovery API endpoints.

Tests GET /api/modules and GET /api/modules/{id}/endpoint
which the Druppie SDK uses to discover module URLs at runtime.
"""

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from druppie.api.routes.modules import router
from druppie.core.mcp_config import MCPConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """MCPConfig loaded from an in-memory dict (no YAML file needed)."""
    config = MagicMock(spec=MCPConfig)

    servers = {
        "llm": {"url": "http://module-llm:9008/mcp", "type": "both"},
        "web": {"url": "http://module-web:9009/mcp", "type": "module"},
        "coding": {"url": "http://module-coding:9001/mcp", "type": "core"},
        "docker": {"url": "http://module-docker:9002/mcp", "type": "core"},
        "builtin": {"url": "", "type": "core"},
    }

    config.get_servers.return_value = list(servers.keys())

    def _get_type(server_id):
        return servers.get(server_id, {}).get("type", "core")

    def _get_url(server_id):
        return servers.get(server_id, {}).get("url", "")

    config.get_server_type.side_effect = _get_type
    config.get_server_url.side_effect = _get_url

    return config


@pytest.fixture
def client(mock_config):
    """FastAPI test client with mocked MCP config."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with patch("druppie.api.routes.modules.get_mcp_config", return_value=mock_config):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/modules
# ---------------------------------------------------------------------------


class TestListModules:
    """Tests for the list modules endpoint."""

    def test_returns_module_and_both_types(self, client):
        """Only modules with type 'module' or 'both' should be returned."""
        resp = client.get("/api/modules")
        assert resp.status_code == 200
        modules = resp.json()
        ids = [m["id"] for m in modules]
        assert "llm" in ids
        assert "web" in ids
        assert "coding" not in ids
        assert "docker" not in ids
        assert "builtin" not in ids

    def test_returns_correct_urls(self, client):
        """URLs should have /mcp suffix stripped (base URL only)."""
        resp = client.get("/api/modules")
        modules = {m["id"]: m for m in resp.json()}
        assert modules["llm"]["url"] == "http://module-llm:9008"
        assert modules["web"]["url"] == "http://module-web:9009"

    def test_returns_type_field(self, client):
        """Each module should include its type."""
        resp = client.get("/api/modules")
        modules = {m["id"]: m for m in resp.json()}
        assert modules["llm"]["type"] == "both"
        assert modules["web"]["type"] == "module"

    def test_empty_config(self, mock_config):
        """Empty config should return empty list."""
        mock_config.get_servers.return_value = []
        app = FastAPI()
        app.include_router(router, prefix="/api")
        with patch("druppie.api.routes.modules.get_mcp_config", return_value=mock_config):
            client = TestClient(app)
            resp = client.get("/api/modules")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/modules/{module_id}/endpoint
# ---------------------------------------------------------------------------


class TestGetModuleEndpoint:
    """Tests for the single module endpoint lookup."""

    def test_existing_module_both(self, client):
        """Module with type 'both' should return URL."""
        resp = client.get("/api/modules/llm/endpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "http://module-llm:9008"
        assert data["type"] == "both"

    def test_existing_module_type_module(self, client):
        """Module with type 'module' should return URL."""
        resp = client.get("/api/modules/web/endpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "http://module-web:9009"
        assert data["type"] == "module"

    def test_core_module_returns_404(self, client):
        """Module with type 'core' should return 404."""
        resp = client.get("/api/modules/coding/endpoint")
        assert resp.status_code == 404
        assert "not available to apps" in resp.json()["detail"]

    def test_unknown_module_returns_404(self, client):
        """Non-existent module should return 404."""
        resp = client.get("/api/modules/nonexistent/endpoint")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_builtin_returns_404(self, client):
        """Builtin server (type core) should not be exposed."""
        resp = client.get("/api/modules/builtin/endpoint")
        assert resp.status_code == 404
