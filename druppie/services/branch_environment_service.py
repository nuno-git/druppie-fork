"""Branch environment service (GitOps).

Git is the source of truth: deploying a branch environment commits a manifest
directory to the ``ai/k8s`` GitOps repo (via the Gitea API) and FluxCD does the
actual deploy; tearing one down deletes the directory and Flux prunes the
namespace. The backend never runs helm/kubectl and needs no write access to the
cluster — live status is read from the HelmRelease conditions via the
Kubernetes API (read-only ServiceAccount).

For a branch ``feature/foo`` the environment is:
    slug       feature-foo
    namespace  druppie-feature-foo
    host       druppie-feature-foo.rijnland.dev   (single label -> *.rijnland.dev cert)
    url        https://druppie-feature-foo.rijnland.dev

Each environment is one directory ``clusters/branch-envs/druppie-<slug>/`` in
the GitOps repo (reconciled by Kustomization/branch-envs with prune):
    namespace.yaml        Namespace + owner/branch annotations (authz metadata)
    gitrepository.yaml    Flux GitRepository pinned to the branch (chart source)
    helmrelease.yaml      HelmRelease with the branch overrides + imageTag
    externalsecrets.yaml  druppie-tls mirror + harbor-regcred (ESO)

Because both the prod and colab-dev instances read/write the same git repo,
the feature is safe to enable on multiple instances: git (compare-and-swap on
file SHAs) arbitrates concurrent writes, and the environment list is identical
everywhere.
"""

import asyncio
import base64
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
import structlog
import yaml

from ..api.errors import (
    AuthorizationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from ..domain import BranchEnvironmentDetail
from ..domain.branch_environment import (
    BranchEnvironmentPipeline,
    BranchEnvironmentStatus,
    PipelineStage,
    PipelineStageStatus,
)

logger = structlog.get_logger()

# -----------------------------------------------------------------------------
# Configuration (env-overridable; values come from the chart's branchEnvDeployer
# block in the cluster)
# -----------------------------------------------------------------------------
GITOPS_URL = os.getenv("BRANCH_ENV_GITOPS_URL", "https://aigit.waterschap.org")
GITOPS_REPO = os.getenv("BRANCH_ENV_GITOPS_REPO", "ai/k8s")
GITOPS_BRANCH = os.getenv("BRANCH_ENV_GITOPS_BRANCH", "main")
GITOPS_PATH = os.getenv("BRANCH_ENV_GITOPS_PATH", "clusters/branch-envs")
GITOPS_TOKEN = os.getenv("BRANCH_ENV_GITOPS_TOKEN", "")
# Optional CA bundle for the (private-CA) Gitea server; falls back to system CAs.
GITOPS_CA = os.getenv("BRANCH_ENV_GITOPS_CA", "")

# The application repo whose branch supplies the chart + images for an env.
CHART_REPO_URL = os.getenv(
    "BRANCH_ENV_CHART_REPO_URL", "https://aigit.waterschap.org/ai/druppie.git"
)
# "https://aigit.waterschap.org/ai/druppie.git" -> "ai/druppie" (same Gitea as
# the GitOps repo, so the GitOps token/CA apply).
CHART_REPO = urlparse(CHART_REPO_URL).path.strip("/").removesuffix(".git")
# Base for app branches the deployer creates when they don't exist yet.
APP_BASE_BRANCH = os.getenv("BRANCH_ENV_APP_BASE_BRANCH", "colab-dev")
# The instance that creates branch-envs — its imageTag is the default for new
# envs (callers can still override with an explicit image_tag).
PARENT_NAMESPACE = os.getenv("BRANCH_ENV_PARENT_NAMESPACE", f"druppie-{APP_BASE_BRANCH}")

BRANCH_ENV_REGISTRY = os.getenv("BRANCH_ENV_REGISTRY", "harbor.rijnland.dev/druppie")
BRANCH_ENV_PULL_SECRET = os.getenv("BRANCH_ENV_PULL_SECRET", "harbor-regcred")
# Ephemeral StorageClass: 1 replica, strict-local, reclaimPolicy=Delete.
BRANCH_ENV_STORAGE_CLASS = os.getenv("BRANCH_ENV_STORAGE_CLASS", "longhorn-branch-env")

# Secrets source for branch envs: determines the Vault path prefix for env
# secrets. "colab-dev" → druppie/colab-dev/*, any other value maps to
# druppie/developers/<value>/*. Accept any non-empty string.
SECRETS_SOURCE_COLAB_DEV = "colab-dev"
_SECRETS_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

# Domain suffix: environments live at druppie-<slug>.<DOMAIN_SUFFIX>. Must stay a
# single label under this suffix to match the *.rijnland.dev wildcard cert.
DOMAIN_SUFFIX = os.getenv("BRANCH_ENV_DOMAIN_SUFFIX", "rijnland.dev")

# Every module the chart deploys (values.yaml modules.*).
ALL_MODULES = [
    "coding",
    "docker",
    "filesearch",
    "web",
    "archimate",
    "registry",
    "llm",
    "vision",
    "data_access",
    "layout_service",
    "azuredevops",
]
# Dev-profile CPU requests: a whole env must fit on the shared pinned node, so
# request little and burst up to the chart's default limits. Memory requests
# stay at chart defaults (the node is CPU-request-bound, not memory-bound).
_DEV_CPU = {"backend": "100m", "component": "50m", "module": "25m"}

# Namespaces that must never be deployed to or torn down by this service
# (live instances).
_PROTECTED_NAMESPACES = frozenset({"druppie", "druppie-colab-dev"})

# In-cluster ServiceAccount credentials (absent in local dev / tests).
_SA_DIR = Path(os.getenv("KUBE_SA_DIR", "/var/run/secrets/kubernetes.io/serviceaccount"))
_KUBE_URL = os.getenv("KUBE_API_URL", "https://kubernetes.default.svc")

HELMRELEASE_NAME = "druppie"
_ANN = "druppie.io"  # annotation prefix

_HTTP_TIMEOUT = 30.0

# Strict input validation.
_IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _slugify(branch: str) -> str:
    """Sanitize a git branch into a DNS-1123 label.

    Lowercase, replace any non-[a-z0-9-] with '-', collapse consecutive dashes,
    strip leading/trailing dashes. Raises ValidationError if the result is empty.
    """
    slug = branch.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    if not slug:
        raise ValidationError(f"branch '{branch}' produced an empty slug", field="branch")
    return slug


def _validate_image_tag(image_tag: str) -> str:
    """Validate an image tag against a strict allowlist regex."""
    if not _IMAGE_TAG_RE.match(image_tag):
        raise ValidationError(f"invalid image tag: {image_tag!r}", field="image_tag")
    return image_tag


def _validate_branch(branch: str) -> str:
    """Validate a git branch name (also guards the GitRepository ref we commit)."""
    if not _BRANCH_RE.match(branch) or ".." in branch:
        raise ValidationError(f"invalid branch name: {branch!r}", field="branch")
    return branch


def _validate_slug(slug: str) -> str:
    """Validate a slug/id path segment (route input → git path, so be strict)."""
    if not _SLUG_RE.match(slug):
        raise ValidationError(f"invalid environment id: {slug!r}", field="env_id")
    return slug


def _assert_safe_namespace(namespace: str, slug: str) -> None:
    """Refuse any git operation targeting a live or mismatched namespace."""
    if (
        namespace in _PROTECTED_NAMESPACES
        or not namespace.startswith("druppie-")
        or namespace != f"druppie-{slug}"
    ):
        raise ValidationError(
            f"refusing to operate on protected/mismatched namespace '{namespace}'",
            field="namespace",
        )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# Manifest builders — the exact YAML committed per environment
# -----------------------------------------------------------------------------


def _dump(*docs: dict) -> str:
    """Render one or more manifests as a multi-doc YAML string."""
    return yaml.safe_dump_all(docs, sort_keys=False, default_flow_style=False)


def build_namespace_yaml(
    slug: str,
    branch: str,
    owner_id: UUID,
    created_at: str,
    secrets_source: str = SECRETS_SOURCE_COLAB_DEV,
) -> str:
    return _dump(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": f"druppie-{slug}",
                "labels": {
                    f"{_ANN}/branch-env": "true",
                    "app.kubernetes.io/managed-by": "druppie-branch-environments",
                },
                "annotations": {
                    f"{_ANN}/branch": branch,
                    f"{_ANN}/owner-id": str(owner_id),
                    f"{_ANN}/created-at": created_at,
                    f"{_ANN}/secrets-source": secrets_source,
                },
            },
        }
    )


def build_gitrepository_yaml(slug: str, branch: str) -> str:
    return _dump(
        {
            "apiVersion": "source.toolkit.fluxcd.io/v1",
            "kind": "GitRepository",
            "metadata": {
                "name": f"druppie-branch-{slug}",
                "namespace": "flux-system",
                "labels": {f"{_ANN}/branch-env": slug},
            },
            "spec": {
                "interval": "1m",
                "ref": {"branch": branch},
                "secretRef": {"name": "flux-git-auth"},
                "url": CHART_REPO_URL,
            },
        }
    )


def build_helmrelease_yaml(
    slug: str,
    branch: str,
    host: str,
    image_tag: str | None,
    updated_at: str,
    reconcile_epoch: str | None = None,
    secrets_source: str = SECRETS_SOURCE_COLAB_DEV,
    workspace_enabled: bool = True,
    stack_mode: str = "real",
    recovery_mode: bool = False,
) -> str:
    namespace = f"druppie-{slug}"
    annotations = {
        f"{_ANN}/branch": branch,
        f"{_ANN}/updated-at": updated_at,
    }
    if reconcile_epoch:
        # Committed annotation bump: forces helm-controller to reconcile (and
        # retry a previously failed release) without any kube write from us.
        annotations["reconcile.fluxcd.io/requestedAt"] = reconcile_epoch
        annotations["reconcile.fluxcd.io/forceAt"] = reconcile_epoch

    values: dict = {
        "global": {
            "instance": namespace,
            "domain": host,
            "imageRegistry": BRANCH_ENV_REGISTRY,
            "imagePullSecrets": [{"name": BRANCH_ENV_PULL_SECRET}],
        },
        # Branch envs are reached via Traefik ingress, not NodePort — ClusterIP
        # so they don't grab cluster-global NodePorts held by the live instance.
        "backend": {
            "service": {"type": "ClusterIP"},
            "resources": {"requests": {"cpu": _DEV_CPU["backend"]}},
        },
        "frontend": {
            "service": {"type": "ClusterIP"},
            "resources": {"requests": {"cpu": _DEV_CPU["component"]}},
        },
        "keycloak": {
            "service": {"type": "ClusterIP"},
            "resources": {"requests": {"cpu": _DEV_CPU["component"]}},
        },
        "gitea": {
            "service": {"type": "ClusterIP"},
            "resources": {"requests": {"cpu": _DEV_CPU["component"]}},
        },
        "modules": {
            module: {
                "resources": {"requests": {"cpu": _DEV_CPU["module"]}},
                **({"enabled": False} if recovery_mode else {}),
            }
            for module in ALL_MODULES
        },
        # The branch namespace IS the hot-reload dev workspace: a single pod
        # (code-server + uvicorn --reload + Vite HMR) replaces the baked
        # backend/frontend Deployments. externalSecrets.managed=true lets ESO
        # own <instance>-secrets; devWorkspace.secretsSource determines the
        # Vault path prefix (druppie/colab-dev/* or druppie/developers/<name>/*).
        "externalSecrets": {"managed": True},
        # Ephemeral storage: 1 replica + Delete reclaim policy. Branch-env
        # data is disposable (DBs rebuilt by the init job, repos re-cloned
        # from git); 3 replicas would triple the cost and Retain leaves
        # orphaned volumes that clog the Longhorn scheduler after teardown.
        "persistence": {"storageClass": BRANCH_ENV_STORAGE_CLASS},
        "devWorkspace": {
            "enabled": workspace_enabled,
            "stackMode": "degraded" if recovery_mode else stack_mode,
            "secretsSource": secrets_source,
            "gitBranch": branch,
            "codeServer": {"devHost": _workspace_host(host)},
        },
    }
    if recovery_mode:
        values["recoveryMode"] = True
    if image_tag is not None:
        values["global"]["imageTag"] = image_tag

    return _dump(
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {
                "name": HELMRELEASE_NAME,
                "namespace": namespace,
                "annotations": annotations,
            },
            "spec": {
                "interval": "10m",
                "releaseName": HELMRELEASE_NAME,
                "storageNamespace": namespace,
                "targetNamespace": namespace,
                "chart": {
                    "spec": {
                        "chart": "./helm/druppie",
                        "sourceRef": {
                            "kind": "GitRepository",
                            "name": f"druppie-branch-{slug}",
                            "namespace": "flux-system",
                        },
                        "reconcileStrategy": "Revision",
                        # Same layering as the original imperative deploy:
                        # base values + rijnland overrides, from the BRANCH.
                        "valuesFiles": [
                            "helm/druppie/values.yaml",
                            "helm/druppie/values-rijnland.yaml",
                        ],
                    }
                },
                "install": {"timeout": "10m", "remediation": {"retries": 3}},
                "upgrade": {
                    "timeout": "10m",
                    "cleanupOnFail": True,
                    "remediation": {"retries": 3},
                },
                "values": values,
            },
        }
    )


def build_externalsecrets_yaml(slug: str) -> str:
    namespace = f"druppie-{slug}"
    return _dump(
        # Wildcard TLS cert, mirrored from ns druppie (not in Vault) via the
        # druppie-tls-mirror ClusterSecretStore (ESO kubernetes provider).
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": "druppie-tls", "namespace": namespace},
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": "druppie-tls-mirror", "kind": "ClusterSecretStore"},
                "target": {
                    "name": "druppie-tls",
                    "creationPolicy": "Owner",
                    "template": {"type": "kubernetes.io/tls"},
                },
                "data": [
                    {
                        "secretKey": "tls.crt",
                        "remoteRef": {"key": "druppie-tls", "property": "tls.crt"},
                    },
                    {
                        "secretKey": "tls.key",
                        "remoteRef": {"key": "druppie-tls", "property": "tls.key"},
                    },
                ],
            },
        },
        # Harbor pull secret, same Vault path as the live instances.
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": BRANCH_ENV_PULL_SECRET, "namespace": namespace},
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": "vault-ai-team-k8s", "kind": "ClusterSecretStore"},
                "target": {
                    "name": BRANCH_ENV_PULL_SECRET,
                    "creationPolicy": "Owner",
                    "template": {
                        "type": "kubernetes.io/dockerconfigjson",
                        "data": {
                            ".dockerconfigjson": (
                                '{"auths":{"{{ .registry }}":{"username":"{{ .username }}",'
                                '"password":"{{ .password }}",'
                                '"auth":"{{ printf "%s:%s" .username .password | b64enc }}"}}}'
                            )
                        },
                    },
                },
                "data": [
                    {"secretKey": "username", "remoteRef": {"key": "ci/harbor", "property": "username"}},
                    {"secretKey": "password", "remoteRef": {"key": "ci/harbor", "property": "password"}},
                    {"secretKey": "registry", "remoteRef": {"key": "ci/harbor", "property": "registry"}},
                ],
            },
        },
    )


def _workspace_host(host: str) -> str:
    """Env host with ``-dev`` inserted before the first dot.

    ``druppie-<slug>.rijnland.dev`` -> ``druppie-<slug>-dev.rijnland.dev``.
    The env's Keycloak is path-routed under the *base* host, so the workspace
    host is a sibling label under the same wildcard cert.
    """
    label, _, rest = host.partition(".")
    return f"{label}-dev.{rest}" if rest else f"{label}-dev"


_ENV_FILES = ("namespace.yaml", "gitrepository.yaml", "helmrelease.yaml", "externalsecrets.yaml")


# -----------------------------------------------------------------------------
# Gitea GitOps client — commits/reads the env directories
# -----------------------------------------------------------------------------


class GiteaGitopsClient:
    """Minimal Gitea contents-API client for the GitOps repo."""

    def __init__(
        self,
        base_url: str = GITOPS_URL,
        repo: str = GITOPS_REPO,
        branch: str = GITOPS_BRANCH,
        token: str = GITOPS_TOKEN,
        ca_path: str = GITOPS_CA,
    ):
        self._base = base_url.rstrip("/")
        self._api = f"{self._base}/api/v1/repos/{repo}"
        self._branch = branch
        self._headers = {"Authorization": f"token {token}"} if token else {}
        self._verify: bool | str = ca_path if ca_path else True

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers, verify=self._verify, timeout=_HTTP_TIMEOUT
        )

    @staticmethod
    def _raise_for(resp: httpx.Response, what: str) -> None:
        if resp.status_code < 400:
            return
        if resp.status_code in (409, 422):
            raise ConflictError(
                f"git conflict while {what} (concurrent change?): {resp.text[:300]}"
            )
        raise ExternalServiceError(
            service="gitops-repo",
            message=f"{what} failed: HTTP {resp.status_code} {resp.text[:300]}",
        )

    async def list_dir(self, path: str) -> list[dict] | None:
        """List a directory; None if the path does not exist."""
        async with self._client() as client:
            resp = await client.get(f"{self._api}/contents/{path}", params={"ref": self._branch})
        if resp.status_code == 404:
            return None
        self._raise_for(resp, f"listing {path}")
        entries = resp.json()
        return entries if isinstance(entries, list) else [entries]

    async def get_file(self, path: str) -> tuple[str, str] | None:
        """Return (decoded content, blob sha) for a file; None if absent."""
        async with self._client() as client:
            resp = await client.get(f"{self._api}/contents/{path}", params={"ref": self._branch})
        if resp.status_code == 404:
            return None
        self._raise_for(resp, f"reading {path}")
        body = resp.json()
        content = base64.b64decode(body.get("content") or "").decode("utf-8")
        return content, body["sha"]

    async def branch_exists(self, repo: str, branch: str) -> bool:
        """True if `branch` exists in `repo` (any repo on the same Gitea)."""
        async with self._client() as client:
            resp = await client.get(
                f"{self._base}/api/v1/repos/{repo}/branches/{quote(branch, safe='')}"
            )
        if resp.status_code == 404:
            return False
        self._raise_for(resp, f"checking branch '{branch}' in {repo}")
        return True

    async def list_branches(self, repo: str) -> list[dict]:
        """List all branches in a repo."""
        async with self._client() as client:
            resp = await client.get(f"{self._base}/api/v1/repos/{repo}/branches")
        self._raise_for(resp, f"listing branches in {repo}")
        return resp.json()

    async def create_branch(self, repo: str, branch: str, from_branch: str) -> None:
        """Create `branch` in `repo` from `from_branch`; existing branch is fine."""
        async with self._client() as client:
            resp = await client.post(
                f"{self._base}/api/v1/repos/{repo}/branches",
                json={"new_branch_name": branch, "old_ref_name": from_branch},
            )
        if resp.status_code == 409:  # created concurrently — it exists, which is all we need
            return
        self._raise_for(resp, f"creating branch '{branch}' in {repo}")

    async def dispatch_workflow(
        self, repo: str, branch: str, workflow: str = "build.yaml"
    ) -> None:
        """Trigger a workflow_dispatch on ``workflow`` for ``branch`` in ``repo``.

        Guarantees the CI build runs for an env's branch even when the branch
        already existed (so no push event fires to trigger build.yaml on its own).
        """
        async with self._client() as client:
            resp = await client.post(
                f"{self._base}/api/v1/repos/{repo}/actions/workflows/{workflow}/dispatches",
                json={"ref": branch},
            )
        self._raise_for(
            resp, f"dispatching workflow '{workflow}' for branch '{branch}' in {repo}"
        )
        logger.info(
            "branch_env_workflow_dispatched",
            repo=repo,
            branch=branch,
            workflow=workflow,
        )

    async def change_files(self, message: str, files: list[dict]) -> None:
        """Single-commit batch create/update/delete via POST /contents.

        files: [{"operation": "create"|"update"|"delete", "path": ...,
                 "content": <plain str, for create/update>, "sha": <for update/delete>}]
        """
        payload_files = []
        for f in files:
            entry: dict = {"operation": f["operation"], "path": f["path"]}
            if f["operation"] in ("create", "update"):
                entry["content"] = base64.b64encode(f["content"].encode("utf-8")).decode("ascii")
            if f.get("sha"):
                entry["sha"] = f["sha"]
            payload_files.append(entry)
        async with self._client() as client:
            resp = await client.post(
                f"{self._api}/contents",
                json={"branch": self._branch, "message": message, "files": payload_files},
            )
        self._raise_for(resp, f"committing '{message}'")


# -----------------------------------------------------------------------------
# Cluster status client — read-only, in-cluster ServiceAccount
# -----------------------------------------------------------------------------


class ClusterStatusClient:
    """Read-only Kubernetes API reader for live env status.

    Outside the cluster (local dev, tests) ``available`` is False and all reads
    return None — envs then report status from git alone.
    """

    def __init__(self, sa_dir: Path = _SA_DIR, api_url: str = _KUBE_URL):
        self._token_path = sa_dir / "token"
        self._ca_path = sa_dir / "ca.crt"
        self._api_url = api_url

    @property
    def available(self) -> bool:
        return self._token_path.exists()

    async def _request(
        self, method: str, path: str, json_body: dict | None = None
    ) -> dict | None:
        if not self.available:
            return None
        token = self._token_path.read_text().strip()
        verify: bool | str = str(self._ca_path) if self._ca_path.exists() else True
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/merge-patch+json"
        async with httpx.AsyncClient(
            headers=headers, verify=verify, timeout=_HTTP_TIMEOUT
        ) as client:
            resp = await client.request(method, f"{self._api_url}{path}", json=json_body)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            verb = method.upper()
            raise ExternalServiceError(
                service="kubernetes",
                message=f"{verb} {path} failed: HTTP {resp.status_code} {resp.text[:300]}",
            )
        return resp.json() if resp.text else None

    async def _get(self, path: str) -> dict | None:
        return await self._request("GET", path)

    async def _patch(self, path: str, body: dict) -> dict | None:
        return await self._request("PATCH", path, body)

    async def force_reconcile_flux(self) -> None:
        """Force Flux to immediately reconcile the GitRepository that sources
        the branch-envs manifests and the Kustomization that applies them.

        Without this, Flux waits up to 5 minutes for the GitRepository poll
        interval before it notices the backend's commit — this cuts the deploy
        wait from minutes to seconds. Safe to call outside the cluster (no-op).
        """
        if not self.available:
            return
        epoch = str(int(time.time()))
        annotation = {"metadata": {"annotations": {"fluxcd.io/request": epoch}}}
        # GitRepository ai-k8s is in flux-custom (the bootstrap namespace).
        try:
            await self._patch(
                "/apis/source.toolkit.fluxcd.io/v1/namespaces/flux-custom"
                "/gitrepositories/ai-k8s",
                annotation,
            )
        except Exception:
            logger.warning("flux_reconcile_gitsrc_failed", exc_info=True)
        # Kustomization branch-envs is in flux-system.
        try:
            await self._patch(
                "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system"
                "/kustomizations/branch-envs",
                annotation,
            )
        except Exception:
            logger.warning("flux_reconcile_kustomization_failed", exc_info=True)

    async def get_helmrelease(self, namespace: str, name: str = HELMRELEASE_NAME) -> dict | None:
        return await self._get(
            f"/apis/helm.toolkit.fluxcd.io/v2/namespaces/{namespace}"
            f"/helmreleases/{name}"
        )

    async def get_namespace(self, namespace: str) -> dict | None:
        return await self._get(f"/api/v1/namespaces/{namespace}")

    async def get_deployment(self, namespace: str, name: str) -> dict | None:
        return await self._get(
            f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}"
        )

    async def list_branch_namespaces(self) -> list[dict]:
        body = await self._get(f"/api/v1/namespaces?labelSelector={_ANN}%2Fbranch-env%3Dtrue")
        return (body or {}).get("items", [])

    # ---- pipeline reads (all read-only; None/[] outside the cluster) ----

    async def get_kustomization(self) -> dict | None:
        """The Flux Kustomization that applies the branch-envs directory."""
        return await self._get(
            "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system"
            "/kustomizations/branch-envs"
        )

    async def get_gitrepository(self, slug: str) -> dict | None:
        """The env's Flux GitRepository (chart source pinned to the branch)."""
        return await self._get(
            "/apis/source.toolkit.fluxcd.io/v1/namespaces/flux-system"
            f"/gitrepositories/druppie-branch-{slug}"
        )

    async def list_externalsecrets(self, namespace: str) -> list[dict]:
        body = await self._get(
            f"/apis/external-secrets.io/v1/namespaces/{namespace}/externalsecrets"
        )
        return (body or {}).get("items", [])

    async def list_deployments(self, namespace: str) -> list[dict]:
        body = await self._get(f"/apis/apps/v1/namespaces/{namespace}/deployments")
        return (body or {}).get("items", [])

    async def list_pods(self, namespace: str) -> list[dict]:
        body = await self._get(f"/api/v1/namespaces/{namespace}/pods")
        return (body or {}).get("items", [])


# -----------------------------------------------------------------------------
# Status derivation
# -----------------------------------------------------------------------------

_FAILED_REASONS = frozenset(
    {"InstallFailed", "UpgradeFailed", "RollbackFailed", "UninstallFailed", "ArtifactFailed"}
)


def _derive_status(hr: dict | None, cluster_available: bool) -> tuple[str, str | None]:
    """Map a HelmRelease object (or its absence) to (status, message)."""
    if not cluster_available:
        return (
            BranchEnvironmentStatus.DEPLOYING.value,
            "committed to GitOps repo; live status unavailable from here",
        )
    if hr is None:
        return (
            BranchEnvironmentStatus.DEPLOYING.value,
            "waiting for Flux to apply the environment manifests",
        )
    conditions = {c.get("type"): c for c in (hr.get("status", {}).get("conditions") or [])}
    ready = conditions.get("Ready") or {}
    stalled = conditions.get("Stalled") or {}
    if ready.get("status") == "True":
        return BranchEnvironmentStatus.RUNNING.value, None
    message = ready.get("message") or stalled.get("message")
    if stalled.get("status") == "True" or ready.get("reason") in _FAILED_REASONS:
        return BranchEnvironmentStatus.FAILED.value, (message or "helm release failed")[:900]
    return (
        BranchEnvironmentStatus.DEPLOYING.value,
        (message or "helm release reconciling")[:900],
    )


# -----------------------------------------------------------------------------
# Pipeline stage derivation — one pure function per node in the deploy visual
# -----------------------------------------------------------------------------

_STAGE_DONE = PipelineStageStatus.DONE
_STAGE_BUSY = PipelineStageStatus.BUSY
_STAGE_PENDING = PipelineStageStatus.PENDING
_STAGE_FAILED = PipelineStageStatus.FAILED

# Container waiting reasons that mean the workloads stage has hard-failed
# (image can't be pulled from Harbor, or the container keeps crashing).
_POD_BAD_REASONS = frozenset(
    {
        "ImagePullBackOff",
        "ErrImagePull",
        "InvalidImageName",
        "CrashLoopBackOff",
        "CreateContainerConfigError",
        "CreateContainerError",
    }
)


def _ready_condition(obj: dict | None) -> dict:
    """The Ready condition of any Flux/ESO object ({} when absent)."""
    conditions = (obj or {}).get("status", {}).get("conditions") or []
    return next((c for c in conditions if c.get("type") == "Ready"), {})


def _derive_flux_stage(ns: dict | None, kustomization: dict | None) -> PipelineStage:
    """Flux applying the env manifests: done once the namespace exists."""
    if ns is not None:
        return PipelineStage(id="flux", name="Flux sync", status=_STAGE_DONE)
    ready = _ready_condition(kustomization)
    if ready.get("status") == "False":
        return PipelineStage(
            id="flux",
            name="Flux sync",
            status=_STAGE_FAILED,
            message=(ready.get("message") or "branch-envs kustomization failed")[:900],
        )
    return PipelineStage(
        id="flux",
        name="Flux sync",
        status=_STAGE_BUSY,
        message="waiting for Flux to apply the environment manifests",
    )


def _derive_source_stage(gitrepo: dict | None, branch: str) -> PipelineStage:
    """The env's GitRepository fetching the app branch (chart source)."""
    name = "Chart source"
    if gitrepo is None:
        return PipelineStage(id="source", name=name, status=_STAGE_PENDING)
    ready = _ready_condition(gitrepo)
    if ready.get("status") == "True":
        return PipelineStage(id="source", name=name, status=_STAGE_DONE)
    message = (ready.get("message") or f"fetching branch '{branch}'")[:900]
    if ready.get("status") == "False":
        return PipelineStage(id="source", name=name, status=_STAGE_FAILED, message=message)
    return PipelineStage(id="source", name=name, status=_STAGE_BUSY, message=message)


def _derive_secrets_stage(ns: dict | None, externalsecrets: list[dict]) -> PipelineStage:
    """ESO syncing the env's ExternalSecrets (Vault keys, TLS mirror, Harbor pull)."""
    name = "Secrets (Vault)"
    if ns is None:
        return PipelineStage(id="secrets", name=name, status=_STAGE_PENDING)
    if not externalsecrets:
        return PipelineStage(
            id="secrets",
            name=name,
            status=_STAGE_BUSY,
            message="waiting for ExternalSecrets to appear",
        )
    failures: list[str] = []
    synced = 0
    for es in externalsecrets:
        es_name = es.get("metadata", {}).get("name", "?")
        ready = _ready_condition(es)
        if ready.get("status") == "True":
            synced += 1
        elif ready.get("status") == "False":
            failures.append(f"{es_name}: {ready.get('message') or 'sync failed'}")
    total = len(externalsecrets)
    if failures:
        return PipelineStage(
            id="secrets",
            name=name,
            status=_STAGE_FAILED,
            message="; ".join(failures)[:900],
            detail=f"{synced}/{total} secrets synced",
        )
    if synced < total:
        return PipelineStage(
            id="secrets",
            name=name,
            status=_STAGE_BUSY,
            detail=f"{synced}/{total} secrets synced",
        )
    return PipelineStage(id="secrets", name=name, status=_STAGE_DONE)


def _derive_helm_stage(ns: dict | None, hr: dict | None) -> PipelineStage:
    """helm-controller installing/upgrading the chart (HelmRelease conditions)."""
    name = "Helm install"
    if hr is None and ns is None:
        return PipelineStage(id="helm", name=name, status=_STAGE_PENDING)
    status, message = _derive_status(hr, cluster_available=True)
    if status == BranchEnvironmentStatus.RUNNING.value:
        return PipelineStage(id="helm", name=name, status=_STAGE_DONE)
    if status == BranchEnvironmentStatus.FAILED.value:
        return PipelineStage(id="helm", name=name, status=_STAGE_FAILED, message=message)
    return PipelineStage(id="helm", name=name, status=_STAGE_BUSY, message=message)


def _derive_workloads_stage(deployments: list[dict], pods: list[dict]) -> PipelineStage:
    """Pods starting up — images pulled from Harbor, containers becoming ready."""
    name = "Pods & images"
    if not deployments:
        # Helm hasn't created the workloads yet.
        return PipelineStage(id="workloads", name=name, status=_STAGE_PENDING)

    # Hard container failures first (ImagePullBackOff from Harbor, crash loops).
    for pod in pods:
        pod_name = pod.get("metadata", {}).get("name", "?")
        pod_status = pod.get("status", {}) or {}
        statuses = (pod_status.get("containerStatuses") or []) + (
            pod_status.get("initContainerStatuses") or []
        )
        for cs in statuses:
            waiting = (cs.get("state") or {}).get("waiting") or {}
            reason = waiting.get("reason")
            if reason in _POD_BAD_REASONS:
                message = f"{pod_name}: {reason}"
                if waiting.get("message"):
                    message += f" — {waiting['message']}"
                return PipelineStage(
                    id="workloads", name=name, status=_STAGE_FAILED, message=message[:900]
                )

    total = len(deployments)
    ready = sum(
        1
        for d in deployments
        if ((d.get("status", {}) or {}).get("readyReplicas") or 0)
        >= ((d.get("spec", {}) or {}).get("replicas") or 1)
    )
    detail = f"{ready}/{total} deployments ready"
    if ready >= total:
        return PipelineStage(id="workloads", name=name, status=_STAGE_DONE, detail=detail)
    return PipelineStage(id="workloads", name=name, status=_STAGE_BUSY, detail=detail)


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------


def _require_owner_or_admin(
    owner_id: UUID | None, user_id: UUID, user_roles: list[str], action: str
) -> None:
    """Authorize a mutating action: owner or admin only.

    Environments without a readable owner annotation are admin-only.
    """
    if "admin" in user_roles:
        return
    if owner_id is None or owner_id != user_id:
        raise AuthorizationError(f"Only owner or admin can {action} a branch environment")


class BranchEnvironmentService:
    """Business logic for per-branch Druppie environments (GitOps-backed)."""

    def __init__(
        self,
        gitea: GiteaGitopsClient | None = None,
        cluster: ClusterStatusClient | None = None,
    ):
        self.gitea = gitea or GiteaGitopsClient()
        self.cluster = cluster or ClusterStatusClient()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def list_branches(self) -> list[str]:
        """List all branches from the application repo (ai/druppie)."""
        branches = await self.gitea.list_branches(CHART_REPO)
        return [
            b["name"]
            for b in branches
            if not b.get("protected", False)
        ]

    async def _change_files_with_retry(
        self,
        slug: str,
        message: str,
        files: list[dict],
        max_retries: int = 3,
    ) -> None:
        """Commit files with retry on 409/422 (stal SHA from concurrent CI writes)."""
        for attempt in range(max_retries):
            try:
                await self.gitea.change_files(message, files)
                return
            except ConflictError:
                if attempt == max_retries - 1:
                    raise
                logger.warning("change_files_conflict", slug=slug, attempt=attempt + 1)
                await asyncio.sleep(1)
        raise ExternalServiceError(
            service="gitops-repo",
            message=f"could not commit to git for {slug} after {max_retries} attempts",
        )

    async def create(
        self,
        owner_id: UUID,
        branch: str,
        image_tag: str | None,
        user_roles: list[str],
        secrets_source: str = SECRETS_SOURCE_COLAB_DEV,
        owner_username: str | None = None,
        recovery_mode: bool = False,
    ) -> BranchEnvironmentDetail:
        """Commit the environment manifests; Flux does the deploy."""
        _ = user_roles  # role gating happens at the route layer
        _validate_branch(branch)
        secrets_source = (secrets_source or SECRETS_SOURCE_COLAB_DEV).strip().lower()
        if not secrets_source or not _SECRETS_SOURCE_RE.match(secrets_source):
            raise ValidationError(
                f"invalid secrets_source: {secrets_source!r}", field="secrets_source"
            )
        slug = _slugify(branch)
        namespace = f"druppie-{slug}"
        host = f"druppie-{slug}.{DOMAIN_SUFFIX}"

        # Namespace must be a valid DNS-1123 label (<=63 chars).
        if len(namespace) > 63:
            raise ValidationError(f"namespace '{namespace}' exceeds 63 chars", field="branch")
        # Host must stay a single label under the domain suffix to match the cert.
        if "." in host[: -(len(DOMAIN_SUFFIX) + 1)]:
            raise ValidationError(
                f"host '{host}' is not a single label under {DOMAIN_SUFFIX}", field="branch"
            )
        # The dev workspace is enabled by default and renders a -dev ingress
        # whose label (druppie-<slug>-dev) must also be a valid DNS-1123 label.
        ws_label = _workspace_host(host).split(".", 1)[0]
        if len(ws_label) > 63:
            raise ValidationError(
                f"workspace host label '{ws_label}' exceeds 63 chars", field="branch"
            )
        # SAFETY GUARD: never target the live instances (e.g. branch "colab-dev"
        # would map to namespace druppie-colab-dev).
        _assert_safe_namespace(namespace, slug)
        if image_tag is not None:
            image_tag = _validate_image_tag(image_tag)
        elif self.cluster.available:
            parent = await self.cluster.get_helmrelease(PARENT_NAMESPACE, name=PARENT_NAMESPACE)
            image_tag = (
                (parent or {}).get("spec", {}).get("values", {})
                .get("global", {}).get("imageTag")
            ) or None
            if image_tag:
                logger.info("branch_env_image_tag_resolved", tag=image_tag, source=PARENT_NAMESPACE)

        if await self.gitea.get_file(self._env_path(slug, "namespace.yaml")) is not None:
            raise ConflictError(f"branch environment already exists for branch '{branch}'")
        # A namespace still terminating from an earlier teardown blocks recreation.
        if self.cluster.available and await self.cluster.get_namespace(namespace) is not None:
            raise ConflictError(
                f"namespace '{namespace}' still exists (previous teardown in progress); retry later"
            )

        # The env's GitRepository clones this branch from the app repo. Create
        # it from the base branch when it doesn't exist yet, so Flux never
        # stalls on a missing ref.
        branch_created = False
        if not await self.gitea.branch_exists(CHART_REPO, branch):
            await self.gitea.create_branch(CHART_REPO, branch, APP_BASE_BRANCH)
            branch_created = True
            logger.info(
                "branch_env_app_branch_created",
                branch=branch,
                repo=CHART_REPO,
                base=APP_BASE_BRANCH,
            )

        # Always dispatch the CI build so images are guaranteed fresh, even
        # when the branch already existed (no push event fires in that case to
        # trigger build.yaml). The env stands up on the parent image tag first;
        # CI's deploy step then patches imageTag once the build finishes.
        await self.gitea.dispatch_workflow(CHART_REPO, branch)

        created_at = _utcnow_iso()
        files = [
            {
                "operation": "create",
                "path": self._env_path(slug, "namespace.yaml"),
                "content": build_namespace_yaml(
                    slug, branch, owner_id, created_at, secrets_source=secrets_source
                ),
            },
            {
                "operation": "create",
                "path": self._env_path(slug, "gitrepository.yaml"),
                "content": build_gitrepository_yaml(slug, branch),
            },
            {
                "operation": "create",
                "path": self._env_path(slug, "helmrelease.yaml"),
                "content": build_helmrelease_yaml(
                    slug, branch, host, image_tag, created_at, secrets_source=secrets_source, recovery_mode=recovery_mode
                ),
            },
            {
                "operation": "create",
                "path": self._env_path(slug, "externalsecrets.yaml"),
                "content": build_externalsecrets_yaml(slug),
            },
        ]
        await self.gitea.change_files(
            f"branch-env: deploy {namespace} (branch {branch}, by {owner_id})", files
        )
        await self.cluster.force_reconcile_flux()
        logger.info("branch_env_created", slug=slug, branch=branch, namespace=namespace)

        return BranchEnvironmentDetail(
            id=slug,
            branch=branch,
            slug=slug,
            namespace=namespace,
            url=f"https://{host}",
            image_tag=image_tag,
            status=BranchEnvironmentStatus.DEPLOYING.value,
            status_message=(
                f"created branch '{branch}' from {APP_BASE_BRANCH}; "
                "CI build dispatched; manifests committed; waiting for Flux to deploy"
                if branch_created
                else "CI build dispatched; manifests committed; waiting for Flux to deploy"
            ),
            created_at=datetime.fromisoformat(created_at),
            owner_id=owner_id,
            secrets_source=secrets_source,
            recovery_mode=recovery_mode,
        )

    async def redeploy(
        self,
        env_id: str,
        user_id: UUID,
        user_roles: list[str],
        image_tag: str | None = None,
    ) -> BranchEnvironmentDetail:
        """Commit a new image tag and/or a forced-reconcile annotation bump.

        Owner or admin only. The committed ``reconcile.fluxcd.io`` annotations
        make helm-controller reconcile (and retry a failed release) as soon as
        Flux applies the change — no kube write needed from the backend.
        """
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        if env is None:
            raise NotFoundError("branch_environment", slug)

        _require_owner_or_admin(env["owner_id"], user_id, user_roles, "redeploy")
        _assert_safe_namespace(env["namespace"], slug)

        if image_tag is not None:
            image_tag = _validate_image_tag(image_tag)
        else:
            image_tag = env["image_tag"]

        updated_at = _utcnow_iso()
        content = build_helmrelease_yaml(
            slug,
            env["branch"],
            env["host"],
            image_tag,
            updated_at,
            reconcile_epoch=str(int(time.time())),
            secrets_source=env.get("secrets_source") or SECRETS_SOURCE_COLAB_DEV,
            workspace_enabled=env.get("workspace_enabled", True),
            stack_mode=env.get("stack_mode", "real"),
        )
        await self._change_files_with_retry(
            slug,
            f"branch-env: redeploy {env['namespace']} (tag {image_tag or 'unchanged'}, by {user_id})",
            [
                {
                    "operation": "update",
                    "path": self._env_path(slug, "helmrelease.yaml"),
                    "content": content,
                    "sha": env["helmrelease_sha"],
                }
            ],
        )
        logger.info("branch_env_redeploy", slug=slug, image_tag=image_tag)
        await self.cluster.force_reconcile_flux()

        detail = await self.get(slug)
        return detail.model_copy(
            update={
                "status": BranchEnvironmentStatus.DEPLOYING,
                "status_message": "redeploy committed; waiting for Flux",
                "image_tag": image_tag,
            }
        )

    async def teardown(
        self,
        env_id: str,
        user_id: UUID,
        user_roles: list[str],
    ) -> BranchEnvironmentDetail:
        """Delete the env directory from git; Flux prunes the namespace.

        Retries up to 3 times on 409/422 conflict (e.g. CI updating the
        HelmRelease at the same time), re-reading the directory for fresh SHAs.
        """
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        if env is None:
            raise NotFoundError("branch_environment", slug)

        _require_owner_or_admin(env["owner_id"], user_id, user_roles, "tear down")
        _assert_safe_namespace(env["namespace"], slug)

        max_retries = 3
        for attempt in range(max_retries):
            entries = await self.gitea.list_dir(self._env_path(slug)) or []
            deletes = [
                {"operation": "delete", "path": e["path"], "sha": e["sha"]}
                for e in entries
                if e.get("type") == "file"
            ]
            if not deletes:
                raise NotFoundError("branch_environment", slug)
            try:
                await self.gitea.change_files(
                    f"branch-env: teardown {env['namespace']} (by {user_id})",
                    deletes,
                )
                break
            except ConflictError:
                if attempt == max_retries - 1:
                    raise
                logger.warning(
                    "branch_env_teardown_conflict",
                    slug=slug,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(1)
        else:
            raise ExternalServiceError(
                service="gitops-repo",
                message=f"could not delete {slug} after {max_retries} attempts",
            )

        logger.info("branch_env_teardown", slug=slug, namespace=env["namespace"])
        await self.cluster.force_reconcile_flux()

        return self._detail_from_env(
            env,
            status=BranchEnvironmentStatus.DELETING.value,
            message="removed from GitOps repo; Flux is pruning the namespace",
        )

    async def enable_workspace(
        self,
        env_id: str,
        user_id: UUID,
        user_roles: list[str],
    ) -> BranchEnvironmentDetail:
        """Enable the env's dev workspace by re-committing the HelmRelease with
        ``devWorkspace.enabled=true`` (202). Owner or admin only. Conflict if a
        workspace is already enabled.
        """
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        if env is None:
            raise NotFoundError("branch_environment", slug)

        _require_owner_or_admin(env["owner_id"], user_id, user_roles, "enable a workspace for")
        _assert_safe_namespace(env["namespace"], slug)

        # The workspace host is a single label under the domain suffix; it must
        # stay a valid DNS-1123 label (<=63 chars) to match the wildcard cert.
        workspace_host = _workspace_host(env["host"])
        label = workspace_host.split(".", 1)[0]
        if len(label) > 63:
            raise ValidationError(
                f"workspace host label '{label}' exceeds 63 chars", field="env_id"
            )

        if env["workspace_enabled"]:
            raise ConflictError(f"workspace already enabled for '{slug}'")

        updated_at = _utcnow_iso()
        content = build_helmrelease_yaml(
            slug,
            env["branch"],
            env["host"],
            env["image_tag"],
            updated_at,
            reconcile_epoch=str(int(time.time())),
            secrets_source=env.get("secrets_source") or SECRETS_SOURCE_COLAB_DEV,
            workspace_enabled=True,
            stack_mode=env.get("stack_mode", "real"),
        )
        await self._change_files_with_retry(
            slug,
            f"branch-env: enable workspace {env['namespace']} (by {user_id})",
            [
                {
                    "operation": "update",
                    "path": self._env_path(slug, "helmrelease.yaml"),
                    "content": content,
                    "sha": env["helmrelease_sha"],
                }
            ],
        )
        logger.info("branch_env_workspace_enabled", slug=slug, namespace=env["namespace"])
        await self.cluster.force_reconcile_flux()

        env["workspace_enabled"] = True
        status, message = await self._live_status(env["namespace"])
        ws_status = await self._workspace_status(env["namespace"], True)
        return self._detail_from_env(
            env, status=status, message=message, workspace_status=ws_status
        )

    async def disable_workspace(
        self,
        env_id: str,
        user_id: UUID,
        user_roles: list[str],
    ) -> BranchEnvironmentDetail:
        """Disable the dev workspace by re-committing the HelmRelease with
        ``devWorkspace.enabled=false``; Flux prunes the workspace resources."""
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        if env is None:
            raise NotFoundError("branch_environment", slug)

        _require_owner_or_admin(env["owner_id"], user_id, user_roles, "disable the workspace for")
        _assert_safe_namespace(env["namespace"], slug)

        if not env["workspace_enabled"]:
            raise ConflictError(f"workspace is not enabled for '{slug}'")

        updated_at = _utcnow_iso()
        content = build_helmrelease_yaml(
            slug,
            env["branch"],
            env["host"],
            env["image_tag"],
            updated_at,
            reconcile_epoch=str(int(time.time())),
            secrets_source=env.get("secrets_source") or SECRETS_SOURCE_COLAB_DEV,
            workspace_enabled=False,
            stack_mode=env.get("stack_mode", "real"),
        )
        await self._change_files_with_retry(
            slug,
            f"branch-env: disable workspace {env['namespace']} (by {user_id})",
            [
                {
                    "operation": "update",
                    "path": self._env_path(slug, "helmrelease.yaml"),
                    "content": content,
                    "sha": env["helmrelease_sha"],
                }
            ],
        )
        logger.info("branch_env_workspace_disabled", slug=slug, namespace=env["namespace"])
        await self.cluster.force_reconcile_flux()

        env["workspace_enabled"] = False
        status, message = await self._live_status(env["namespace"])
        return self._detail_from_env(
            env, status=status, message=message, workspace_status=None
        )

    async def list_all(self, page: int = 1, limit: int = 100):
        """List all branch environments (git = source of truth, plus any
        namespaces still terminating after teardown)."""
        entries = await self.gitea.list_dir(GITOPS_PATH) or []
        slugs = [
            e["name"].removeprefix("druppie-")
            for e in entries
            if e.get("type") == "dir" and e["name"].startswith("druppie-")
        ]

        envs = [e for e in await asyncio.gather(*(self._read_env(s) for s in slugs)) if e]
        details: list[BranchEnvironmentDetail] = []
        statuses, ws_statuses = await asyncio.gather(
            asyncio.gather(*(self._live_status(env["namespace"]) for env in envs)),
            asyncio.gather(
                *(self._workspace_status(env["namespace"], env["workspace_enabled"]) for env in envs)
            ),
        )
        for env, (status, message), ws_status in zip(envs, statuses, ws_statuses):
            details.append(
                self._detail_from_env(
                    env, status=status, message=message, workspace_status=ws_status
                )
            )

        # Envs deleted from git but whose namespace is still terminating.
        in_git = {d.namespace for d in details}
        if self.cluster.available:
            for ns in await self.cluster.list_branch_namespaces():
                name = ns["metadata"]["name"]
                if name in in_git:
                    continue
                details.append(self._detail_from_namespace(ns))

        details.sort(key=lambda d: d.created_at, reverse=True)
        total = len(details)
        offset = (page - 1) * limit
        return details[offset : offset + limit], total

    async def get(self, env_id: str) -> BranchEnvironmentDetail:
        """Get a single branch environment detail."""
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        if env is not None:
            status, message = await self._live_status(env["namespace"])
            ws_status = await self._workspace_status(env["namespace"], env["workspace_enabled"])
            return self._detail_from_env(
                env, status=status, message=message, workspace_status=ws_status
            )
        # Gone from git — still visible while the namespace terminates.
        if self.cluster.available:
            ns = await self.cluster.get_namespace(f"druppie-{slug}")
            if ns is not None and ns.get("metadata", {}).get("labels", {}).get(
                f"{_ANN}/branch-env"
            ):
                return self._detail_from_namespace(ns)
        raise NotFoundError("branch_environment", slug)

    async def pipeline(self, env_id: str) -> BranchEnvironmentPipeline:
        """Live deploy pipeline for an env — one stage per hop in the chain.

        commit → flux → (source | secrets) → helm → workloads → live, each
        derived read-only from git + the cluster. Envs deleted from git but
        still terminating report a short teardown pipeline instead.
        """
        slug = _validate_slug(env_id)
        env = await self._read_env(slug)
        namespace = f"druppie-{slug}"

        if env is None:
            # Gone from git — teardown pipeline while the namespace terminates.
            if self.cluster.available:
                ns = await self.cluster.get_namespace(namespace)
                if ns is not None and ns.get("metadata", {}).get("labels", {}).get(
                    f"{_ANN}/branch-env"
                ):
                    return BranchEnvironmentPipeline(
                        env_id=slug,
                        status=BranchEnvironmentStatus.DELETING,
                        stages=[
                            PipelineStage(
                                id="commit-removed",
                                name="Removed from GitOps repo",
                                status=_STAGE_DONE,
                            ),
                            PipelineStage(
                                id="pruning",
                                name="Flux pruning namespace",
                                status=_STAGE_BUSY,
                                message="namespace is terminating",
                            ),
                        ],
                    )
            raise NotFoundError("branch_environment", slug)

        commit = PipelineStage(id="commit", name="Commit (aigit)", status=_STAGE_DONE)

        if not self.cluster.available:
            # Local dev / tests: git says the env exists, but the deploy chain
            # is not observable from here.
            unavailable = "live status unavailable from here"
            stages = [commit] + [
                PipelineStage(id=sid, name=sname, status=_STAGE_PENDING, message=unavailable)
                for sid, sname in (
                    ("flux", "Flux sync"),
                    ("source", "Chart source"),
                    ("secrets", "Secrets (Vault)"),
                    ("helm", "Helm install"),
                    ("workloads", "Pods & images"),
                    ("live", "Live"),
                )
            ]
            return BranchEnvironmentPipeline(
                env_id=slug, status=BranchEnvironmentStatus.DEPLOYING, stages=stages
            )

        ns, kustomization, gitrepo, externalsecrets, hr, deployments, pods = (
            await asyncio.gather(
                self.cluster.get_namespace(namespace),
                self.cluster.get_kustomization(),
                self.cluster.get_gitrepository(slug),
                self.cluster.list_externalsecrets(namespace),
                self.cluster.get_helmrelease(namespace),
                self.cluster.list_deployments(namespace),
                self.cluster.list_pods(namespace),
            )
        )

        stages = [
            commit,
            _derive_flux_stage(ns, kustomization),
            _derive_source_stage(gitrepo, env["branch"]),
            _derive_secrets_stage(ns, externalsecrets),
            _derive_helm_stage(ns, hr),
            _derive_workloads_stage(deployments, pods),
        ]
        all_done = all(s.status == _STAGE_DONE for s in stages)
        stages.append(
            PipelineStage(
                id="live",
                name="Live",
                status=_STAGE_DONE if all_done else _STAGE_PENDING,
                detail=f"https://{env['host']}" if all_done else None,
            )
        )

        if any(s.status == _STAGE_FAILED for s in stages):
            overall = BranchEnvironmentStatus.FAILED
        elif all(s.status == _STAGE_DONE for s in stages):
            overall = BranchEnvironmentStatus.RUNNING
        else:
            overall = BranchEnvironmentStatus.DEPLOYING
        return BranchEnvironmentPipeline(env_id=slug, status=overall, stages=stages)

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    @staticmethod
    def _env_path(slug: str, filename: str | None = None) -> str:
        base = f"{GITOPS_PATH}/druppie-{slug}"
        return f"{base}/{filename}" if filename else base

    async def _read_env(self, slug: str) -> dict | None:
        """Read an env's metadata from its committed manifests. None if absent."""
        ns_file, hr_file = await asyncio.gather(
            self.gitea.get_file(self._env_path(slug, "namespace.yaml")),
            self.gitea.get_file(self._env_path(slug, "helmrelease.yaml")),
        )
        if ns_file is None:
            return None
        ns_manifest = yaml.safe_load(ns_file[0]) or {}
        annotations = ns_manifest.get("metadata", {}).get("annotations", {}) or {}

        image_tag = None
        updated_at = None
        helmrelease_sha = None
        workspace_enabled = False
        developer = ""
        stack_mode = "real"
        recovery_mode = False
        if hr_file is not None:
            helmrelease_sha = hr_file[1]
            hr_manifest = yaml.safe_load(hr_file[0]) or {}
            hr_values = hr_manifest.get("spec", {}).get("values", {}) or {}
            image_tag = hr_values.get("global", {}).get("imageTag")
            updated_at = (
                hr_manifest.get("metadata", {}).get("annotations", {}) or {}
            ).get(f"{_ANN}/updated-at")
            # Workspace state lives in the HelmRelease values now (no separate
            # workspace.yaml): devWorkspace.enabled/developer/stackMode.
            dev_ws = hr_values.get("devWorkspace", {}) or {}
            workspace_enabled = bool(dev_ws.get("enabled", False))
            developer = dev_ws.get("developer", "") or ""
            stack_mode = dev_ws.get("stackMode", "real") or "real"
            recovery_mode = bool(hr_values.get("recoveryMode", False))

        owner_raw = annotations.get(f"{_ANN}/owner-id")
        try:
            owner_id = UUID(owner_raw) if owner_raw else None
        except ValueError:
            owner_id = None

        return {
            "slug": slug,
            "branch": annotations.get(f"{_ANN}/branch", slug),
            "namespace": f"druppie-{slug}",
            "host": f"druppie-{slug}.{DOMAIN_SUFFIX}",
            "owner_id": owner_id,
            "created_at": annotations.get(f"{_ANN}/created-at"),
            "updated_at": updated_at,
            "image_tag": image_tag,
            "helmrelease_sha": helmrelease_sha,
            "secrets_source": annotations.get(f"{_ANN}/secrets-source"),
            "workspace_enabled": workspace_enabled,
            "developer": developer,
            "stack_mode": stack_mode,
            "recovery_mode": recovery_mode,
        }

    async def _live_status(self, namespace: str) -> tuple[str, str | None]:
        if not self.cluster.available:
            return _derive_status(None, cluster_available=False)
        hr = await self.cluster.get_helmrelease(namespace)
        return _derive_status(hr, cluster_available=True)

    async def _workspace_status(self, namespace: str, enabled: bool) -> str | None:
        """Live workspace status: 'running' once the Deployment has a ready
        replica, else 'deploying'. None when the workspace is disabled."""
        if not enabled:
            return None
        deploying = BranchEnvironmentStatus.DEPLOYING.value
        if not self.cluster.available:
            return deploying
        # Chart-native workspace Deployment: <instance>-workspace (the chart's
        # druppie.fullname + "-workspace"), not the old standalone "workspace".
        dep = await self.cluster.get_deployment(namespace, f"{namespace}-workspace")
        if dep is None:
            return deploying
        ready = (dep.get("status", {}) or {}).get("readyReplicas", 0) or 0
        return BranchEnvironmentStatus.RUNNING.value if ready >= 1 else deploying

    def _detail_from_env(
        self,
        env: dict,
        status: str,
        message: str | None,
        workspace_status: str | None = None,
    ) -> BranchEnvironmentDetail:
        enabled = env.get("workspace_enabled", False)
        return BranchEnvironmentDetail(
            id=env["slug"],
            branch=env["branch"],
            slug=env["slug"],
            namespace=env["namespace"],
            url=f"https://{env['host']}",
            image_tag=env["image_tag"],
            status=status,
            status_message=message,
            created_at=self._parse_ts(env["created_at"]),
            updated_at=self._parse_ts(env["updated_at"]) if env["updated_at"] else None,
            owner_id=env["owner_id"],
            secrets_source=env.get("secrets_source"),
            workspace_enabled=enabled,
            workspace_url=f"https://{_workspace_host(env['host'])}" if enabled else None,
            workspace_status=workspace_status,
            recovery_mode=env.get("recovery_mode", False),
        )

    def _detail_from_namespace(self, ns: dict) -> BranchEnvironmentDetail:
        """Detail for an env that only exists as a terminating namespace."""
        meta = ns.get("metadata", {})
        annotations = meta.get("annotations", {}) or {}
        name = meta["name"]
        slug = name.removeprefix("druppie-")
        owner_raw = annotations.get(f"{_ANN}/owner-id")
        try:
            owner_id = UUID(owner_raw) if owner_raw else None
        except ValueError:
            owner_id = None
        return BranchEnvironmentDetail(
            id=slug,
            branch=annotations.get(f"{_ANN}/branch", slug),
            slug=slug,
            namespace=name,
            url=f"https://druppie-{slug}.{DOMAIN_SUFFIX}",
            image_tag=None,
            status=BranchEnvironmentStatus.DELETING.value,
            status_message="removed from GitOps repo; namespace is terminating",
            created_at=self._parse_ts(annotations.get(f"{_ANN}/created-at")),
            owner_id=owner_id,
        )

    @staticmethod
    def _parse_ts(value: str | None) -> datetime:
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.fromtimestamp(0, tz=timezone.utc)
