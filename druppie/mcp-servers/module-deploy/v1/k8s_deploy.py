"""
K8s Deploy Manager — GitOps-native replacement for Docker operations.

Used by module-deploy when DRUPPIE_SANDBOX_MODE=k8s.

Model: a generated app ships its OWN Helm chart (chart/) and its OWN Gitea
Actions CI. Deploying it means committing a Flux GitRepository + HelmRelease to
ai/k8s (clusters/user-apps/<slug>/) and letting Flux reconcile — identical to how
Druppie deploys itself. No Docker daemon, no Kaniko, no imperative kubectl apply.

  build        → dispatch the app's .gitea/workflows/build.yaml + poll the run
  compose_up   → commit namespace+gitrepository+helmrelease, (re)build, wait for
                 Flux HelmRelease Ready, then health-gate the ingress URL (300s)
  compose_down → delete the app's ai/k8s subdir (Flux prune tears down the ns)
  logs         → read the app pod's logs (in-cluster SA token, read-only)
  list         → list deployed user-apps (namespaces labelled managed-by)
  stop         → scale the app Deployment to 0
  inspect/exec/volumes → not supported in GitOps mode (explicit error)

All cluster reads use httpx + the pod ServiceAccount token (no `kubernetes`
python dependency). All GitOps writes use the Gitea batch contents API
(POST /repos/{repo}/contents — one atomic commit).
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
APP_REPO_ORG = os.getenv("USERAPPS_APP_REPO_ORG", "ai")

BUILD_POLL_TIMEOUT = int(os.getenv("USERAPPS_BUILD_TIMEOUT", "1200"))   # 20m
ROLLOUT_TIMEOUT = int(os.getenv("USERAPPS_ROLLOUT_TIMEOUT", "600"))     # 10m
HEALTH_TIMEOUT_DEFAULT = 300
HTTP_TIMEOUT = 30.0

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
        self._runs_api = f"{base}/api/v1/repos/{APP_REPO_ORG}"  # /<repo>/actions...
        self._branch = GITOPS_BRANCH
        self._headers = {"Authorization": f"token {GITOPS_TOKEN}"} if GITOPS_TOKEN else {}
        self._verify: Any = GITOPS_CA if GITOPS_CA else True

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self._headers, verify=self._verify, timeout=HTTP_TIMEOUT)

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
    async def dispatch_workflow(self, repo: str, workflow: str, ref: str) -> None:
        async with self._client() as c:
            resp = await c.post(
                f"{self._runs_api}/{repo}/actions/workflows/{workflow}/dispatches",
                json={"ref": ref},
            )
        self._raise_for(resp, f"dispatching workflow {workflow} on {APP_REPO_ORG}/{repo}@{ref}")

    async def latest_run(self, repo: str, branch: str) -> dict | None:
        async with self._client() as c:
            resp = await c.get(
                f"{self._runs_api}/{repo}/actions/runs",
                params={"branch": branch, "per_page": 1, "sort": "updated", "state": ""},
            )
        self._raise_for(resp, f"listing runs for {APP_REPO_ORG}/{repo}")
        runs = resp.json().get("runs") or []
        return runs[0] if runs else None


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
# Polling helpers
# ---------------------------------------------------------------------------
async def _poll_build(client: GitopsClient, repo: str, branch: str) -> dict:
    """Wait for the latest workflow run on `branch` to complete. Returns the run."""
    deadline = asyncio.get_event_loop().time() + BUILD_POLL_TIMEOUT
    # The run registers a moment after dispatch; wait for it to appear.
    run: dict | None = None
    while asyncio.get_event_loop().time() < deadline:
        run = await client.latest_run(repo, branch)
        if run and run.get("status") == "completed":
            return run
        await asyncio.sleep(5)
    if run is None:
        return {"status": "unknown", "conclusion": "no_run"}
    return run


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


async def _health_gate(url: str, timeout: int, path: str = "/health") -> bool:
    """Poll the ingress URL until it answers 200 (or timeout)."""
    deadline = asyncio.get_event_loop().time() + timeout
    target = url.rstrip("/") + path
    async with httpx.AsyncClient(verify=False, timeout=10.0) as c:
        while asyncio.get_event_loop().time() < deadline:
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
async def k8s_build(
    repo_name: str,
    branch: str = "main",
    repo_owner: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Dispatch the app's CI workflow and wait for it to finish."""
    org = repo_owner or APP_REPO_ORG
    repo = repo_name
    g = _gitops_client()
    try:
        await g.dispatch_workflow(repo, "build.yaml", branch)
    except RuntimeError as e:
        return {"success": False, "error": f"workflow dispatch failed: {e}"}

    run = await _poll_build(g, repo, branch)
    status, conclusion = run.get("status"), run.get("conclusion")
    image_repo = f"{HARBOR_REGISTRY}/{HARBOR_PROJECT}/{repo.lower()}"
    if status == "completed" and conclusion == "success":
        return {
            "success": True,
            "image_name": image_repo,
            "message": f"Build succeeded ({run.get('html_url', '')})",
            "session_id": session_id,
        }
    return {
        "success": False,
        "error": f"build did not succeed (status={status}, conclusion={conclusion})",
        "run_url": run.get("html_url"),
        "session_id": session_id,
    }


async def k8s_compose_up(
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
    """Deploy a user app via GitOps: commit footprint, build, wait for rollout."""
    org = repo_owner or APP_REPO_ORG
    slug = _slugify(compose_project_name or repo_name)
    repo = repo_name
    app_repo = f"{GITOPS_URL.rstrip('/')}/{org}/{repo}.git"
    host = f"{slug}-apps.{APPS_DOMAIN}"
    image_repo = f"{HARBOR_REGISTRY}/{HARBOR_PROJECT}/{repo.lower()}"
    vault_path = f"apps/{slug}/db"
    g = _gitops_client()

    # 1. Commit (create or update) the GitOps footprint. Detect existing files
    #    via get_file (None -> create, else update with sha).
    ns_file = await g.get_file(_app_path(slug, "namespace.yaml"))
    gitrepo_existing = await g.get_file(_app_path(slug, "gitrepository.yaml"))
    hr_existing = await g.get_file(_app_path(slug, "helmrelease.yaml"))
    image_tag = ""  # left blank on commit; the CI bumps it after building (Option A)

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
    await g.change_files(f"user-app: deploy {slug} (repo {org}/{repo}@{branch})", files)

    # 2. Trigger a fresh build and wait for it (CI bumps image.tag in the HR).
    build = await k8s_build(repo_name=repo, branch=branch, repo_owner=org, session_id=session_id)
    if not build.get("success"):
        return {
            "success": False,
            "slug": slug,
            "url": f"https://{host}",
            "error": f"build failed: {build.get('error')}",
        }

    # 3. Wait for Flux to roll the new tag out.
    rolled = await _wait_helmrelease_ready(slug, slug)
    # 4. Health-gate the ingress URL.
    healthy = await _health_gate(f"https://{host}", health_timeout, health_path)

    return {
        "success": healthy,
        "slug": slug,
        "url": f"https://{host}",
        "namespace": slug,
        "compose_project_name": slug,
        "helmrelease_ready": rolled,
        "health_check": "healthy" if healthy else "timeout",
        "project_id": project_id,
        "session_id": session_id,
        "labels": {"managed-by": "druppie-module-deploy", "druppie.io/user-app": slug},
    }


async def k8s_compose_down(compose_project_name: str) -> dict:
    """Teardown: delete the app's ai/k8s subdir. Flux prune removes the namespace."""
    slug = _slugify(compose_project_name)
    g = _gitops_client()
    entries = await g.list_dir(_app_path(slug)) or []
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


async def k8s_remove(container_name: str) -> dict:
    """Remove = teardown via GitOps (same as compose_down)."""
    return await k8s_compose_down(container_name)


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


async def k8s_list_containers(
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
    return {
        "success": False,
        "error": (
            "'inspect' is not supported in GitOps/K8s mode. Use 'logs' or "
            "'list_containers' for status."
        ),
    }


async def k8s_exec_command(container_name: str, command: str) -> dict:
    return {
        "success": False,
        "error": "'exec' is not supported in GitOps/K8s mode (apps are deployed, not interactive).",
    }


async def k8s_list_volumes() -> dict:
    return {
        "success": False,
        "error": (
            "'list_volumes' is not supported in GitOps/K8s mode. PVCs are managed "
            "by the app Helm chart (longhorn-branch-env, Delete reclaim)."
        ),
    }
