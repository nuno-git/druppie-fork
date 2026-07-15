"""Avatar service — fetches and caches user profile photos from Microsoft Graph."""

import os
import time
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()

AVATAR_DIR = Path(os.getenv("WORKSPACE_PATH", "/app/workspace")) / "avatars"
MAX_PHOTO_BYTES = 1_048_576  # 1 MB
CACHE_TTL_SECONDS = 86400  # 24 hours
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}


def _avatar_path(user_id: str) -> Path:
    safe_id = user_id.replace("/", "").replace("..", "").replace("\x00", "")
    return AVATAR_DIR / f"{safe_id}.jpg"


def get_cached_avatar(user_id: str) -> tuple[bytes, str] | None:
    path = _avatar_path(user_id)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    return path.read_bytes(), "image/jpeg"


async def fetch_and_cache_avatar(user_id: str, graph_token: str) -> bool:
    url = "https://graph.microsoft.com/v1.0/me/photo/$value"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {graph_token}"},
                timeout=10,
            )
        if resp.status_code == 404:
            logger.info("avatar_not_set_in_entra", user_id=user_id)
            return False
        if resp.status_code != 200:
            logger.warning("avatar_fetch_failed", user_id=user_id, status=resp.status_code)
            return False

        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            logger.warning("avatar_invalid_content_type", user_id=user_id, content_type=content_type)
            return False

        data = resp.content
        if len(data) > MAX_PHOTO_BYTES:
            logger.warning("avatar_too_large", user_id=user_id, size=len(data))
            return False
        if len(data) < 100:
            logger.warning("avatar_too_small", user_id=user_id, size=len(data))
            return False

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        path = _avatar_path(user_id)
        path.write_bytes(data)
        logger.info("avatar_cached", user_id=user_id, size=len(data))
        return True

    except Exception as e:
        logger.warning("avatar_fetch_error", user_id=user_id, error=str(e))
        return False
