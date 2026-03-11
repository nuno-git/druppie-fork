"""Application models. Add your SQLAlchemy models here."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

# Example model — replace or extend as needed:
#
# class Category(Base):
#     __tablename__ = "categories"
#     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
#     name = Column(String(255), nullable=False)
#     created_at = Column(DateTime, default=datetime.utcnow)
