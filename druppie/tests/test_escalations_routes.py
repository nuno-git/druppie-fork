"""Route-level tests for escalations.py.

Focus: auth enforcement, error mapping, request validation.
Service and orchestrator are mocked — no DB required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from druppie.api.deps import get_current_user, get_escalation_service, get_orchestrator
from druppie.api.errors import AuthorizationError, ConflictError, NotFoundError
from druppie.api.main import create_app
from druppie.api.routes import escalations as esc_mod
from druppie.core.background_tasks import SessionTaskConflict
from druppie.domain.common import EscalationEventType
from druppie.domain.escalation import EscalationEventDetail, EscalationEventList

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_SUB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BA_SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ARCHITECT_SUB = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OWNER_SUB = "dddddddd-dddd-dddd-dddd-dddddddddddd"
PLAIN_SUB = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

SESSION_ID = uuid4()
EVENT_ID = uuid4()


def _user(sub: str, roles: list[str] | None = None) -> dict:
    return {"sub": sub, "realm_access": {"roles": roles or ["user"]}}


def _override_deps(app, mock_service, mock_orchestrator) -> None:
    """Wire mocked service/orchestrator via FastAPI dependency overrides.

    patch.object(esc_mod, ...) does NOT intercept dependencies that FastAPI
    captures by reference at route-definition time; dependency_overrides does.
    """
    app.dependency_overrides[get_escalation_service] = lambda: mock_service
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator


def _fake_event(**overrides) -> EscalationEventDetail:
    defaults = dict(
        id=EVENT_ID,
        session_id=SESSION_ID,
        event_type=EscalationEventType.BA_HITL_ITERATE,
        actor_user_id=None,
        created_at=datetime.now(timezone.utc),
        decision="iterate",
        feedback=None,
        rejection_count_at_event=0,
    )
    defaults.update(overrides)
    return EscalationEventDetail(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def mock_orchestrator():
    return MagicMock()


@pytest.fixture()
def as_admin(app, mock_service, mock_orchestrator):
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, ["admin"])
    _override_deps(app, mock_service, mock_orchestrator)
    with patch.object(esc_mod, "create_session_task"), \
         patch.object(esc_mod, "_resume_ba_hitl"), \
         patch.object(esc_mod, "_resume_architect_hitl"):
        yield
    app.dependency_overrides.clear()


@pytest.fixture()
def as_ba(app, mock_service, mock_orchestrator):
    app.dependency_overrides[get_current_user] = lambda: _user(BA_SUB, ["business_analyst"])
    _override_deps(app, mock_service, mock_orchestrator)
    with patch.object(esc_mod, "create_session_task"), \
         patch.object(esc_mod, "_resume_ba_hitl"), \
         patch.object(esc_mod, "_resume_architect_hitl"):
        yield
    app.dependency_overrides.clear()


@pytest.fixture()
def as_architect(app, mock_service, mock_orchestrator):
    app.dependency_overrides[get_current_user] = lambda: _user(ARCHITECT_SUB, ["architect"])
    _override_deps(app, mock_service, mock_orchestrator)
    with patch.object(esc_mod, "create_session_task"), \
         patch.object(esc_mod, "_resume_ba_hitl"), \
         patch.object(esc_mod, "_resume_architect_hitl"):
        yield
    app.dependency_overrides.clear()


@pytest.fixture()
def as_owner(app, mock_service, mock_orchestrator):
    app.dependency_overrides[get_current_user] = lambda: _user(OWNER_SUB, ["user"])
    _override_deps(app, mock_service, mock_orchestrator)
    with patch.object(esc_mod, "create_session_task"), \
         patch.object(esc_mod, "_resume_ba_hitl"), \
         patch.object(esc_mod, "_resume_architect_hitl"):
        yield
    app.dependency_overrides.clear()


@pytest.fixture()
def as_plain(app, mock_service, mock_orchestrator):
    app.dependency_overrides[get_current_user] = lambda: _user(PLAIN_SUB, ["user"])
    _override_deps(app, mock_service, mock_orchestrator)
    with patch.object(esc_mod, "create_session_task"), \
         patch.object(esc_mod, "_resume_ba_hitl"), \
         patch.object(esc_mod, "_resume_architect_hitl"):
        yield
    app.dependency_overrides.clear()


# =============================================================================
# POST /api/sessions/{session_id}/ba-hitl
# =============================================================================


class TestBaHitlRoute:
    """BA HITL decision endpoint."""

    BASE = f"/api/sessions/{SESSION_ID}/ba-hitl"

    def test_iterate_happy_path(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.return_value = _fake_event(decision="iterate")
        mock_orchestrator.resume_after_ba_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 200
        body = r.json()
        assert body["event"]["decision"] == "iterate"

    def test_ready_happy_path(self, client, as_ba, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.return_value = _fake_event(
            decision="ready",
            event_type=EscalationEventType.BA_HITL_READY,
        )
        mock_orchestrator.resume_after_ba_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "ready", "feedback": "looks good"})
        assert r.status_code == 200
        assert r.json()["event"]["decision"] == "ready"

    def test_escalate_happy_path(self, client, as_ba, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.return_value = _fake_event(
            decision="escalate",
            event_type=EscalationEventType.BA_HITL_ESCALATE,
        )
        mock_orchestrator.resume_after_ba_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "escalate"})
        assert r.status_code == 200

    def test_terminate_happy_path(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.terminate.return_value = _fake_event(
            event_type=EscalationEventType.SESSION_TERMINATED,
            decision="terminate",
        )
        mock_orchestrator.terminate_session = MagicMock()
        r = client.post(self.BASE, json={"decision": "terminate", "feedback": "done"})
        assert r.status_code == 200
        mock_orchestrator.terminate_session.assert_called_once()
        # resume should NOT be called when terminate
        mock_orchestrator.resume_after_ba_hitl.assert_not_called()

    def test_feedback_optional(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.return_value = _fake_event(decision="iterate")
        mock_orchestrator.resume_after_ba_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 200

    def test_404_session_not_found(self, client, as_admin, mock_service):
        mock_service.record_ba_hitl_decision.side_effect = NotFoundError("session", str(SESSION_ID))
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 404

    def test_403_unauthorized_plain_user(self, client, as_plain, mock_service):
        mock_service.record_ba_hitl_decision.side_effect = AuthorizationError(
            "Only the session owner or a business analyst can act on the BA HITL",
        )
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 403

    def test_409_wrong_session_state(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.side_effect = ConflictError(
            "Session not in paused_ba_hitl (status=active)"
        )
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 409

    def test_409_task_already_running(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.record_ba_hitl_decision.return_value = _fake_event(decision="iterate")
        esc_mod.create_session_task.side_effect = SessionTaskConflict(
            "A background task is already running"
        )
        r = client.post(self.BASE, json={"decision": "iterate"})
        assert r.status_code == 409

    def test_422_invalid_decision(self, client, as_admin):
        r = client.post(self.BASE, json={"decision": "invalid_choice"})
        assert r.status_code == 422

    def test_422_missing_decision(self, client, as_admin):
        r = client.post(self.BASE, json={})
        assert r.status_code == 422


# =============================================================================
# POST /api/sessions/{session_id}/architect-hitl
# =============================================================================


class TestArchitectHitlRoute:
    """Architect HITL decision endpoint."""

    BASE = f"/api/sessions/{SESSION_ID}/architect-hitl"

    def test_approve_happy_path(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.return_value = _fake_event(
            decision="approve",
            event_type=EscalationEventType.ARCHITECT_HITL_APPROVE,
        )
        mock_orchestrator.resume_after_architect_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "approve"})
        assert r.status_code == 200

    def test_reject_to_ba_hitl(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.return_value = _fake_event(
            decision="reject",
            event_type=EscalationEventType.ARCHITECT_HITL_REJECT_TO_BA,
        )
        mock_orchestrator.resume_after_architect_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "reject", "next_on_reject": "ba_hitl"})
        assert r.status_code == 200

    def test_reject_terminate(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.return_value = _fake_event(
            decision="reject",
            event_type=EscalationEventType.ARCHITECT_HITL_REJECT_TERMINATE,
        )
        mock_orchestrator.resume_after_architect_hitl = AsyncMock(return_value=SESSION_ID)
        r = client.post(self.BASE, json={"decision": "reject", "next_on_reject": "terminate"})
        assert r.status_code == 200

    def test_reject_terminate_records_decision(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.return_value = _fake_event(
            decision="reject",
            event_type=EscalationEventType.ARCHITECT_HITL_REJECT_TERMINATE,
        )
        # The orchestrator resume runs in a background task (create_session_task,
        # patched out here); the synchronous contract is the service audit call.
        r = client.post(self.BASE, json={"decision": "reject", "next_on_reject": "terminate"})
        assert r.status_code == 200
        mock_service.record_architect_hitl_decision.assert_called_once_with(
            session_id=SESSION_ID,
            user_id=UUID(ARCHITECT_SUB),
            user_roles=["architect"],
            decision="reject",
            next_on_reject="terminate",
            feedback=None,
        )

    def test_403_non_architect(self, client, as_plain, mock_service):
        mock_service.record_architect_hitl_decision.side_effect = AuthorizationError(
            "Requires architect role for the architect HITL",
            required_roles=["architect"],
        )
        r = client.post(self.BASE, json={"decision": "approve"})
        assert r.status_code == 403

    def test_404_session_not_found(self, client, as_architect, mock_service):
        mock_service.record_architect_hitl_decision.side_effect = NotFoundError(
            "session", str(SESSION_ID)
        )
        r = client.post(self.BASE, json={"decision": "approve"})
        assert r.status_code == 404

    def test_409_wrong_state(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.side_effect = ConflictError(
            "Session not in paused_architect_hitl (status=active)"
        )
        r = client.post(self.BASE, json={"decision": "approve"})
        assert r.status_code == 409

    def test_409_task_already_running(self, client, as_architect, mock_service, mock_orchestrator):
        mock_service.record_architect_hitl_decision.return_value = _fake_event(decision="approve")
        esc_mod.create_session_task.side_effect = SessionTaskConflict(
            "A background task is already running"
        )
        r = client.post(self.BASE, json={"decision": "approve"})
        assert r.status_code == 409

    def test_422_invalid_decision(self, client, as_architect):
        r = client.post(self.BASE, json={"decision": "maybe"})
        assert r.status_code == 422

    def test_422_reject_without_next_on_reject(self, client, as_architect):
        r = client.post(self.BASE, json={"decision": "reject"})
        assert r.status_code == 422

    def test_422_invalid_next_on_reject(self, client, as_architect):
        r = client.post(self.BASE, json={"decision": "reject", "next_on_reject": "invalid"})
        assert r.status_code == 422


# =============================================================================
# POST /api/sessions/{session_id}/terminate
# =============================================================================


class TestTerminateRoute:
    """Terminate session endpoint."""

    BASE = f"/api/sessions/{SESSION_ID}/terminate"

    def test_terminate_happy_path(self, client, as_owner, mock_service, mock_orchestrator):
        mock_service.terminate.return_value = _fake_event(
            event_type=EscalationEventType.SESSION_TERMINATED,
            decision="terminate",
        )
        mock_orchestrator.terminate_session = MagicMock()
        r = client.post(self.BASE, json={"reason": "project cancelled"})
        assert r.status_code == 200

    def test_terminate_no_reason(self, client, as_admin, mock_service, mock_orchestrator):
        mock_service.terminate.return_value = _fake_event(
            event_type=EscalationEventType.SESSION_TERMINATED,
            decision="terminate",
        )
        mock_orchestrator.terminate_session = MagicMock()
        r = client.post(self.BASE, json={})
        assert r.status_code == 200

    def test_403_non_owner(self, client, as_plain, mock_service):
        mock_service.terminate.side_effect = AuthorizationError(
            "Only the session owner can terminate this session",
        )
        r = client.post(self.BASE, json={"reason": "bye"})
        assert r.status_code == 403

    def test_404_session_not_found(self, client, as_admin, mock_service):
        mock_service.terminate.side_effect = NotFoundError("session", str(SESSION_ID))
        r = client.post(self.BASE, json={"reason": "bye"})
        assert r.status_code == 404


# =============================================================================
# GET /api/sessions/{session_id}/escalation-history
# =============================================================================


class TestEscalationHistoryRoute:
    """Escalation history endpoint."""

    BASE = f"/api/sessions/{SESSION_ID}/escalation-history"

    def test_history_happy_path(self, client, as_admin, mock_service):
        mock_service.list_history.return_value = _fake_event_list(2)
        r = client.get(self.BASE)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert len(body["items"]) == 2
        mock_service.list_history.assert_called_once_with(
            session_id=SESSION_ID,
            user_id=UUID(ADMIN_SUB),
            user_roles=["admin"],
        )

    def test_history_empty(self, client, as_admin, mock_service):
        mock_service.list_history.return_value = _fake_event_list(0)
        r = client.get(self.BASE)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_owner_gets_200(self, client, as_owner, mock_service):
        mock_service.list_history.return_value = _fake_event_list(1)
        r = client.get(self.BASE)
        assert r.status_code == 200
        mock_service.list_history.assert_called_once_with(
            session_id=SESSION_ID,
            user_id=UUID(OWNER_SUB),
            user_roles=["user"],
        )

    def test_admin_not_owner_gets_200(self, client, as_admin, mock_service):
        mock_service.list_history.return_value = _fake_event_list(1)
        r = client.get(self.BASE)
        assert r.status_code == 200

    def test_403_non_owner_non_admin(self, client, as_plain, mock_service):
        mock_service.list_history.side_effect = AuthorizationError(
            "Only the session owner can view escalation history",
        )
        r = client.get(self.BASE)
        assert r.status_code == 403
        mock_service.list_history.assert_called_once_with(
            session_id=SESSION_ID,
            user_id=UUID(PLAIN_SUB),
            user_roles=["user"],
        )

    def test_404_session_not_found(self, client, as_admin, mock_service):
        mock_service.list_history.side_effect = NotFoundError("session", str(SESSION_ID))
        r = client.get(self.BASE)
        assert r.status_code == 404


# =============================================================================
# Helpers
# =============================================================================


def _fake_event_list(count: int) -> EscalationEventList:
    return EscalationEventList(items=[_fake_event() for _ in range(count)])
