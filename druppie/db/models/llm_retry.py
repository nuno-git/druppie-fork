"""LLM retry database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class LlmRetry(Base):
    """Tracks individual retry attempts on LLM API calls.

    One row per retry attempt. Only created when retries actually occur,
    so normal (no-retry) calls have zero rows here.
    """

    __tablename__ = "llm_retries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    llm_call_id = Column(UUID(as_uuid=True), ForeignKey("llm_calls.id", ondelete="CASCADE"))
    attempt = Column(Integer, nullable=False)  # 1-based attempt number
    error_type = Column(String(100), nullable=False)  # e.g., "RateLimitError"
    error_message = Column(Text)  # truncated error text
    delay_seconds = Column(Integer)  # seconds waited before next attempt
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    llm_call = relationship("LlmCall", back_populates="retries")
