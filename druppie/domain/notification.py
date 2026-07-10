"""Notification domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationDetail(BaseModel):
    """Single notification returned to the frontend."""

    id: UUID
    session_id: UUID
    kind: str
    role: str
    message: str
    is_read: bool
    created_at: datetime
