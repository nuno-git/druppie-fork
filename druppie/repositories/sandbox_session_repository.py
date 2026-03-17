"""Sandbox session repository for ownership lookups."""

from datetime import datetime, timezone
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
        webhook_secret: str | None = None,
        model_chain: str | None = None,
        model_chain_index: int = 0,
        task_prompt: str | None = None,
        agent_name: str | None = None,
        git_user_id: str | None = None,
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
            webhook_secret=webhook_secret,
            model_chain=model_chain,
            model_chain_index=model_chain_index,
            task_prompt=task_prompt,
            agent_name=agent_name,
            git_user_id=git_user_id,
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

    def get_webhook_secret(self, sandbox_session_id: str) -> str | None:
        """Return the per-session webhook secret, or None if not found."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session:
            return session.webhook_secret
        return None

    def update_tool_call_id(self, sandbox_session_id: str, tool_call_id: UUID) -> None:
        """Link a sandbox session to its tool call for direct lookup."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session:
            session.tool_call_id = tool_call_id
            self.db.flush()

    def get_by_tool_call_id(self, tool_call_id: UUID) -> SandboxSession | None:
        """Look up a sandbox session by its linked tool call ID."""
        return (
            self.db.query(SandboxSession)
            .filter_by(tool_call_id=tool_call_id)
            .first()
        )

    def get_latest_by_tool_call_id(self, tool_call_id: UUID) -> SandboxSession | None:
        """Look up the most recent sandbox session for a tool call (after retries)."""
        return (
            self.db.query(SandboxSession)
            .filter_by(tool_call_id=tool_call_id)
            .order_by(SandboxSession.created_at.desc())
            .first()
        )

    def mark_completed(self, sandbox_session_id: str) -> None:
        """Mark a sandbox session as completed."""
        session = self.get_by_sandbox_id(sandbox_session_id)
        if session:
            session.completed_at = datetime.now(timezone.utc)
            self.db.flush()
