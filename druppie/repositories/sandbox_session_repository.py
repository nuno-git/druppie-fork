"""Sandbox session repository for ownership lookups."""

from uuid import UUID

from .base import BaseRepository
from ..db.models import SandboxSession


class SandboxSessionRepository(BaseRepository):
    """Database access for sandbox session ownership mappings."""

    def create(
        self,
        sandbox_session_id: str,
        user_id: UUID,
        session_id: UUID | None = None,
    ) -> SandboxSession:
        """Register a sandbox session ownership mapping.

        Idempotent: returns existing record if sandbox_session_id already registered.
        """
        existing = self.get_by_sandbox_id(sandbox_session_id)
        if existing:
            return existing

        mapping = SandboxSession(
            sandbox_session_id=sandbox_session_id,
            user_id=user_id,
            session_id=session_id,
        )
        self.db.add(mapping)
        self.db.flush()
        return mapping

    def get_by_sandbox_id(self, sandbox_session_id: str) -> SandboxSession | None:
        """Look up ownership by sandbox control plane session ID."""
        return (
            self.db.query(SandboxSession)
            .filter_by(sandbox_session_id=sandbox_session_id)
            .first()
        )
