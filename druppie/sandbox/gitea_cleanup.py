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

_GITEA_URL = os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")
_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "")


def _admin_auth() -> tuple[str, str]:
    return (_ADMIN_USER, _ADMIN_PASSWORD)


async def cleanup_orphaned_sandbox_users() -> int:
    """Delete Gitea users matching 'sandbox-*' that are restricted.

    Returns the number of users deleted.
    """
    base = _GITEA_URL.rstrip("/")
    deleted = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/api/v1/admin/users",
                params={"limit": 50},
                auth=_admin_auth(),
            )
            if resp.status_code != 200:
                logger.warning(
                    "sandbox_gc_list_users_failed",
                    status=resp.status_code,
                )
                return 0

            for user in resp.json():
                username = user.get("login", "")
                if username.startswith("sandbox-") and user.get("restricted"):
                    try:
                        del_resp = await client.delete(
                            f"{base}/api/v1/admin/users/{username}",
                            params={"purge": "true"},
                            auth=_admin_auth(),
                        )
                        if del_resp.status_code in (204, 404):
                            deleted += 1
                            logger.info("sandbox_gc_user_deleted", username=username)
                        else:
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
    except Exception as e:
        logger.warning("sandbox_gc_error", error=str(e))

    if deleted > 0:
        logger.info("sandbox_gc_completed", deleted=deleted)

    return deleted
