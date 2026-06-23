"""Model override database model for runtime LLM configuration."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class ModelOverride(Base):
    """Runtime override for agent or translation model selection.

    Stores admin-set provider/model overrides that take priority over
    YAML profile defaults. One row per target (agent or translation).
    """

    __tablename__ = "model_overrides"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_model_overrides_target"),
        Index("idx_model_overrides_target", "target_type", "target_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    target_type = Column(String(20), nullable=False)  # "agent" or "translation"
    target_id = Column(String(100), nullable=False)  # agent_id or "translation"
    provider = Column(String(50), nullable=False)
    model = Column(String(200), nullable=False)
    enabled = Column(Boolean, default=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
