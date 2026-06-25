"""Tests for the Harbor registry webhook auth (fail-closed).

The endpoint can trigger cluster rollouts from an untrusted payload, so it must
reject every request unless a shared secret is configured AND matches.
"""

from unittest.mock import AsyncMock, patch

import pytest

from druppie.api.routes import registry_webhook
from druppie.api.routes.registry_webhook import _verify_secret, harbor_webhook


def test_verify_secret_fails_closed_when_unconfigured():
    with patch.object(registry_webhook, "REGISTRY_WEBHOOK_SECRET", ""):
        assert _verify_secret(None) is False
        assert _verify_secret("anything") is False


def test_verify_secret_requires_exact_match():
    with patch.object(registry_webhook, "REGISTRY_WEBHOOK_SECRET", "topsecret"):
        assert _verify_secret(None) is False
        assert _verify_secret("wrong") is False
        assert _verify_secret("topsecret") is True


@pytest.mark.asyncio
async def test_webhook_does_not_deploy_when_no_secret_configured():
    """A push event must NOT trigger a deploy when the endpoint is unsecured."""
    deploy_service = AsyncMock()
    payload = {
        "type": "PUSH_ARTIFACT",
        "event_data": {"resources": [{"resource_url": "harbor/druppie/backend", "tag": "latest"}]},
    }
    with patch.object(registry_webhook, "REGISTRY_WEBHOOK_SECRET", ""):
        result = await harbor_webhook(
            payload=payload,
            deploy_service=deploy_service,
            x_registry_webhook_secret="whatever",
        )

    assert result["status"] == "unauthorized"
    deploy_service.trigger_deploy.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_deploys_with_valid_secret():
    deploy_service = AsyncMock()
    deploy_service.trigger_deploy = AsyncMock(return_value={"ok": True})
    payload = {
        "type": "PUSH_ARTIFACT",
        "event_data": {"resources": [{"resource_url": "harbor/druppie/backend", "tag": "v1"}]},
    }
    with patch.object(registry_webhook, "REGISTRY_WEBHOOK_SECRET", "topsecret"):
        result = await harbor_webhook(
            payload=payload,
            deploy_service=deploy_service,
            x_registry_webhook_secret="topsecret",
        )

    assert result["status"] == "accepted"
    deploy_service.trigger_deploy.assert_awaited_once_with(
        image="harbor/druppie/backend", tag="v1"
    )
