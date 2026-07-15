"""User API routes — avatar and profile endpoints."""

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import FileResponse
import structlog

from druppie.api.deps import get_current_user, get_bearer_token
from druppie.services.avatar_service import get_cached_avatar, fetch_and_cache_avatar, _avatar_path

logger = structlog.get_logger()

router = APIRouter()


@router.get("/users/me/avatar")
async def get_my_avatar(
    user: dict = Depends(get_current_user),
    bearer_token: str = Depends(get_bearer_token),
):
    user_id = user.get("sub", "")

    # Serve from cache if available
    result = get_cached_avatar(user_id)
    if result:
        path = _avatar_path(user_id)
        return FileResponse(
            path=str(path),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    # Cache miss — try to fetch from Graph via KC broker
    from druppie.core.entra_token import get_entra_token, is_entra_configured
    if not is_entra_configured():
        return Response(status_code=404)

    token_result = await get_entra_token(bearer_token)
    graph_token = token_result.get("access_token")
    if not graph_token:
        return Response(status_code=404)

    ok = await fetch_and_cache_avatar(user_id, graph_token)
    if not ok:
        return Response(status_code=404)

    path = _avatar_path(user_id)
    return FileResponse(
        path=str(path),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )
