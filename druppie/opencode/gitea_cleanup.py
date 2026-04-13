"""Garbage collection for orphaned sandbox Gitea users.

If sandbox completion cleanup fails (network error, process crash),
orphaned `sandbox-*` users accumulate in Gitea. This module provides
a sweep that deletes all restricted sandbox users.

Called on backend startup to clean up any leftovers.
"""

import os

import httpx
import structlog

logger = structlog.get_logger()


def _get_gitea_config() -> tuple[str, str, str]:
    """Read Gitea config from env at call time (not import time)."""
    return (
        os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000"),
        os.getenv("GITEA_ADMIN_USER", "gitea_admin"),
        os.getenv("GITEA_ADMIN_PASSWORD", ""),
    )


async def cleanup_orphaned_sandbox_users() -> int:
    """Delete Gitea users matching 'sandbox-*' that are restricted.

    Returns the number of users deleted.
    """
    gitea_url, admin_user, admin_password = _get_gitea_config()
    admin_auth = (admin_user, admin_password)
    base = gitea_url.rstrip("/")
    deleted = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            page = 1
            while True:
                resp = await client.get(
                    f"{base}/api/v1/admin/users",
                    params={"limit": 50, "page": page},
                    auth=admin_auth,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "sandbox_gc_list_users_failed",
                        status=resp.status_code,
                    )
                    break

                users = resp.json()
                if not users:
                    break

                for user in users:
                    username = user.get("login", "")
                    if username.startswith("sandbox-") and user.get("restricted"):
                        try:
                            del_resp = await client.delete(
                                f"{base}/api/v1/admin/users/{username}",
                                params={"purge": "true"},
                                auth=admin_auth,
                            )
                            if del_resp.status_code == 204:
                                deleted += 1
                                logger.info("sandbox_gc_user_deleted", username=username)
                            elif del_resp.status_code != 404:
                                logger.warning(
                                    "sandbox_gc_user_delete_failed",
                                    username=username,
                                    status=del_resp.status_code,
                                )
                        except Exception as e:
                            logger.warning(
                                "sandbox_gc_user_delete_error",
                                username=username,
                                error=str(e),
                            )

                if len(users) < 50:
                    break
                page += 1
    except Exception as e:
        logger.warning("sandbox_gc_error", error=str(e))

    if deleted > 0:
        logger.info("sandbox_gc_completed", deleted=deleted)

    return deleted
