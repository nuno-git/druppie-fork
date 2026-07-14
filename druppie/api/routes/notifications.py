"""Notification API routes.

Endpoints for listing and marking notifications as read.
Notifications are scoped strictly to the authenticated user.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from druppie.api.deps import get_current_user, get_notification_repository
from druppie.domain import NotificationDetail
from druppie.repositories import NotificationRepository

router = APIRouter()


@router.get("", response_model=list[NotificationDetail])
async def list_notifications(
    repo: NotificationRepository = Depends(get_notification_repository),
    user: dict = Depends(get_current_user),
) -> list[NotificationDetail]:
    user_id = UUID(user["sub"])
    return repo.get_for_user(user_id)


@router.post("/{notification_id}/read", status_code=200)
async def mark_as_read(
    notification_id: UUID,
    repo: NotificationRepository = Depends(get_notification_repository),
    user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    user_id = UUID(user["sub"])
    updated = repo.mark_as_read(notification_id, user_id)
    if updated:
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Notification not found")
