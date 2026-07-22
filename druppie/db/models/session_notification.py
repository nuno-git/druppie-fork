"""Session notification database model.

Tracks which sessions have been notified about translation failures,
so the notification is only sent once per session across all workers.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Index

from .base import Base, utcnow


class SessionNotification(Base):
    """Records that a session has been notified about a translation failure."""

    __tablename__ = "session_notifications"
    __table_args__ = (
        Index("idx_session_notifications_session", "session_id"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String(36), nullable=False, unique=True)
    notified_at = Column(DateTime(timezone=True), default=utcnow)