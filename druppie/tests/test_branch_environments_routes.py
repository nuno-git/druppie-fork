"""Tests for the branch environments feature (GitOps model).

Git is the source of truth: the service commits/deletes manifest directories
in the GitOps repo and reads live status from HelmRelease conditions. These
tests replace the Gitea and Kubernetes clients with in-memory fakes — no HTTP,
no cluster.
"""
from __future__ import annotations

import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

from druppie.api.deps import get_branch_environment_service, get_current_user
from druppie.api.errors import ConflictError, ValidationError
from druppie.api.main import create_app
from druppie.services.branch_environment_service import (
    GITOPS_PATH,
    BranchEnvironmentService,
    _slugify,
    build_helmrelease_yaml,
)

ADMIN_SUB = "11111111-1111-1111-1111-111111111111"
OWNER_SUB = "22222222-2222-2222-2222-222222222222"
OTHER_SUB = "33333333-3333-3333-3333-333333333333"


def _user(sub: str, admin: bool = False, developer: bool = True) -> dict:
    roles = []
    if admin:
        roles.append("admin")
    if developer:
        roles.append("developer")
    return {"sub": sub, "realm_access": {"roles": roles}}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGitea:
    """In-memory stand-in for GiteaGitopsClient (path -> content)."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.commits: list[str] = []

    @staticmethod
    def _sha(content: str) -> str:
        return f"sha-{hash(content) & 0xFFFFFFFF:x}"

    async def list_dir(self, path: str):
        prefix = path.rstrip("/") + "/"
        names = {}
        for p in self.files:
            if not p.startswith(prefix):
                continue
            rest = p[len(prefix):]
            if "/" in rest:
                names[rest.split("/", 1)[0]] = {"type": "dir"}
            else:
                names[rest] = {"type": "file", "sha": self._sha(self.files[p])}
        if not names and path.rstrip("/") not in {p.rsplit("/", 1)[0] for p in self.files}:
            return None
        return [{"name": n, "path": f"{prefix}{n}", **meta} for n, meta in names.items()]

    async def get_file(self, path: str):
        if path not in self.files:
            return None
        return self.files[path], self._sha(self.files[path])

    async def change_files(self, message: str, files: list[dict]):
        # Validate the whole batch first (a real commit is atomic).
        for f in files:
            op, path = f["operation"], f["path"]
            if op == "create" and path in self.files:
                raise ConflictError(f"file already exists: {path}")
            if op in ("update", "delete"):
                if path not in self.files:
                    raise ConflictError(f"file missing: {path}")
                if f.get("sha") != self._sha(self.files[path]):
                    raise ConflictError(f"sha mismatch: {path}")
        for f in files:
            if f["operation"] == "delete":
                del self.files[f["path"]]
            else:
                self.files[f["path"]] = f["content"]
        self.commits.append(message)


class FakeCluster:
    """In-memory stand-in for ClusterStatusClient."""

    def __init__(self, available: bool = True):
        self.available = available
        self.namespaces: dict[str, dict] = {}
        self.helmreleases: dict[str, dict] = {}

    async def get_helmrelease(self, namespace: str):
        return self.helmreleases.get(namespace)

    async def get_namespace(self, namespace: str):
        return self.namespaces.get(namespace)

    async def list_branch_namespaces(self):
        return [
            ns
            for ns in self.namespaces.values()
            if ns.get("metadata", {}).get("labels", {}).get("druppie.io/branch-env")
        ]


def _hr_ready(status: str = "True", reason: str = "ReconciliationSucceeded", message: str = "ok"):
    return {
        "status": {
            "conditions": [
                {"type": "Ready", "status": status, "reason": reason, "message": message}
            ]
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_gitea():
    return FakeGitea()


@pytest.fixture()
def fake_cluster():
    return FakeCluster()


@pytest.fixture()
def service(fake_gitea, fake_cluster):
    return BranchEnvironmentService(gitea=fake_gitea, cluster=fake_cluster)


@pytest.fixture()
def app(service):
    application = create_app()
    application.dependency_overrides[get_branch_environment_service] = lambda: service
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


@pytest.fixture()
def as_other_developer(app):
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)


def _env_dir(slug: str) -> str:
    return f"{GITOPS_PATH}/druppie-{slug}"


def _deploy(client, branch="feature/foo", image_tag=None):
    body = {"branch": branch}
    if image_tag:
        body["image_tag"] = image_tag
    return client.post("/api/branch-environments", json=body)


# ---------------------------------------------------------------------------
# slugify / validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch,slug",
    [
        ("feature/foo", "feature-foo"),
        ("Feature/Foo_Bar", "feature-foo-bar"),
        ("fix--double---dash", "fix-double-dash"),
        ("-lead-and-trail-", "lead-and-trail"),
    ],
)
def test_slugify(branch, slug):
    assert _slugify(branch) == slug


def test_slugify_empty_raises():
    with pytest.raises(ValidationError):
        _slugify("///")


def test_helmrelease_yaml_contains_branch_overrides():
    manifest = yaml.safe_load(
        build_helmrelease_yaml("foo", "feature/foo", "druppie-foo.rijnland.dev", "tag-1", "now")
    )
    values = manifest["spec"]["values"]
    assert values["global"]["instance"] == "druppie-foo"
    assert values["global"]["imageTag"] == "tag-1"
    assert values["backend"]["service"]["type"] == "ClusterIP"
    assert manifest["spec"]["chart"]["spec"]["sourceRef"]["name"] == "druppie-branch-foo"
    assert "helm/druppie/values-rijnland.yaml" in manifest["spec"]["chart"]["spec"]["valuesFiles"]


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_commits_manifests(client, as_owner, fake_gitea):
    r = _deploy(client, image_tag="feature-foo-123-abc")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["id"] == "feature-foo"
    assert body["status"] == "deploying"
    assert body["url"] == "https://druppie-feature-foo.rijnland.dev"
    assert body["owner_id"] == OWNER_SUB

    d = _env_dir("feature-foo")
    for f in ("namespace.yaml", "gitrepository.yaml", "helmrelease.yaml", "externalsecrets.yaml"):
        assert f"{d}/{f}" in fake_gitea.files, f"missing {f}"

    ns = yaml.safe_load(fake_gitea.files[f"{d}/namespace.yaml"])
    assert ns["metadata"]["annotations"]["druppie.io/owner-id"] == OWNER_SUB
    assert ns["metadata"]["labels"]["druppie.io/branch-env"] == "true"

    hr = yaml.safe_load(fake_gitea.files[f"{d}/helmrelease.yaml"])
    assert hr["spec"]["values"]["global"]["imageTag"] == "feature-foo-123-abc"


def test_create_duplicate_branch_conflicts(client, as_owner):
    assert _deploy(client).status_code == 202
    assert _deploy(client).status_code == 409


def test_create_refuses_protected_namespace(client, as_owner):
    # Branch "colab-dev" would map to the live namespace druppie-colab-dev.
    r = _deploy(client, branch="colab-dev")
    assert r.status_code == 422


def test_create_invalid_image_tag(client, as_owner):
    r = _deploy(client, image_tag="bad tag!")
    assert r.status_code == 422


def test_create_requires_role(app, client):
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB, developer=False)
    assert _deploy(client).status_code == 403


def test_create_blocked_while_namespace_terminating(client, as_owner, fake_cluster):
    fake_cluster.namespaces["druppie-feature-foo"] = {
        "metadata": {"name": "druppie-feature-foo", "labels": {"druppie.io/branch-env": "true"}}
    }
    assert _deploy(client).status_code == 409


# ---------------------------------------------------------------------------
# get / list — status from the cluster
# ---------------------------------------------------------------------------


def test_get_running_when_helmrelease_ready(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.helmreleases["druppie-feature-foo"] = _hr_ready()
    r = client.get("/api/branch-environments/feature-foo")
    assert r.status_code == 200
    assert r.json()["status"] == "running"


def test_get_deploying_before_flux_applies(client, as_owner):
    _deploy(client)
    r = client.get("/api/branch-environments/feature-foo")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "deploying"
    assert "Flux" in body["status_message"]


def test_get_failed_on_install_failure(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.helmreleases["druppie-feature-foo"] = _hr_ready(
        status="False", reason="InstallFailed", message="chart render error"
    )
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["status"] == "failed"
    assert "chart render error" in body["status_message"]


def test_get_unknown_env_404(client, as_owner):
    assert client.get("/api/branch-environments/nope").status_code == 404


def test_list_includes_terminating_namespace(client, as_owner, fake_cluster):
    _deploy(client)
    # A second env that was torn down: gone from git, namespace still terminating.
    fake_cluster.namespaces["druppie-old-env"] = {
        "metadata": {
            "name": "druppie-old-env",
            "labels": {"druppie.io/branch-env": "true"},
            "annotations": {"druppie.io/branch": "old-env"},
        }
    }
    body = client.get("/api/branch-environments").json()
    assert body["total"] == 2
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["feature-foo"]["status"] == "deploying"
    assert by_id["old-env"]["status"] == "deleting"


def test_list_requires_role(app, client):
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB, developer=False)
    assert client.get("/api/branch-environments").status_code == 403


# ---------------------------------------------------------------------------
# redeploy
# ---------------------------------------------------------------------------


def test_redeploy_owner_bumps_reconcile_and_tag(client, as_owner, fake_gitea):
    _deploy(client, image_tag="tag-1")
    r = client.post("/api/branch-environments/feature-foo/redeploy")
    assert r.status_code == 202, r.text
    hr = yaml.safe_load(fake_gitea.files[f"{_env_dir('feature-foo')}/helmrelease.yaml"])
    ann = hr["metadata"]["annotations"]
    assert "reconcile.fluxcd.io/requestedAt" in ann
    assert "reconcile.fluxcd.io/forceAt" in ann
    assert hr["spec"]["values"]["global"]["imageTag"] == "tag-1"  # unchanged tag kept


def test_redeploy_non_owner_forbidden(client, as_owner, app):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    assert client.post("/api/branch-environments/feature-foo/redeploy").status_code == 403


def test_redeploy_admin_allowed(client, as_owner, app):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, admin=True)
    assert client.post("/api/branch-environments/feature-foo/redeploy").status_code == 202


def test_redeploy_unknown_env_404(client, as_owner):
    assert client.post("/api/branch-environments/nope/redeploy").status_code == 404


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


def test_teardown_deletes_env_dir(client, as_owner, fake_gitea):
    _deploy(client)
    r = client.delete("/api/branch-environments/feature-foo")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "deleting"
    assert not [p for p in fake_gitea.files if "druppie-feature-foo" in p]


def test_teardown_non_owner_forbidden(client, as_owner, app, fake_gitea):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    assert client.delete("/api/branch-environments/feature-foo").status_code == 403
    assert [p for p in fake_gitea.files if "druppie-feature-foo" in p]  # untouched


def test_teardown_admin_allowed(client, as_owner, app):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(ADMIN_SUB, admin=True)
    assert client.delete("/api/branch-environments/feature-foo").status_code == 202


def test_teardown_invalid_slug_rejected(client, as_admin):
    # Path-traversal-ish ids must be rejected before touching git.
    assert client.delete("/api/branch-environments/Foo_%2E%2E").status_code in (404, 422)


def test_teardown_unknown_env_404(client, as_admin):
    assert client.delete("/api/branch-environments/nope").status_code == 404


# ---------------------------------------------------------------------------
# concurrency: stale sha on concurrent modification
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_redeploy_conflicts_on_concurrent_change(service, fake_gitea):
    await service.create(
        owner_id=uuid.UUID(OWNER_SUB), branch="feature/foo", image_tag=None, user_roles=["developer"]
    )
    env = await service._read_env("feature-foo")
    # Simulate CI updating the file between our read and our commit.
    path = f"{_env_dir('feature-foo')}/helmrelease.yaml"
    fake_gitea.files[path] = fake_gitea.files[path] + "\n# ci touch\n"
    with pytest.raises(ConflictError):
        await service.gitea.change_files(
            "stale", [{"operation": "update", "path": path, "content": "x", "sha": env["helmrelease_sha"]}]
        )
