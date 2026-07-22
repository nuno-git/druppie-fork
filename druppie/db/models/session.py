"""Session database model."""

from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, utcnow


class Session(Base):
    """A conversation session."""

    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    title = Column(String(500))
    status = Column(String(20), default="active", index=True)  # active, paused, paused_approval, paused_hitl, paused_crashed, completed, failed
    error_message = Column(Text)  # Error details when status is 'failed'
    intent = Column(String(50))  # create_project, update_project, general_chat
    branch_name = Column(String(255), nullable=True)  # Feature branch for update_project

    language = Column(String(10), nullable=True)  # Detected conversational language (e.g., "nl", "en")

    # Token usage (aggregated)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # MDTO archiving metadata (PBI #9737)
    # Procestype number from the Selectielijst Waterschappen (e.g. "15.1", "17.1.6")
    classificatie_code = Column(String(20), nullable=True)
    # Human-readable label for the procestype (e.g. "Beheerobject realiseren — Uitgevoerd")
    informatiecategorie = Column(String(255), nullable=True)
    # Waardering: "B" (bewaren/permanent) or "V" (vernietigen/destroy after term)
    waardering = Column(String(1), nullable=True)
    # Retention period as ISO 8601 duration (e.g. "P10Y" = 10 years)
    bewaartermijn_looptijd = Column(String(20), nullable=True)
    # What triggers the retention clock (e.g. "na_afhandeling", "na_einde_object")
    bewaartermijn_trigger = Column(String(50), nullable=True)
    # Confidentiality: "openbaar", "intern", or "vertrouwelijk"
    access_level = Column(String(20), nullable=True, default="intern")

    retry_snapshots = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "title": self.title,
            "status": self.status,
            "error_message": self.error_message,
            "intent": self.intent,
            "branch_name": self.branch_name,
            "language": self.language,
            "prompt_tokens": self.prompt_tokens or 0,
            "completion_tokens": self.completion_tokens or 0,
            "total_tokens": self.total_tokens or 0,
            "classificatie_code": self.classificatie_code,
            "informatiecategorie": self.informatiecategorie,
            "waardering": self.waardering,
            "bewaartermijn_looptijd": self.bewaartermijn_looptijd,
            "bewaartermijn_trigger": self.bewaartermijn_trigger,
            "access_level": self.access_level,
            "retry_snapshots": self.retry_snapshots,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
