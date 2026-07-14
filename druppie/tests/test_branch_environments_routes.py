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


def _user(
    sub: str, admin: bool = False, developer: bool = True, username: str | None = "robbe"
) -> dict:
    roles = []
    if admin:
        roles.append("admin")
    if developer:
        roles.append("developer")
    user = {"sub": sub, "realm_access": {"roles": roles}}
    if username:
        user["preferred_username"] = username
    return user


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGitea:
    """In-memory stand-in for GiteaGitopsClient (path -> content)."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.commits: list[str] = []
        # App-repo branches (repo -> set of branch names); create() ensures the
        # env's branch exists here before committing manifests.
        self.branches: dict[str, set[str]] = {"ai/druppie": {"colab-dev", "main"}}
        self.created_branches: list[tuple[str, str, str]] = []

    async def branch_exists(self, repo: str, branch: str) -> bool:
        return branch in self.branches.get(repo, set())

    async def create_branch(self, repo: str, branch: str, from_branch: str) -> None:
        self.branches.setdefault(repo, set()).add(branch)
        self.created_branches.append((repo, branch, from_branch))

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
        # keyed by (namespace, name)
        self.deployments: dict[tuple[str, str], dict] = {}
        # Pipeline reads
        self.kustomization: dict | None = None
        self.gitrepositories: dict[str, dict] = {}  # keyed by slug
        self.externalsecrets: dict[str, list[dict]] = {}  # keyed by namespace
        self.pods: dict[str, list[dict]] = {}  # keyed by namespace

    async def get_helmrelease(self, namespace: str):
        return self.helmreleases.get(namespace)

    async def get_namespace(self, namespace: str):
        return self.namespaces.get(namespace)

    async def get_deployment(self, namespace: str, name: str):
        return self.deployments.get((namespace, name))

    async def list_branch_namespaces(self):
        return [
            ns
            for ns in self.namespaces.values()
            if ns.get("metadata", {}).get("labels", {}).get("druppie.io/branch-env")
        ]

    async def get_kustomization(self):
        return self.kustomization

    async def get_gitrepository(self, slug: str):
        return self.gitrepositories.get(slug)

    async def list_externalsecrets(self, namespace: str):
        return self.externalsecrets.get(namespace, [])

    async def list_deployments(self, namespace: str):
        return [d for (ns, _), d in self.deployments.items() if ns == namespace]

    async def list_pods(self, namespace: str):
        return self.pods.get(namespace, [])


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


def _deploy(client, branch="feature/foo", image_tag=None, secrets_source=None):
    body = {"branch": branch}
    if image_tag:
        body["image_tag"] = image_tag
    if secrets_source:
        body["secrets_source"] = secrets_source
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
        build_helmrelease_yaml(
            "foo", "feature/foo", "druppie-foo.rijnland.dev", "tag-1", "now",
            developer="robbe",
        )
    )
    values = manifest["spec"]["values"]
    assert values["global"]["instance"] == "druppie-foo"
    assert values["global"]["imageTag"] == "tag-1"
    assert values["backend"]["service"]["type"] == "ClusterIP"
    assert manifest["spec"]["chart"]["spec"]["sourceRef"]["name"] == "druppie-branch-foo"
    assert "helm/druppie/values-rijnland.yaml" in manifest["spec"]["chart"]["spec"]["valuesFiles"]
    # The branch namespace IS the hot-reload dev workspace.
    assert values["externalSecrets"]["managed"] is True
    dw = values["devWorkspace"]
    assert dw["enabled"] is True
    assert dw["stackMode"] == "real"
    assert dw["developer"] == "robbe"
    assert dw["gitBranch"] == "feature/foo"
    assert dw["codeServer"]["devHost"] == "druppie-foo-dev.rijnland.dev"


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


def test_create_missing_app_branch_is_created(client, as_owner, fake_gitea):
    r = _deploy(client, branch="feature/nieuw")
    assert r.status_code == 202, r.text
    assert ("ai/druppie", "feature/nieuw", "colab-dev") in fake_gitea.created_branches
    assert "created branch 'feature/nieuw' from colab-dev" in r.json()["status_message"]


def test_create_existing_app_branch_is_not_recreated(client, as_owner, fake_gitea):
    fake_gitea.branches["ai/druppie"].add("feature/bestaat")
    r = _deploy(client, branch="feature/bestaat")
    assert r.status_code == 202, r.text
    assert fake_gitea.created_branches == []


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
# secrets source (Vault-backed app secrets)
# ---------------------------------------------------------------------------


def test_create_default_secrets_source_borrows_colab_dev_keys(client, as_owner, fake_gitea):
    r = _deploy(client)
    assert r.status_code == 202, r.text
    assert r.json()["secrets_source"] == "colab-dev"

    docs = list(yaml.safe_load_all(fake_gitea.files[f"{_env_dir('feature-foo')}/externalsecrets.yaml"]))
    app_es = next(d for d in docs if d["metadata"]["name"] == "branch-env-secrets")
    props = {d["remoteRef"]["key"] for d in app_es["spec"]["data"]}
    assert props == {"druppie/colab-dev/app"}
    keys = {d["secretKey"] for d in app_es["spec"]["data"]}
    assert "ZAI_API_KEY" in keys and "OPENROUTER_API_KEY" in keys

    hr = yaml.safe_load(fake_gitea.files[f"{_env_dir('feature-foo')}/helmrelease.yaml"])
    assert hr["spec"]["values"]["global"]["extraEnvFromSecret"] == "branch-env-secrets"


def test_create_developer_secrets_source_uses_own_vault_map(client, as_owner, fake_gitea):
    r = _deploy(client, secrets_source="developer")
    assert r.status_code == 202, r.text
    assert r.json()["secrets_source"] == "developer"

    docs = list(yaml.safe_load_all(fake_gitea.files[f"{_env_dir('feature-foo')}/externalsecrets.yaml"]))
    app_es = next(d for d in docs if d["metadata"]["name"] == "branch-env-secrets")
    # dataFrom extract on the deployer's OWN map (username from the token).
    assert app_es["spec"]["dataFrom"] == [{"extract": {"key": "druppie/developers/robbe"}}]
    assert "data" not in app_es["spec"]

    ns = yaml.safe_load(fake_gitea.files[f"{_env_dir('feature-foo')}/namespace.yaml"])
    assert ns["metadata"]["annotations"]["druppie.io/secrets-source"] == "developer"


def test_create_invalid_secrets_source_rejected(client, as_owner):
    assert _deploy(client, secrets_source="druppie/main/app").status_code == 422


def test_create_developer_secrets_requires_usable_username(app, client):
    app.dependency_overrides[get_current_user] = lambda: _user(OWNER_SUB, username=None)
    assert _deploy(client, secrets_source="developer").status_code == 422


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
        owner_id=uuid.UUID(OWNER_SUB), branch="feature/foo", image_tag=None,
        user_roles=["developer"], owner_username="robbe",
    )
    env = await service._read_env("feature-foo")
    # Simulate CI updating the file between our read and our commit.
    path = f"{_env_dir('feature-foo')}/helmrelease.yaml"
    fake_gitea.files[path] = fake_gitea.files[path] + "\n# ci touch\n"
    with pytest.raises(ConflictError):
        await service.gitea.change_files(
            "stale", [{"operation": "update", "path": path, "content": "x", "sha": env["helmrelease_sha"]}]
        )


# ---------------------------------------------------------------------------
# workspace: chart-native (enabled by default at creation)
# ---------------------------------------------------------------------------


def _ready_deployment():
    return {"status": {"readyReplicas": 1}}


def _hr_values(fake_gitea, slug="feature-foo"):
    docs = yaml.safe_load_all(fake_gitea.files[f"{_env_dir(slug)}/helmrelease.yaml"])
    hr = next(d for d in docs if d and d.get("kind") == "HelmRelease")
    return hr["spec"]["values"]


def test_create_enables_workspace_by_default(client, as_owner, fake_gitea):
    _deploy(client)
    values = _hr_values(fake_gitea)
    assert values["externalSecrets"]["managed"] is True
    dw = values["devWorkspace"]
    assert dw["enabled"] is True
    assert dw["developer"] == "robbe"
    assert dw["gitBranch"] == "feature/foo"
    assert dw["codeServer"]["devHost"] == "druppie-feature-foo-dev.rijnland.dev"
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_enabled"] is True
    assert body["workspace_url"] == "https://druppie-feature-foo-dev.rijnland.dev"


def test_create_workspace_host_too_long_422(client, as_owner):
    # slug 52 chars -> workspace label 'druppie-<slug>-dev' (64) exceeds 63,
    # checked at creation because the workspace is enabled by default.
    long_branch = "a" * 52
    assert _deploy(client, branch=long_branch).status_code == 422


def test_enable_workspace_when_already_enabled_conflicts(client, as_owner):
    _deploy(client)
    # Enabled at creation -> a second enable is a conflict.
    assert client.post("/api/branch-environments/feature-foo/workspace").status_code == 409


def test_enable_workspace_non_owner_forbidden(client, as_owner, app, fake_gitea):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    assert client.post("/api/branch-environments/feature-foo/workspace").status_code == 403
    # HelmRelease unchanged (still enabled from creation).
    assert _hr_values(fake_gitea)["devWorkspace"]["enabled"] is True


def test_enable_workspace_unknown_env_404(client, as_owner):
    assert client.post("/api/branch-environments/nope/workspace").status_code == 404


def test_disable_workspace_toggles_helmrelease(client, as_owner, fake_gitea):
    _deploy(client)
    r = client.delete("/api/branch-environments/feature-foo/workspace")
    assert r.status_code == 202, r.text
    assert r.json()["workspace_enabled"] is False
    assert _hr_values(fake_gitea)["devWorkspace"]["enabled"] is False
    # No standalone workspace.yaml is committed anymore.
    assert f"{_env_dir('feature-foo')}/workspace.yaml" not in fake_gitea.files


def test_disable_then_enable_roundtrip(client, as_owner, fake_gitea):
    _deploy(client)
    assert client.delete("/api/branch-environments/feature-foo/workspace").status_code == 202
    assert _hr_values(fake_gitea)["devWorkspace"]["enabled"] is False
    r = client.post("/api/branch-environments/feature-foo/workspace")
    assert r.status_code == 202, r.text
    assert _hr_values(fake_gitea)["devWorkspace"]["enabled"] is True


def test_disable_workspace_unknown_env_404(client, as_owner):
    assert client.delete("/api/branch-environments/nope/workspace").status_code == 404


def test_detail_reports_workspace_running(client, as_owner, fake_cluster):
    _deploy(client)
    # Chart-native Deployment: <instance>-workspace (not the old "workspace").
    fake_cluster.deployments[("druppie-feature-foo", "druppie-feature-foo-workspace")] = _ready_deployment()
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_enabled"] is True
    assert body["workspace_url"] == "https://druppie-feature-foo-dev.rijnland.dev"
    assert body["workspace_status"] == "running"


def test_detail_workspace_deploying_before_ready(client, as_owner):
    _deploy(client)
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_status"] == "deploying"


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

_NS = "druppie-feature-foo"
_PIPELINE_URL = "/api/branch-environments/feature-foo/pipeline"


def _branch_env_ns(name: str = _NS) -> dict:
    return {
        "metadata": {
            "name": name,
            "labels": {"druppie.io/branch-env": "true"},
            "annotations": {
                "druppie.io/branch": "feature/foo",
                "druppie.io/owner-id": OWNER_SUB,
                "druppie.io/created-at": "2026-01-01T00:00:00+00:00",
            },
        }
    }


def _stages(body: dict) -> dict[str, dict]:
    return {s["id"]: s for s in body["stages"]}


def _make_cluster_all_ready(fake_cluster):
    fake_cluster.namespaces[_NS] = _branch_env_ns()
    fake_cluster.gitrepositories["feature-foo"] = _hr_ready()
    fake_cluster.externalsecrets[_NS] = [
        {"metadata": {"name": "branch-env-secrets"}, **_hr_ready()},
        {"metadata": {"name": "druppie-tls"}, **_hr_ready()},
    ]
    fake_cluster.helmreleases[_NS] = _hr_ready()
    fake_cluster.deployments[(_NS, "druppie-backend")] = {
        "spec": {"replicas": 1},
        "status": {"readyReplicas": 1},
    }


def test_pipeline_all_done(client, as_owner, fake_cluster):
    _deploy(client)
    _make_cluster_all_ready(fake_cluster)
    r = client.get(_PIPELINE_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    assert [s["id"] for s in body["stages"]] == [
        "commit",
        "flux",
        "source",
        "secrets",
        "helm",
        "workloads",
        "live",
    ]
    assert all(s["status"] == "done" for s in body["stages"])
    assert _stages(body)["live"]["detail"] == "https://druppie-feature-foo.rijnland.dev"
    assert _stages(body)["workloads"]["detail"] == "1/1 deployments ready"


def test_pipeline_waiting_for_flux(client, as_owner):
    _deploy(client)
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "deploying"
    assert s["commit"]["status"] == "done"
    assert s["flux"]["status"] == "busy"
    for sid in ("source", "secrets", "helm", "workloads", "live"):
        assert s[sid]["status"] == "pending", sid


def test_pipeline_source_fetch_failure(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.namespaces[_NS] = _branch_env_ns()
    fake_cluster.gitrepositories["feature-foo"] = _hr_ready(
        status="False",
        reason="GitOperationFailed",
        message="couldn't find remote ref refs/heads/feature/foo",
    )
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "failed"
    assert s["source"]["status"] == "failed"
    assert "remote ref" in s["source"]["message"]


def test_pipeline_secrets_sync_failure(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.namespaces[_NS] = _branch_env_ns()
    fake_cluster.externalsecrets[_NS] = [
        {
            "metadata": {"name": "branch-env-secrets"},
            **_hr_ready(
                status="False",
                reason="SecretSyncedError",
                message="key not found: druppie/developers/robbe",
            ),
        }
    ]
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "failed"
    assert s["secrets"]["status"] == "failed"
    assert "branch-env-secrets" in s["secrets"]["message"]
    assert "key not found" in s["secrets"]["message"]
    assert s["secrets"]["detail"] == "0/1 secrets synced"


def test_pipeline_image_pull_backoff(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.namespaces[_NS] = _branch_env_ns()
    fake_cluster.gitrepositories["feature-foo"] = _hr_ready()
    fake_cluster.helmreleases[_NS] = _hr_ready(
        status="Unknown", reason="Progressing", message="reconciling"
    )
    fake_cluster.deployments[(_NS, "druppie-backend")] = {
        "spec": {"replicas": 1},
        "status": {},
    }
    fake_cluster.pods[_NS] = [
        {
            "metadata": {"name": "druppie-backend-abc"},
            "status": {
                "containerStatuses": [
                    {
                        "state": {
                            "waiting": {
                                "reason": "ImagePullBackOff",
                                "message": 'pulling image "harbor.rijnland.dev/druppie/backend:nope"',
                            }
                        }
                    }
                ]
            },
        }
    ]
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "failed"
    assert s["workloads"]["status"] == "failed"
    assert "druppie-backend-abc" in s["workloads"]["message"]
    assert "ImagePullBackOff" in s["workloads"]["message"]
    assert s["helm"]["status"] == "busy"


def test_pipeline_workloads_progress_detail(client, as_owner, fake_cluster):
    _deploy(client)
    _make_cluster_all_ready(fake_cluster)
    fake_cluster.deployments[(_NS, "druppie-frontend")] = {
        "spec": {"replicas": 1},
        "status": {"readyReplicas": 0},
    }
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "deploying"
    assert s["workloads"]["status"] == "busy"
    assert s["workloads"]["detail"] == "1/2 deployments ready"
    assert s["live"]["status"] == "pending"


def test_pipeline_cluster_unavailable(client, as_owner, fake_cluster):
    _deploy(client)
    fake_cluster.available = False
    body = client.get(_PIPELINE_URL).json()
    s = _stages(body)
    assert body["status"] == "deploying"
    assert s["commit"]["status"] == "done"
    for sid in ("flux", "source", "secrets", "helm", "workloads", "live"):
        assert s[sid]["status"] == "pending", sid
        assert "unavailable" in s[sid]["message"]


def test_pipeline_deleting_env(client, as_owner, fake_cluster):
    # Gone from git, but the labeled namespace is still terminating.
    fake_cluster.namespaces[_NS] = _branch_env_ns()
    body = client.get(_PIPELINE_URL).json()
    assert body["status"] == "deleting"
    assert [s["id"] for s in body["stages"]] == ["commit-removed", "pruning"]
    assert _stages(body)["pruning"]["status"] == "busy"


def test_pipeline_unknown_env_404(client, as_owner):
    assert client.get("/api/branch-environments/nope/pipeline").status_code == 404


def test_pipeline_requires_developer_role(client, app):
    app.dependency_overrides[get_current_user] = lambda: _user(OWNER_SUB, developer=False)
    assert client.get(_PIPELINE_URL).status_code == 403
