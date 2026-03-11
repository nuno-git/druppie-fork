"""Per-sandbox Gitea credential management.

Creates a restricted Gitea user per sandbox session with access to only
the target repository. This replaces the shared admin credentials so a
compromised sandbox cannot access other repos.

Lifecycle:
  create_sandbox_git_user()  — called before sandbox creation
  delete_sandbox_git_user()  — called after sandbox completion (webhook handler + retry)
"""

import os
import secrets

import httpx
import structlog

logger = structlog.get_logger()

_GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "")


def _admin_auth() -> tuple[str, str]:
    return (_ADMIN_USER, _ADMIN_PASSWORD)


async def create_sandbox_git_user(
    sandbox_session_id: str,
    repo_owner: str,
    repo_name: str,
) -> dict[str, str]:
    """Create a restricted Gitea user scoped to one repo.

    Returns a git credential dict compatible with build_git_credentials() format:
      {"provider": "gitea", "url": ..., "username": ..., "password": ..., "authorizedRepo": ...}

    The user is named `sandbox-{sandbox_session_id[:12]}` to stay within
    Gitea's username length limits while remaining identifiable.
    """
    username = f"sandbox-{sandbox_session_id[:12]}"
    password = secrets.token_urlsafe(24)
    email = f"{username}@sandbox.druppie.local"
    base = _GITEA_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Create restricted user via admin API
        user_payload = {
            "username": username,
            "password": password,
            "email": email,
            "must_change_password": False,
            "restricted": True,
            "visibility": "private",
        }
        resp = await client.post(
            f"{base}/api/v1/admin/users",
            json=user_payload,
            auth=_admin_auth(),
        )

        if resp.status_code == 422 and "already exists" in resp.text.lower():
            logger.warning("sandbox_gitea_user_exists_recreating", username=username)
            await _delete_user(client, base, username)
            resp = await client.post(
                f"{base}/api/v1/admin/users",
                json=user_payload,
                auth=_admin_auth(),
            )
            if resp.status_code != 201:
                raise RuntimeError(
                    f"Failed to recreate sandbox Gitea user: {resp.status_code} {resp.text[:200]}"
                )
        elif resp.status_code != 201:
            raise RuntimeError(
                f"Failed to create sandbox Gitea user: {resp.status_code} {resp.text[:200]}"
            )

        # 2. Add as collaborator on target repo (write access)
        resp = await client.put(
            f"{base}/api/v1/repos/{repo_owner}/{repo_name}/collaborators/{username}",
            json={"permission": "write"},
            auth=_admin_auth(),
        )

        if resp.status_code not in (204, 200):
            # Clean up orphaned user
            await _delete_user(client, base, username)
            raise RuntimeError(
                f"Failed to add collaborator: {resp.status_code} {resp.text[:200]}"
            )

        # 3. Create scoped access token for the user
        resp = await client.post(
            f"{base}/api/v1/users/{username}/tokens",
            json={
                "name": "sandbox-token",
                "scopes": ["write:repository"],
            },
            auth=(username, password),
        )

        if resp.status_code != 201:
            await _delete_user(client, base, username)
            raise RuntimeError(
                f"Failed to create token: {resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        token = data.get("sha1") or data.get("token") or ""
        if not token:
            await _delete_user(client, base, username)
            raise RuntimeError("Token creation returned no token value")

        logger.info(
            "sandbox_gitea_user_created",
            username=username,
            repo=f"{repo_owner}/{repo_name}",
        )

        return {
            "provider": "gitea",
            "url": _GITEA_URL,
            "username": username,
            "password": token,
            "authorizedRepo": f"{repo_owner}/{repo_name}",
        }


async def delete_sandbox_git_user(sandbox_session_id: str) -> None:
    """Delete the sandbox's Gitea user. Idempotent — ignores 404."""
    username = f"sandbox-{sandbox_session_id[:12]}"
    base = _GITEA_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        await _delete_user(client, base, username)


async def _delete_user(client: httpx.AsyncClient, base: str, username: str) -> None:
    """Delete a Gitea user via admin API. Ignores 404."""
    try:
        resp = await client.delete(
            f"{base}/api/v1/admin/users/{username}",
            params={"purge": "true"},
            auth=_admin_auth(),
        )
        if resp.status_code in (204, 404):
            logger.info("sandbox_gitea_user_deleted", username=username)
        else:
            logger.warning(
                "sandbox_gitea_user_delete_failed",
                username=username,
                status=resp.status_code,
            )
    except Exception as e:
        logger.warning("sandbox_gitea_user_delete_error", username=username, error=str(e))
