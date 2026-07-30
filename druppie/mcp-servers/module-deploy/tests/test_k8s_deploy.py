"""Tests for module-deploy K8s deploy path (GitOps model).

Covers:
  - _slugify
  - manifest builders (namespace / gitrepository / helmrelease)
  - build-infra manifest builders (build namespace / Harbor-push + git-auth
    ExternalSecrets / kaniko Job) + _job_name / _build_ns naming rules
  - k8s_build: commits build infra to git, then create -> poll -> delete a
    kaniko Job, returning the exact image tag it built
  - k8s_deploy: builds first (kaniko Job), then commits namespace+gitrepository+
    helmrelease pinned to that tag, waits for rollout + health gate
  - k8s_teardown: deletes the app subdir incl. build/ via list_dir -> delete ops
  - k8s_inspect: reports a clear error when no in-cluster SA token is available

Run:  python druppie/mcp-servers/module-deploy/tests/test_k8s_deploy.py
   or pytest druppie/mcp-servers/module-deploy/tests/test_k8s_deploy.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Make `import k8s_deploy` resolve to module-deploy/v1/k8s_deploy.py.
_V1 = Path(__file__).resolve().parents[1] / "v1"
sys.path.insert(0, str(_V1))
import k8s_deploy as kd  # noqa: E402
import yaml  # noqa: E402


class FakeGitops:
    """In-memory stand-in for GitopsClient (no network)."""

    def __init__(self, existing: dict[str, tuple[str, str]] | None = None) -> None:
        # path -> (content, sha); only "existing" files appear here.
        self.files = dict(existing or {})
        self.committed: list[dict] = []
        self.dispatched: list[tuple[str, str, str]] = []
        self._counter = 0

    async def get_file(self, path: str):
        return self.files.get(path)  # None if absent -> "create"

    async def list_dir(self, path: str):
        # Path-aware: the build/ subdir holds the build namespace + 2 ESOs; the
        # top-level dir holds the app manifests.
        if path.endswith("/build"):
            return [
                {"type": "file", "path": f"{path}/namespace.yaml", "sha": "b1"},
                {"type": "file", "path": f"{path}/harbor-push-externalsecret.yaml", "sha": "b2"},
                {"type": "file", "path": f"{path}/git-auth-externalsecret.yaml", "sha": "b3"},
            ]
        return [
            {"type": "file", "path": f"{path}/namespace.yaml", "sha": "s1"},
            {"type": "file", "path": f"{path}/helmrelease.yaml", "sha": "s2"},
        ]

    async def change_files(self, message: str, files: list[dict]) -> None:
        self.committed.append({"message": message, "files": files})

    async def branch_head_sha(self, repo: str, branch: str, repo_owner=None):
        return "abcdef1234567890"

    async def dispatch_workflow(self, repo: str, workflow: str, ref: str,
                                repo_owner: str | None = None) -> None:
        self.dispatched.append((repo, workflow, ref))

    async def latest_run(self, repo: str, branch: str):
        return {"status": "completed", "conclusion": "success", "html_url": "http://run/1"}


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(kd._slugify("Todo-App"), "todo-app")

    def test_collapses_and_trims(self):
        self.assertEqual(kd._slugify("  My__Cool!! App  "), "my-cool-app")

    def test_strips_leading_trailing_dash(self):
        self.assertEqual(kd._slugify("--foo--"), "foo")


class TestManifestBuilders(unittest.TestCase):
    def test_namespace(self):
        ns = yaml.safe_load(kd.build_namespace_yaml("todo"))
        self.assertEqual(ns["kind"], "Namespace")
        self.assertEqual(ns["metadata"]["name"], "todo")
        self.assertEqual(ns["metadata"]["labels"]["managed-by"], "druppie-module-deploy")

    def test_gitrepository(self):
        gr = yaml.safe_load(kd.build_gitrepository_yaml("todo", "https://x/ai/todo.git", "main"))
        self.assertEqual(gr["kind"], "GitRepository")
        self.assertEqual(gr["metadata"]["name"], "user-app-todo")
        self.assertEqual(gr["metadata"]["namespace"], "flux-system")
        self.assertEqual(gr["spec"]["ref"]["branch"], "main")
        self.assertEqual(gr["spec"]["url"], "https://x/ai/todo.git")
        self.assertEqual(gr["spec"]["secretRef"]["name"], "flux-git-auth")

    def test_helmrelease(self):
        hr = yaml.safe_load(
            kd.build_helmrelease_yaml(
                "todo", "harbor.rijnland.dev/druppie/todo", "", "todo-apps.rijnland.dev", "apps/todo/db"
            )
        )
        self.assertEqual(hr["kind"], "HelmRelease")
        self.assertEqual(hr["metadata"]["name"], "todo")
        self.assertEqual(hr["metadata"]["namespace"], "todo")
        self.assertEqual(hr["spec"]["releaseName"], "todo")
        self.assertEqual(hr["spec"]["targetNamespace"], "todo")
        self.assertEqual(hr["spec"]["chart"]["spec"]["chart"], "./chart")
        self.assertEqual(hr["spec"]["chart"]["spec"]["sourceRef"]["name"], "user-app-todo")
        self.assertEqual(hr["spec"]["values"]["ingress"]["host"], "todo-apps.rijnland.dev")
        self.assertEqual(hr["spec"]["values"]["externalSecret"]["vaultPath"], "apps/todo/db")


class TestComposeUp(unittest.TestCase):
    # k8s_deploy builds first (kaniko Job) then commits the footprint pinned to
    # the built tag. The build is exercised in TestBuild; here we mock k8s_build
    # so these tests stay focused on the commit/rollout/health-gate behaviour.
    _TAG = "main-20260101-abcdef12"

    def _build_ok(self):
        return AsyncMock(return_value={
            "success": True,
            "image_tag": self._TAG,
            "image_name": "harbor.rijnland.dev/druppie/todo-app",
            "image": f"harbor.rijnland.dev/druppie/todo-app:{self._TAG}",
        })

    def test_deploys_new_app_commits_three_files(self):
        fake = FakeGitops(existing={})  # nothing exists -> all "create"
        kd._gitops = fake
        with patch.object(kd, "k8s_build", new=self._build_ok()), \
             patch.object(kd, "_wait_helmrelease_ready", new=AsyncMock(return_value=True)), \
             patch.object(kd, "_health_gate", new=AsyncMock(return_value=True)):
            result = asyncio.run(
                kd.k8s_deploy(repo_name="todo-app", branch="main", compose_project_name="todo-app")
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["slug"], "todo-app")
        self.assertEqual(result["url"], "https://todo-app-apps.rijnland.dev")
        self.assertEqual(result["health_check"], "healthy")
        self.assertEqual(result["image_tag"], self._TAG)

        # Exactly one atomic commit with 3 create operations, pinned to the tag.
        self.assertEqual(len(fake.committed), 1)
        commit = fake.committed[0]
        self.assertIn(self._TAG, commit["message"])  # HR is pinned to the built tag
        ops = commit["files"]
        self.assertEqual([o["operation"] for o in ops], ["create", "create", "create"])
        paths = [o["path"] for o in ops]
        self.assertTrue(any(p.endswith("todo-app/namespace.yaml") for p in paths))
        self.assertTrue(any(p.endswith("todo-app/gitrepository.yaml") for p in paths))
        self.assertTrue(any(p.endswith("todo-app/helmrelease.yaml") for p in paths))

        # The committed HelmRelease pins image.tag to exactly what the build produced.
        hr_op = next(o for o in ops if o["path"].endswith("helmrelease.yaml"))
        hr = yaml.safe_load(hr_op["content"])
        self.assertEqual(hr["spec"]["values"]["image"]["tag"], self._TAG)

    def test_build_failure_aborts_before_commit(self):
        fake = FakeGitops(existing={})
        kd._gitops = fake
        with patch.object(kd, "k8s_build", new=AsyncMock(return_value={
            "success": False, "error": "kaniko build failed: boom", "image_tag": self._TAG})), \
             patch.object(kd, "_wait_helmrelease_ready", new=AsyncMock(return_value=True)), \
             patch.object(kd, "_health_gate", new=AsyncMock(return_value=True)):
            result = asyncio.run(
                kd.k8s_deploy(repo_name="todo-app", branch="main", compose_project_name="todo-app")
            )
        self.assertFalse(result["success"])
        self.assertIn("build failed", result["error"])
        # No footprint is committed when the image never built.
        self.assertEqual(fake.committed, [])

    def test_existing_app_uses_update_ops(self):
        # Pre-existing files -> get_file returns (content, sha) -> "update" ops.
        base = f"{kd.GITOPS_PATH}/todo-app"
        fake = FakeGitops(existing={
            f"{base}/namespace.yaml": ("old", "sha-ns"),
            f"{base}/gitrepository.yaml": ("old", "sha-gr"),
            f"{base}/helmrelease.yaml": ("old", "sha-hr"),
        })
        kd._gitops = fake
        with patch.object(kd, "k8s_build", new=self._build_ok()), \
             patch.object(kd, "_wait_helmrelease_ready", new=AsyncMock(return_value=True)), \
             patch.object(kd, "_health_gate", new=AsyncMock(return_value=True)):
            asyncio.run(kd.k8s_deploy(repo_name="todo-app", branch="main"))

        ops = fake.committed[0]["files"]
        self.assertTrue(all(o["operation"] == "update" for o in ops))
        self.assertEqual([o["sha"] for o in ops], ["sha-ns", "sha-gr", "sha-hr"])


class TestComposeDown(unittest.TestCase):
    def test_teardown_deletes_all_files(self):
        fake = FakeGitops()
        kd._gitops = fake
        result = asyncio.run(kd.k8s_teardown("todo-app"))
        self.assertTrue(result["success"])
        # 2 top-level app manifests + 3 build/ files (namespace + 2 ESOs).
        self.assertEqual(len(result["removed"]), 5)
        ops = fake.committed[0]["files"]
        self.assertTrue(all(o["operation"] == "delete" for o in ops))
        self.assertEqual([o["sha"] for o in ops], ["s1", "s2", "b1", "b2", "b3"])

    def test_teardown_missing_app_returns_error(self):
        fake = FakeGitops()
        fake.list_dir = AsyncMock(return_value=[])
        kd._gitops = fake
        result = asyncio.run(kd.k8s_teardown("nope"))
        self.assertFalse(result["success"])


class TestInspect(unittest.TestCase):
    def test_inspect_without_cluster_token_errors(self):
        # k8s_inspect is a real cluster read; with no SA token it reports clearly.
        cc = FakeBuildCluster(available=False)
        with patch.object(kd, "_cluster_client", return_value=cc):
            r = asyncio.run(kd.k8s_inspect("x"))
        self.assertFalse(r["success"])
        self.assertIn("no in-cluster SA token", r["error"])


class FakeCluster:
    """In-memory stand-in for ClusterClient (no network)."""

    def __init__(self, services: dict | None = None, available: bool = True) -> None:
        self._services = services
        self.available = available
        self.calls: list[tuple[str, str]] = []

    async def list_services(self, namespace: str, label_selector: str):
        self.calls.append((namespace, label_selector))
        return self._services


class FakeBuildCluster:
    """In-memory ClusterClient for the git-driven kaniko-Job build path.

    The build is committed to git and created by Flux — this fake only serves
    the READS module-deploy performs: namespace exists, ExternalSecrets Ready,
    and the Job's terminal status (`job_result`), all satisfied on the first
    poll so the waits return without sleeping. There is deliberately NO
    create_job/delete_job here: module-deploy never writes to the cluster.
    """

    def __init__(self, job_result: str = "succeeded", available: bool = True) -> None:
        self.available = available
        self.job_result = job_result  # "succeeded" | "failed"

    async def get_namespace(self, name: str):
        return {"metadata": {"name": name}}

    async def get_externalsecret(self, namespace: str, name: str):
        return {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}

    async def get_job(self, namespace: str, name: str):
        if self.job_result == "succeeded":
            return {"status": {"succeeded": 1}}
        return {"status": {"failed": 1,
                           "conditions": [{"type": "Failed", "message": "kaniko exited 1"}]}}

    async def list_pods(self, namespace: str, label_selector: str):
        return {"items": [{"metadata": {"name": "build-pod"}}]}

    async def pod_log(self, namespace: str, pod: str, container: str, tail: int):
        return "kaniko log tail"


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status_code = status


class _FakeAsyncClient:
    """Records GET targets; returns 200 only for URLs in `ok`."""

    def __init__(self, ok: set[str]) -> None:
        self.ok = ok
        self.gets: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url: str, *a, **k):
        self.gets.append(url)
        return _FakeResp(200 if url in self.ok else 503)


def _svc(cluster_ip: str, port: int, port_name: str = "http") -> dict:
    return {
        "items": [{
            "spec": {"clusterIP": cluster_ip, "ports": [{"name": port_name, "port": port}]},
        }]
    }


class TestInclusterHealthUrl(unittest.TestCase):
    def test_resolves_clusterip_and_http_port(self):
        cc = FakeCluster(services=_svc("10.43.0.9", 8080))
        url = asyncio.run(kd._incluster_health_url(cc, "todo"))
        self.assertEqual(url, "http://10.43.0.9:8080")
        # Selector targets the app Service specifically (not the db Service).
        self.assertEqual(cc.calls[0][0], "todo")
        self.assertIn("app.kubernetes.io/component=app", cc.calls[0][1])

    def test_falls_back_to_first_port_when_no_http_named(self):
        cc = FakeCluster(services=_svc("10.43.0.9", 5000, port_name="web"))
        self.assertEqual(asyncio.run(kd._incluster_health_url(cc, "todo")), "http://10.43.0.9:5000")

    def test_skips_headless_service(self):
        svc = {"items": [{"spec": {"clusterIP": "None", "ports": [{"name": "http", "port": 80}]}}]}
        cc = FakeCluster(services=svc)
        self.assertIsNone(asyncio.run(kd._incluster_health_url(cc, "todo")))

    def test_none_when_cluster_unavailable(self):
        cc = FakeCluster(available=False)
        self.assertIsNone(asyncio.run(kd._incluster_health_url(cc, "todo")))

    def test_none_on_list_error(self):
        cc = FakeCluster()
        cc.list_services = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertIsNone(asyncio.run(kd._incluster_health_url(cc, "todo")))


class TestHealthGate(unittest.TestCase):
    def test_prefers_incluster_target(self):
        client = _FakeAsyncClient(ok={"http://10.43.0.9:8080/health"})
        with patch.object(kd, "_incluster_health_url",
                          new=AsyncMock(return_value="http://10.43.0.9:8080")), \
             patch.object(kd, "_cluster_client", return_value=object()), \
             patch.object(kd.httpx, "AsyncClient", return_value=client):
            ok = asyncio.run(
                kd._health_gate("https://todo-apps.rijnland.dev", 5, "/health", slug="todo")
            )
        self.assertTrue(ok)
        # In-cluster ClusterIP was hit; public FQDN never needed.
        self.assertEqual(client.gets, ["http://10.43.0.9:8080/health"])

    def test_falls_back_to_public_url(self):
        client = _FakeAsyncClient(ok={"https://todo-apps.rijnland.dev/health"})
        with patch.object(kd, "_incluster_health_url", new=AsyncMock(return_value=None)), \
             patch.object(kd, "_cluster_client", return_value=object()), \
             patch.object(kd.httpx, "AsyncClient", return_value=client):
            ok = asyncio.run(
                kd._health_gate("https://todo-apps.rijnland.dev", 5, "/health", slug="todo")
            )
        self.assertTrue(ok)
        self.assertIn("https://todo-apps.rijnland.dev/health", client.gets)

    def test_timeout_returns_false(self):
        client = _FakeAsyncClient(ok=set())  # nothing ever answers 200
        with patch.object(kd, "_incluster_health_url", new=AsyncMock(return_value=None)), \
             patch.object(kd, "_cluster_client", return_value=object()), \
             patch.object(kd.httpx, "AsyncClient", return_value=client), \
             patch.object(kd.asyncio, "sleep", new=AsyncMock(return_value=None)):
            ok = asyncio.run(
                kd._health_gate("https://todo-apps.rijnland.dev", 0.05, "/health", slug="todo")
            )
        self.assertFalse(ok)


class TestBuild(unittest.TestCase):
    """k8s_build: build infra + kaniko Job both committed to git; status polled.

    module-deploy performs NO imperative cluster writes here — it commits the
    Job manifest and reads its status, exactly like the deploy footprint.
    """

    def setUp(self):
        self._orig_gitops = kd._gitops
        self._orig_cluster = kd._cluster

    def tearDown(self):
        kd._gitops = self._orig_gitops
        kd._cluster = self._orig_cluster

    @staticmethod
    def _commit_for(fake, suffix):
        """Return the commit whose file set contains a path ending in `suffix`."""
        for c in fake.committed:
            if any(f["path"].endswith(suffix) for f in c["files"]):
                return c
        return None

    def test_build_commits_infra_and_job_to_git(self):
        fake = FakeGitops()
        kd._gitops = fake
        kd._cluster = FakeBuildCluster(job_result="succeeded")

        result = asyncio.run(kd.k8s_build(
            repo_name="todo-app", branch="main", slug="todo-app", image_tag="test-tag"
        ))

        self.assertTrue(result["success"], result)
        self.assertEqual(result["image_tag"], "test-tag")
        self.assertTrue(result["image"].endswith(":test-tag"))

        # Two commits: build infra (ns + 2 ESOs), then the kaniko Job.
        infra = self._commit_for(fake, "build/namespace.yaml")
        self.assertIsNotNone(infra)
        infra_paths = [f["path"] for f in infra["files"]]
        self.assertTrue(any(p.endswith("build/harbor-push-externalsecret.yaml") for p in infra_paths))
        self.assertTrue(any(p.endswith("build/git-auth-externalsecret.yaml") for p in infra_paths))

        # The kaniko Job is committed to git (Flux creates it), pinned to the tag.
        job_commit = self._commit_for(fake, "build/job.yaml")
        self.assertIsNotNone(job_commit)
        job_file = next(f for f in job_commit["files"] if f["path"].endswith("build/job.yaml"))
        job = yaml.safe_load(job_file["content"])
        self.assertEqual(job["kind"], "Job")
        kaniko_args = job["spec"]["template"]["spec"]["containers"][0]["args"]
        self.assertIn(f"--destination={result['image']}", kaniko_args)

    def test_build_failure_returns_error_and_tag(self):
        fake = FakeGitops()
        kd._gitops = fake
        kd._cluster = FakeBuildCluster(job_result="failed")

        result = asyncio.run(kd.k8s_build(
            repo_name="todo-app", branch="main", slug="todo-app", image_tag="test-tag"
        ))

        self.assertFalse(result["success"])
        self.assertEqual(result["image_tag"], "test-tag")  # tag returned even on failure
        self.assertIn("kaniko build failed", result["error"])
        # The Job was still committed (Flux owns cleanup / next-build supersede).
        self.assertIsNotNone(self._commit_for(fake, "build/job.yaml"))

    def test_build_without_cluster_token_errors_before_commit(self):
        fake = FakeGitops()
        kd._gitops = fake
        kd._cluster = FakeBuildCluster(available=False)
        result = asyncio.run(kd.k8s_build(
            repo_name="todo-app", slug="todo-app", image_tag="t"
        ))
        self.assertFalse(result["success"])
        self.assertIn("no in-cluster SA token", result["error"])
        self.assertEqual(fake.committed, [])  # nothing committed when we can't observe status


class TestBuildManifests(unittest.TestCase):
    def test_build_namespace(self):
        ns = yaml.safe_load(kd.build_build_namespace_yaml("todo-build", "todo"))
        self.assertEqual(ns["kind"], "Namespace")
        self.assertEqual(ns["metadata"]["name"], "todo-build")
        self.assertEqual(ns["metadata"]["labels"]["druppie.io/user-app-build"], "todo")
        # PSA baseline (not privileged): kaniko runs unprivileged.
        self.assertEqual(
            ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "baseline"
        )

    def test_harbor_push_externalsecret(self):
        es = yaml.safe_load(kd.build_harbor_push_externalsecret_yaml("todo-build"))
        self.assertEqual(es["kind"], "ExternalSecret")
        self.assertEqual(es["metadata"]["namespace"], "todo-build")
        self.assertEqual(
            es["spec"]["target"]["template"]["type"], "kubernetes.io/dockerconfigjson"
        )
        self.assertEqual(es["spec"]["secretStoreRef"]["kind"], "ClusterSecretStore")
        keys = {d["secretKey"] for d in es["spec"]["data"]}
        self.assertEqual(keys, {"username", "password", "registry"})

    def test_git_auth_externalsecret(self):
        es = yaml.safe_load(kd.build_git_auth_externalsecret_yaml("todo-build"))
        self.assertEqual(es["kind"], "ExternalSecret")
        self.assertEqual(es["spec"]["data"][0]["secretKey"], "token")

    def test_kaniko_job_shape(self):
        job = kd.build_kaniko_job(
            "todo-build", "build-todo-tag", "todo", "gitea:3000",
            "druppie-apps", "todo-app", "main",
            "harbor/druppie/todo-app:tag", "harbor/druppie/todo-app/cache",
        )
        self.assertEqual(job["kind"], "Job")
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], kd.BUILD_JOB_DEADLINE)
        # No TTL: Flux owns the Job now — a TTL delete would make Flux re-create
        # (and re-run) the build. Supersede-by-name handles cleanup instead.
        self.assertNotIn("ttlSecondsAfterFinished", job["spec"])
        spec = job["spec"]["template"]["spec"]
        self.assertEqual(spec["restartPolicy"], "Never")

        # The git token is exposed ONLY to the clone init-container, never to
        # the kaniko container that runs the untrusted Dockerfile.
        init = spec["initContainers"][0]
        self.assertEqual(init["name"], "clone")
        self.assertEqual(init["env"][0]["name"], "GIT_TOKEN")
        kaniko = spec["containers"][0]
        self.assertEqual(kaniko["name"], "kaniko")
        self.assertNotIn("env", kaniko)
        self.assertIn("requests", kaniko["resources"])  # schedulable + quota-safe
        self.assertIn("--destination=harbor/druppie/todo-app:tag", kaniko["args"])

    def test_job_name_is_dns1123(self):
        name = kd._job_name("My_App", "feature/Big-Change-20260101")
        self.assertRegex(name, r"^[a-z0-9-]+$")
        self.assertLessEqual(len(name), 63)
        self.assertFalse(name.startswith("-"))
        self.assertFalse(name.endswith("-"))

    def test_build_ns_truncates_to_63(self):
        self.assertLessEqual(len(kd._build_ns("a" * 70)), 63)
        self.assertEqual(kd._build_ns("todo"), "todo-build")


if __name__ == "__main__":
    unittest.main()
