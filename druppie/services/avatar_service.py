"""Avatar service — fetches and caches user profile photos from Microsoft Graph."""

import time
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from druppie.db.models.user import UserAvatar

logger = structlog.get_logger()

MAX_PHOTO_BYTES = 1_048_576  # 1 MB
CACHE_TTL_SECONDS = 86400  # 24 hours
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp"}


def get_cached_avatar(db: Session, user_id: str) -> tuple[bytes, str] | None:
    avatar = db.query(UserAvatar).filter(UserAvatar.user_id == UUID(user_id)).first()
    if not avatar:
        return None
    if avatar.updated_at and (time.time() - avatar.updated_at.timestamp()) > CACHE_TTL_SECONDS:
        return None
    return avatar.image_data, avatar.content_type


async def fetch_and_cache_avatar(db: Session, user_id: str, graph_token: str) -> bool:
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

        uid = UUID(user_id)
        existing = db.query(UserAvatar).filter(UserAvatar.user_id == uid).first()
        if existing:
            existing.image_data = data
            existing.content_type = content_type
        else:
            db.add(UserAvatar(user_id=uid, image_data=data, content_type=content_type))
        db.commit()
        logger.info("avatar_cached_to_db", user_id=user_id, size=len(data))
        return True

    except Exception as e:
        logger.warning("avatar_fetch_error", user_id=user_id, error=str(e))
        db.rollback()
        return False
