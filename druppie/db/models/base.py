"""Base model and utility functions."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid4())
