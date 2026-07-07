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
    build_workspace_yaml,
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


# ---------------------------------------------------------------------------
# workspace: build_workspace_yaml
# ---------------------------------------------------------------------------


def test_build_workspace_yaml_shape():
    docs = list(
        yaml.safe_load_all(
            build_workspace_yaml(
                "feature-foo", "feature/foo", "druppie-feature-foo.rijnland.dev", "now"
            )
        )
    )
    kinds = {d["kind"] for d in docs}
    assert kinds == {
        "ExternalSecret",
        "PersistentVolumeClaim",
        "Deployment",
        "Service",
        "Ingress",
    }
    by_kind = {d["kind"]: d for d in docs}

    # Ingress host = env host with -dev inserted before the first dot.
    ingress = by_kind["Ingress"]
    assert ingress["spec"]["rules"][0]["host"] == "druppie-feature-foo-dev.rijnland.dev"
    assert ingress["spec"]["tls"][0]["secretName"] == "druppie-tls"
    assert ingress["spec"]["ingressClassName"] == "traefik"

    # Deployment: workspace + oauth2-proxy containers, Recreate strategy.
    dep = by_kind["Deployment"]
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    containers = {c["name"]: c for c in dep["spec"]["template"]["spec"]["containers"]}
    assert set(containers) == {"workspace", "oauth2-proxy"}

    ws = containers["workspace"]
    env_vars = {e["name"]: e["value"] for e in ws["env"]}
    assert env_vars["DRUPPIE_GIT_BRANCH"] == "feature/foo"
    assert "druppie.git" in env_vars["DRUPPIE_REPO_URL"]
    ports = {p["containerPort"] for p in ws["ports"]}
    assert {8080, 8000, 5173} <= ports

    # oauth2-proxy: issuer points at the ENV's OWN Keycloak realm (path-routed).
    proxy = containers["oauth2-proxy"]
    args = " ".join(proxy["args"])
    assert "--oidc-issuer-url=https://druppie-feature-foo.rijnland.dev/realms/druppie" in args
    assert "--redirect-url=https://druppie-feature-foo-dev.rijnland.dev/oauth2/callback" in args
    assert "--client-id=workspace" in args

    # Service maps 80 -> 4180 (oauth2-proxy).
    svc = by_kind["Service"]
    assert svc["spec"]["ports"][0]["port"] == 80
    assert svc["spec"]["ports"][0]["targetPort"] == 4180


# ---------------------------------------------------------------------------
# workspace: enable / disable
# ---------------------------------------------------------------------------


def _ready_deployment():
    return {"status": {"readyReplicas": 1}}


def test_enable_workspace_commits_file(client, as_owner, fake_gitea):
    _deploy(client)
    r = client.post("/api/branch-environments/feature-foo/workspace")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["workspace_enabled"] is True
    assert body["workspace_url"] == "https://druppie-feature-foo-dev.rijnland.dev"

    path = f"{_env_dir('feature-foo')}/workspace.yaml"
    assert path in fake_gitea.files
    docs = {d["kind"]: d for d in yaml.safe_load_all(fake_gitea.files[path])}
    containers = {
        c["name"] for c in docs["Deployment"]["spec"]["template"]["spec"]["containers"]
    }
    assert "oauth2-proxy" in containers
    assert docs["Ingress"]["spec"]["rules"][0]["host"] == "druppie-feature-foo-dev.rijnland.dev"


def test_enable_workspace_twice_conflicts(client, as_owner):
    _deploy(client)
    assert client.post("/api/branch-environments/feature-foo/workspace").status_code == 202
    assert client.post("/api/branch-environments/feature-foo/workspace").status_code == 409


def test_enable_workspace_non_owner_forbidden(client, as_owner, app, fake_gitea):
    _deploy(client)
    app.dependency_overrides[get_current_user] = lambda: _user(OTHER_SUB)
    assert client.post("/api/branch-environments/feature-foo/workspace").status_code == 403
    assert f"{_env_dir('feature-foo')}/workspace.yaml" not in fake_gitea.files


def test_enable_workspace_unknown_env_404(client, as_owner):
    assert client.post("/api/branch-environments/nope/workspace").status_code == 404


def test_enable_workspace_host_too_long_422(client, as_owner):
    # slug 52 chars -> namespace 'druppie-<slug>' (60) is a valid label, but the
    # workspace label 'druppie-<slug>-dev' (64) exceeds 63.
    long_branch = "a" * 52
    assert _deploy(client, branch=long_branch).status_code == 202
    slug = _slugify(long_branch)
    assert client.post(f"/api/branch-environments/{slug}/workspace").status_code == 422


def test_disable_workspace_deletes_file(client, as_owner, fake_gitea):
    _deploy(client)
    client.post("/api/branch-environments/feature-foo/workspace")
    r = client.delete("/api/branch-environments/feature-foo/workspace")
    assert r.status_code == 202, r.text
    assert r.json()["workspace_enabled"] is False
    assert f"{_env_dir('feature-foo')}/workspace.yaml" not in fake_gitea.files


def test_disable_workspace_when_absent(client, as_owner):
    _deploy(client)
    assert client.delete("/api/branch-environments/feature-foo/workspace").status_code in (404, 409)


def test_disable_workspace_unknown_env_404(client, as_owner):
    assert client.delete("/api/branch-environments/nope/workspace").status_code == 404


def test_detail_reports_workspace_running(client, as_owner, fake_cluster):
    _deploy(client)
    client.post("/api/branch-environments/feature-foo/workspace")
    fake_cluster.deployments[("druppie-feature-foo", "workspace")] = _ready_deployment()
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_enabled"] is True
    assert body["workspace_url"] == "https://druppie-feature-foo-dev.rijnland.dev"
    assert body["workspace_status"] == "running"


def test_detail_workspace_deploying_before_ready(client, as_owner):
    _deploy(client)
    client.post("/api/branch-environments/feature-foo/workspace")
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_status"] == "deploying"


def test_detail_workspace_disabled_by_default(client, as_owner):
    _deploy(client)
    body = client.get("/api/branch-environments/feature-foo").json()
    assert body["workspace_enabled"] is False
    assert body["workspace_url"] is None
    assert body["workspace_status"] is None
