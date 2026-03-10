"""Retry/revert operations for the Coding MCP Server.

Contains business logic for git revert (hard reset + force push) and
PR closure, used by the backend during retry-from-run operations.
"""

import logging
import re
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger("coding-mcp")

# Matches a valid git commit reference: 7-40 hex chars, optionally followed by ~N
_COMMIT_REF_RE = re.compile(r"^[0-9a-f]{7,40}(~\d+)?$")


def revert_to_commit(
    workspace_path: str | Path,
    branch: str,
    target_commit: str,
    *,
    gitea_clone_url: str | None = None,
    is_gitea_configured: bool = False,
) -> dict:
    """Hard reset workspace to target commit and force push to remote.

    Args:
        workspace_path: Path to the git workspace.
        branch: Branch name to force push.
        target_commit: Commit SHA to reset to.
        gitea_clone_url: Authenticated Gitea clone URL (if pushing).
        is_gitea_configured: Whether Gitea credentials are available.

    Returns:
        Dict with success, previous_head, new_head, force_pushed, and
        error on failure.
    """
    cwd = str(workspace_path)

    # Validate target_commit looks like a real commit reference
    if not target_commit or not _COMMIT_REF_RE.match(target_commit):
        return {
            "success": False,
            "error": f"Invalid target_commit: {target_commit!r}. Expected a hex SHA (7-40 chars), optionally with ~N suffix.",
        }

    # Capture current HEAD
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True
    )
    previous_head = head_result.stdout.strip() if head_result.returncode == 0 else None

    logger.info(
        "revert_to_commit: %s -> %s (branch=%s)",
        previous_head, target_commit, branch,
    )

    # Ensure remote is configured before fetch (workspace may have been
    # created with git init and no remote, e.g. when repo info was missing)
    if is_gitea_configured and gitea_clone_url:
        # Use set-url in case origin already exists, fall back to add
        set_url = subprocess.run(
            ["git", "remote", "set-url", "origin", gitea_clone_url],
            cwd=cwd, capture_output=True, text=True,
        )
        if set_url.returncode != 0:
            subprocess.run(
                ["git", "remote", "add", "origin", gitea_clone_url],
                cwd=cwd, capture_output=True, text=True,
            )

    # Fetch latest from remote (commit may only exist on remote, e.g. pushed by sandbox)
    fetch_result = subprocess.run(
        ["git", "fetch", "origin"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if fetch_result.returncode != 0:
        logger.warning("git fetch origin failed: %s", fetch_result.stderr)

    # Hard reset to target commit
    reset_result = subprocess.run(
        ["git", "reset", "--hard", target_commit],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if reset_result.returncode != 0:
        return {
            "success": False,
            "error": f"git reset --hard failed: {reset_result.stderr}",
        }

    # Capture new HEAD
    new_head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True
    )
    new_head = new_head_result.stdout.strip() if new_head_result.returncode == 0 else None

    # Force push if Gitea is configured
    force_pushed = False
    if is_gitea_configured:
        push_result = subprocess.run(
            ["git", "push", "--force", "origin", branch],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if push_result.returncode == 0:
            force_pushed = True
            logger.info("Force pushed to %s after revert", branch)
        else:
            logger.error("Force push failed after revert: %s", push_result.stderr)
            return {
                "success": False,
                "error": f"Git reset succeeded but force push failed: {push_result.stderr}",
                "previous_head": previous_head,
                "new_head": new_head,
                "force_pushed": False,
            }

    return {
        "success": True,
        "previous_head": previous_head,
        "new_head": new_head,
        "force_pushed": force_pushed,
    }


async def close_pull_request(
    pr_number: int,
    repo_owner: str,
    repo_name: str,
    gitea_url: str,
    api_headers: dict,
) -> dict:
    """Close a pull request on Gitea without merging.

    Args:
        pr_number: The PR number to close.
        repo_owner: Repository owner.
        repo_name: Repository name.
        gitea_url: Base Gitea URL.
        api_headers: Headers with authentication for Gitea API.

    Returns:
        Dict with success, pr_number, closed, and error on failure.
    """
    api_url = f"{gitea_url}/api/v1/repos/{repo_owner}/{repo_name}/pulls/{pr_number}"
    payload = {"state": "closed"}

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            api_url,
            json=payload,
            headers=api_headers,
            timeout=30.0,
        )

    if resp.status_code in (200, 204):
        logger.info("Closed PR #%d on %s/%s", pr_number, repo_owner, repo_name)
        return {"success": True, "pr_number": pr_number, "closed": True}
    else:
        return {
            "success": False,
            "error": f"Gitea API error {resp.status_code}: {resp.text}",
        }
