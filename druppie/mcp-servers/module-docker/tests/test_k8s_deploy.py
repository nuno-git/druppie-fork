"""Tests for module-docker K8s deploy path (GitOps model).

Covers:
  - _slugify
  - manifest builders (namespace / gitrepository / helmrelease)
  - k8s_compose_up: commits namespace+gitrepository+helmrelease, dispatches the
    CI build, waits for rollout + health gate
  - k8s_compose_down: deletes the app subdir via list_dir -> delete ops
  - stubs (inspect/exec/volumes) return a clear not-supported error

Run:  python druppie/mcp-servers/module-docker/tests/test_k8s_deploy.py
   or pytest druppie/mcp-servers/module-docker/tests/test_k8s_deploy.py
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Make `import k8s_deploy` resolve to module-docker/v1/k8s_deploy.py.
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
        return [
            {"type": "file", "path": f"{path}/namespace.yaml", "sha": "s1"},
            {"type": "file", "path": f"{path}/helmrelease.yaml", "sha": "s2"},
        ]

    async def change_files(self, message: str, files: list[dict]) -> None:
        self.committed.append({"message": message, "files": files})

    async def dispatch_workflow(self, repo: str, workflow: str, ref: str) -> None:
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
        self.assertEqual(ns["metadata"]["labels"]["managed-by"], "druppie-module-docker")

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
    def test_deploys_new_app_commits_three_files(self):
        fake = FakeGitops(existing={})  # nothing exists -> all "create"
        kd._gitops = fake
        with patch.object(kd, "_poll_build", new=AsyncMock(return_value={
            "status": "completed", "conclusion": "success", "html_url": "u"})), \
             patch.object(kd, "_wait_helmrelease_ready", new=AsyncMock(return_value=True)), \
             patch.object(kd, "_health_gate", new=AsyncMock(return_value=True)):
            result = asyncio.run(
                kd.k8s_compose_up(repo_name="todo-app", branch="main", compose_project_name="todo-app")
            )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["slug"], "todo-app")
        self.assertEqual(result["url"], "https://todo-app-apps.rijnland.dev")
        self.assertEqual(result["health_check"], "healthy")

        # Exactly one atomic commit with 3 create operations.
        self.assertEqual(len(fake.committed), 1)
        ops = fake.committed[0]["files"]
        self.assertEqual([o["operation"] for o in ops], ["create", "create", "create"])
        paths = [o["path"] for o in ops]
        self.assertTrue(any(p.endswith("todo-app/namespace.yaml") for p in paths))
        self.assertTrue(any(p.endswith("todo-app/gitrepository.yaml") for p in paths))
        self.assertTrue(any(p.endswith("todo-app/helmrelease.yaml") for p in paths))

        # CI workflow was dispatched on the app repo.
        self.assertEqual(fake.dispatched, [("todo-app", "build.yaml", "main")])

    def test_existing_app_uses_update_ops(self):
        # Pre-existing files -> get_file returns (content, sha) -> "update" ops.
        base = f"{kd.GITOPS_PATH}/todo-app"
        fake = FakeGitops(existing={
            f"{base}/namespace.yaml": ("old", "sha-ns"),
            f"{base}/gitrepository.yaml": ("old", "sha-gr"),
            f"{base}/helmrelease.yaml": ("old", "sha-hr"),
        })
        kd._gitops = fake
        with patch.object(kd, "_poll_build", new=AsyncMock(return_value={
            "status": "completed", "conclusion": "success"})), \
             patch.object(kd, "_wait_helmrelease_ready", new=AsyncMock(return_value=True)), \
             patch.object(kd, "_health_gate", new=AsyncMock(return_value=True)):
            asyncio.run(kd.k8s_compose_up(repo_name="todo-app", branch="main"))

        ops = fake.committed[0]["files"]
        self.assertTrue(all(o["operation"] == "update" for o in ops))
        self.assertEqual([o["sha"] for o in ops], ["sha-ns", "sha-gr", "sha-hr"])


class TestComposeDown(unittest.TestCase):
    def test_teardown_deletes_all_files(self):
        fake = FakeGitops()
        kd._gitops = fake
        result = asyncio.run(kd.k8s_compose_down("todo-app"))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["removed"]), 2)
        ops = fake.committed[0]["files"]
        self.assertTrue(all(o["operation"] == "delete" for o in ops))
        self.assertEqual([o["sha"] for o in ops], ["s1", "s2"])

    def test_teardown_missing_app_returns_error(self):
        fake = FakeGitops()
        fake.list_dir = AsyncMock(return_value=[])
        kd._gitops = fake
        result = asyncio.run(kd.k8s_compose_down("nope"))
        self.assertFalse(result["success"])


class TestStubs(unittest.TestCase):
    def test_inspect_not_supported(self):
        r = asyncio.run(kd.k8s_inspect("x"))
        self.assertFalse(r["success"])
        self.assertIn("not supported", r["error"])

    def test_exec_not_supported(self):
        r = asyncio.run(kd.k8s_exec_command("x", "ls"))
        self.assertFalse(r["success"])

    def test_volumes_not_supported(self):
        r = asyncio.run(kd.k8s_list_volumes())
        self.assertFalse(r["success"])


if __name__ == "__main__":
    unittest.main()
