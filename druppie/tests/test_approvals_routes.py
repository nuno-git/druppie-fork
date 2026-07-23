"""Route-level tests for approvals.py.

Focus: the resume-after-decision spawn uses the DB-guarded
``create_session_task`` and maps ``SessionTaskConflict`` to HTTP 409
(matching chat.py / sessions.py). Service and orchestrator are mocked —
no DB required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from druppie.api.deps import get_approval_service, get_current_user
from druppie.api.main import create_app
from druppie.api.routes import approvals as appr_mod
from druppie.core.background_tasks import SessionTaskConflict
from druppie.domain.approval import ApprovalDetail
from druppie.domain.common import ApprovalStatus

ADMIN_SUB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

APPROVAL_ID = uuid4()
SESSION_ID = uuid4()


def _user(sub: str, roles: list[str] | None = None) -> dict:
    return {"sub": sub, "realm_access": {"roles": roles or ["user"]}}


def _fake_approval(status: ApprovalStatus = ApprovalStatus.APPROVED) -> ApprovalDetail:
    return ApprovalDetail(
        id=APPROVAL_ID,
        status=status,
        required_role="developer",
        session_id=SESSION_ID,
        agent_run_id=uuid4(),
        tool_call_id=uuid4(),
        mcp_server="coding",
        tool_name="write_file",
        arguments={"path": "/app/main.py"},
        agent_id="developer",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def mock_service():
    return MagicMock()


@pytest.fixture()
def as_admin(app, mock_service):
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, ["admin"])
    app.dependency_overrides[get_approval_service] = lambda: mock_service
    with patch.object(appr_mod, "create_session_task"), \
         patch.object(appr_mod, "_resume_workflow_after_approval"):
        yield
    app.dependency_overrides.clear()


class TestApproveRoute:
    BASE = f"/api/approvals/{APPROVAL_ID}/approve"

    def test_approve_happy_path(self, client, as_admin, mock_service):
        mock_service.approve.return_value = _fake_approval(ApprovalStatus.APPROVED)
        r = client.post(self.BASE)
        assert r.status_code == 200
        assert r.json()["approval"]["status"] == "approved"
        mock_service.approve.assert_called_once()

    def test_approve_409_task_already_running(self, client, as_admin, mock_service):
        mock_service.approve.return_value = _fake_approval(ApprovalStatus.APPROVED)
        appr_mod.create_session_task.side_effect = SessionTaskConflict(
            "A background task is already running"
        )
        r = client.post(self.BASE)
        assert r.status_code == 409


class TestRejectRoute:
    BASE = f"/api/approvals/{APPROVAL_ID}/reject"

    def test_reject_happy_path(self, client, as_admin, mock_service):
        mock_service.reject.return_value = _fake_approval(ApprovalStatus.REJECTED)
        r = client.post(self.BASE, json={"reason": "wrong approach"})
        assert r.status_code == 200
        assert r.json()["approval"]["status"] == "rejected"
        mock_service.reject.assert_called_once()

    def test_reject_409_task_already_running(self, client, as_admin, mock_service):
        mock_service.reject.return_value = _fake_approval(ApprovalStatus.REJECTED)
        appr_mod.create_session_task.side_effect = SessionTaskConflict(
            "A background task is already running"
        )
        r = client.post(self.BASE, json={"reason": "wrong approach"})
        assert r.status_code == 409
