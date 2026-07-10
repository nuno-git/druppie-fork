"""Notification repository for database access."""

from uuid import UUID

from ..db.models.notification import Notification
from .base import BaseRepository


class NotificationRepository(BaseRepository):
    """Database access for in-app notifications."""

    def create(
        self,
        user_id: UUID,
        session_id: UUID,
        kind: str,
        role: str,
        message: str,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            session_id=session_id,
            kind=kind,
            role=role,
            message=message,
        )
        self.db.add(notification)
        self.db.flush()
        return notification

    def get_for_user(
        self,
        user_id: UUID,
        unread_only: bool = False,
    ) -> list[Notification]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.is_read.is_(False))
        return query.order_by(Notification.created_at.desc()).all()

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> bool:
        updated = (
            self.db.query(Notification)
            .filter(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
            .update({"is_read": True}, synchronize_session="fetch")
        )
        return updated > 0
