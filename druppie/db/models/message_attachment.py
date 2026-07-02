"""Message attachment database model."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class MessageAttachment(Base):
    """A file attached to a chat message."""

    __tablename__ = "message_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"), nullable=True)
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"), nullable=True)

    original_filename = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    storage_path = Column(String(1000), nullable=False)
    extracted_text = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    message = relationship("Message", back_populates="attachments")

    def to_dict(self):
        return {
            "id": str(self.id),
            "owner_user_id": str(self.owner_user_id) if self.owner_user_id else None,
            "message_id": str(self.message_id) if self.message_id else None,
            "session_id": str(self.session_id) if self.session_id else None,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
