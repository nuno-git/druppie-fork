"""Route-level tests for deployments.py.

Focus: ownership enforcement on mutations and scoping on reads.
MCP calls are mocked; no Docker daemon is required.
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from druppie.api.deps import get_current_user
from druppie.api.main import create_app
from druppie.api.routes import deployments as dep_mod


ADMIN_SUB = "11111111-1111-1111-1111-111111111111"
OWNER_SUB = "22222222-2222-2222-2222-222222222222"
OTHER_SUB = "33333333-3333-3333-3333-333333333333"
PROJECT_ID = "proj-abc"


def _user(sub: str, admin: bool = False) -> dict:
    roles = ["admin"] if admin else ["user"]
    return {"sub": sub, "realm_access": {"roles": roles}}


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def as_admin(app):
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, admin=True)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def as_owner(app):
    app.dependency_overrides[get_current_user] = lambda: _user(OWNER_SUB, admin=False)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def as_other(app):
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB, admin=False)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mcp():
    fake = AsyncMock()
    with patch.object(dep_mod, "get_mcp_http", return_value=fake):
        yield fake


def _inspect_ok(user_id: str | None, project_id: str = PROJECT_ID):
    labels = {"druppie.project_id": project_id}
    if user_id:
        labels["druppie.user_id"] = user_id
    return {"success": True, "labels": labels}


# =============================================================================
# _verify_owner_or_admin via start endpoint
# =============================================================================


def test_start_admin_bypasses_ownership(client, mcp, as_admin):
    mcp.call.side_effect = [{"success": True}]
    r = client.post("/api/deployments/some-container/start")
    assert r.status_code == 200
    assert mcp.call.await_count == 1
    assert mcp.call.call_args.kwargs["tool"] == "start"


def test_start_owner_allowed(client, mcp, as_owner):
    mcp.call.side_effect = [_inspect_ok(OWNER_SUB), {"success": True}]
    r = client.post("/api/deployments/some-container/start")
    assert r.status_code == 200
    assert mcp.call.await_count == 2


def test_start_non_owner_403(client, mcp, as_other):
    mcp.call.side_effect = [_inspect_ok(OWNER_SUB)]
    r = client.post("/api/deployments/some-container/start")
    assert r.status_code == 403


def test_start_missing_owner_label_denied(client, mcp, as_other):
    # Fail closed: no druppie.user_id on a container means no non-admin may act on it.
    mcp.call.side_effect = [_inspect_ok(user_id=None)]
    r = client.post("/api/deployments/some-container/start")
    assert r.status_code == 403


def test_start_inspect_failure_404(client, mcp, as_other):
    mcp.call.side_effect = [{"success": False}]
    r = client.post("/api/deployments/ghost/start")
    assert r.status_code == 404


# =============================================================================
# stop/restart/logs use the same helper — spot-check one each
# =============================================================================


def test_stop_missing_owner_label_denied(client, mcp, as_other):
    mcp.call.side_effect = [_inspect_ok(user_id=None)]
    r = client.post("/api/deployments/some-container/stop")
    assert r.status_code == 403


def test_restart_non_owner_403(client, mcp, as_other):
    mcp.call.side_effect = [_inspect_ok(OWNER_SUB)]
    r = client.post("/api/deployments/some-container/restart")
    assert r.status_code == 403


def test_logs_missing_owner_label_denied(client, mcp, as_other):
    mcp.call.side_effect = [_inspect_ok(user_id=None)]
    r = client.get("/api/deployments/some-container/logs")
    assert r.status_code == 403


# =============================================================================
# wipe_project
# =============================================================================


def _list_containers(containers: list[dict]):
    return {"success": True, "containers": containers}


def test_wipe_admin_removes_all(client, mcp, as_admin):
    containers = [
        {"name": "app-1",
         "labels": {"druppie.project_id": PROJECT_ID, "druppie.user_id": OWNER_SUB,
                    "druppie.compose_project": "app"}},
    ]
    mcp.call.side_effect = [
        _list_containers(containers),
        {"success": True},
        {"success": True, "volumes": []},
    ]
    r = client.post(f"/api/deployments/project/{PROJECT_ID}/wipe")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["containers_removed"] == ["app-1"]


def test_wipe_owner_allowed(client, mcp, as_owner):
    containers = [
        {"name": "app-1",
         "labels": {"druppie.project_id": PROJECT_ID, "druppie.user_id": OWNER_SUB}},
    ]
    mcp.call.side_effect = [
        _list_containers(containers),
        {"success": True},
        {"success": True, "volumes": []},
    ]
    r = client.post(f"/api/deployments/project/{PROJECT_ID}/wipe")
    assert r.status_code == 200


def test_wipe_non_owner_403(client, mcp, as_other):
    containers = [
        {"name": "app-1",
         "labels": {"druppie.project_id": PROJECT_ID, "druppie.user_id": OWNER_SUB}},
    ]
    mcp.call.side_effect = [_list_containers(containers)]
    r = client.post(f"/api/deployments/project/{PROJECT_ID}/wipe")
    assert r.status_code == 403


def test_wipe_missing_label_is_foreign(client, mcp, as_other):
    # A container without druppie.user_id must NOT be wipeable by a non-admin.
    containers = [{"name": "x", "labels": {"druppie.project_id": PROJECT_ID}}]
    mcp.call.side_effect = [_list_containers(containers)]
    r = client.post(f"/api/deployments/project/{PROJECT_ID}/wipe")
    assert r.status_code == 403


def test_wipe_empty_project_404_for_non_admin(client, mcp, as_other):
    mcp.call.side_effect = [_list_containers([])]
    r = client.post(f"/api/deployments/project/{PROJECT_ID}/wipe")
    assert r.status_code == 404


# =============================================================================
# list_volumes scoping
# =============================================================================


def test_list_volumes_admin_sees_linked(client, mcp, as_admin):
    mcp.call.side_effect = [
        {"success": True, "volumes": [
            {"name": "foo_pgdata", "driver": "local",
             "labels": {"com.docker.compose.project": "foo"},
             "compose_project": "foo"},
        ]},
        {"success": True, "containers": [
            {"labels": {"druppie.compose_project": "foo",
                        "druppie.project_id": PROJECT_ID,
                        "druppie.user_id": OWNER_SUB}},
        ]},
    ]
    r = client.get("/api/deployments/volumes/list")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["project_id"] == PROJECT_ID


def test_list_volumes_non_admin_scoped(client, mcp, as_other):
    # Volume's linked project is owned by someone else → non-admin sees none.
    mcp.call.side_effect = [
        {"success": True, "volumes": [
            {"name": "foo_pgdata", "driver": "local",
             "labels": {"com.docker.compose.project": "foo"},
             "compose_project": "foo"},
        ]},
        {"success": True, "containers": [
            {"labels": {"druppie.compose_project": "foo",
                        "druppie.project_id": PROJECT_ID,
                        "druppie.user_id": OWNER_SUB}},
        ]},
    ]
    r = client.get("/api/deployments/volumes/list")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_list_volumes_drops_unlinked(client, mcp, as_admin):
    # Volume with no matching druppie container must not appear even for admins.
    mcp.call.side_effect = [
        {"success": True, "volumes": [
            {"name": "random_vol", "driver": "local",
             "labels": {}, "compose_project": None},
        ]},
        {"success": True, "containers": []},
    ]
    r = client.get("/api/deployments/volumes/list")
    assert r.status_code == 200
    assert r.json()["count"] == 0
