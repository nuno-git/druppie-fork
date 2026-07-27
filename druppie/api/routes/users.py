"""User API routes — avatar and profile endpoints."""

from fastapi import APIRouter, Depends, Response
import structlog

from druppie.api.deps import get_current_user, get_bearer_token, get_db
from druppie.services.avatar_service import get_cached_avatar, fetch_and_cache_avatar

logger = structlog.get_logger()

router = APIRouter()

_AVATAR_HEADERS = {
    "Cache-Control": "private, no-store",
    "Vary": "Authorization",
}


@router.get("/users/me/avatar")
async def get_my_avatar(
    user: dict = Depends(get_current_user),
    bearer_token: str = Depends(get_bearer_token),
    db=Depends(get_db),
):
    user_id = user.get("sub", "")

    result = get_cached_avatar(db, user_id)
    if result:
        data, content_type = result
        return Response(content=data, media_type=content_type, headers=_AVATAR_HEADERS)

    from druppie.core.entra_token import get_entra_token, is_entra_configured
    if not is_entra_configured():
        return Response(status_code=404, headers=_AVATAR_HEADERS)

    token_result = await get_entra_token(bearer_token)
    graph_token = token_result.get("access_token")
    if not graph_token:
        return Response(status_code=404, headers=_AVATAR_HEADERS)

    ok = await fetch_and_cache_avatar(db, user_id, graph_token)
    if not ok:
        return Response(status_code=404, headers=_AVATAR_HEADERS)

    result = get_cached_avatar(db, user_id)
    if result:
        data, content_type = result
        return Response(content=data, media_type=content_type, headers=_AVATAR_HEADERS)

    return Response(status_code=404, headers=_AVATAR_HEADERS)
