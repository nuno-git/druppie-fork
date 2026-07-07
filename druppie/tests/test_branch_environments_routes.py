"""Tests for the branch environments feature.

Covers the slugify/validation logic, route auth + persistence, the teardown
safety guard, and the CI webhook — all without touching kubectl/helm (the
subprocess-driving background tasks are stubbed out).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from druppie.api.deps import get_current_user
from druppie.api.errors import ValidationError
from druppie.api.main import create_app
from druppie.db.database import get_db
from druppie.db.models import Base, BranchEnvironment
from druppie.services import branch_environment_service as svc_mod
from druppie.services.branch_environment_service import _slugify

ADMIN_SUB = "11111111-1111-1111-1111-111111111111"
OWNER_SUB = "22222222-2222-2222-2222-222222222222"
OTHER_SUB = "33333333-3333-3333-3333-333333333333"


# ---------------------------------------------------------------------------
# SQLite / PostgreSQL-UUID compatibility (same shim as test_jobs.py)
# ---------------------------------------------------------------------------


class _SQLiteUUID(TypeDecorator):
    """Store Python uuid.UUID as a String(36) in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


def _patch_uuid_columns_for_sqlite(base):
    """Replace PG UUID column types with a SQLite-safe decorator.

    Idempotent. Besides swapping ``col.type``, this resets each mapped
    attribute's memoized ``__clause_element__`` (an annotated clone of the
    column created at mapper-configure time). Without that reset, WHERE
    clauses built via ``Model.attr`` keep binding with the pre-swap type
    (hex-without-dashes) while inserts store dashed strings, making committed
    rows invisible to ORM lookups when other test modules configured the
    mappers first.
    """
    for table in base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, PG_UUID):
                col.type = _SQLiteUUID()
            if type(col.type).__name__ == "_SQLiteUUID":
                col.__dict__.pop("comparator", None)
    for mapper in base.registry.mappers:
        for prop in mapper.column_attrs:
            comparator = getattr(mapper.class_, prop.key).comparator
            for slot in ("__clause_element__", "expressions"):
                try:
                    delattr(comparator, slot)
                except AttributeError:
                    pass


def _user(sub: str, admin: bool = False, developer: bool = True) -> dict:
    roles = []
    if admin:
        roles.append("admin")
    if developer:
        roles.append("developer")
    return {"sub": sub, "realm_access": {"roles": roles}}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_uuid():
    _patch_uuid_columns_for_sqlite(Base)
    yield


@pytest.fixture()
def session_factory():
    """Shared in-memory SQLite (StaticPool) with tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    yield factory
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _no_background_tasks():
    """Stub create_tracked_task so deploy/teardown never runs kubectl/helm.

    The returned coroutine is closed to avoid 'coroutine was never awaited'
    warnings.
    """
    def _stub(coro, *, name=None):
        coro.close()
        return None

    orig = svc_mod.create_tracked_task
    svc_mod.create_tracked_task = _stub
    yield
    svc_mod.create_tracked_task = orig


@pytest.fixture()
def app(session_factory):
    application = create_app()

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def as_owner(app):
    app.dependency_overrides[get_current_user] = lambda: _user(OWNER_SUB)


@pytest.fixture()
def as_admin(app):
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, admin=True)


def _make_env(session_factory, **overrides) -> str:
    """Insert a BranchEnvironment row directly; returns its id (str)."""
    db = session_factory()
    try:
        env = BranchEnvironment(
            branch=overrides.get("branch", "feature/foo"),
            slug=overrides.get("slug", "feature-foo"),
            namespace=overrides.get("namespace", "druppie-feature-foo"),
            url=overrides.get("url", "https://druppie-feature-foo.rijnland.dev"),
            image_tag=overrides.get("image_tag"),
            status=overrides.get("status", "running"),
            owner_id=uuid.UUID(overrides.get("owner_id", OWNER_SUB)),
        )
        db.add(env)
        db.commit()
        return str(env.id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# _slugify edge cases
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercases_and_replaces(self):
        assert _slugify("feature/Foo_Bar") == "feature-foo-bar"

    def test_uppercase(self):
        assert _slugify("MAIN") == "main"

    def test_collapses_and_strips_dashes(self):
        assert _slugify("--feature///bar--") == "feature-bar"

    def test_empty_result_rejected(self):
        with pytest.raises(ValidationError):
            _slugify("///")

    def test_only_dashes_rejected(self):
        with pytest.raises(ValidationError):
            _slugify("___")


# ---------------------------------------------------------------------------
# create + conflict
# ---------------------------------------------------------------------------


def test_create_returns_202_and_persists(client, session_factory, as_owner):
    r = client.post("/api/branch-environments", json={"branch": "feature/foo"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["slug"] == "feature-foo"
    assert body["namespace"] == "druppie-feature-foo"
    assert body["url"] == "https://druppie-feature-foo.rijnland.dev"
    assert body["status"] == "deploying"

    # Row persisted.
    db = session_factory()
    try:
        rows = db.query(BranchEnvironment).all()
        assert len(rows) == 1
        assert rows[0].branch == "feature/foo"
        assert rows[0].owner_id == uuid.UUID(OWNER_SUB)
    finally:
        db.close()


def test_create_duplicate_branch_conflicts(client, as_owner):
    r1 = client.post("/api/branch-environments", json={"branch": "feature/foo"})
    assert r1.status_code == 202
    r2 = client.post("/api/branch-environments", json={"branch": "feature/foo"})
    assert r2.status_code == 409


def test_create_requires_role(app, client):
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB, developer=False)
    r = client.post("/api/branch-environments", json={"branch": "feature/foo"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# teardown safety guard
# ---------------------------------------------------------------------------


def test_teardown_refuses_protected_namespace(client, session_factory, as_admin):
    # A row whose namespace is the live prod namespace must never be torn down.
    env_id = _make_env(
        session_factory,
        branch="prod",
        slug="prod",
        namespace="druppie",
        owner_id=ADMIN_SUB,
    )
    r = client.delete(f"/api/branch-environments/{env_id}")
    assert r.status_code == 422

    # Status not flipped to deleting.
    db = session_factory()
    try:
        row = db.query(BranchEnvironment).filter_by(id=uuid.UUID(env_id)).first()
        assert row.status != "deleting"
    finally:
        db.close()


def test_teardown_owner_accepts(client, session_factory, as_owner):
    env_id = _make_env(session_factory)
    r = client.delete(f"/api/branch-environments/{env_id}")
    assert r.status_code == 202
    assert r.json()["status"] == "deleting"


def test_teardown_non_owner_forbidden(app, client, session_factory):
    env_id = _make_env(session_factory)  # owned by OWNER_SUB
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    r = client.delete(f"/api/branch-environments/{env_id}")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# CI webhook (internal key auth)
# ---------------------------------------------------------------------------


def test_ci_webhook_updates_existing_env(client, session_factory, monkeypatch):
    monkeypatch.setattr("druppie.api.deps.INTERNAL_API_KEY", "test-key")
    _make_env(session_factory, branch="feature/foo", status="running")
    r = client.post(
        "/api/branch-environments/ci-webhook",
        json={"branch": "feature/foo", "image_tag": "feature-foo-123-abc"},
        headers={"X-Internal-Api-Key": "test-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["environment_updated"] is True


def test_ci_webhook_unknown_branch_returns_false(client, monkeypatch):
    monkeypatch.setattr("druppie.api.deps.INTERNAL_API_KEY", "test-key")
    r = client.post(
        "/api/branch-environments/ci-webhook",
        json={"branch": "no-such-branch", "image_tag": "tag-1"},
        headers={"X-Internal-Api-Key": "test-key"},
    )
    assert r.status_code == 200
    assert r.json()["environment_updated"] is False


def test_ci_webhook_without_key_rejected(client):
    r = client.post(
        "/api/branch-environments/ci-webhook",
        json={"branch": "feature/foo", "image_tag": "tag-1"},
    )
    assert r.status_code in (401, 403)


def test_ci_webhook_wrong_key_rejected(client, monkeypatch):
    monkeypatch.setattr("druppie.api.deps.INTERNAL_API_KEY", "test-key")
    r = client.post(
        "/api/branch-environments/ci-webhook",
        json={"branch": "feature/foo", "image_tag": "tag-1"},
        headers={"X-Internal-Api-Key": "wrong"},
    )
    assert r.status_code == 403


def test_create_protected_branch_rejected(client, session_factory, as_owner):
    """Deploying branch 'colab-dev' would target the live druppie-colab-dev ns."""
    r = client.post("/api/branch-environments", json={"branch": "colab-dev"})
    assert r.status_code == 422, r.text
    db = session_factory()
    try:
        assert db.query(BranchEnvironment).count() == 0
    finally:
        db.close()


def test_redeploy_owner_accepts(client, session_factory, as_owner):
    env_id = _make_env(session_factory, status="running")
    r = client.post(f"/api/branch-environments/{env_id}/redeploy")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "deploying"


def test_redeploy_non_owner_forbidden(app, client, session_factory):
    env_id = _make_env(session_factory, status="running", owner_id=OWNER_SUB)
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    r = client.post(f"/api/branch-environments/{env_id}/redeploy")
    assert r.status_code == 403, r.text


def test_redeploy_while_deploying_conflicts(client, session_factory, as_owner):
    env_id = _make_env(session_factory, status="deploying")
    r = client.post(f"/api/branch-environments/{env_id}/redeploy")
    assert r.status_code == 409, r.text


def test_ci_webhook_skips_env_mid_deploy(client, session_factory, monkeypatch):
    monkeypatch.setattr("druppie.api.deps.INTERNAL_API_KEY", "test-key")
    _make_env(session_factory, branch="feature/foo", status="deploying")
    r = client.post(
        "/api/branch-environments/ci-webhook",
        json={"branch": "feature/foo", "image_tag": "feature-foo-123-abc"},
        headers={"X-Internal-Api-Key": "test-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["environment_updated"] is False
