"""Tests for ATK Copilot integration — domain models, service logic, and MCP server.

These tests run without Docker, database, or M365 credentials.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Pre-mock fastmcp before any imports trigger the full dependency chain.
# fastmcp is a Docker-only dep (installed in the MCP server containers) but
# the main backend also imports it transitively via execution/mcp_http.py.
if "fastmcp" not in sys.modules:
    _mock_fastmcp = MagicMock()
    sys.modules["fastmcp"] = _mock_fastmcp
    sys.modules["fastmcp.client"] = MagicMock()
    sys.modules["fastmcp.client.transports"] = MagicMock()


# =============================================================================
# Domain Model Tests
# =============================================================================


class TestAtkDomainModels:
    """Test Pydantic domain models for ATK agents."""

    def test_atk_agent_status_enum(self):
        from druppie.domain.atk_agent import AtkAgentStatus

        assert AtkAgentStatus.SCAFFOLDED == "scaffolded"
        assert AtkAgentStatus.PROVISIONED == "provisioned"
        assert AtkAgentStatus.DEPLOYED == "deployed"
        assert AtkAgentStatus.SHARED == "shared"
        assert AtkAgentStatus.UNINSTALLED == "uninstalled"
        assert AtkAgentStatus.FAILED == "failed"

    def test_atk_agent_summary(self):
        from druppie.domain.atk_agent import AtkAgentSummary, AtkAgentStatus

        summary = AtkAgentSummary(
            id=uuid4(),
            name="test-agent",
            description="A test agent",
            environment="dev",
            status=AtkAgentStatus.SCAFFOLDED,
            project_id=None,
            created_at=datetime.now(timezone.utc),
        )
        assert summary.name == "test-agent"
        assert summary.status == AtkAgentStatus.SCAFFOLDED
        assert summary.project_id is None

    def test_atk_agent_summary_with_project(self):
        from druppie.domain.atk_agent import AtkAgentSummary, AtkAgentStatus

        project_id = uuid4()
        summary = AtkAgentSummary(
            id=uuid4(),
            name="linked-agent",
            description=None,
            environment="production",
            status=AtkAgentStatus.PROVISIONED,
            project_id=project_id,
            created_at=datetime.now(timezone.utc),
        )
        assert summary.project_id == project_id
        assert summary.environment == "production"

    def test_atk_agent_detail(self):
        from druppie.domain.atk_agent import (
            AtkAgentDetail,
            AtkAgentStatus,
            AtkShareInfo,
            AtkDeploymentLogEntry,
        )

        now = datetime.now(timezone.utc)
        agent_id = uuid4()
        user_id = uuid4()

        detail = AtkAgentDetail(
            id=agent_id,
            name="full-agent",
            description="Full detail test",
            environment="dev",
            status=AtkAgentStatus.SHARED,
            project_id=None,
            created_at=now,
            m365_app_id="app-123-456",
            created_by=user_id,
            updated_at=now,
            shares=[
                AtkShareInfo(
                    id=uuid4(),
                    email="user@example.com",
                    scope="users",
                    shared_at=now,
                )
            ],
            deployment_logs=[
                AtkDeploymentLogEntry(
                    id=uuid4(),
                    action="scaffold",
                    environment=None,
                    status="success",
                    details=None,
                    performed_by=user_id,
                    performed_at=now,
                ),
                AtkDeploymentLogEntry(
                    id=uuid4(),
                    action="provision",
                    environment="dev",
                    status="success",
                    details=None,
                    performed_by=user_id,
                    performed_at=now,
                ),
            ],
        )
        assert detail.m365_app_id == "app-123-456"
        assert len(detail.shares) == 1
        assert detail.shares[0].email == "user@example.com"
        assert len(detail.deployment_logs) == 2

    def test_atk_agent_detail_serialization(self):
        """Ensure models serialize to JSON (for API responses)."""
        from druppie.domain.atk_agent import AtkAgentSummary, AtkAgentStatus

        summary = AtkAgentSummary(
            id=uuid4(),
            name="serialize-test",
            description=None,
            environment="dev",
            status=AtkAgentStatus.SCAFFOLDED,
            project_id=None,
            created_at=datetime.now(timezone.utc),
        )
        data = summary.model_dump(mode="json")
        assert isinstance(data["id"], str)
        assert data["name"] == "serialize-test"
        assert data["status"] == "scaffolded"


# =============================================================================
# MCP Server Tool Tests (filesystem-level, no ATK CLI)
# =============================================================================


def _import_atk_server(projects_dir: Path):
    """Import ATK server module with mocked fastmcp and custom projects dir.

    The ATK MCP server lives in mcp-servers/atk/ (non-importable path) and
    depends on fastmcp (Docker-only). We mock fastmcp and use importlib to
    load the module, then override ATK_PROJECTS_DIR for test isolation.
    """
    import importlib.util

    # Mock fastmcp before loading the server module
    mock_fastmcp = MagicMock()
    # FastMCP().tool() is a decorator — make it return the function unchanged
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.tool.return_value = lambda fn: fn
    mock_fastmcp.FastMCP.return_value = mock_mcp_instance

    saved = sys.modules.get("fastmcp")
    sys.modules["fastmcp"] = mock_fastmcp
    try:
        server_path = Path(__file__).parent.parent / "mcp-servers" / "atk" / "server.py"
        spec = importlib.util.spec_from_file_location("atk_server_test", server_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        # Restore original state
        if saved is not None:
            sys.modules["fastmcp"] = saved
        else:
            del sys.modules["fastmcp"]

    # Override projects directory for test isolation
    module.ATK_PROJECTS_DIR = projects_dir
    return module


class TestAtkMcpServerTools:
    """Test MCP server tool logic that doesn't require ATK CLI."""

    def test_list_agents_empty_dir(self, tmp_path):
        """list_agents should return empty list for empty directory."""
        import asyncio

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(server.list_agents())
        assert result["success"] is True
        assert result["count"] == 0
        assert result["agents"] == []

    def test_list_agents_with_projects(self, tmp_path):
        """list_agents should find project directories."""
        import asyncio

        # Create a fake project with manifest
        project_dir = tmp_path / "test-agent" / "appPackage"
        project_dir.mkdir(parents=True)
        manifest = {"description": "Test agent"}
        (project_dir / "declarativeAgent.json").write_text(json.dumps(manifest))

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(server.list_agents())
        assert result["success"] is True
        assert result["count"] == 1
        assert result["agents"][0]["name"] == "test-agent"
        assert result["agents"][0]["description"] == "Test agent"
        assert result["agents"][0]["has_manifest"] is True

    def test_get_agent_status_not_found(self, tmp_path):
        """get_agent_status should error for missing project."""
        import asyncio

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            server.get_agent_status("nonexistent")
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_get_agent_status_with_manifest(self, tmp_path):
        """get_agent_status should read manifest and env files."""
        import asyncio

        # Create project with manifest
        project_dir = tmp_path / "my-agent"
        app_dir = project_dir / "appPackage"
        app_dir.mkdir(parents=True)
        manifest = {"description": "My agent", "instructions": "Help users"}
        (app_dir / "declarativeAgent.json").write_text(json.dumps(manifest))

        # Create env file
        env_dir = project_dir / "env"
        env_dir.mkdir()
        (env_dir / ".env.dev").write_text("M365_APP_ID=test-app-id-123\n")

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            server.get_agent_status("my-agent")
        )
        assert result["success"] is True
        assert result["name"] == "my-agent"
        assert result["has_manifest"] is True
        assert result["manifest"]["description"] == "My agent"
        assert "dev" in result["environments"]
        assert result["m365_app_id"] == "test-app-id-123"

    def test_configure_manifest_read_only(self, tmp_path):
        """configure_manifest should read manifest without changes."""
        import asyncio

        project_dir = tmp_path / "read-agent" / "appPackage"
        project_dir.mkdir(parents=True)
        manifest = {"description": "Original", "instructions": "Do things"}
        (project_dir / "declarativeAgent.json").write_text(json.dumps(manifest))

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            server.configure_manifest("read-agent")
        )
        assert result["success"] is True
        assert result["updated"] is False
        assert result["manifest"]["description"] == "Original"

    def test_configure_manifest_update(self, tmp_path):
        """configure_manifest should update manifest fields."""
        import asyncio

        project_dir = tmp_path / "update-agent" / "appPackage"
        project_dir.mkdir(parents=True)
        manifest = {"description": "Old", "instructions": "Old instructions"}
        manifest_path = project_dir / "declarativeAgent.json"
        manifest_path.write_text(json.dumps(manifest))

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            server.configure_manifest(
                "update-agent",
                description="New description",
                instructions="New instructions",
            )
        )
        assert result["success"] is True
        assert result["updated"] is True
        assert result["manifest"]["description"] == "New description"
        assert result["manifest"]["instructions"] == "New instructions"

        # Verify file was actually written
        saved = json.loads(manifest_path.read_text())
        assert saved["description"] == "New description"

    def test_scaffold_agent_existing_dir(self, tmp_path):
        """scaffold_agent should fail if directory already exists."""
        import asyncio

        (tmp_path / "existing-agent").mkdir()

        server = _import_atk_server(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            server.scaffold_agent("existing-agent")
        )
        assert result["success"] is False
        assert "already exists" in result["error"]


# =============================================================================
# Service Layer Tests (mocked repository)
# =============================================================================


class TestAtkService:
    """Test AtkService business logic with mocked repository."""

    def _make_service(self):
        from druppie.services.atk_service import AtkService

        mock_repo = MagicMock()
        service = AtkService(mock_repo)
        return service, mock_repo

    def test_list_agents_pagination(self):
        service, mock_repo = self._make_service()
        mock_repo.list_all.return_value = ([], 0)

        items, total = service.list_agents(page=2, limit=10)

        mock_repo.list_all.assert_called_once_with(10, 10)  # offset = (2-1)*10
        assert items == []
        assert total == 0

    def test_get_detail_not_found(self):
        service, mock_repo = self._make_service()
        mock_repo.get_detail.return_value = None

        with pytest.raises(Exception) as exc_info:
            service.get_detail(uuid4())

        assert "not found" in str(exc_info.value).lower() or "NotFoundError" in type(exc_info.value).__name__

    def test_get_detail_success(self):
        from druppie.domain.atk_agent import AtkAgentDetail, AtkAgentStatus

        service, mock_repo = self._make_service()
        now = datetime.now(timezone.utc)
        agent_id = uuid4()
        detail = AtkAgentDetail(
            id=agent_id,
            name="test",
            description=None,
            environment="dev",
            status=AtkAgentStatus.SCAFFOLDED,
            project_id=None,
            created_at=now,
            m365_app_id=None,
            created_by=uuid4(),
            updated_at=now,
            shares=[],
            deployment_logs=[],
        )
        mock_repo.get_detail.return_value = detail

        result = service.get_detail(agent_id)
        assert result.id == agent_id

    def test_record_scaffold(self):
        from druppie.domain.atk_agent import AtkAgentSummary, AtkAgentStatus

        service, mock_repo = self._make_service()
        user_id = uuid4()

        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "new-agent"
        mock_agent.description = "desc"
        mock_agent.environment = "dev"
        mock_agent.status = "scaffolded"
        mock_agent.project_id = None
        mock_agent.created_at = datetime.now(timezone.utc)

        mock_repo.create.return_value = mock_agent
        mock_repo._to_summary.return_value = AtkAgentSummary(
            id=mock_agent.id,
            name="new-agent",
            description="desc",
            environment="dev",
            status=AtkAgentStatus.SCAFFOLDED,
            project_id=None,
            created_at=mock_agent.created_at,
        )

        result = service.record_scaffold("new-agent", user_id, description="desc")

        mock_repo.create.assert_called_once()
        mock_repo.add_log.assert_called_once()
        mock_repo.commit.assert_called_once()
        assert result.name == "new-agent"

    def test_record_provision_not_found(self):
        service, mock_repo = self._make_service()
        mock_repo.get_by_id.return_value = None

        with pytest.raises(Exception):
            service.record_provision(uuid4(), uuid4(), "dev")

    def test_record_provision_success(self):
        service, mock_repo = self._make_service()
        mock_repo.get_by_id.return_value = MagicMock()

        service.record_provision(uuid4(), uuid4(), "dev", m365_app_id="app-123")

        mock_repo.update_status.assert_called_once()
        mock_repo.add_log.assert_called_once()
        mock_repo.commit.assert_called_once()

    def test_record_uninstall(self):
        service, mock_repo = self._make_service()
        mock_repo.get_by_id.return_value = MagicMock()

        agent_id = uuid4()
        user_id = uuid4()
        service.record_uninstall(agent_id, user_id)

        mock_repo.update_status.assert_called_once_with(agent_id, "uninstalled")
        mock_repo.commit.assert_called_once()


# =============================================================================
# Import Verification Tests
# =============================================================================


def _can_import(module_name: str) -> bool:
    """Check if a module can be imported without actually importing it."""
    import importlib.util
    return importlib.util.find_spec(module_name) is not None


class TestImports:
    """Verify all new modules import cleanly."""

    def test_import_domain_models(self):
        from druppie.domain.atk_agent import (
            AtkAgentStatus,
            AtkAgentSummary,
            AtkAgentDetail,
            AtkShareInfo,
            AtkDeploymentLogEntry,
        )

    def test_import_domain_init(self):
        from druppie.domain import (
            AtkAgentStatus,
            AtkAgentSummary,
            AtkAgentDetail,
            AtkShareInfo,
            AtkDeploymentLogEntry,
        )

    def test_import_db_models(self):
        from druppie.db.models.atk_agent import AtkAgent, AtkAgentShare, AtkDeploymentLog

    def test_import_db_init(self):
        from druppie.db.models import AtkAgent, AtkAgentShare, AtkDeploymentLog

    def test_import_repository(self):
        from druppie.repositories.atk_agent_repository import AtkAgentRepository

    def test_import_repository_init(self):
        from druppie.repositories import AtkAgentRepository

    @pytest.mark.skipif(
        "pydantic_settings" not in sys.modules and not _can_import("pydantic_settings"),
        reason="pydantic_settings not available (Docker-only dep chain)",
    )
    def test_import_service(self):
        from druppie.services.atk_service import AtkService

    @pytest.mark.skipif(
        "pydantic_settings" not in sys.modules and not _can_import("pydantic_settings"),
        reason="pydantic_settings not available (Docker-only dep chain)",
    )
    def test_import_service_init(self):
        from druppie.services import AtkService
