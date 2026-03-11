"""Database models.

Define your SQLAlchemy models here. They will be auto-created on startup.

Example:

    class Category(Base):
        __tablename__ = "categories"

        id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
        name = Column(String(100), nullable=False)
        created_at = Column(DateTime, default=datetime.utcnow)
"""

from datetime import datetime  # noqa: F401
from uuid import uuid4  # noqa: F401

from sqlalchemy import (  # noqa: F401
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID  # noqa: F401
from sqlalchemy.orm import relationship  # noqa: F401

from app.database import Base  # noqa: F401
