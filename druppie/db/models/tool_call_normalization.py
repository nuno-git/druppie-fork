"""Tool call normalization database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class ToolCallNormalization(Base):
    """Tracks individual field normalizations on tool call arguments.

    One row per field that was normalized. Only created when normalization
    actually changes a value, so normal calls have zero rows here.
    """

    __tablename__ = "tool_call_normalizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tool_call_id = Column(UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="CASCADE"))
    field_name = Column(String(200), nullable=False)  # e.g., "path"
    original_value = Column(Text)  # serialized original, e.g., "\"null\""
    normalized_value = Column(Text)  # serialized normalized, e.g., "\"\""
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    tool_call = relationship("ToolCall", back_populates="normalizations")
