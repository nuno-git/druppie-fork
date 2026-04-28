"""Async tests for MCP tool functions (validate, list, deploy).

FoundryClient is mocked — these tests exercise the pipeline logic
in tools.py without touching Azure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from v1.tools import deploy_agent, list_foundry_tools, validate_agent_yaml

VALID_YAML = """
name: test-agent
model: gpt-4o-mini
instructions: You are a helpful agent. Always be concise and professional.
"""

VALID_YAML_WITH_TOOL = """
name: test-agent
model: gpt-4o-mini
instructions: You are a helpful agent. Always be concise and professional.
tools:
  - type: code_interpreter
"""

INVALID_YAML = """
name: has spaces!
model: ""
"""


# ------------------------------------------------------------------
# validate_agent_yaml
# ------------------------------------------------------------------


class TestValidateAgentYaml:
    @pytest.mark.asyncio
    async def test_valid_yaml_passes(self):
        r = await validate_agent_yaml(VALID_YAML)
        assert r["ok"] is True
        assert r["valid"] is True
        assert r["errors"] == []
        assert r["normalized"]["name"] == "test-agent"

    @pytest.mark.asyncio
    async def test_invalid_yaml_returns_errors(self):
        r = await validate_agent_yaml(INVALID_YAML)
        assert r["ok"] is False
        assert r["valid"] is False
        assert len(r["errors"]) > 0

    @pytest.mark.asyncio
    async def test_empty_yaml_fails(self):
        r = await validate_agent_yaml("")
        assert r["ok"] is False


# ------------------------------------------------------------------
# list_foundry_tools
# ------------------------------------------------------------------


def _mock_client(connections_ok=True, models_ok=True, connections=None, models=None):
    client = MagicMock()
    client.endpoint = "https://test.endpoint.azure.com"

    if connections_ok:
        client.list_connections.return_value = {
            "ok": True,
            "connections": connections or [],
            "by_tool_type": {},
        }
    else:
        client.list_connections.return_value = {
            "ok": False,
            "reason": "connection failed",
            "code": "connection_error",
        }

    if models_ok:
        client.list_deployed_models.return_value = {
            "ok": True,
            "models": models or [{"name": "gpt-4o-mini", "model": "gpt-4o-mini"}],
        }
    else:
        client.list_deployed_models.return_value = {
            "ok": False,
            "reason": "SDK has no deployments accessor",
            "code": "unsupported",
            "models": [],
        }

    return client


class TestListFoundryTools:
    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_success(self, mock_client_fn):
        mock_client_fn.return_value = _mock_client()
        r = await list_foundry_tools()
        assert r["ok"] is True
        assert "always_available" in r
        assert "connection_backed" in r
        assert "deployed_models" in r

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_connection_failure(self, mock_client_fn):
        mock_client_fn.return_value = _mock_client(connections_ok=False)
        r = await list_foundry_tools()
        assert r["ok"] is False
        assert "reason" in r

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_models_failure_adds_warning(self, mock_client_fn):
        mock_client_fn.return_value = _mock_client(models_ok=False)
        r = await list_foundry_tools()
        assert r["ok"] is True
        assert "deployed_models_warning" in r
        assert r["deployed_models"] == []


# ------------------------------------------------------------------
# deploy_agent
# ------------------------------------------------------------------


class TestDeployAgent:
    @pytest.mark.asyncio
    async def test_schema_fail_aborts(self):
        r = await deploy_agent(INVALID_YAML)
        assert r["ok"] is False
        assert r["stage"] == "validate"

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_availability_fail_aborts(self, mock_client_fn):
        mock_client_fn.return_value = _mock_client(connections_ok=False)
        r = await deploy_agent(VALID_YAML)
        assert r["ok"] is False
        assert r["stage"] == "availability"

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_model_mismatch_aborts(self, mock_client_fn):
        client = _mock_client(models=[{"name": "gpt-4o", "model": "gpt-4o"}])
        mock_client_fn.return_value = client
        r = await deploy_agent(VALID_YAML)
        assert r["ok"] is False
        assert r["stage"] == "availability"
        assert any(e["code"] == "model_not_deployed" for e in r["errors"])

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_dry_run_success(self, mock_client_fn):
        mock_client_fn.return_value = _mock_client()
        r = await deploy_agent(VALID_YAML, dry_run=True)
        assert r["ok"] is True
        assert r["dry_run"] is True
        assert r["plan"]["name"] == "test-agent"

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_deploy_success(self, mock_client_fn):
        client = _mock_client()
        client.create_agent.return_value = {
            "ok": True,
            "foundry_agent_id": "agent-123",
            "name": "test-agent",
            "version": "1",
            "model": "gpt-4o-mini",
            "deployed_at": "2026-04-28T00:00:00+00:00",
        }
        mock_client_fn.return_value = client
        r = await deploy_agent(VALID_YAML)
        assert r["ok"] is True
        assert r["stage"] == "deploy"
        assert r["deployment"]["foundry_agent_id"] == "agent-123"

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_deploy_failure(self, mock_client_fn):
        client = _mock_client()
        client.create_agent.return_value = {
            "ok": False,
            "reason": "Foundry rejected deployment: quota exceeded",
            "code": "deploy_failed",
        }
        mock_client_fn.return_value = client
        r = await deploy_agent(VALID_YAML)
        assert r["ok"] is False
        assert r["stage"] == "deploy"

    @pytest.mark.asyncio
    @patch("v1.tools._client")
    async def test_deploy_with_skipped_tools_adds_warning(self, mock_client_fn):
        yaml_with_browser = """
name: test-agent
model: gpt-4o-mini
instructions: You are a helpful agent. Always be concise and professional.
tools:
  - type: browser_automation
"""
        client = _mock_client()
        client.create_agent.return_value = {
            "ok": True,
            "foundry_agent_id": "agent-456",
            "name": "test-agent",
            "version": "1",
            "model": "gpt-4o-mini",
            "deployed_at": "2026-04-28T00:00:00+00:00",
            "skipped_tools": ["browser_automation"],
        }
        mock_client_fn.return_value = client
        r = await deploy_agent(yaml_with_browser)
        assert r["ok"] is True
        assert any("skipped" in w["message"] for w in r["warnings"])
