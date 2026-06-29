"""Regression tests for Guacamole connection-permission JSON patches.

Guacamole keys ``connectionPermissions`` by connection IDENTIFIER, not by
connection name. A prior bug passed the connection name into the patch path
(``/connectionPermissions/{name}``), so per-VM READ grants never matched the
connection and isolation silently failed. These tests pin the patch path to the
identifier.
"""

from unittest.mock import AsyncMock

import pytest

from druppie.core.guacamole import GuacamoleClient


def _make_client() -> GuacamoleClient:
    """A client whose user lookup and HTTP layer are stubbed out."""
    client = GuacamoleClient()
    # User already exists -> skip the create-user branch.
    client.get_user_id = AsyncMock(return_value="user-id-1")
    client._request = AsyncMock(return_value={"success": True, "data": {}})
    return client


def _patch_payload(client: GuacamoleClient) -> tuple[str, str, list]:
    """Extract (method, path, json_data) from the single _request call."""
    args, kwargs = client._request.call_args
    method, path = args[0], args[1]
    return method, path, kwargs["json_data"]


@pytest.mark.asyncio
async def test_grant_uses_connection_identifier_in_patch_path():
    client = _make_client()

    result = await client.grant_read_permission("alice", "1234")

    assert result["success"] is True
    method, path, patch = _patch_payload(client)
    assert method == "PATCH"
    assert path == "/guacamole/api/session/data/postgresql/users/user-id-1"
    assert patch == [
        {"op": "add", "path": "/connectionPermissions/1234", "value": "READ"}
    ]


@pytest.mark.asyncio
async def test_revoke_uses_connection_identifier_and_omits_value():
    client = _make_client()

    await client.revoke_read_permission("alice", "1234")

    _, _, patch = _patch_payload(client)
    assert patch == [{"op": "remove", "path": "/connectionPermissions/1234"}]
    assert "value" not in patch[0]


@pytest.mark.asyncio
async def test_register_guacamole_grants_on_identifier_not_name():
    """The service must grant READ keyed by the connection identifier returned
    by create_connection, never the (human-readable) container name."""
    from druppie.services.dev_env_service import DevEnvService

    # Bypass __init__ so we don't construct the real Guacamole/K8s clients.
    svc = DevEnvService.__new__(DevEnvService)
    guac = AsyncMock()
    guac.create_connection = AsyncMock(
        return_value={
            "success": True,
            "data": {"identifier": "42", "name": "dev-vm-alice"},
            "connection_id": "42",
            "name": "dev-vm-alice",
        }
    )
    guac.grant_read_permission = AsyncMock(return_value={"success": True})
    svc.guac = guac

    conn_id = await svc._register_guacamole(
        container_name="dev-vm-alice",
        container_ip="10.0.0.5",
        username="alice",
        creds={},
    )

    assert conn_id == "42"
    guac.grant_read_permission.assert_awaited_once_with("alice", "42")
    # Regression guard: the old bug passed the container name here.
    assert guac.grant_read_permission.await_args.args[1] != "dev-vm-alice"
