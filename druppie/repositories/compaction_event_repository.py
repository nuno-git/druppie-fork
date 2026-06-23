"""Repository for CompactionEvent persistence."""

from uuid import UUID

from ..db.models import CompactionEvent
from .base import BaseRepository


class CompactionEventRepository(BaseRepository):

    def create(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        phase: str,
        tokens_before: int = 0,
        tokens_after: int = 0,
        turns_compressed: int = 0,
        summary_text: str | None = None,
        llm_call_id: UUID | None = None,
    ) -> CompactionEvent:
        event = CompactionEvent(
            session_id=session_id,
            agent_run_id=agent_run_id,
            llm_call_id=llm_call_id,
            phase=phase,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            turns_compressed=turns_compressed,
            summary_text=summary_text,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def get_for_agent_run(self, agent_run_id: UUID) -> list[CompactionEvent]:
        return (
            self.db.query(CompactionEvent)
            .filter_by(agent_run_id=agent_run_id)
            .order_by(CompactionEvent.created_at)
            .all()
        )

    def get_for_session(self, session_id: UUID) -> list[CompactionEvent]:
        return (
            self.db.query(CompactionEvent)
            .filter_by(session_id=session_id)
            .order_by(CompactionEvent.created_at)
            .all()
        )
