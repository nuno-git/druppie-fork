"""Notification API routes.

Endpoints for listing and marking notifications as read.
Notifications are scoped strictly to the authenticated user.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from druppie.api.deps import get_current_user
from druppie.db.database import get_db
from druppie.domain.notification import NotificationDetail
from druppie.repositories import NotificationRepository

router = APIRouter()


def _get_notification_repo(db: Session = Depends(get_db)) -> NotificationRepository:
    return NotificationRepository(db)


def _to_detail(n) -> NotificationDetail:
    return NotificationDetail(
        id=n.id,
        session_id=n.session_id,
        kind=n.kind,
        role=n.role,
        message=n.message,
        is_read=n.is_read,
        created_at=n.created_at,
    )


@router.get("", response_model=list[NotificationDetail])
async def list_notifications(
    repo: NotificationRepository = Depends(_get_notification_repo),
    user: dict = Depends(get_current_user),
) -> list[NotificationDetail]:
    user_id = UUID(user["sub"])
    notifications = repo.get_for_user(user_id)
    return [_to_detail(n) for n in notifications]


@router.post("/{notification_id}/read", status_code=200)
async def mark_as_read(
    notification_id: UUID,
    repo: NotificationRepository = Depends(_get_notification_repo),
    user: dict = Depends(get_current_user),
):
    user_id = UUID(user["sub"])
    updated = repo.mark_as_read(notification_id, user_id)
    if updated:
        repo.db.commit()
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Notification not found")
