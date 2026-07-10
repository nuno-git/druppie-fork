"""Route-level tests for notifications.py.

Focus: auth scoping (user only sees/reads own notifications), error mapping.
Repository is mocked via dependency_overrides -- no DB required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from druppie.api.deps import get_current_user
from druppie.api.main import create_app
from druppie.api.routes.notifications import _get_notification_repo
from druppie.db.models.notification import Notification

USER_A_SUB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B_SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
NOTIF_ID_A = uuid4()
NOTIF_ID_B = uuid4()


def _user(sub: str, roles: list[str] | None = None) -> dict:
    return {"sub": sub, "realm_access": {"roles": roles or ["user"]}}


def _fake_notification(
    notification_id: UUID = NOTIF_ID_A,
    user_id_str: str = USER_A_SUB,
    is_read: bool = False,
) -> MagicMock:
    n = MagicMock(spec=Notification)
    n.id = notification_id
    n.user_id = UUID(user_id_str)
    n.session_id = uuid4()
    n.kind = "hitl_pause"
    n.role = "business_analyst"
    n.message = "Session awaiting BA review"
    n.is_read = is_read
    n.created_at = datetime.now(timezone.utc)
    return n


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def mock_repo():
    return MagicMock()


@pytest.fixture()
def as_user_a(app, mock_repo):
    app.dependency_overrides[get_current_user] = lambda: _user(USER_A_SUB)
    app.dependency_overrides[_get_notification_repo] = lambda: mock_repo
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def as_user_b(app, mock_repo):
    app.dependency_overrides[get_current_user] = lambda: _user(USER_B_SUB)
    app.dependency_overrides[_get_notification_repo] = lambda: mock_repo
    yield
    app.dependency_overrides.clear()


class TestListNotificationsRoute:
    BASE = "/api/notifications"

    def test_returns_own_notifications(self, client, as_user_a, mock_repo):
        mock_repo.get_for_user.return_value = [_fake_notification()]
        mock_repo.db = MagicMock()

        r = client.get(self.BASE)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == str(NOTIF_ID_A)
        mock_repo.get_for_user.assert_called_once_with(UUID(USER_A_SUB))

    def test_empty_list(self, client, as_user_a, mock_repo):
        mock_repo.get_for_user.return_value = []
        mock_repo.db = MagicMock()

        r = client.get(self.BASE)
        assert r.status_code == 200
        assert r.json() == []

    def test_different_user_sees_own_only(self, client, as_user_b, mock_repo):
        notif_b = _fake_notification(notification_id=NOTIF_ID_B, user_id_str=USER_B_SUB)
        mock_repo.get_for_user.return_value = [notif_b]
        mock_repo.db = MagicMock()

        r = client.get(self.BASE)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == str(NOTIF_ID_B)
        mock_repo.get_for_user.assert_called_once_with(UUID(USER_B_SUB))


class TestMarkAsReadRoute:
    def _url(self, notification_id: UUID) -> str:
        return f"/api/notifications/{notification_id}/read"

    def test_mark_own_notification_read(self, client, as_user_a, mock_repo):
        mock_repo.mark_as_read.return_value = True
        mock_repo.db = MagicMock()

        r = client.post(self._url(NOTIF_ID_A))
        assert r.status_code == 200
        mock_repo.mark_as_read.assert_called_once_with(NOTIF_ID_A, UUID(USER_A_SUB))
        mock_repo.db.commit.assert_called_once()

    def test_mark_already_read_returns_404(self, client, as_user_a, mock_repo):
        mock_repo.mark_as_read.return_value = False
        mock_repo.db = MagicMock()

        r = client.post(self._url(NOTIF_ID_A))
        assert r.status_code == 404

    def test_mark_other_users_notification_returns_404(self, client, as_user_b, mock_repo):
        mock_repo.mark_as_read.return_value = False
        mock_repo.db = MagicMock()

        r = client.post(self._url(NOTIF_ID_A))
        assert r.status_code == 404
