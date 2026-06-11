"""Attachment repository - handles MessageAttachment records."""

from uuid import UUID

from druppie.db.models import MessageAttachment
from druppie.repositories.base import BaseRepository


class AttachmentRepository(BaseRepository):
    """Repository for message attachment CRUD."""

    def create(
        self,
        original_filename: str,
        content_type: str,
        file_size: int,
        storage_path: str,
        session_id: UUID | None = None,
        extracted_text: str | None = None,
    ) -> MessageAttachment:
        attachment = MessageAttachment(
            session_id=session_id,
            original_filename=original_filename,
            content_type=content_type,
            file_size=file_size,
            storage_path=storage_path,
            extracted_text=extracted_text,
        )
        self.db.add(attachment)
        self.db.flush()
        return attachment

    def get_by_id(self, attachment_id: UUID) -> MessageAttachment | None:
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.id == attachment_id)
            .first()
        )

    def get_by_ids(self, attachment_ids: list[UUID]) -> list[MessageAttachment]:
        if not attachment_ids:
            return []
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.id.in_(attachment_ids))
            .all()
        )

    def link_to_message(
        self,
        attachment_ids: list[UUID],
        message_id: UUID,
        session_id: UUID,
    ) -> None:
        if not attachment_ids:
            return
        (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.id.in_(attachment_ids))
            .update(
                {"message_id": message_id, "session_id": session_id},
                synchronize_session="fetch",
            )
        )

    def get_for_message_ids(self, message_ids: list[UUID]) -> list[MessageAttachment]:
        if not message_ids:
            return []
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.message_id.in_(message_ids))
            .all()
        )

    def link_to_approval(
        self,
        attachment_ids: list[UUID],
        approval_id: UUID,
        session_id: UUID,
    ) -> None:
        if not attachment_ids:
            return
        (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.id.in_(attachment_ids))
            .update(
                {"approval_id": approval_id, "session_id": session_id},
                synchronize_session="fetch",
            )
        )

    def get_for_approval(self, approval_id: UUID) -> list[MessageAttachment]:
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.approval_id == approval_id)
            .order_by(MessageAttachment.created_at)
            .all()
        )

    def link_to_question(
        self,
        attachment_ids: list[UUID],
        question_id: UUID,
        session_id: UUID,
    ) -> None:
        if not attachment_ids:
            return
        (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.id.in_(attachment_ids))
            .update(
                {"question_id": question_id, "session_id": session_id},
                synchronize_session="fetch",
            )
        )

    def get_for_question(self, question_id: UUID) -> list[MessageAttachment]:
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.question_id == question_id)
            .order_by(MessageAttachment.created_at)
            .all()
        )

    def get_for_session(self, session_id: UUID) -> list[MessageAttachment]:
        return (
            self.db.query(MessageAttachment)
            .filter(MessageAttachment.session_id == session_id)
            .order_by(MessageAttachment.created_at)
            .all()
        )
