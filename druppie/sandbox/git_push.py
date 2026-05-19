"""
Git bundle extraction from sandbox containers and push to external Gitea.

Flow:
  1. exec: git bundle create inside the sandbox container
  2. copy_from: pull the bundle to host
  3. On host: init bare repo, fetch from bundle, push to Gitea branch
  4. Create PR via Gitea API
  5. Cleanup temp files
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid

from .manager import ContainerError, ContainerManager, _run

log = logging.getLogger(__name__)


async def extract_and_push(
    manager: ContainerManager,
    container_id: str,
    repo_url: str,
    branch: str,
    gitea_url: str,
    gitea_token: str,
    repo_owner: str,
    repo_name: str,
    pr_title: str,
    pr_body: str = "",
) -> dict:
    bundle_name = f"changes-{uuid.uuid4().hex[:8]}.bundle"
    bundle_container_path = f"/tmp/{bundle_name}"
    tmpdir = tempfile.mkdtemp(prefix="druppie-git-")

    try:
        rc, stdout, stderr = await manager.exec(
            container_id,
            ["git", "bundle", "create", bundle_container_path, "HEAD", "^origin/main"],
            timeout=120,
        )
        if rc != 0:
            raise ContainerError(f"git bundle create failed: {stderr}")

        bundle_host_path = os.path.join(tmpdir, bundle_name)
        await manager.copy_from(container_id, bundle_container_path, bundle_host_path)

        bare_repo = os.path.join(tmpdir, "bare")
        rc, _, stderr = await _run(["git", "init", "--bare", bare_repo], timeout=30)
        if rc != 0:
            raise ContainerError(f"git init --bare failed: {stderr}")

        rc, _, stderr = await _run(
            ["git", "-C", bare_repo, "fetch", bundle_host_path, "HEAD:refs/heads/" + branch],
            timeout=60,
        )
        if rc != 0:
            raise ContainerError(f"git fetch from bundle failed: {stderr}")

        push_url = _inject_token(gitea_url, gitea_token, repo_owner, repo_name)
        rc, _, stderr = await _run(
            ["git", "-C", bare_repo, "push", push_url, f"{branch}:{branch}"],
            timeout=60,
        )
        if rc != 0:
            raise ContainerError(f"git push to Gitea failed: {stderr}")

        pr = await _create_gitea_pr(
            gitea_url, gitea_token, repo_owner, repo_name, branch, pr_title, pr_body
        )
        return pr

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        await manager.exec(
            container_id, ["rm", "-f", bundle_container_path], timeout=10
        )


def _inject_token(gitea_url: str, token: str, owner: str, repo: str) -> str:
    """Build an authenticated Gitea push URL: https://token@gitea.example.com/owner/repo.git"""
    base = gitea_url.rstrip("/")
    scheme, _, rest = base.partition("://")
    return f"{scheme}://{token}@{rest}/{owner}/{repo}.git"


async def _create_gitea_pr(
    gitea_url: str,
    token: str,
    owner: str,
    repo: str,
    branch: str,
    title: str,
    body: str,
) -> dict:
    base = gitea_url.rstrip("/")
    api_url = f"{base}/api/v1/repos/{owner}/{repo}/pulls"

    payload = json.dumps({
        "head": branch,
        "base": "main",
        "title": title,
        "body": body,
    })

    proc = await asyncio.create_subprocess_exec(
        "curl",
        "-s",
        "-X",
        "POST",
        api_url,
        "-H",
        f"Authorization: token {token}",
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

    if proc.returncode != 0:
        raise ContainerError(f"Gitea PR creation failed: {stderr.decode()}")

    result = json.loads(stdout.decode())
    log.info("Created PR #%s in %s/%s", result.get("number"), owner, repo)
    return result
