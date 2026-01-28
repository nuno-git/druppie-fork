"""User domain models."""

from pydantic import BaseModel
from uuid import UUID


class UserInfo(BaseModel):
    """Current user info."""
    id: UUID
    username: str
    email: str | None
    display_name: str | None
    roles: list[str]
