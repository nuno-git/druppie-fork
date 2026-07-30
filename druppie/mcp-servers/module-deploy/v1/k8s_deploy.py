"""
K8s Deploy Manager — GitOps-native replacement for Docker operations.

Used by module-deploy when DRUPPIE_SANDBOX_MODE=k8s.

Model: a generated app ships its OWN Helm chart (chart/). Deploying it means
committing a Flux GitRepository + HelmRelease to ai/k8s (clusters/user-apps/
<slug>/) and letting Flux reconcile — identical to how Druppie deploys itself.
No Docker daemon.

Build is k8s-native (no Docker daemon, no Gitea Actions runner) and PURELY
git-driven — the same GitOps pattern branch environments use, with NO
imperative build write. Everything under clusters/user-apps/<slug>/build/ is
committed to git and created by Flux:
      namespace.yaml                    a dedicated build namespace
      harbor-push-externalsecret.yaml   Harbor push dockerconfig (Vault ci/harbor)
      git-auth-externalsecret.yaml      clone token (Vault ci/gitea)
      job.yaml                          the kaniko build Job (name carries the tag)
No secret ever lands in git in plaintext; ESO pulls them from Vault. kaniko is
daemonless and runs in its own isolated pod (never on a shared Actions runner).
module-deploy only READS status back (namespace exists, ExternalSecrets Ready,
Job succeeded, HelmRelease Ready); Flux owns every build object's lifecycle,
incl. pruning a superseded Job when a new tag is committed.

  build    → commit build infra + kaniko Job to git; Flux runs it; poll status
  deploy   → build the image, then commit namespace+gitrepository+helmrelease
             pinned to the freshly-built tag, wait for Flux HelmRelease Ready,
             then health-gate the ingress URL (300s)
  teardown → delete the app's ai/k8s subdir incl. build/ (Flux prune tears down)
  logs     → read the app pod's logs (in-cluster SA token, read-only)
  list     → list deployed user-apps (namespaces labelled managed-by)
  stop     → scale the app Deployment to 0 (the ONE imperative cluster write)
  inspect  → read app HelmRelease + pod status (read-only)

Cluster access is READ-ONLY via httpx + the pod ServiceAccount token (no
`kubernetes` python dependency) — the sole exception is k8s_stop, which scales
a Deployment to 0. Every other mutation (app footprint AND build) goes through
the Gitea batch contents API (POST /repos/{repo}/contents, one atomic commit
per step) and is applied by Flux.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env, with branch-env-compatible fallbacks)
# ---------------------------------------------------------------------------


GITOPS_URL = os.getenv(
    "USERAPPS_GITOPS_URL", os.getenv("BRANCH_ENV_GITOPS_URL", "https://aigit.waterschap.org")
)
GITOPS_REPO = os.getenv("USERAPPS_GITOPS_REPO", "ai/k8s")
GITOPS_BRANCH = os.getenv("USERAPPS_GITOPS_BRANCH", "main")
GITOPS_PATH = os.getenv("USERAPPS_GITOPS_PATH", "clusters/user-apps")
GITOPS_TOKEN = os.getenv("USERAPPS_GITOPS_TOKEN", os.getenv("BRANCH_ENV_GITOPS_TOKEN", ""))
GITOPS_CA = os.getenv("USERAPPS_GITOPS_CA", os.getenv("BRANCH_ENV_GITOPS_CA", ""))

HARBOR_REGISTRY = os.getenv("HARBOR_REGISTRY", "harbor.rijnland.dev")
HARBOR_PROJECT = os.getenv("HARBOR_PROJECT", "druppie")
# Hostname scheme: <slug>-apps.<domain> (e.g. counter-apps.rijnland.dev). The
# "-apps" label is a single DNS label, so it is covered by the existing
# *.<domain> wildcard cert (secret druppie-tls) — no separate cert needed.
APPS_DOMAIN = os.getenv("USERAPPS_DOMAIN", "rijnland.dev")
CHART_PATH = os.getenv("USERAPPS_CHART_PATH", "chart")
APP_REPO_ORG = os.getenv("USERAPPS_APP_REPO_ORG", "druppie-apps")
# Separate URL for the Gitea instance hosting user app repos (internal Gitea).
# Used for workflow dispatch and run polling. Defaults to the in-cluster Gitea.
APP_REPO_URL = os.getenv("GITEA_INTERNAL_URL", os.getenv("USERAPPS_APP_REPO_URL", "http://druppie-gitea:3000"))

# Wall-clock the poller waits for the kaniko Job to finish. Must comfortably
# exceed the Job's own hard cap (BUILD_JOB_DEADLINE, below) plus the Flux
# reconcile lag before the Job is even created (interval 1m) — otherwise the
# poller gives up while the Job is still legitimately building. Job-side
# activeDeadlineSeconds is the real cap; this is just the client-side ceiling.
BUILD_POLL_TIMEOUT = int(os.getenv("USERAPPS_BUILD_TIMEOUT", "2400"))   # 40m
ROLLOUT_TIMEOUT = int(os.getenv("USERAPPS_ROLLOUT_TIMEOUT", "600"))     # 10m
HEALTH_TIMEOUT_DEFAULT = 300
HTTP_TIMEOUT = 30.0

# --- k8s-native build (kaniko Job) -----------------------------------------
# Build runs as a kaniko Job in a per-app build namespace. The namespace and
# its two ExternalSecrets are committed to git and created by Flux (branch-env
# pattern); only the ephemeral Job is created imperatively by module-deploy.
BUILD_NS_SUFFIX = os.getenv("USERAPPS_BUILD_NS_SUFFIX", "-build")
# kaniko is daemonless and MUST run in its own container (it extracts the base
# image over /). Pinned to match the version the app CI template installed.
KANIKO_IMAGE = os.getenv("USERAPPS_KANIKO_IMAGE", "gcr.io/kaniko-project/executor:v1.23.2")
# Small git client for the clone init-container. Pinned (not :latest) for
# reproducible builds. Override to a Harbor mirror if egress to Docker Hub is
# blocked or rate-limited.
GIT_CLONE_IMAGE = os.getenv("USERAPPS_GIT_CLONE_IMAGE", "alpine/git:2.45.2")
# Username paired with the ci/gitea token for the clone URL. Gitea accepts the
# token as the password with any non-empty username.
GIT_CLONE_USER = os.getenv("USERAPPS_GIT_CLONE_USER", "druppie-ci")
# ESO ClusterSecretStore + Vault paths the build ExternalSecrets read from.
SECRET_STORE = os.getenv("USERAPPS_SECRET_STORE", "vault-ai-team-k8s")
VAULT_HARBOR_PATH = os.getenv("USERAPPS_VAULT_HARBOR_PATH", "ci/harbor")
VAULT_GITEA_PATH = os.getenv("USERAPPS_VAULT_GITEA_PATH", "ci/gitea")
HARBOR_PUSH_SECRET = "harbor-push"   # dockerconfigjson, mounted into kaniko
GIT_AUTH_SECRET = "git-auth"         # token, read by the clone init-container
# Hard wall-clock cap on a single kaniko Job (server-side, via the Job spec).
BUILD_JOB_DEADLINE = int(os.getenv("USERAPPS_BUILD_JOB_DEADLINE", "1800"))   # 30m
# How long to wait for Flux to create the build namespace + ESO to sync.
BUILD_INFRA_TIMEOUT = int(os.getenv("USERAPPS_BUILD_INFRA_TIMEOUT", "180"))  # 3m

_APP_LABEL = "managed-by=druppie-module-deploy"


def _slugify(name: str) -> str:
    """Lowercase, [a-z0-9-] only, dashes collapsed + trimmed (matches CI slug)."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# GitOps client — Gitea batch contents API (token auth + optional private CA)
# ---------------------------------------------------------------------------
class GitopsClient:
    def __init__(self) -> None:
        base = GITOPS_URL.rstrip("/")
        self._api = f"{base}/api/v1/repos/{GITOPS_REPO}"
        # User-app repos live on the internal Gitea (APP_REPO_URL). The runs API
        # base is constructed without a hardcoded org — dispatch_workflow and
        # latest_run accept repo_owner to build the full URL dynamically.
        app_base = APP_REPO_URL.rstrip("/")
        self._runs_api_base = f"{app_base}/api/v1/repos"
        self._branch = GITOPS_BRANCH
        self._headers = {"Authorization": f"token {GITOPS_TOKEN}"} if GITOPS_TOKEN else {}
        # Internal Gitea (app repos) may use a different token than the external GitOps Gitea.
        # In branch envs, GITEA_TOKEN is often a stale SHA1 hash from setup_gitea.py
        # that doesn't work for auth. Prefer basic auth (GITEA_USER + GITEA_PASSWORD)
        # which is always fresh, then dedicated internal token, then stale GITEA_TOKEN.
        _gitea_user = os.getenv("GITEA_USER", "")
        _gitea_pass = os.getenv("GITEA_PASSWORD", "")
        _internal_token = os.getenv("INTERNAL_GITEA_TOKEN", "")
        if _gitea_user and _gitea_pass:
            import base64 as _b64
            _creds = _b64.b64encode(f"{_gitea_user}:{_gitea_pass}".encode()).decode()
            self._internal_headers = {"Authorization": f"basic {_creds}"}
        elif _internal_token:
            self._internal_headers = {"Authorization": f"token {_internal_token}"}
        else:
            # Last resort: use the branch-env GITEA_TOKEN (may be stale SHA1).
            _fallback_token = os.getenv("GITEA_TOKEN", "")
            self._internal_headers = {"Authorization": f"token {_fallback_token}"} if _fallback_token else self._headers
        self._verify: Any = GITOPS_CA if GITOPS_CA else True

    def _client(self, internal: bool = False) -> httpx.AsyncClient:
        headers = self._internal_headers if internal else self._headers
        # Internal Gitea is HTTP, no CA verification needed.
        verify = False if internal else self._verify
        return httpx.AsyncClient(headers=headers, verify=verify, timeout=HTTP_TIMEOUT)

    @staticmethod
    def _raise_for(resp: httpx.Response, what: str) -> None:
        if 200 <= resp.status_code < 300:
            return
        raise RuntimeError(f"GitOps {what} failed: HTTP {resp.status_code}: {resp.text[:300]}")

    async def get_file(self, path: str) -> tuple[str, str] | None:
        """Return (content, sha), or None if the file does not exist (404)."""
        async with self._client() as c:
            resp = await c.get(f"{self._api}/contents/{path}", params={"ref": self._branch})
        if resp.status_code == 404:
            return None
        self._raise_for(resp, f"reading {path}")
        body = resp.json()
        content = base64.b64decode(body.get("content") or "").decode("utf-8")
        return content, body["sha"]

    async def list_dir(self, path: str) -> list[dict] | None:
        async with self._client() as c:
            resp = await c.get(f"{self._api}/contents/{path}", params={"ref": self._branch})
        if resp.status_code == 404:
            return None
        self._raise_for(resp, f"listing {path}")
        entries = resp.json()
        return entries if isinstance(entries, list) else [entries]

    async def change_files(self, message: str, files: list[dict]) -> None:
        """Atomic batch create/update/delete (one commit)."""
        payload_files = []
        for f in files:
            entry: dict = {"operation": f["operation"], "path": f["path"]}
            if f["operation"] in ("create", "update"):
                entry["content"] = base64.b64encode(f["content"].encode("utf-8")).decode("ascii")
            if f.get("sha"):
                entry["sha"] = f["sha"]
            payload_files.append(entry)
        async with self._client() as c:
            resp = await c.post(
                f"{self._api}/contents",
                json={"branch": self._branch, "message": message, "files": payload_files},
            )
        self._raise_for(resp, f"committing '{message}'")

    # -- Gitea Actions ------------------------------------------------------
    async def dispatch_workflow(
        self, repo: str, workflow: str, ref: str, repo_owner: str | None = None
    ) -> None:
        owner = repo_owner or APP_REPO_ORG
        async with self._client(internal=True) as c:
            resp = await c.post(
                f"{self._runs_api_base}/{owner}/{repo}/actions/workflows/{workflow}/dispatches",
                json={"ref": ref},
            )
        self._raise_for(resp, f"dispatching workflow {workflow} on {owner}/{repo}@{ref}")

    async def latest_run(self, repo: str, branch: str, repo_owner: str | None = None) -> dict | None:
        owner = repo_owner or APP_REPO_ORG
        async with self._client(internal=True) as c:
            resp = await c.get(
                f"{self._runs_api_base}/{owner}/{repo}/actions/runs",
                params={"branch": branch, "per_page": 1, "sort": "updated", "state": ""},
            )
        self._raise_for(resp, f"listing runs for {owner}/{repo}")
        runs = resp.json().get("runs") or []
        return runs[0] if runs else None

    async def branch_head_sha(
        self, repo: str, branch: str, repo_owner: str | None = None
    ) -> str | None:
        """Return the HEAD commit sha of `branch` on the internal Gitea repo."""
        owner = repo_owner or APP_REPO_ORG
        async with self._client(internal=True) as c:
            resp = await c.get(f"{self._runs_api_base}/{owner}/{repo}/branches/{branch}")
        if resp.status_code >= 400:
            return None
        return (resp.json().get("commit") or {}).get("id")


_gitops: GitopsClient | None = None


def _gitops_client() -> GitopsClient:
    global _gitops
    if _gitops is None:
        if not GITOPS_TOKEN:
            raise RuntimeError(
                "USERAPPS_GITOPS_TOKEN (or BRANCH_ENV_GITOPS_TOKEN) is not set; "
                "cannot commit to ai/k8s."
            )
        _gitops = GitopsClient()
    return _gitops


# ---------------------------------------------------------------------------
# In-cluster Kubernetes client (httpx + ServiceAccount token, read-only)
# ---------------------------------------------------------------------------
class ClusterClient:
    def __init__(self) -> None:
        # Prefer the kubelet-injected API service env (an IP, e.g. 10.43.0.1) so
        # reaching the API needs no DNS — kubernetes.default.svc resolution has
        # failed intermittently in-cluster ([Errno -2] Name or service not
        # known). Fall back to the DNS name only if the env is absent.
        host = os.getenv("KUBERNETES_SERVICE_HOST")
        port = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS") or os.getenv(
            "KUBERNETES_SERVICE_PORT", "443"
        )
        if host:
            # IPv6 literals need bracketing for the URL authority.
            host_part = f"[{host}]" if ":" in host else host
            self._base = f"https://{host_part}:{port}"
        else:
            self._base = "https://kubernetes.default.svc"
        self._token = os.getenv("K8S_SA_TOKEN")
        if not self._token:
            try:
                self._token = open(
                    "/var/run/secrets/kubernetes.io/serviceaccount/token"
                ).read().strip()
            except OSError:
                self._token = ""
        self._verify = (
            "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
            else False
        )

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def get(self, path: str) -> dict | None:
        if not self.available:
            return None
        async with httpx.AsyncClient(verify=self._verify, timeout=HTTP_TIMEOUT) as c:
            resp = await c.get(f"{self._base}{path}", headers=self._headers())
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"k8s GET {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def get_helmrelease(self, namespace: str, name: str) -> dict | None:
        return await self.get(
            f"/apis/helm.toolkit.fluxcd.io/v2/namespaces/{namespace}/helmreleases/{name}"
        )

    async def list_pods(self, namespace: str, label_selector: str) -> dict | None:
        return await self.get(
            f"/api/v1/namespaces/{namespace}/pods?labelSelector={label_selector}"
        )

    async def list_services(self, namespace: str, label_selector: str) -> dict | None:
        return await self.get(
            f"/api/v1/namespaces/{namespace}/services?labelSelector={label_selector}"
        )

    async def pod_log(self, namespace: str, pod: str, container: str, tail: int) -> str:
        if not self.available:
            return ""
        async with httpx.AsyncClient(verify=self._verify, timeout=HTTP_TIMEOUT) as c:
            resp = await c.get(
                f"{self._base}/api/v1/namespaces/{namespace}/pods/{pod}/log",
                params={"container": container, "tailLines": tail},
                headers=self._headers(),
            )
        return resp.text if resp.status_code < 400 else f"<log error HTTP {resp.status_code}>"

    async def scale(self, namespace: str, deployment: str, replicas: int) -> None:
        if not self.available:
            raise RuntimeError("no in-cluster SA token; cannot scale")
        async with httpx.AsyncClient(verify=self._verify, timeout=HTTP_TIMEOUT) as c:
            resp = await c.patch(
                f"{self._base}/apis/apps/v1/namespaces/{namespace}/deployments/{deployment}/scale",
                json={"spec": {"replicas": replicas}},
                headers={**self._headers(), "Content-Type": "application/strategic-merge-patch+json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"scale -> HTTP {resp.status_code}: {resp.text[:200]}")

    async def get_namespace(self, name: str) -> dict | None:
        return await self.get(f"/api/v1/namespaces/{name}")

    async def get_externalsecret(self, namespace: str, name: str) -> dict | None:
        return await self.get(
            f"/apis/external-secrets.io/v1/namespaces/{namespace}/externalsecrets/{name}"
        )

    async def get_job(self, namespace: str, name: str) -> dict | None:
        # Read-only: the kaniko Job is created by Flux from git, not by us. We
        # only poll its status to know when the build finished.
        return await self.get(f"/apis/batch/v1/namespaces/{namespace}/jobs/{name}")


_cluster: ClusterClient | None = None


def _cluster_client() -> ClusterClient:
    global _cluster
    if _cluster is None:
        _cluster = ClusterClient()
    return _cluster


# ---------------------------------------------------------------------------
# Manifest builders
# ---------------------------------------------------------------------------
def _app_path(slug: str, filename: str | None = None) -> str:
    base = f"{GITOPS_PATH}/{slug}"
    return f"{base}/{filename}" if filename else base


def build_namespace_yaml(slug: str) -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": slug,
                "labels": {
                    "managed-by": "druppie-module-deploy",
                    "druppie.io/user-app": "true",
                },
                "annotations": {"druppie.io/created-at": _utcnow_iso()},
            },
        },
        sort_keys=False,
    )


def build_gitrepository_yaml(slug: str, app_repo: str, branch: str) -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "source.toolkit.fluxcd.io/v1",
            "kind": "GitRepository",
            "metadata": {
                "name": f"user-app-{slug}",
                "namespace": "flux-system",
                "labels": {"druppie.io/user-app": slug},
            },
            "spec": {
                "interval": "1m",
                "ref": {"branch": branch},
                "secretRef": {"name": "flux-git-auth"},
                "url": app_repo,
            },
        },
        sort_keys=False,
    )


def build_helmrelease_yaml(
    slug: str, image_repo: str, image_tag: str, host: str, vault_path: str
) -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {
                "name": slug,
                "namespace": slug,
                "annotations": {
                    "druppie.io/user-app": "true",
                    "druppie.io/updated-at": _utcnow_iso(),
                },
            },
            "spec": {
                "interval": "10m",
                "releaseName": slug,
                "storageNamespace": slug,
                "targetNamespace": slug,
                "chart": {
                    "spec": {
                        "chart": f"./{CHART_PATH}",
                        "sourceRef": {
                            "kind": "GitRepository",
                            "name": f"user-app-{slug}",
                            "namespace": "flux-system",
                        },
                        "reconcileStrategy": "Revision",
                    }
                },
                "install": {"timeout": "10m", "remediation": {"retries": 3}},
                "upgrade": {
                    "timeout": "10m",
                    "cleanupOnFail": True,
                    "remediation": {"retries": 3},
                },
                "values": {
                    "image": {"repository": image_repo, "tag": image_tag},
                    "ingress": {"host": host},
                    "externalSecret": {"vaultPath": vault_path},
                },
            },
        },
        sort_keys=False,
    )


# ---------------------------------------------------------------------------
# Build-infra manifest builders (committed to git; Flux creates them)
# ---------------------------------------------------------------------------
def _build_ns(slug: str) -> str:
    """Per-app build namespace name (kept short for the 63-char DNS limit)."""
    return f"{slug}{BUILD_NS_SUFFIX}"[:63].rstrip("-")


def _job_name(slug: str, tag: str) -> str:
    """DNS-1123 Job name derived from slug+tag, capped at 63 chars."""
    name = re.sub(r"[^a-z0-9-]", "-", f"build-{slug}-{tag}".lower())
    name = re.sub(r"-+", "-", name)[:63]
    return name.strip("-")


def build_build_namespace_yaml(build_ns: str, slug: str) -> str:
    return yaml.safe_dump(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": build_ns,
                "labels": {
                    "managed-by": "druppie-module-deploy",
                    "druppie.io/user-app-build": slug,
                    # Explicit PSA profile so the namespace is not silently
                    # unenforced. kaniko runs as root but needs no privileged
                    # mode / caps, so `baseline` admits it (matches the app
                    # namespaces); it deliberately does NOT get `privileged`
                    # like the old DinD runner namespace.
                    "pod-security.kubernetes.io/enforce": "baseline",
                    "pod-security.kubernetes.io/warn": "baseline",
                },
            },
        },
        sort_keys=False,
    )


def build_harbor_push_externalsecret_yaml(build_ns: str) -> str:
    """dockerconfigjson synced from Vault ci/harbor (CI robot, push+pull).

    Mounted into the kaniko Job at /kaniko/.docker/config.json. The inner
    ``{{ }}`` are ESO template directives (not Helm) — this YAML is committed
    to ai/k8s verbatim, so no Helm escaping is needed.
    """
    return yaml.safe_dump(
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": HARBOR_PUSH_SECRET, "namespace": build_ns},
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {
                    "name": HARBOR_PUSH_SECRET,
                    "creationPolicy": "Owner",
                    "template": {
                        "type": "kubernetes.io/dockerconfigjson",
                        "data": {
                            ".dockerconfigjson": (
                                '{"auths":{"{{ .registry }}":{"username":"{{ .username }}",'
                                '"password":"{{ .password }}",'
                                '"auth":"{{ printf "%s:%s" .username .password | b64enc }}"}}}'
                            ),
                        },
                    },
                },
                "data": [
                    {"secretKey": "username", "remoteRef": {"key": VAULT_HARBOR_PATH, "property": "username"}},
                    {"secretKey": "password", "remoteRef": {"key": VAULT_HARBOR_PATH, "property": "password"}},
                    {"secretKey": "registry", "remoteRef": {"key": VAULT_HARBOR_PATH, "property": "registry"}},
                ],
            },
        },
        sort_keys=False,
    )


def build_git_auth_externalsecret_yaml(build_ns: str) -> str:
    """Gitea token synced from Vault ci/gitea; read only by the clone init-container.

    NOTE (§5.1 of the story): ci/gitea is the shared CI token (also has write to
    ai/k8s). It is mounted ONLY into the clone init-container — never the kaniko
    container that runs the untrusted Dockerfile — so untrusted build steps
    cannot read it. Harden to a read-only per-org deploy key when available.
    """
    return yaml.safe_dump(
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": GIT_AUTH_SECRET, "namespace": build_ns},
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {"name": GIT_AUTH_SECRET, "creationPolicy": "Owner"},
                "data": [
                    {"secretKey": "token", "remoteRef": {"key": VAULT_GITEA_PATH, "property": "token"}},
                ],
            },
        },
        sort_keys=False,
    )


def build_kaniko_job(
    build_ns: str,
    job_name: str,
    slug: str,
    clone_hostport: str,
    org: str,
    repo: str,
    branch: str,
    image_dest: str,
    cache_repo: str,
) -> dict:
    """kaniko build Job: clone app source (init) → build+push (kaniko container).

    Committed to git and created by Flux (never imperatively). The git token is
    injected at runtime as $GIT_TOKEN (from GIT_AUTH_SECRET) so it never appears
    in the manifest committed anywhere. kaniko gets the Harbor dockerconfig via
    the mounted HARBOR_PUSH_SECRET — no daemon, no privilege.

    NOTE: no ttlSecondsAfterFinished. Flux owns this object's lifecycle — a TTL
    delete would leave the git manifest present, so Flux would re-create (and
    re-run) the build on its next reconcile. A finished Job simply lingers until
    the next build's manifest (a new name carrying the new tag) supersedes it,
    at which point Flux prunes the old one.
    """
    clone_url = f"http://{GIT_CLONE_USER}:${{GIT_TOKEN}}@{clone_hostport}/{org}/{repo}.git"
    clone_script = (
        "set -eu\n"
        f'git clone --depth 1 --branch "{branch}" "{clone_url}" /src\n'
        'echo "cloned $(git -C /src rev-parse --short HEAD)"\n'
    )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": build_ns,
            "labels": {
                "managed-by": "druppie-module-deploy",
                "druppie.io/user-app-build": slug,
            },
        },
        "spec": {
            "backoffLimit": 0,   # a build failure is terminal — don't retry blindly
            "activeDeadlineSeconds": BUILD_JOB_DEADLINE,   # hard server-side cap
            "template": {
                "metadata": {
                    "labels": {"druppie.io/user-app-build": slug, "job-name": job_name},
                },
                "spec": {
                    "restartPolicy": "Never",
                    "initContainers": [
                        {
                            "name": "clone",
                            "image": GIT_CLONE_IMAGE,
                            "command": ["/bin/sh", "-c"],
                            "args": [clone_script],
                            "env": [
                                {
                                    "name": "GIT_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": GIT_AUTH_SECRET, "key": "token"}
                                    },
                                }
                            ],
                            "volumeMounts": [{"name": "src", "mountPath": "/src"}],
                        }
                    ],
                    "containers": [
                        {
                            "name": "kaniko",
                            "image": KANIKO_IMAGE,
                            "args": [
                                "--context=dir:///src",
                                "--dockerfile=Dockerfile",
                                f"--destination={image_dest}",
                                "--cache=true",
                                f"--cache-repo={cache_repo}",
                                "--skip-tls-verify-pull",
                                "--skip-tls-verify-push",
                            ],
                            # kaniko is memory-hungry; requests keep it schedulable
                            # and satisfy any namespace LimitRange/quota, limits
                            # cap a runaway build.
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "512Mi"},
                                "limits": {"cpu": "2", "memory": "4Gi"},
                            },
                            "volumeMounts": [
                                {"name": "src", "mountPath": "/src"},
                                {"name": "docker-config", "mountPath": "/kaniko/.docker"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "src", "emptyDir": {}},
                        {
                            "name": "docker-config",
                            "secret": {
                                "secretName": HARBOR_PUSH_SECRET,
                                "items": [{"key": ".dockerconfigjson", "path": "config.json"}],
                            },
                        },
                    ],
                },
            },
        },
    }


def _hostport(url: str) -> str:
    """Strip scheme (and trailing slash) from a URL → 'host:port'."""
    return re.sub(r"^\w+://", "", url).rstrip("/")


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------
async def _wait_namespace(cc: "ClusterClient", name: str, timeout: int) -> bool:
    """True once the namespace exists (Flux created it)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await cc.get_namespace(name):
            return True
        await asyncio.sleep(3)
    return False


async def _wait_externalsecret_ready(
    cc: "ClusterClient", namespace: str, name: str, timeout: int
) -> bool:
    """True once the ExternalSecret reports Ready=True (its target Secret synced)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        es = await cc.get_externalsecret(namespace, name)
        if es:
            conds = (es.get("status") or {}).get("conditions") or []
            if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds):
                return True
        await asyncio.sleep(3)
    return False


async def _wait_job(
    cc: "ClusterClient", namespace: str, name: str, timeout: int
) -> tuple[bool, str]:
    """Wait for the kaniko Job to succeed or fail. Returns (ok, detail)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        job = await cc.get_job(namespace, name)
        status = (job or {}).get("status") or {}
        if status.get("succeeded"):
            return True, ""
        if status.get("failed"):
            conds = status.get("conditions") or []
            reason = next(
                (c.get("message") or c.get("reason") for c in conds if c.get("type") == "Failed"),
                "build Job failed",
            )
            return False, f"{reason}\n{await _build_pod_logs(cc, namespace, name)}"
        await asyncio.sleep(5)
    return False, f"build did not complete within {timeout}s\n{await _build_pod_logs(cc, namespace, name)}"


async def _build_pod_logs(cc: "ClusterClient", namespace: str, job_name: str) -> str:
    """Best-effort tail of the kaniko container log for failure diagnostics."""
    try:
        pods = await cc.list_pods(namespace, f"job-name={job_name}")
        items = (pods or {}).get("items") or []
        if not items:
            return ""
        pod = items[-1]["metadata"]["name"]
        return await cc.pod_log(namespace, pod, "kaniko", 40)
    except Exception:  # noqa: BLE001
        return ""


async def _wait_helmrelease_ready(namespace: str, name: str) -> bool:
    """True once the HelmRelease reports Ready=True (or timeout)."""
    cc = _cluster_client()
    if not cc.available:
        return False
    deadline = asyncio.get_event_loop().time() + ROLLOUT_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        hr = await cc.get_helmrelease(namespace, name)
        if hr:
            conds = (hr.get("status") or {}).get("conditions") or []
            if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds):
                return True
        await asyncio.sleep(5)
    return False


async def _incluster_health_url(cc: "ClusterClient", slug: str) -> str | None:
    """Resolve the app Service's in-cluster ClusterIP:port health target.

    k8s-native: prefer the Service ClusterIP over the public FQDN so the health
    gate does not depend on the public DNS name resolving *and* hairpinning back
    into the ingress from inside the cluster. On split-horizon / no-hairpin
    setups that round-trip fails, making a perfectly healthy app look like a
    timeout. Talking straight to the ClusterIP proves the app is serving.

    Returns None if the cluster is unreachable or no usable Service exists yet.
    """
    if not cc.available:
        return None
    try:
        svcs = await cc.list_services(
            slug,
            f"app.kubernetes.io/instance={slug},app.kubernetes.io/component=app",
        )
    except Exception:
        return None
    for s in (svcs or {}).get("items") or []:
        spec = s.get("spec") or {}
        cip = spec.get("clusterIP")
        if not cip or cip == "None":  # skip headless Services (no ClusterIP)
            continue
        ports = spec.get("ports") or []
        port = next((p.get("port") for p in ports if p.get("name") == "http"), None)
        if port is None and ports:
            port = ports[0].get("port")
        if port:
            return f"http://{cip}:{port}"
    return None


async def _health_gate(
    url: str, timeout: int, path: str = "/health", slug: str | None = None
) -> bool:
    """Poll the app until it answers 200 on `path` (or timeout).

    k8s-native: probe the in-cluster Service (ClusterIP) first so the gate
    proves the app is actually serving without relying on the public FQDN
    resolving + hairpinning back into the cluster. The public ingress URL is
    still probed as a fallback (and confirms external reachability where the
    cluster does allow hairpin).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    public_target = url.rstrip("/") + path
    cc = _cluster_client()
    async with httpx.AsyncClient(verify=False, timeout=10.0) as c:
        while asyncio.get_event_loop().time() < deadline:
            incluster = await _incluster_health_url(cc, slug) if slug else None
            targets = []
            if incluster:
                targets.append(incluster.rstrip("/") + path)
            targets.append(public_target)
            for target in targets:
                try:
                    r = await c.get(target)
                    if r.status_code == 200:
                        return True
                except Exception:
                    pass
            await asyncio.sleep(3)
    return False


def _hr_ready(hr: dict | None) -> tuple[bool, str]:
    if not hr:
        return False, "HelmRelease not found"
    conds = (hr.get("status") or {}).get("conditions") or []
    ready = next((c for c in conds if c.get("type") == "Ready"), {})
    return ready.get("status") == "True", ready.get("message", "")


# ---------------------------------------------------------------------------
# Public API (names match the dispatch in tools.py)
# ---------------------------------------------------------------------------
async def _compute_tag(repo: str, branch: str, org: str) -> str:
    """Image tag = <branch-slug>-<utc-ts>-<short-sha> (mirrors the CI scheme)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    branch_slug = re.sub(r"[^A-Za-z0-9._-]", "-", branch)
    try:
        sha = await _gitops_client().branch_head_sha(repo, branch, org)
    except Exception:  # noqa: BLE001
        sha = None
    return f"{branch_slug}-{ts}-{(sha or 'unknown')[:8]}"


async def _ensure_build_infra(g: GitopsClient, slug: str, build_ns: str) -> None:
    """Commit (create/update) the build namespace + Harbor-push + git-auth ESO.

    These are stable, declarative resources — Flux owns their lifecycle. One
    atomic commit under clusters/user-apps/<slug>/build/.
    """
    specs = [
        (_app_path(slug, "build/namespace.yaml"), build_build_namespace_yaml(build_ns, slug)),
        (_app_path(slug, "build/harbor-push-externalsecret.yaml"),
         build_harbor_push_externalsecret_yaml(build_ns)),
        (_app_path(slug, "build/git-auth-externalsecret.yaml"),
         build_git_auth_externalsecret_yaml(build_ns)),
    ]
    files: list[dict] = []
    for path, content in specs:
        existing = await g.get_file(path)
        files.append(
            {
                "operation": "create" if existing is None else "update",
                "path": path,
                "content": content,
                **({"sha": existing[1]} if existing else {}),
            }
        )
    await g.change_files(f"user-app: build infra for {slug}", files)


async def _commit_build_job(g: GitopsClient, slug: str, job: dict) -> None:
    """Commit (create/update) the kaniko Job manifest; Flux creates the Job.

    A single file build/job.yaml whose object name carries the image tag. On a
    new build the name changes, so Flux prunes the previous Job and creates the
    new one — no imperative create/delete from module-deploy.
    """
    path = _app_path(slug, "build/job.yaml")
    content = yaml.safe_dump(job, sort_keys=False)
    existing = await g.get_file(path)
    await g.change_files(
        f"user-app: build {slug} @ {job['metadata']['name']}",
        [
            {
                "operation": "create" if existing is None else "update",
                "path": path,
                "content": content,
                **({"sha": existing[1]} if existing else {}),
            }
        ],
    )


async def k8s_build(
    repo_name: str,
    branch: str = "main",
    repo_owner: str | None = None,
    session_id: str | None = None,
    slug: str | None = None,
    image_tag: str | None = None,
) -> dict:
    """Build the app image via a kaniko Job (daemonless, k8s-native, git-driven).

    Commits the build namespace + ExternalSecrets AND the kaniko Job to git;
    Flux creates them all. module-deploy only READS status (namespace, ESO,
    Job) — it never creates or deletes cluster objects. Returns the exact tag it
    built so the caller can pin the HelmRelease to it.
    """
    org = repo_owner or APP_REPO_ORG
    repo = repo_name
    slug = slug or _slugify(repo)
    build_ns = _build_ns(slug)
    image_repo = f"{HARBOR_REGISTRY}/{HARBOR_PROJECT}/{repo.lower()}"
    g = _gitops_client()
    cc = _cluster_client()

    # We don't write to the cluster, but we must READ build status to gate the
    # deploy — without the SA token we can't observe it, so fail fast+clearly.
    if not cc.available:
        return {"success": False, "error": "no in-cluster SA token; cannot observe build status"}

    tag = image_tag or await _compute_tag(repo, branch, org)
    image_dest = f"{image_repo}:{tag}"
    cache_repo = f"{image_repo}/cache"
    job_name = _job_name(slug, tag)
    job = build_kaniko_job(
        build_ns, job_name, slug, _hostport(APP_REPO_URL), org, repo, branch, image_dest, cache_repo
    )

    # 1. Commit the build namespace + push/clone credentials (Flux creates them).
    try:
        await _ensure_build_infra(g, slug, build_ns)
    except RuntimeError as e:
        return {"success": False, "error": f"committing build infra failed: {e}"}

    # 2. Wait for Flux to reconcile the namespace + ESO to sync BEFORE the Job
    #    pod tries to mount the secrets. A clear error here usually means Vault
    #    is missing a declared key (see below).
    if not await _wait_namespace(cc, build_ns, BUILD_INFRA_TIMEOUT):
        return {"success": False, "error": f"build namespace '{build_ns}' not created by Flux in time"}
    for secret in (HARBOR_PUSH_SECRET, GIT_AUTH_SECRET):
        if not await _wait_externalsecret_ready(cc, build_ns, secret, BUILD_INFRA_TIMEOUT):
            return {
                "success": False,
                "error": (
                    f"ExternalSecret '{secret}' not Ready in '{build_ns}'. Check that Vault "
                    f"has every declared key — {VAULT_HARBOR_PATH}: username/password/registry; "
                    f"{VAULT_GITEA_PATH}: token (ESO stalls if any one is missing)."
                ),
            }

    # 3. Commit the kaniko Job to git; Flux creates it. We only poll its status.
    try:
        await _commit_build_job(g, slug, job)
    except RuntimeError as e:
        return {"success": False, "error": f"committing build Job failed: {e}"}

    ok, detail = await _wait_job(cc, build_ns, job_name, BUILD_POLL_TIMEOUT)
    if ok:
        return {
            "success": True,
            "image_name": image_repo,
            "image_tag": tag,
            "image": image_dest,
            "message": f"kaniko build succeeded ({image_dest})",
            "session_id": session_id,
        }
    return {
        "success": False,
        "error": f"kaniko build failed: {detail}",
        "image_tag": tag,
        "session_id": session_id,
    }


async def k8s_deploy(
    repo_name: str,
    branch: str = "main",
    repo_owner: str | None = None,
    compose_project_name: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    health_path: str = "/health",
    health_timeout: int = HEALTH_TIMEOUT_DEFAULT,
) -> dict:
    """Deploy a user app via GitOps: build the image, commit footprint, roll out.

    Order matters: build FIRST (kaniko Job) so we know the exact image tag, then
    commit the HelmRelease already pinned to it — the app never reconciles
    against a tag that isn't in Harbor yet.
    """
    org = repo_owner or APP_REPO_ORG
    slug = _slugify(compose_project_name or repo_name)
    repo = repo_name
    app_repo = f"{APP_REPO_URL.rstrip('/')}/{org}/{repo}.git"
    host = f"{slug}-apps.{APPS_DOMAIN}"
    image_repo = f"{HARBOR_REGISTRY}/{HARBOR_PROJECT}/{repo.lower()}"
    vault_path = f"apps/{slug}/db"
    g = _gitops_client()

    # 1. Build the image (kaniko Job). Yields the exact tag to pin the HR to.
    build = await k8s_build(
        repo_name=repo, branch=branch, repo_owner=org, session_id=session_id, slug=slug
    )
    if not build.get("success"):
        return {
            "success": False,
            "slug": slug,
            "url": f"https://{host}",
            "error": f"build failed: {build.get('error')}",
        }
    image_tag = build["image_tag"]

    # 2. Commit (create or update) the GitOps footprint, pinned to the built tag.
    #    Detect existing files via get_file (None -> create, else update w/ sha).
    ns_file = await g.get_file(_app_path(slug, "namespace.yaml"))
    gitrepo_existing = await g.get_file(_app_path(slug, "gitrepository.yaml"))
    hr_existing = await g.get_file(_app_path(slug, "helmrelease.yaml"))

    files: list[dict] = [
        {
            "operation": "create" if ns_file is None else "update",
            "path": _app_path(slug, "namespace.yaml"),
            "content": build_namespace_yaml(slug),
            **({"sha": ns_file[1]} if ns_file else {}),
        },
        {
            "operation": "create" if gitrepo_existing is None else "update",
            "path": _app_path(slug, "gitrepository.yaml"),
            "content": build_gitrepository_yaml(slug, app_repo, branch),
            **({"sha": gitrepo_existing[1]} if gitrepo_existing else {}),
        },
        {
            "operation": "create" if hr_existing is None else "update",
            "path": _app_path(slug, "helmrelease.yaml"),
            "content": build_helmrelease_yaml(slug, image_repo, image_tag, host, vault_path),
            **({"sha": hr_existing[1]} if hr_existing else {}),
        },
    ]
    await g.change_files(f"user-app: deploy {slug} @ {image_tag} (repo {org}/{repo}@{branch})", files)

    # 3. Wait for Flux to roll the new tag out.
    rolled = await _wait_helmrelease_ready(slug, slug)
    # 4. Health-gate: in-cluster Service (ClusterIP) first, public URL as fallback.
    healthy = await _health_gate(f"https://{host}", health_timeout, health_path, slug=slug)

    return {
        "success": healthy,
        "slug": slug,
        "url": f"https://{host}",
        "namespace": slug,
        "compose_project_name": slug,
        "image_tag": image_tag,
        "helmrelease_ready": rolled,
        "health_check": "healthy" if healthy else "timeout",
        "project_id": project_id,
        "session_id": session_id,
        "labels": {"managed-by": "druppie-module-deploy", "druppie.io/user-app": slug},
    }


async def k8s_teardown(compose_project_name: str) -> dict:
    """Teardown: delete the app's ai/k8s subdir. Flux prune removes the namespace."""
    slug = _slugify(compose_project_name)
    g = _gitops_client()
    # Top-level app manifests + the build/ subdir (namespace + ESOs). Deleting
    # both lets Flux prune the app namespace AND the build namespace.
    entries = await g.list_dir(_app_path(slug)) or []
    entries += await g.list_dir(_app_path(slug, "build")) or []
    deletes = [
        {"operation": "delete", "path": e["path"], "sha": e["sha"]}
        for e in entries
        if e.get("type") == "file"
    ]
    if not deletes:
        return {"success": False, "error": f"no user-app found for slug '{slug}'"}
    await g.change_files(f"user-app: teardown {slug}", deletes)
    return {"success": True, "removed": [d["path"] for d in deletes], "slug": slug}


async def k8s_stop(container_name: str) -> dict:
    """Scale the app Deployment to 0 (in its per-app namespace)."""
    slug = _slugify(container_name)
    try:
        await _cluster_client().scale(slug, slug, 0)
        return {"success": True, "container_name": slug, "status": "stopped"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def k8s_logs(container_name: str, tail: int = 100) -> dict:
    """Read logs from the app's first pod (in-cluster, read-only)."""
    slug = _slugify(container_name)
    cc = _cluster_client()
    if not cc.available:
        return {"success": False, "error": "no in-cluster SA token available"}
    try:
        pods = await cc.list_pods(slug, "app.kubernetes.io/instance=%s" % slug)
        items = (pods or {}).get("items") if pods else []
        if not items:
            return {"success": False, "error": f"no pods found in ns '{slug}'"}
        pod = items[0]["metadata"]["name"]
        container = (items[0]["spec"]["containers"][0]["name"]
                     if items[0]["spec"]["containers"] else "app")
        logs = await cc.pod_log(slug, pod, container, tail)
        return {"success": True, "container_name": slug, "logs": logs}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def k8s_list_apps(
    session_id: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """List deployed user-apps by scanning ai/k8s clusters/user-apps/*."""
    g = _gitops_client()
    try:
        entries = await g.list_dir(GITOPS_PATH) or []
    except Exception as e:
        logger.warning("list user-apps failed: %s", e)
        return []
    result = []
    cc = _cluster_client()
    for e in entries:
        if e.get("type") != "dir":
            continue
        slug = e["name"]
        ready, msg = (False, "")
        if cc.available:
            try:
                ready, msg = _hr_ready(await cc.get_helmrelease(slug, slug))
            except Exception:
                pass
        result.append(
            {
                "name": slug,
                "namespace": slug,
                "url": f"https://{slug}-apps.{APPS_DOMAIN}",
                "ready": ready,
                "status_message": msg,
            }
        )
    return result


async def k8s_inspect(container_name: str) -> dict:
    """Inspect a deployed app: status, URL, labels, pod info."""
    slug = _slugify(container_name)
    cc = _cluster_client()
    if not cc.available:
        return {"success": False, "error": "no in-cluster SA token available"}

    try:
        hr = await cc.get_helmrelease(slug, slug)
        if not hr:
            return {"success": False, "error": f"app '{slug}' not found (no HelmRelease)"}

        status = hr.get("status", {})
        conditions = status.get("conditions", [])
        ready = any(
            c.get("status") == "True" and c.get("type") == "Ready"
            for c in conditions
        )

        pods = await cc.list_pods(slug, f"app.kubernetes.io/instance={slug}")
        items = (pods or {}).get("items") if pods else []

        pod_info = []
        for p in items:
            pod_info.append({
                "name": p["metadata"]["name"],
                "status": p.get("status", {}).get("phase", "Unknown"),
                "ready": all(
                    c.get("ready") for c in p.get("status", {}).get("containerStatuses", [])
                ) if p.get("status", {}).get("containerStatuses") else False,
            })

        return {
            "success": True,
            "name": slug,
            "namespace": slug,
            "url": f"https://{slug}-apps.{APPS_DOMAIN}",
            "ready": ready,
            "helmrelease_status": {
                "reconciled_at": status.get("lastAppliedRevision"),
                "revision": status.get("lastAppliedRevision"),
            },
            "pods": pod_info,
            "labels": {
                "managed-by": "druppie-module-deploy",
                "druppie.io/user-app": "true",
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
